"""ASR 音频分块结果合并模块

基于精确/模糊文本匹配的音频分块合并算法（参考 Groq API Cookbook）。
使用滑动窗口找到最佳对齐位置，在重叠区域中点切分。

匹配策略：
- 词级时间戳（字级）: 精确文本匹配
- 句子级时间戳（非字级）: difflib 模糊匹配（相似度 > 0.7）
"""

import difflib
from typing import List, Optional

from ..utils.logger import setup_logger
from .asr_data import ASRData, ASRDataSeg

logger = setup_logger("chunk_merger")


class ChunkMerger:
    """音频分块后的 ASR 结果合并器

    使用滑动窗口算法找到最佳对齐位置，在重叠区域中点切分。
    适用于长音频分块识别后的结果拼接。
    """

    def __init__(self, min_match_count: int = 2, fuzzy_threshold: float = 0.7):
        """初始化合并器

        Args:
            min_match_count: 最小匹配数阈值，低于此值视为无效匹配
            fuzzy_threshold: 模糊匹配相似度阈值（仅用于句子级）
        """
        self.min_match_count = min_match_count
        self.fuzzy_threshold = fuzzy_threshold

    def merge_chunks(
        self,
        chunks: List[ASRData],
        chunk_offsets: Optional[List[int]] = None,
        overlap_duration: int = 10000,
    ) -> ASRData:
        """合并多个音频片段的 ASR 结果

        Args:
            chunks: ASRData 对象列表（每个 chunk 的 segments 应从 0 开始）
            chunk_offsets: 每个 chunk 的绝对时间偏移（毫秒），None 则自动推断
            overlap_duration: 重叠时长（毫秒），默认 10 秒

        Returns:
            合并后的 ASRData 对象

        Raises:
            ValueError: 如果 chunks 为空或 chunk_offsets 长度不匹配
        """
        if not chunks:
            raise ValueError("chunks 不能为空")

        if len(chunks) == 1:
            logger.info("只有一个 chunk，直接返回")
            return chunks[0]

        # 判断是否为词级时间戳（用于选择匹配策略）
        self._is_word_level = any(chunk.is_word_timestamp() for chunk in chunks)
        if self._is_word_level:
            logger.info("检测到词级时间戳，使用精确文本匹配")
        else:
            logger.info(
                f"检测到句子级时间戳，使用模糊匹配（阈值={self.fuzzy_threshold}）"
            )

        # 自动推断 offsets
        if chunk_offsets is None:
            chunk_offsets = self._infer_chunk_offsets(chunks, overlap_duration)
            logger.info(f"自动推断 chunk_offsets: {chunk_offsets}")

        if len(chunks) != len(chunk_offsets):
            raise ValueError(
                f"chunks 数量 ({len(chunks)}) 与 chunk_offsets 数量 ({len(chunk_offsets)}) 不匹配"
            )

        # 调整所有 chunk 的时间戳到绝对时间
        adjusted_chunks = [
            self._adjust_timestamps(chunk.segments, offset)
            for chunk, offset in zip(chunks, chunk_offsets)
        ]

        # 逐对合并
        merged_segments = adjusted_chunks[0]
        for i in range(1, len(adjusted_chunks)):
            logger.info(f"合并 chunk {i-1} 和 chunk {i}")
            merged_segments = self._merge_two_sequences(
                merged_segments,
                adjusted_chunks[i],
                overlap_duration,
            )

        logger.info(f"合并完成，总片段数: {len(merged_segments)}")
        return ASRData(merged_segments)

    def _merge_two_sequences(
        self,
        left: List[ASRDataSeg],
        right: List[ASRDataSeg],
        overlap_duration: int,
    ) -> List[ASRDataSeg]:
        """合并两个 segment 序列（Groq 滑动窗口算法）

        Args:
            left: 左侧序列（已调整到绝对时间）
            right: 右侧序列（已调整到绝对时间）
            overlap_duration: 预期重叠时长（毫秒）

        Returns:
            合并后的 segment 列表
        """
        if not left:
            return right
        if not right:
            return left

        left_len = len(left)

        # 提取重叠区域用于匹配
        left_overlap = self._extract_overlap_segments(
            left, from_end=True, duration=overlap_duration
        )
        right_overlap = self._extract_overlap_segments(
            right, from_end=False, duration=overlap_duration
        )

        if not left_overlap or not right_overlap:
            # 无重叠，直接拼接
            logger.info("未检测到重叠区域，直接拼接")
            return left + right

        # 滑动窗口找最佳对齐位置
        best_match = self._find_best_alignment(left_overlap, right_overlap)

        if best_match is None:
            # 未找到有效匹配，使用时间边界切分
            logger.warning("未找到有效文本匹配，使用时间边界切分")
            # 找到 left 中最后一个在 right[0].start_time 之前结束的 segment
            split_idx = left_len
            right_start = right[0].start_time
            for i in range(left_len - 1, -1, -1):
                if left[i].end_time <= right_start:
                    split_idx = i + 1
                    break
            logger.info(f"时间边界切分: left[:{split_idx}] + right")
            return left[:split_idx] + right

        # 使用最佳匹配结果
        left_start_idx, left_end_idx, right_start_idx, right_end_idx, matches = (
            best_match
        )

        # 计算中点：在重叠区域取中间��置
        left_mid = (left_start_idx + left_end_idx) // 2
        right_mid = (right_start_idx + right_end_idx) // 2

        # 映射回原始序列的索引
        left_overlap_offset = left_len - len(left_overlap)
        left_cut = left_overlap_offset + left_mid

        logger.info(
            f"找到最佳匹配: {matches} 个词, "
            f"重叠区域=[{left_start_idx}:{left_end_idx}] vs [{right_start_idx}:{right_end_idx}], "
            f"切分点: left[:{left_cut}] + right[{right_mid}:]"
        )

        # 合并：左边取到中点，右边从中点开始
        return left[:left_cut] + right[right_mid:]

    def _find_best_alignment(
        self,
        left: List[ASRDataSeg],
        right: List[ASRDataSeg],
    ) -> Optional[tuple[int, int, int, int, int]]:
        """使用滑动窗口找最佳对齐位置（Groq 算法）

        Args:
            left: 左侧重叠区域
            right: 右侧重叠区域

        Returns:
            (left_start, left_end, right_start, right_end, matches) 或 None
            - left_start/end: left 序列的匹配区域索引
            - right_start/end: right 序列的匹配区域索引
            - matches: 匹配数量
        """
        left_len = len(left)
        right_len = len(right)

        best_score = 0.0
        best_result = None

        # 滑动窗口：尝试所有对齐位置
        for i in range(1, left_len + right_len + 1):
            # epsilon: 偏好更长的匹配
            epsilon = float(i) / 10000.0

            # 计算当前对齐位置的重叠区域
            left_start = max(0, left_len - i)
            left_end = min(left_len, left_len + right_len - i)

            right_start = max(0, i - left_len)
            right_end = min(right_len, i)

            # 提取重叠部分
            left_slice = left[left_start:left_end]
            right_slice = right[right_start:right_end]

            if len(left_slice) != len(right_slice):
                raise RuntimeError(
                    f"对齐错误: left[{left_start}:{left_end}]={len(left_slice)} "
                    f"vs right[{right_start}:{right_end}]={len(right_slice)}"
                )

            # 计算匹配数（词级用精确匹配，句子级用模糊匹配）
            if self._is_word_level:
                # 词级：精确匹配
                matches = sum(
                    1
                    for left_seg, right_seg in zip(left_slice, right_slice)
                    if left_seg.text == right_seg.text
                )
            else:
                # 句子级：模糊匹配（difflib 相似度 > threshold）
                matches = sum(
                    1
                    for left_seg, right_seg in zip(left_slice, right_slice)
                    if difflib.SequenceMatcher(
                        None, left_seg.text, right_seg.text
                    ).ratio()
                    > self.fuzzy_threshold
                )

            # 归一化得分 + epsilon（偏好长匹配）
            score = matches / float(i) + epsilon

            # 至少需要 min_match_count 个匹配
            if matches >= self.min_match_count and score > best_score:
                best_score = score
                best_result = (left_start, left_end, right_start, right_end, matches)

        return best_result

    def _adjust_timestamps(
        self, segments: List[ASRDataSeg], offset: int
    ) -> List[ASRDataSeg]:
        """调整 segments 时间戳

        Args:
            segments: 原始片段列表
            offset: 时间偏移量（毫秒）

        Returns:
            调整后的片段列表（新对象）
        """
        return [
            ASRDataSeg(
                text=seg.text,
                start_time=seg.start_time + offset,
                end_time=seg.end_time + offset,
                translated_text=seg.translated_text,
            )
            for seg in segments
        ]

    def _extract_overlap_segments(
        self, segments: List[ASRDataSeg], from_end: bool, duration: int
    ) -> List[ASRDataSeg]:
        """提取重叠区域的 segments

        Args:
            segments: segment 列表
            from_end: True=从末尾提取，False=从开头提取
            duration: 提取时长（毫秒）

        Returns:
            重叠区域的 segment 列表
        """
        if not segments:
            return []

        overlap = []

        if from_end:
            # 从末尾往前提取
            threshold = segments[-1].end_time - duration
            for seg in reversed(segments):
                if seg.start_time >= threshold:
                    overlap.insert(0, seg)
                else:
                    break
        else:
            # 从开头往后提取
            threshold = segments[0].start_time + duration
            for seg in segments:
                if seg.end_time <= threshold:
                    overlap.append(seg)
                else:
                    break

        return overlap

    def _infer_chunk_offsets(
        self, chunks: List[ASRData], overlap_duration: int
    ) -> List[int]:
        """自动推断 chunk 的时间偏移

        Args:
            chunks: ASRData 列表
            overlap_duration: 重叠时长（毫秒）

        Returns:
            推断的时间偏移列表
        """
        offsets = [0]

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            if prev_chunk.segments:
                # 下一个 chunk 的起始 = 上一个 chunk 结束 - 重叠时长
                prev_end = prev_chunk.segments[-1].end_time
                next_offset = offsets[-1] + prev_end - overlap_duration
                offsets.append(max(next_offset, offsets[-1]))
            else:
                offsets.append(offsets[-1])

        return offsets
