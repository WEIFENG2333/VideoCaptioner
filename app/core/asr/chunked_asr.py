"""音频分块 ASR 装饰器

为任何 BaseASR 实现添加音频分块转录能力，适用于长音频处理。
使用装饰器模式实现关注点分离。
"""

import io
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from pydub import AudioSegment

from ..utils.logger import setup_logger
from .asr_data import ASRData
from .base import BaseASR
from .chunk_merger import ChunkMerger

logger = setup_logger("chunked_asr")

# 常量定义
MS_PER_SECOND = 1000
DEFAULT_CHUNK_LENGTH_SEC = 60 * 10  # 20分钟
DEFAULT_CHUNK_OVERLAP_SEC = 10  # 10秒重叠
DEFAULT_CHUNK_CONCURRENCY = 3  # 3个并发


class ChunkedASR:
    """音频分块 ASR 包装器

    为任何 BaseASR 子类添加音频分块能力。
    适用于长音频的分块转录，避免 API 超时或内存溢出。

    工作流程：
        1. 将长音频切割为多个重叠的块
        2. 为每个块创建独立的 ASR 实例并发转录
        3. 使用 ChunkMerger 合并结果，消除重叠区域的重复内容

    示例:
        >>> # 使用 ASR 类和参数创建分块转录器
        >>> chunked_asr = ChunkedASR(
        ...     asr_class=BcutASR,
        ...     audio_path="long_audio.mp3",
        ...     asr_kwargs={"need_word_time_stamp": True},
        ...     chunk_length=1200
        ... )
        >>> result = chunked_asr.run(callback)

    Args:
        asr_class: ASR 类（非实例），如 BcutASR, JianYingASR
        audio_path: 音频文件路径
        asr_kwargs: 传递给 ASR 构造函数的参数字典
        chunk_length: 每块长度（秒），默认 480 秒（8分钟）
        chunk_overlap: 块之间重叠时长（秒），默认 10 秒
        chunk_concurrency: 并发转录数量，默认 3
    """

    def __init__(
        self,
        asr_class: type[BaseASR],
        audio_path: str,
        asr_kwargs: Optional[dict] = None,
        chunk_length: int = DEFAULT_CHUNK_LENGTH_SEC,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_SEC,
        chunk_concurrency: int = DEFAULT_CHUNK_CONCURRENCY,
    ):
        self.asr_class = asr_class
        self.audio_path = audio_path
        self.asr_kwargs = asr_kwargs or {}
        self.chunk_length_ms = chunk_length * MS_PER_SECOND
        self.chunk_overlap_ms = chunk_overlap * MS_PER_SECOND
        self.chunk_concurrency = chunk_concurrency

        # 读取完整音频文件（用于分块）
        with open(audio_path, "rb") as f:
            self.file_binary = f.read()

    def run(self, callback: Optional[Callable[[int, str], None]] = None) -> ASRData:
        """执行分块转录

        Args:
            callback: 进度回调函数(progress: int, message: str)

        Returns:
            ASRData: 合并后的转录结果
        """
        # 1. 分块音频
        chunks = self._split_audio()

        # 2. 如果只有一块，直接创建单个 ASR 实例转录
        if len(chunks) == 1:
            logger.info("音频短于分块长度，直接转录")
            single_asr = self.asr_class(self.audio_path, **self.asr_kwargs)
            return single_asr.run(callback)

        logger.info(f"音频分为 {len(chunks)} 块，开始并发转录")

        # 3. 并发转录所有块
        chunk_results = self._transcribe_chunks(chunks, callback)

        # 4. 合并结果
        merged_result = self._merge_results(chunk_results, chunks)

        logger.info(f"分块转录完成，共 {len(merged_result.segments)} 个片段")
        return merged_result

    def _split_audio(self) -> List[Tuple[bytes, int]]:
        """使用 pydub 将音频切割为重叠的块

        Returns:
            List[(chunk_bytes, offset_ms), ...]
            每个元素包含音频块的字节数据和时间偏移（毫秒）
        """
        # 从字节数据加载音频
        if self.file_binary is None:
            raise ValueError("file_binary is None, cannot split audio")

        audio = AudioSegment.from_file(io.BytesIO(self.file_binary))
        total_duration_ms = len(audio)

        logger.info(
            f"音频总时长: {total_duration_ms/1000:.1f}s, "
            f"分块长度: {self.chunk_length_ms/1000:.1f}s, "
            f"重叠: {self.chunk_overlap_ms/1000:.1f}s"
        )

        chunks = []
        start_ms = 0

        while start_ms < total_duration_ms:
            end_ms = min(start_ms + self.chunk_length_ms, total_duration_ms)
            chunk = audio[start_ms:end_ms]

            buffer = io.BytesIO()
            chunk.export(buffer, format="mp3")
            chunk_bytes = buffer.getvalue()

            chunks.append((chunk_bytes, start_ms))
            logger.debug(
                f"切割 chunk {len(chunks)}: "
                f"{start_ms/1000:.1f}s - {end_ms/1000:.1f}s ({len(chunk_bytes)} bytes)"
            )

            # 下一个块的起始位置（有重叠）
            start_ms += self.chunk_length_ms - self.chunk_overlap_ms

            # 如果已到末尾，停止
            if end_ms >= total_duration_ms:
                break

        # logger.info(f"音频切割完成，共 {len(chunks)} 个块")
        return chunks

    def _transcribe_chunks(
        self,
        chunks: List[Tuple[bytes, int]],
        callback: Optional[Callable[[int, str], None]],
    ) -> List[ASRData]:
        """并发转录多个音频块

        Args:
            chunks: 音频块列表 [(chunk_bytes, offset_ms), ...]
            callback: 进度回调

        Returns:
            List[ASRData]: 每个块的转录结果
        """
        results: List[Optional[ASRData]] = [None] * len(chunks)
        total_chunks = len(chunks)

        # 进度追踪：记录每个 chunk 的进度，确保整体进度单调递增
        chunk_progress = [0] * total_chunks
        last_overall = 0
        progress_lock = threading.Lock()

        def transcribe_single_chunk(
            idx: int, chunk_bytes: bytes, offset_ms: int
        ) -> Tuple[int, ASRData]:
            """转录单个音频块 - 为每个块创建独立的 ASR 实例"""
            nonlocal last_overall
            logger.info(f"开始转录 chunk {idx+1}/{total_chunks} (offset={offset_ms}ms)")

            def chunk_callback(progress: int, message: str):
                nonlocal last_overall
                if not callback:
                    return
                with progress_lock:
                    chunk_progress[idx] = progress
                    overall = sum(chunk_progress) // total_chunks
                    # 只允许进度单调递增
                    if overall > last_overall:
                        last_overall = overall
                        callback(overall, f"{idx+1}/{total_chunks}: {message}")

            # 为当前 chunk 创建独立的 ASR 实例
            # 使用 chunk_bytes 作为音频输入
            chunk_asr = self.asr_class(chunk_bytes, **self.asr_kwargs)

            # 调用 ASR 的 run() 方法转录
            asr_data = chunk_asr.run(chunk_callback)

            logger.info(
                f"Chunk {idx+1}/{total_chunks} 转录完成，"
                f"获得 {len(asr_data.segments)} 个片段"
            )
            return idx, asr_data

        # 使用 ThreadPoolExecutor 并发转录
        with ThreadPoolExecutor(max_workers=self.chunk_concurrency) as executor:
            futures = {
                executor.submit(transcribe_single_chunk, i, chunk_bytes, offset): i
                for i, (chunk_bytes, offset) in enumerate(chunks)
            }

            for future in as_completed(futures):
                idx, asr_data = future.result()
                results[idx] = asr_data

        logger.info(f"所有 {total_chunks} 个块转录完成")
        return [r for r in results if r is not None]  # 过滤 None

    def _merge_results(
        self, chunk_results: List[ASRData], chunks: List[Tuple[bytes, int]]
    ) -> ASRData:
        """使用 ChunkMerger 合并转录结果

        Args:
            chunk_results: 每个块的 ASRData 结果
            chunks: 原始音频块信息（用于获取 offset）

        Returns:
            合并后的 ASRData
        """
        merger = ChunkMerger(min_match_count=2, fuzzy_threshold=0.7)

        # 提取每个 chunk 的时间偏移
        chunk_offsets = [offset for _, offset in chunks]

        # 合并
        merged = merger.merge_chunks(
            chunks=chunk_results,
            chunk_offsets=chunk_offsets,
            overlap_duration=self.chunk_overlap_ms,
        )
        return merged
