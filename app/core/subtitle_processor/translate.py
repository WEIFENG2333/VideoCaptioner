import hashlib
from string import Template
from typing import Callable, Dict, Optional, List, Any, Union
import logging
from pathlib import Path
import os
import retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from abc import ABC, abstractmethod
from enum import Enum
from openai import OpenAI
import json
from dataclasses import dataclass
from functools import lru_cache
import signal
import requests
import re
import html
from urllib.parse import quote
import time

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.utils import json_repair
from app.core.subtitle_processor.prompt import (
    TRANSLATE_PROMPT,
    REFLECT_TRANSLATE_PROMPT,
    SINGLE_TRANSLATE_PROMPT,
)
from app.core.storage.cache_manager import CacheManager
from app.config import CACHE_PATH
from app.core.utils.logger import setup_logger


logger = setup_logger("subtitle_translator")


class TranslatorType(Enum):
    """翻译器类型"""

    OPENAI = "openai"
    GOOGLE = "google"
    BING = "bing"
    DEEPLX = "deeplx"


class BaseTranslator(ABC):
    """翻译器基类"""

    def __init__(
        self,
        thread_num: int = 10,
        batch_num: int = 20,
        target_language: str = "Chinese",
        retry_times: int = 1,
        timeout: int = 60,
        update_callback: Optional[Callable] = None,
        custom_prompt: Optional[str] = None,
    ):
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.target_language = target_language
        self.retry_times = retry_times
        self.timeout = timeout
        self.is_running = True
        self.update_callback = update_callback
        self.custom_prompt = custom_prompt
        self._init_thread_pool()
        self.cache_manager = CacheManager(CACHE_PATH)

    def _init_thread_pool(self):
        """初始化线程池"""
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        import atexit

        atexit.register(self.stop)

    def translate_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
        """翻译字幕文件"""
        try:
            # 读取字幕文件
            if isinstance(subtitle_data, str):
                asr_data = ASRData.from_subtitle_file(subtitle_data)
            else:
                asr_data = subtitle_data

            # 将ASRData转换为字典格式
            subtitle_dict = {
                str(i): seg.text for i, seg in enumerate(asr_data.segments, 1)
            }

            # 分批处理字幕
            chunks = self._split_chunks(subtitle_dict)

            # 多线程翻译
            translated_dict = self._parallel_translate(chunks)

            # 创建新的ASRDataSeg列表
            new_segments = self._create_segments(asr_data.segments, translated_dict)

            return ASRData(new_segments)
        except Exception as e:
            logger.error(f"翻译失败：{str(e)}")
            raise RuntimeError(f"翻译失败：{str(e)}")

    def _split_chunks(self, subtitle_dict: Dict[str, str]) -> List[Dict[str, str]]:
        """将字幕分割成块"""
        items = list(subtitle_dict.items())
        return [
            dict(items[i : i + self.batch_num])
            for i in range(0, len(items), self.batch_num)
        ]

    def _parallel_translate(self, chunks: List[Dict[str, str]]) -> Dict[str, str]:
        """并行翻译所有块"""
        futures = []
        translated_dict = {}

        for chunk in chunks:
            future = self.executor.submit(self._safe_translate_chunk, chunk)
            futures.append(future)

        for future in as_completed(futures):
            if not self.is_running:
                logger.info("翻译器已停止运行，退出翻译")
                break
            try:
                result = future.result()
                translated_dict.update(result)
            except Exception as e:
                logger.error(f"翻译块失败：{str(e)}")
                # 对于失败的块，保留原文
                for k, v in chunk.items():
                    translated_dict[k] = f"{v}||ERROR"

        return translated_dict

    def _safe_translate_chunk(self, chunk: Dict[str, str]) -> Dict[str, str]:
        """安全的翻译块，包含重试逻辑"""
        for i in range(self.retry_times):
            try:
                result = self._translate_chunk(chunk)
                if self.update_callback:
                    self.update_callback(result)
                return result
            except Exception as e:
                if i == self.retry_times - 1:
                    raise
                logger.warning(f"翻译重试 {i+1}/{self.retry_times}: {str(e)}")

    @staticmethod
    def _create_segments(
        original_segments: List[ASRDataSeg], translated_dict: Dict[str, str]
    ) -> List[ASRDataSeg]:
        """创建新的字幕段"""
        for i, seg in enumerate(original_segments, 1):
            try:
                seg.translated_text = translated_dict[str(i)]  # 设置翻译文本
            except Exception as e:
                logger.error(f"创建新的字幕段失败：{str(e)}")
                seg.translated_text = seg.text
        return original_segments

    @abstractmethod
    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """翻译字幕块"""
        pass

    def stop(self):
        """停止翻译器"""
        if not self.is_running:
            return

        logger.info("正在停止翻译器...")
        self.is_running = False
        if hasattr(self, "executor") and self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.error(f"关闭线程池时出错：{str(e)}")
            finally:
                self.executor = None


