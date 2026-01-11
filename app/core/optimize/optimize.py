"""字幕优化模块

使用LLM优化字幕内容，支持agent loop自动验证和修正。
"""

import atexit
import difflib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple, Union

import json_repair

from ..asr.asr_data import ASRData, ASRDataSeg
from ..entities import SubtitleProcessData
from ..llm import call_llm
from ..prompts import get_prompt
from ..split.alignment import SubtitleAligner
from ..utils.logger import setup_logger
from ..utils.text_utils import count_words

logger = setup_logger("subtitle_optimizer")

MAX_STEPS = 3


class SubtitleOptimizer:
    """字幕优化器

    使用LLM优化字幕内容，支持：
    - Agent loop自动验证和修正
    - 并发批量处理
    - 自动对齐修复
    """

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        model: str,
        custom_prompt: str,
        update_callback: Optional[Callable] = None,
    ):
        """初始化优化器

        Args:
            thread_num: 并发线程数
            batch_num: 每批处理的字幕数量
            model: LLM模型名称
            custom_prompt: 自定义优化提示词
            temperature: LLM温度参数
            update_callback: 进度更新回调函数
        """
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.model = model
        self.custom_prompt = custom_prompt
        self.update_callback = update_callback

        self.is_running = True
        self.executor: Optional[ThreadPoolExecutor] = None
        self._init_thread_pool()

    def _init_thread_pool(self) -> None:
        """初始化线程池并注册清理函数"""
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    def optimize_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
        """优化字幕

        Args:
            subtitle_data: 字幕文件路径或ASRData对象

        Returns:
            优化后的ASRData对象
        """
        try:
            # 读取字幕
            if isinstance(subtitle_data, str):
                asr_data = ASRData.from_subtitle_file(subtitle_data)
            else:
                asr_data = subtitle_data

            # 转换为字典格式
            subtitle_dict = {
                str(i): seg.text for i, seg in enumerate(asr_data.segments, 1)
            }

            # 分批处理
            chunks = self._split_chunks(subtitle_dict)

            # 并行优化
            optimized_dict = self._parallel_optimize(chunks)

            # 创建新segments
            new_segments = self._create_segments(asr_data.segments, optimized_dict)

            return ASRData(new_segments)

        except Exception as e:
            logger.error(f"优化失败：{str(e)}")
            raise RuntimeError(f"优化失败：{str(e)}")

    def _split_chunks(self, subtitle_dict: Dict[str, str]) -> List[Dict[str, str]]:
        """将字幕字典分割成批次

        Args:
            subtitle_dict: 字幕字典 {index: text}

        Returns:
            批次列表
        """
        items = list(subtitle_dict.items())
        return [
            dict(items[i : i + self.batch_num])
            for i in range(0, len(items), self.batch_num)
        ]

    def _parallel_optimize(self, chunks: List[Dict[str, str]]) -> Dict[str, str]:
        """并行优化所有批次

        Args:
            chunks: 字幕批次列表

        Returns:
            优化后的字幕字典
        """
        if not self.executor:
            raise ValueError("线程池未初始化")

        futures = []
        optimized_dict: Dict[str, str] = {}

        # 提交所有任务
        for chunk in chunks:
            future = self.executor.submit(self._optimize_chunk, chunk)
            futures.append((future, chunk))

        # 收集结果
        for future, chunk in futures:
            if not self.is_running:
                break

            try:
                result = future.result()
                optimized_dict.update(result)
            except Exception as e:
                logger.error(f"优化批次失败：{str(e)}")
                optimized_dict.update(chunk)  # 失败时保留原文

        return optimized_dict

    def _optimize_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """优化单个字幕批次

        Args:
            subtitle_chunk: 字幕批次字典

        Returns:
            优化后的字幕批次
        """
        start_idx = next(iter(subtitle_chunk))
        end_idx = next(reversed(subtitle_chunk))
        logger.info(f"[+]正在优化字幕：{start_idx} - {end_idx}")

        try:
            result = self.agent_loop(subtitle_chunk)

            if self.update_callback:
                callback_data = [
                    SubtitleProcessData(
                        index=int(idx),
                        original_text=subtitle_chunk[idx],
                        optimized_text=result[idx],
                    )
                    for idx in sorted(result.keys(), key=int)
                ]
                self.update_callback(callback_data)

            return result

        except Exception as e:
            logger.error(f"优化失败：{str(e)}")
            return subtitle_chunk

    def agent_loop(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """使用agent loop优化字幕

        LLM → 验证 → 反馈 → 重试 (最多MAX_STEPS次)

        Args:
            subtitle_chunk: 字幕批次字典

        Returns:
            优化后的字幕批次

        Raises:
            ValueError: LLM返回空结果
        """
        # 构建提示词
        user_prompt = (
            f"Correct the following subtitles. Keep the original language, do not translate:\n"
            f"<input_subtitle>{str(subtitle_chunk)}</input_subtitle>"
        )

        if self.custom_prompt:
            user_prompt += (
                f"\nReference content:\n<reference>{self.custom_prompt}</reference>"
            )

        messages = [
            {"role": "system", "content": get_prompt("optimize/subtitle")},
            {"role": "user", "content": user_prompt},
        ]

        last_result = None

        # Agent loop
        for step in range(MAX_STEPS):
            # 调用LLM
            response = call_llm(
                messages=messages,
                model=self.model,
                temperature=0.2,
            )

            result_text = response.choices[0].message.content
            if not result_text:
                raise ValueError("LLM返回空结果")

            # 解析结果
            parsed_result = json_repair.loads(result_text)
            if not isinstance(parsed_result, dict):
                raise ValueError(
                    f"LLM返回结果类型错误，期望dict，实际{type(parsed_result)}"
                )

            result_dict: Dict[str, str] = parsed_result
            last_result = result_dict

            # 验证结果
            is_valid, error_message = self._validate_optimization_result(
                original_chunk=subtitle_chunk, optimized_chunk=result_dict
            )

            if is_valid:
                return self._repair_subtitle(subtitle_chunk, result_dict)

            # 验证失败，添加反馈
            logger.warning(
                f"优化验证失败，开始反馈循环 (第{step + 1}次尝试): {error_message}"
            )
            messages.append({"role": "assistant", "content": result_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Validation failed: {error_message}\n"
                        f"Please fix the errors and output ONLY a valid JSON dictionary."
                    ),
                }
            )

        # 达到最大步数
        logger.warning(f"达到最大尝试次数({MAX_STEPS})，返回最后结果")
        return (
            self._repair_subtitle(subtitle_chunk, last_result)
            if last_result
            else subtitle_chunk
        )

    def _validate_optimization_result(
        self, original_chunk: Dict[str, str], optimized_chunk: Dict[str, str]
    ) -> Tuple[bool, str]:
        """验证优化结果

        检查：
        1. 键是否完全匹配
        2. 改动是否过大（相似度 < 0.7）

        Args:
            original_chunk: 原始字幕批次
            optimized_chunk: 优化后字幕批次

        Returns:
            (是否有效, 错误反馈)
        """
        expected_keys = set(original_chunk.keys())
        actual_keys = set(optimized_chunk.keys())

        # 检查键匹配
        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys

            error_parts = []
            if missing:
                error_parts.append(f"Missing keys: {sorted(missing)}")
            if extra:
                error_parts.append(f"Extra keys: {sorted(extra)}")

            error_msg = (
                "\n".join(error_parts) + f"\nRequired keys: {sorted(expected_keys)}\n"
                f"Please return the COMPLETE optimized dictionary with ALL {len(expected_keys)} keys."
            )
            return False, error_msg

        # 检查改动是否过大（逐条比较相似度）
        excessive_changes = []
        for key in expected_keys:
            original_text = original_chunk[key]
            optimized_text = optimized_chunk[key]

            # 清理文本用于比较
            original_cleaned = re.sub(r"\s+", " ", original_text).strip()
            optimized_cleaned = re.sub(r"\s+", " ", optimized_text).strip()

            # 计算相似度
            matcher = difflib.SequenceMatcher(None, original_cleaned, optimized_cleaned)
            similarity = matcher.ratio()
            similarity_threshold = 0.3 if count_words(original_text) <= 10 else 0.7

            # 相似度过低
            if similarity < similarity_threshold:
                excessive_changes.append(
                    f"Key '{key}': similarity {similarity:.1%} < {similarity_threshold:.0%}. "
                    f"Original: '{original_text}' → Optimized: '{optimized_text}' "
                )

        if excessive_changes:
            error_msg = ";\n".join(excessive_changes)
            error_msg += (
                "\n\nYour optimizations changed the text too much. "
                "Keep high similarity (≥70% for normal text) by making MINIMAL changes: "
                "only fix recognition errors and improve clarity, "
                "but preserve the original wording, length and structure as much as possible."
            )
            return False, error_msg

        return True, ""

    @staticmethod
    def _repair_subtitle(
        original: Dict[str, str], optimized: Dict[str, str]
    ) -> Dict[str, str]:
        """修复字幕对齐

        使用SubtitleAligner对齐原文和优化后的文本，
        处理优化过程中可能产生的段落合并或拆分。

        Args:
            original: 原始字幕字典
            optimized: 优化后字幕字典

        Returns:
            对齐后的字幕字典
        """
        try:
            aligner = SubtitleAligner()
            original_list = list(original.values())
            optimized_list = list(optimized.values())

            aligned_source, aligned_target = aligner.align_texts(
                original_list, optimized_list
            )

            if len(aligned_source) != len(aligned_target):
                logger.warning("对齐后长度不一致，返回原优化结果")
                return optimized

            # 重建字典，保持原有索引
            start_id = next(iter(original.keys()))
            return {
                str(int(start_id) + i): text for i, text in enumerate(aligned_target)
            }

        except Exception as e:
            logger.error(f"对齐失败：{str(e)}，返回原优化结果")
            return optimized

    @staticmethod
    def _create_segments(
        original_segments: List[ASRDataSeg],
        optimized_dict: Dict[str, str],
    ) -> List[ASRDataSeg]:
        """从优化字典创建新的ASRDataSeg列表

        Args:
            original_segments: 原始字幕段列表
            optimized_dict: 优化后字幕字典

        Returns:
            新的字幕段列表
        """
        return [
            ASRDataSeg(
                text=optimized_dict.get(str(i), seg.text),
                start_time=seg.start_time,
                end_time=seg.end_time,
            )
            for i, seg in enumerate(original_segments, 1)
        ]

    def stop(self) -> None:
        """停止优化器并清理资源"""
        if not self.is_running:
            return

        self.is_running = False

        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            finally:
                self.executor = None
