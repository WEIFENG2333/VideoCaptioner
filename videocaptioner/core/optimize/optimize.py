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


class LLMFatalError(RuntimeError):
    """LLM 确定性硬失败（鉴权失效 / 余额不足 / 配额用尽等）。

    这类错误重试也不会好，应立即中止整个流程并给一条清晰提示，而不是逐批吞掉、
    刷屏几十条相同 ERROR 后硬撑到下一步才失败。
    """


_FATAL_LLM_STATUS = {401, 402, 403}
_FATAL_LLM_HINTS = (
    "balance",
    "insufficient",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "quota",
    "permission denied",
)


def _is_fatal_llm_error(exc: Exception) -> bool:
    """判断 LLM 异常是否为鉴权/余额类确定性硬失败（重试无意义）。"""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _FATAL_LLM_STATUS:
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _FATAL_LLM_HINTS)


# 相似度过低时，允许的"新增内容"占比上限。口语字幕优化以删除填充词/口吃为主
# （optimized ⊆ original），字符相似度天然偏低但属于期望行为；只有当改动很大且
# 引入大量原文没有的新内容（改写/翻译/幻觉）时才判为过度改动。
NOVELTY_LIMIT = 0.15

# 内容词切分：拉丁词整段、CJK 逐字（忽略标点/空白）。新增内容占比在词/字粒度上
# 计算——字符级在句首删词后会碎片化误判合法删减为"新增"。
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]")