class OpenAITranslator(BaseTranslator):
    """OpenAI翻译器"""

    def __init__(
        self,
        thread_num: int = 10,
        batch_num: int = 20,
        target_language: str = "Chinese",
        model: str = "gpt-4o-mini",
        custom_prompt: str = "",
        is_reflect: bool = False,
        temperature: float = 0.7,
        timeout: int = 60,
        retry_times: int = 1,
        update_callback: Optional[Callable] = None,
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            retry_times=retry_times,
            timeout=timeout,
            update_callback=update_callback,
            custom_prompt=custom_prompt,
        )
        self.model = model
        self.is_reflect = is_reflect
        self.temperature = temperature
        self._init_client()
        # 添加动态批处理大小调整
        self.current_batch_size = batch_num
        self.success_counter = 0
        self.failure_counter = 0
        self.adjustment_threshold = 5  # 累计5次成功/失败后调整批处理大小
        self.max_batch_size = batch_num
        self.min_batch_size = max(1, batch_num // 4)

    def _init_client(self):
        """初始化OpenAI客户端"""
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not (base_url and api_key):
            raise ValueError("环境变量 OPENAI_BASE_URL 和 OPENAI_API_KEY 必须设置")

        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """翻译字幕块，加入动态批处理大小调整"""
        try:
            # 检查批处理大小是否需要调整
            if len(subtitle_chunk) > self.current_batch_size:
                # 如果当前块大于调整后的批处理大小，分割处理
                items = list(subtitle_chunk.items())
                result = {}
                for i in range(0, len(items), self.current_batch_size):
                    sub_chunk = dict(items[i:i + self.current_batch_size])
                    sub_result = self._process_translate_chunk(sub_chunk)
                    result.update(sub_result)
                
                # 记录成功
                self.success_counter += 1
                self._adjust_batch_size()
                return result
            else:
                # 正常处理
                result = self._process_translate_chunk(subtitle_chunk)
                
                # 记录成功
                self.success_counter += 1
                self._adjust_batch_size()
                return result
                
        except Exception as e:
            # 记录失败
            self.failure_counter += 1
            self._adjust_batch_size()
            logger.error(f"翻译块失败(批处理大小={self.current_batch_size}): {str(e)}")
            raise
    
    def _adjust_batch_size(self):
        """根据成功/失败次数动态调整批处理大小"""
        if self.success_counter >= self.adjustment_threshold:
            # 连续成功，增加批处理大小
            new_size = min(self.current_batch_size + 2, self.max_batch_size)
            if new_size != self.current_batch_size:
                logger.info(f"增加批处理大小: {self.current_batch_size} -> {new_size}")
                self.current_batch_size = new_size
            self.success_counter = 0
            self.failure_counter = 0
        
        elif self.failure_counter >= 2:  # 对失败更敏感
            # 连续失败，减少批处理大小
            new_size = max(self.current_batch_size // 2, self.min_batch_size)
            if new_size != self.current_batch_size:
                logger.info(f"减少批处理大小: {self.current_batch_size} -> {new_size}")
                self.current_batch_size = new_size
            self.success_counter = 0
            self.failure_counter = 0
    
    def _process_translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """处理字幕块的实际翻译逻辑"""
        start_time = time.time()
        logger.info(
            f"正在翻译 {len(subtitle_chunk)} 段字幕: {next(iter(subtitle_chunk.keys()))} - {next(reversed(subtitle_chunk.keys()))}"
        )

        # 检查是否为批量API
        if len(subtitle_chunk) <= 1:
            result = self._translate_chunk_single(subtitle_chunk)
            elapsed = time.time() - start_time
            logger.info(f"单字幕翻译完成，耗时 {elapsed:.2f}s")
            return result

        target_lang = self.target_language
        prompt_template = TRANSLATE_PROMPT if not self.is_reflect else REFLECT_TRANSLATE_PROMPT

        # 构建提示词
        template = Template(prompt_template)
        prompt = template.substitute(
            target_language=target_lang,
            input_subtitles=str(subtitle_chunk),
        )

        # 添加用户自定义提示
        if self.custom_prompt:
            prompt += f"\nReference content:\n{self.custom_prompt}"

        # 检查缓存
        param = {
            "temperature": self.temperature,
            "is_reflect": self.is_reflect,
        }
        cache_key = f"{self.target_language}_{len(prompt)}_{len(subtitle_chunk)}"
        cache_result = self.cache_manager.get_llm_result(
            cache_key, self.model, **param
        )
        if cache_result:
            logger.info("使用缓存的翻译结果")
            try:
                return json.loads(cache_result)
            except Exception:
                logger.warning("缓存结果解析失败，重新翻译")

        # 调用API
        response = self._call_api(prompt, subtitle_chunk)

        # 解析响应
        try:
            result = self._parse_response(response)
            
            # 保存到缓存
            self.cache_manager.set_llm_result(
                cache_key,
                json.dumps(result, ensure_ascii=False),
                self.model,
                **param,
            )
            
            elapsed = time.time() - start_time
            logger.info(f"翻译完成，耗时 {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"解析翻译结果失败，耗时 {elapsed:.2f}s: {str(e)}")
            raise

    def _translate_chunk_single(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """单条翻译模式"""
        result = {}
        single_prompt = Template(SINGLE_TRANSLATE_PROMPT).safe_substitute(
            target_language=self.target_language
        )
        prompt_hash = hashlib.md5(single_prompt.encode()).hexdigest()
        for idx, text in subtitle_chunk.items():
            try:
                # 检查缓存
                cache_params = {
                    "target_language": self.target_language,
                    "is_reflect": self.is_reflect,
                    "temperature": self.temperature,
                    "prompt_hash": prompt_hash,
                }
                cache_result = self.cache_manager.get_llm_result(
                    f"{text}", self.model, **cache_params
                )

                if cache_result:
                    result[idx] = cache_result
                    continue

                response = self._call_api(single_prompt, text)
                translated_text = response.choices[0].message.content.strip()

                # 删除 DeepSeek-R1 等推理模型的思考过程 #300
                translated_text = re.sub(
                    r"<think>.*?</think>", "", translated_text, flags=re.DOTALL
                )
                translated_text = translated_text.strip()

                # 保存到缓存
                self.cache_manager.set_llm_result(
                    f"{text}",
                    translated_text,
                    self.model,
                    **cache_params,
                )

                result[idx] = translated_text
            except Exception as e:
                logger.error(f"单条翻译失败 {idx}: {str(e)}")
                result[idx] = "ERROR"  # 如果翻译失败，返回错误标记

        return result

    def _call_api(self, prompt: str, user_content: Dict[str, str]) -> Any:
        """调用OpenAI API"""
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]

        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            timeout=self.timeout,
        )

    def _parse_response(self, response: Any) -> Dict[str, str]:
        """解析API响应"""
        try:
            result = json_repair.loads(response.choices[0].message.content)
            if self.is_reflect:
                return {k: v["revised_translation"] for k, v in result.items()}
            return result
        except Exception as e:
            raise ValueError(f"解析翻译结果失败：{str(e)}")


class GoogleTranslator(BaseTranslator):
    """谷歌翻译器"""

    def __init__(
        self,
        thread_num: int = 10,
        batch_num: int = 20,
        target_language: str = "Chinese",
        retry_times: int = 1,
        timeout: int = 20,
        update_callback: Optional[Callable] = None,
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            retry_times=retry_times,
            timeout=timeout,
            update_callback=update_callback,
        )
        self.session = requests.Session()
        self.endpoint = "http://translate.google.com/m"
        self.headers = {
            "User-Agent": "Mozilla/4.0 (compatible;MSIE 6.0;Windows NT 5.1;SV1;.NET CLR 1.1.4322;.NET CLR 2.0.50727;.NET CLR 3.0.04506.30)"
        }
        self.lang_map = {
            "简体中文": "zh-CN",
            "繁体中文": "zh-TW",
            "英语": "en",
            "日本語": "ja",
            "韩语": "ko",
            "粤语": "yue",
            "法语": "fr",
            "德语": "de",
            "西班牙语": "es",
            "俄语": "ru",
            "葡萄牙语": "pt",
            "土耳其语": "tr",
        }

    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """翻译字幕块"""
        result = {}
        if self.target_language in self.lang_map.values():
            target_lang = self.target_language
        else:
            target_lang = self.lang_map.get(self.target_language, "zh-CN")

        for idx, text in subtitle_chunk.items():
            try:
                # 检查缓存
                cache_params = {"target_language": target_lang}
                cache_result = self.cache_manager.get_translation(
                    text, TranslatorType.GOOGLE.value, **cache_params
                )

                if cache_result:
                    result[idx] = cache_result
                    logger.info(f"使用缓存的Google翻译结果：{idx}")
                    continue

                text = text[:5000]  # google translate max length
                response = self.session.get(
                    self.endpoint,
                    params={"tl": target_lang, "sl": "auto", "q": text},
                    headers=self.headers,
                    timeout=self.timeout,
                )

                if response.status_code == 400:
                    result[idx] = "TRANSLATION ERROR"
                    continue

                response.raise_for_status()
                re_result = re.findall(
                    r'(?s)class="(?:t0|result-container)">(.*?)<', response.text
                )
                if re_result:
                    translated_text = html.unescape(re_result[0])
                    # 保存到缓存
                    self.cache_manager.set_translation(
                        text,
                        translated_text,
                        TranslatorType.GOOGLE.value,
                        **cache_params,
                    )
                    result[idx] = translated_text
                else:
                    result[idx] = "ERROR"
                    logger.warning(f"无法从Google翻译响应中提取翻译结果: {idx}")
            except Exception as e:
                logger.error(f"Google翻译失败 {idx}: {str(e)}")
                result[idx] = "ERROR"
        return result


class BingTranslator(BaseTranslator):
    """必应翻译器"""

    def __init__(
        self,
        thread_num: int = 10,
        batch_num: int = 20,
        target_language: str = "Chinese",
        retry_times: int = 1,
        timeout: int = 20,
        update_callback: Optional[Callable] = None,
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            retry_times=retry_times,
            timeout=timeout,
            update_callback=update_callback,
        )
        self.session = requests.Session()
        self.auth_endpoint = "https://edge.microsoft.com/translate/auth"
        self.translate_endpoint = (
            "https://api-edge.cognitive.microsofttranslator.com/translate"
        )
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        }
        self.lang_map = {
            "简体中文": "zh-Hans",
            "繁体中文": "zh-Hant",
            "英语": "en",
            "日本語": "ja",
            "韩语": "ko",
            "粤语": "yue",
            "法语": "fr",
            "德语": "de",
            "西班牙语": "es",
            "俄语": "ru",
            "葡萄牙语": "pt",
            "土耳其语": "tr",
            "Chinese": "zh-Hans",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Russian": "ru",
            "Spanish": "es",
        }
        self._init_session()

    def _init_session(self):
        """初始化会话，获取必要的token"""
        try:
            response = self.session.get(self.auth_endpoint, timeout=self.timeout)
            response.raise_for_status()
            self.auth_token = response.text
            self.headers["authorization"] = f"Bearer {self.auth_token}"
        except Exception as e:
            logger.error(f"初始化必应翻译会话失败: {str(e)}")
            raise RuntimeError(f"初始化必应翻译会话失败: {str(e)}")

    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """翻译字幕块"""
        result = {}
        if self.target_language in self.lang_map.values():
            target_lang = self.target_language
        else:
            target_lang = self.lang_map.get(self.target_language, "zh-Hans")

        # 准备批量翻译的数据
        texts_to_translate = []
        idx_map = []

        for idx, text in subtitle_chunk.items():
            # 检查缓存
            cache_params = {"target_language": target_lang}
            cache_result = self.cache_manager.get_translation(
                text, TranslatorType.BING.value, **cache_params
            )

            if cache_result:
                result[idx] = cache_result
                logger.debug(f"使用缓存的Bing翻译结果：{idx}")
            else:
                texts_to_translate.append({"Text": text[:5000]})  # 限制文本长度
                idx_map.append(idx)

        if texts_to_translate:
            try:
                params = {
                    "to": target_lang,
                    "api-version": "3.0",
                    "includeSentenceLength": "true",
                }

                response = self.session.post(
                    self.translate_endpoint,
                    params=params,
                    headers=self.headers,
                    json=texts_to_translate,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                translations = response.json()

                # 处理翻译结果
                for i, translation in enumerate(translations):
                    idx = idx_map[i]
                    translated_text = translation["translations"][0]["text"]

                    # 保存到缓存
                    original_text = texts_to_translate[i]["Text"]
                    self.cache_manager.set_translation(
                        original_text,
                        translated_text,
                        TranslatorType.BING.value,
                        **{"target_language": target_lang},
                    )

                    result[idx] = translated_text

            except Exception as e:
                logger.error(f"必应翻译失败: {str(e)}")
                # 如果是token过期，尝试重新初始化会话
                if "token" in str(e).lower() or response.status_code in [401, 403]:
                    try:
                        self._init_session()
                    except Exception as e:
                        logger.error(f"重新初始化必应翻译会话失败: {str(e)}")
                # 对于失败的翻译，标记为错误
                for idx in idx_map:
                    if idx not in result:
                        result[idx] = "ERROR"

        return result


class DeepLXTranslator(BaseTranslator):
    """DeepLX翻译器"""

    def __init__(
        self,
        thread_num: int = 10,
        batch_num: int = 20,
        target_language: str = "Chinese",
        retry_times: int = 1,
        timeout: int = 20,
        update_callback: Optional[Callable] = None,
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            retry_times=retry_times,
            timeout=timeout,
            update_callback=update_callback,
        )
        self.session = requests.Session()
        self.endpoint = os.getenv("DEEPLX_ENDPOINT", "https://api.deeplx.org/translate")
        self.lang_map = {
            "简体中文": "zh",
            "繁体中文": "zh-TW",
            "英语": "en",
            "日本語": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "西班牙语": "es",
            "俄语": "ru",
            "葡萄牙语": "pt",
            "土耳其语": "tr",
            "Chinese": "zh",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Spanish": "es",
            "Russian": "ru",
        }

    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """翻译字幕块"""
        result = {}
        if self.target_language in self.lang_map.values():
            target_lang = self.target_language
        else:
            target_lang = self.lang_map.get(self.target_language, "zh").lower()

        for idx, text in subtitle_chunk.items():
            try:
                # 检查缓存
                cache_params = {
                    "target_language": target_lang,
                    "endpoint": self.endpoint,
                }
                cache_result = self.cache_manager.get_translation(
                    text, TranslatorType.DEEPLX.value, **cache_params
                )

                if cache_result:
                    result[idx] = cache_result
                    logger.info(f"使用缓存的DeepLX翻译结果：{idx}")
                    continue

                response = self.session.post(
                    self.endpoint,
                    json={
                        "text": text,
                        "source_lang": "auto",
                        "target_lang": target_lang,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                translated_text = response.json()["data"]

                # 保存到缓存
                self.cache_manager.set_translation(
                    text, translated_text, TranslatorType.DEEPLX.value, **cache_params
                )

                result[idx] = translated_text
            except Exception as e:
                logger.error(f"DeepLX翻译失败 {idx}: {str(e)}")
                result[idx] = "ERROR"
        return result


class TranslatorFactory:
    """翻译器工厂类"""

    @staticmethod
    def create_translator(
        translator_type: TranslatorType,
        thread_num: int = 5,
        batch_num: int = 10,
        target_language: str = "Chinese",
        model: str = "gpt-4o-mini",
        custom_prompt: str = "",
        temperature: float = 0.7,
        is_reflect: bool = False,
        update_callback: Optional[Callable] = None,
    ) -> BaseTranslator:
        """创建翻译器实例"""
        try:
            if translator_type == TranslatorType.OPENAI:
                return OpenAITranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    model=model,
                    custom_prompt=custom_prompt,
                    is_reflect=is_reflect,
                    temperature=temperature,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.GOOGLE:
                batch_num = 5
                return GoogleTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.BING:
                batch_num = 10
                return BingTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.DEEPLX:
                batch_num = 5
                return DeepLXTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    update_callback=update_callback,
                )
            else:
                raise ValueError(f"不支持的翻译器类型：{translator_type}")
        except Exception as e:
            logger.error(f"创建翻译器失败：{str(e)}")
            raise
