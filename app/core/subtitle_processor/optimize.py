import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Union

from openai import OpenAI

from app.config import CACHE_PATH
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.storage.cache_manager import CacheManager
from app.core.subtitle_processor.alignment import SubtitleAligner
from app.core.subtitle_processor.prompt import OPTIMIZER_PROMPT
import json_repair
from app.core.utils.logger import setup_logger

logger = setup_logger("subtitle_optimizer")


class SubtitleOptimizer:
    """字幕优化器,支持缓存功能"""

    def __init__(
        self,
        thread_num: int = 5,
        batch_num: int = 10,
        model: str = "gpt-4o-mini",
        custom_prompt: str = "",
        temperature: float = 0.7,
        timeout: int = 60,
        retry_times: int = 1,
        update_callback: Optional[Callable] = None,
    ):
        self._init_client()
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.model = model
        self.custom_prompt = custom_prompt
        self.temperature = temperature
        self.timeout = timeout
        self.retry_times = retry_times
        self.is_running = True
        self.update_callback = update_callback
        self._init_thread_pool()
        self.cache_manager = CacheManager(str(CACHE_PATH))

    def _init_client(self):
        """初始化OpenAI客户端"""
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY")
        if not (base_url and api_key):
            raise ValueError("环境变量 OPENAI_BASE_URL 和 OPENAI_API_KEY 必须设置")

        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _init_thread_pool(self):
        """初始化线程池"""
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        import atexit

        atexit.register(self.stop)

    def optimize_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
        """优化字幕文件"""
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

            # 多线程优化
            optimized_dict = self._parallel_optimize(chunks)

            # 创建新的ASRDataSeg列表
            new_segments = self._create_segments(asr_data.segments, optimized_dict)

            return ASRData(new_segments)
        except Exception as e:
            logger.error(f"优化失败：{str(e)}")
            raise RuntimeError(f"优化失败：{str(e)}")

    def _split_chunks(self, subtitle_dict: Dict[str, str]) -> List[Dict[str, str]]:
        """将字幕分割成块"""
        items = list(subtitle_dict.items())
        return [
            dict(items[i : i + self.batch_num])
            for i in range(0, len(items), self.batch_num)
        ]

    def _parallel_optimize(self, chunks: List[Dict[str, str]]) -> Dict[str, str]:
        """并行优化所有块"""
        futures = []
        optimized_dict = {}

        for chunk in chunks:
            if not self.executor:
                raise ValueError("线程池未初始化")
            future = self.executor.submit(self._safe_optimize_chunk, chunk)
            futures.append(future)

        for future in as_completed(futures):
            if not self.is_running:
                logger.info("优化器已停止运行，退出优化")
                break
            try:
                result = future.result()
                optimized_dict.update(result)
            except Exception as e:
                logger.error(f"优化块失败：{str(e)}")
                # 对于失败的块，保留原文
                for k, v in chunk.items():
                    optimized_dict[k] = v

        return optimized_dict

    def _safe_optimize_chunk(self, chunk: Dict[str, str]) -> Dict[str, str]:
        """安全的优化块，包含重试逻辑"""
        for i in range(self.retry_times):
            try:
                return self._optimize_chunk(chunk)
            except Exception as e:
                if i == self.retry_times - 1:
                    raise
                logger.warning(f"优化重试 {i + 1}/{self.retry_times}: {str(e)}")
        return chunk

    def _optimize_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """优化字幕块"""
        logger.info(
            f"[+]正在优化字幕：{next(iter(subtitle_chunk))} - {next(reversed(subtitle_chunk))}"
        )
        user_prompt = f"Correct the following subtitles. Keep the original language, do not translate:\n<input_subtitle>{str(subtitle_chunk)}</input_subtitle>"
        if self.custom_prompt:
            user_prompt += (
                f"\nReference content:\n<prompt>{self.custom_prompt}</prompt>"
            )

        # 检查缓存
        cache_params = {
            "temperature": self.temperature,
            "model": self.model,
        }
        # 构建缓存key
        cache_key = f"{len(OPTIMIZER_PROMPT)}_{user_prompt}"
        cache_result = self.cache_manager.get_llm_result(
            cache_key, self.model, **cache_params
        )

        if cache_result:
            logger.info("使用缓存的优化结果")
            return json.loads(cache_result)

        # 构建提示词
        messages = [
            {"role": "system", "content": OPTIMIZER_PROMPT},
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        # 调用API优化
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore
            temperature=self.temperature,
            timeout=self.timeout,
        )

        # 解析结果
        result: Dict[str, str] = json_repair.loads(response.choices[0].message.content)  # type: ignore

        # 修复字幕对齐
        aligned_result = self._repair_subtitle(subtitle_chunk, result)

        # 保存到缓存
        self.cache_manager.set_llm_result(
            cache_key,
            json.dumps(aligned_result, ensure_ascii=False),
            self.model,
            **cache_params,
        )

        if self.update_callback:
            self.update_callback(aligned_result)

        return aligned_result

    @staticmethod
    def _repair_subtitle(
        original: Dict[str, str], optimized: Dict[str, str]
    ) -> Dict[str, str]:
        """修复字幕对齐问题"""
        aligner = SubtitleAligner()
        original_list = list(original.values())
        optimized_list = list(optimized.values())

        aligned_source, aligned_target = aligner.align_texts(
            original_list, optimized_list
        )

        if len(aligned_source) != len(aligned_target):
            raise ValueError("对齐后字幕长度不一致")

        # 构建对齐后的字典
        start_id = next(iter(original.keys()))
        return {str(int(start_id) + i): text for i, text in enumerate(aligned_target)}

    @staticmethod
    def _create_segments(
        original_segments: List[ASRDataSeg],
        optimized_dict: Dict[str, str],
    ) -> List[ASRDataSeg]:
        """创建新的字幕段"""
        return [
            ASRDataSeg(
                text=optimized_dict.get(str(i), seg.text),
                start_time=seg.start_time,
                end_time=seg.end_time,
            )
            for i, seg in enumerate(original_segments, 1)
        ]

    def stop(self):
        """停止优化器"""
        if not self.is_running:
            return

        logger.info("正在停止优化器...")
        self.is_running = False
        if hasattr(self, "executor") and self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.error(f"关闭线程池时出错：{str(e)}")
            finally:
                self.executor = None