def _content_tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class SubtitleOptimizer:
    """字幕优化器

    使用LLM优化字幕内容，支持:
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
            # Reading字幕
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

        except LLMFatalError:
            raise  # 保留清晰的硬失败原文（余额/鉴权），不包成通用错误
        except Exception as e:
            logger.error(f"Optimization failed: {str(e)}")
            raise RuntimeError(f"Optimization failed: {str(e)}")

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
        """并行优化All批次

        Args:
            chunks: 字幕批次列表

        Returns:
            优化后的字幕字典
        """
        if not self.executor:
            raise ValueError("Thread pool not initialized")

        futures = []
        optimized_dict: Dict[str, str] = {}

        # 提交All任务
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
            except LLMFatalError:
                # 鉴权/余额类硬失败：立即中止，取消其余批次，避免刷屏几十条相同错误
                self.stop()
                raise
            except Exception as e:
                logger.error(f"Optimization batch failed: {str(e)}")
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
        logger.debug(f"[+]Optimizing subtitles: {start_idx} - {end_idx}")

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

        except LLMFatalError:
            raise  # 鉴权/余额类硬失败：向上冒泡以立即中止，不逐批吞掉
        except Exception as e:
            logger.error(f"Optimization failed: {str(e)}")
            return subtitle_chunk

    def agent_loop(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        """使用 agent loop 优化字幕。

        逐行校验，只对未通过的行发起反馈重试（而非整批重发），
        大幅降低口语素材下的重试放大。

        Args:
            subtitle_chunk: 字幕批次字典

        Returns:
            优化后的字幕批次（键与顺序与输入一致）

        Raises:
            ValueError: LLM returned empty result
        """
        accepted: Dict[str, str] = {}
        best_effort = dict(subtitle_chunk)  # 每行的最优尝试，用尽重试后兜底
        pending = dict(subtitle_chunk)  # 仍需优化的行

        for step in range(MAX_STEPS):
            result_dict = self._request_optimization(pending, retry=step > 0)

            newly_valid: Dict[str, str] = {}
            still_pending: Dict[str, str] = {}
            for key, original_text in pending.items():
                optimized_text = result_dict.get(key)
                if not isinstance(optimized_text, str) or not optimized_text.strip():
                    # 缺键或空结果：保留原文继续重试
                    still_pending[key] = original_text
                    continue
                best_effort[key] = optimized_text
                if self._line_is_valid(original_text, optimized_text)[0]:
                    newly_valid[key] = optimized_text
                else:
                    still_pending[key] = original_text

            accepted.update(newly_valid)

            if not still_pending:
                break

            logger.warning(
                f"优化验证未通过 {len(still_pending)} 行，仅重试这些行 (第{step + 1}次尝试)"
            )
            pending = still_pending

        # 用尽重试：残余行取最优尝试兜底（尽量保留清理效果，而非退回原文）
        for key in pending:
            accepted[key] = best_effort.get(key, subtitle_chunk[key])

        # 恢复输入顺序后再对齐修复
        ordered = {key: accepted[key] for key in subtitle_chunk}
        return self._repair_subtitle(subtitle_chunk, ordered)

    def _request_optimization(
        self, subtitle_chunk: Dict[str, str], retry: bool = False
    ) -> Dict[str, str]:
        """对一批字幕发起一次 LLM 优化请求并解析为字典。

        Args:
            subtitle_chunk: 待优化的字幕行
            retry: 是否为重试请求（会追加"仅删减、勿改写"的强约束）

        Returns:
            优化后的字幕字典（键统一为字符串）
        """
        user_prompt = (
            "Correct the following subtitles. Keep the original language, do not translate:\n"
            f"<input_subtitle>{str(subtitle_chunk)}</input_subtitle>"
        )
        if retry:
            user_prompt += (
                "\nThese lines were flagged for changing the wording too much. "
                "Only fix clear recognition errors and drop filler words; do NOT add "
                "new content or rephrase. Output ONLY a valid JSON dictionary with the "
                "same keys."
            )
        if self.custom_prompt:
            user_prompt += (
                f"\nReference content:\n<reference>{self.custom_prompt}</reference>"
            )

        messages = [
            {"role": "system", "content": get_prompt("optimize/subtitle")},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = call_llm(messages=messages, model=self.model)
        except Exception as e:
            if _is_fatal_llm_error(e):
                raise LLMFatalError(str(e)) from e
            raise
        result_text = response.choices[0].message.content
        if not result_text:
            raise ValueError("LLM returned empty result")

        parsed_result = json_repair.loads(result_text)
        if not isinstance(parsed_result, dict):
            raise ValueError(
                f"LLM返回结果类型Error，期望dict，实际{type(parsed_result)}"
            )
        return {str(key): value for key, value in parsed_result.items()}

    def _line_is_valid(
        self, original_text: str, optimized_text: str
    ) -> Tuple[bool, str]:
        """判断单行优化是否忠实于原文。

        口语字幕优化的核心动作是删除填充词/口吃（optimized ⊆ original），字符级
        相似度会天然偏低但属于期望行为。因此仅当"改动很大"且"引入大量原文没有的
        新内容"（改写/翻译/幻觉）时才判为过度改动；单纯删减一律放行。

        Returns:
            (是否忠实, 失败原因)
        """
        original_cleaned = re.sub(r"\s+", " ", original_text).strip()
        optimized_cleaned = re.sub(r"\s+", " ", optimized_text).strip()

        similarity = difflib.SequenceMatcher(
            None, original_cleaned, optimized_cleaned
        ).ratio()
        threshold = 0.3 if count_words(original_text) <= 10 else 0.7
        if similarity >= threshold:
            return True, ""

        # 相似度低：在词/字粒度上区分"忠实删减"与"改写/新增"。
        original_tokens = _content_tokens(original_cleaned)
        optimized_tokens = _content_tokens(optimized_cleaned)
        if not optimized_tokens:
            return False, (
                f"empty optimization. Original: '{original_text}' → Optimized: '{optimized_text}'"
            )
        matched = sum(
            block.size
            for block in difflib.SequenceMatcher(
                None, original_tokens, optimized_tokens
            ).get_matching_blocks()
        )
        novelty = 1.0 - (matched / len(optimized_tokens))
        if novelty <= NOVELTY_LIMIT:
            return True, ""

        return False, (
            f"similarity {similarity:.1%} < {threshold:.0%}, {novelty:.0%} new content. "
            f"Original: '{original_text}' → Optimized: '{optimized_text}'"
        )

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
                logger.warning("Alignment length mismatch，returning original")
                return optimized

            # 重建字典，保持原有索引
            start_id = next(iter(original.keys()))
            return {
                str(int(start_id) + i): text for i, text in enumerate(aligned_target)
            }

        except Exception as e:
            logger.error(f"Alignment failed: {str(e)}，returning original")
            return optimized

    @staticmethod
    def _create_segments(
        original_segments: List[ASRDataSeg],
        optimized_dict: Dict[str, str],
    ) -> List[ASRDataSeg]:
        """从优化字典创建新的ASRDataSeg列表

        Args:
            original_segments: 原始Subtitle segment列表
            optimized_dict: 优化后字幕字典

        Returns:
            新的Subtitle segment列表
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
