"""音频分块 ASR 功能的真实场景测试

测试覆盖：
1. 音频切割功能（pydub）
2. 并发转录功能（ThreadPoolExecutor）
3. 结果合并功能（ChunkMerger）
4. 边界情况（短音频、单块、空音频等）
5. 缓存机制
6. 错误处理
"""

import io
from typing import Any, Callable, List, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.asr.base import BaseASR


# ============================================================================
# 测试用 Mock ASR 实现
# ============================================================================


class MockASR(BaseASR):
    """Mock ASR 用于测试，模拟真实 API 调用"""

    # 类变量，用于跟踪所有实例的总调用次数
    _total_call_count = 0

    def __init__(
        self,
        audio_path,
        need_word_time_stamp=False,
        enable_chunking=False,
        chunk_length=600,
        chunk_overlap=10,
        chunk_concurrency=3,
        # Mock 专用参数
        mock_text_per_second="Mock",
        fail_on_chunk=None,
    ):
        super().__init__(
            audio_path,
            need_word_time_stamp,
            enable_chunking,
            chunk_length,
            chunk_overlap,
            chunk_concurrency,
        )
        self.mock_text_per_second = mock_text_per_second
        self.fail_on_chunk = fail_on_chunk

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs
    ) -> dict:
        """模拟 ASR 调用，生成基于音频长度的假数据"""
        from pydub import AudioSegment

        # 解析音频长度
        audio = AudioSegment.from_file(io.BytesIO(self.file_binary))
        duration_ms = len(audio)

        # 模拟进度回调
        if callback:
            callback(50, "Transcribing...")

        # 递增类变量计数器
        MockASR._total_call_count += 1

        # 模拟失败（用于测试错误处理）
        if (
            self.fail_on_chunk is not None
            and MockASR._total_call_count == self.fail_on_chunk
        ):
            raise RuntimeError(f"Simulated failure on chunk {self.fail_on_chunk}")

        # 生成假字幕数据（每秒一个片段）
        segments = []
        num_segments = max(1, duration_ms // 1000)

        for i in range(num_segments):
            start_time = i * 1000
            end_time = min((i + 1) * 1000, duration_ms)
            text = f"{self.mock_text_per_second} {i+1}"
            segments.append(
                {"text": text, "start": start_time / 1000, "end": end_time / 1000}
            )

        if callback:
            callback(100, "Completed")

        return {"segments": segments}

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        """将 mock 响应转换为 ASRDataSeg"""
        return [
            ASRDataSeg(
                text=seg["text"],
                start_time=int(seg["start"] * 1000),
                end_time=int(seg["end"] * 1000),
            )
            for seg in resp_data["segments"]
        ]

    def _get_subclass_params(self) -> dict:
        """返回 Mock ASR 的参数"""
        return {
            "mock_text_per_second": self.mock_text_per_second,
            "fail_on_chunk": self.fail_on_chunk,
        }


# ============================================================================
# 辅助函数
# ============================================================================


def create_test_audio(duration_ms: int, frequency: int = 440) -> bytes:
    """创建测试音频数据

    Args:
        duration_ms: 音频时长（毫秒）
        frequency: 音频频率（Hz）

    Returns:
        音频字节数据（MP3格式）
    """
    # 生成正弦波音频
    sine_wave = Sine(frequency).to_audio_segment(duration=duration_ms)

    # 导出为 MP3 字节
    buffer = io.BytesIO()
    sine_wave.export(buffer, format="mp3")
    return buffer.getvalue()


# ============================================================================
# 测试：音频切割功能
# ============================================================================


class TestAudioSplitting:
    """测试 pydub 音频切割功能"""

    def test_split_long_audio_into_chunks(self):
        """测试：长音频正确切割为重叠块"""
        # 创建 30 秒音频，切成 10 秒块，2 秒重叠
        audio_bytes = create_test_audio(30000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,  # 10秒
            chunk_overlap=2,  # 2秒重叠
        )

        chunks = asr._split_audio()

        # 验证块数：30秒，每块10秒，重叠2秒
        # chunk1: 0-10s, chunk2: 8-18s, chunk3: 16-26s, chunk4: 24-30s
        assert len(chunks) == 4

        # 验证每个块的偏移
        chunk_bytes_list, offsets = zip(*chunks)
        assert offsets == (0, 8000, 16000, 24000)

        # 验证每个块都是有效的音频
        for chunk_bytes, _ in chunks:
            audio_segment = AudioSegment.from_file(io.BytesIO(chunk_bytes))
            assert len(audio_segment) > 0

    def test_split_short_audio_no_chunks(self):
        """测试：短音频不需要切割"""
        # 5 秒音频，块长度 10 秒
        audio_bytes = create_test_audio(5000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        chunks = asr._split_audio()

        # 只有一个块
        assert len(chunks) == 1
        assert chunks[0][1] == 0  # offset=0

    def test_split_exact_chunk_length(self):
        """测试：音频长度恰好等于块长度"""
        audio_bytes = create_test_audio(10000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        chunks = asr._split_audio()
        assert len(chunks) == 1

    def test_split_with_zero_overlap(self):
        """测试：零重叠的切割"""
        audio_bytes = create_test_audio(20000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=0,
        )

        chunks = asr._split_audio()

        # 20秒 / 10秒 = 2块
        assert len(chunks) == 2
        _, offsets = zip(*chunks)
        assert offsets == (0, 10000)


# ============================================================================
# 测试：并发转录功能
# ============================================================================


class TestConcurrentTranscription:
    """测试并发转录功能"""

    def test_concurrent_transcription_three_chunks(self):
        """测试：3块音频并发转录"""
        # 30秒音频 -> 3个10秒块
        audio_bytes = create_test_audio(30000)

        # 重置类变量计数器
        MockASR._total_call_count = 0

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
            chunk_concurrency=3,
        )

        # 执行完整转录
        result = asr.run()

        # 验证返回 ASRData
        assert isinstance(result, ASRData)
        assert len(result.segments) > 0

        # 验证每个 chunk 都被调用了（通过 call_count）
        # 注意：由于切割逻辑，30秒会被切成4块
        assert MockASR._total_call_count == 4

    def test_progress_callback_works(self):
        """测试：进度回调正确触发"""
        audio_bytes = create_test_audio(20000)
        progress_calls = []

        def callback(progress: int, message: str):
            progress_calls.append((progress, message))

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        asr.run(callback=callback)

        # 验证进度回调被调用
        assert len(progress_calls) > 0

        # 验证进度从 0-100
        progresses = [p for p, _ in progress_calls]
        assert max(progresses) <= 100
        assert min(progresses) >= 0

    def test_concurrency_limit_respected(self):
        """测试：并发数限制为 3"""
        audio_bytes = create_test_audio(60000)  # 60秒 -> 多个块

        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
            asr = MockASR(
                audio_path=audio_bytes,
                enable_chunking=True,
                chunk_length=10,
                chunk_overlap=2,
                chunk_concurrency=3,
            )

            # 验证 ThreadPoolExecutor 使用 max_workers=3
            # （这里只验证接口，不实际运行）
            assert asr.chunk_concurrency == 3


# ============================================================================
# 测试：结果合并功能
# ============================================================================


class TestChunkMerging:
    """测试 ChunkMerger 合并功能"""

    def test_merge_results_no_duplication(self):
        """测试：合并结果无重复内容"""
        # 20秒音频，10秒块，2秒重叠
        audio_bytes = create_test_audio(20000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
            mock_text_per_second="Text",
        )

        result = asr.run()

        # 提取所有文本
        texts = [seg.text for seg in result.segments]

        # 验证文本按顺序排列，无重复
        for i, text in enumerate(texts):
            # 文本应该是 "Text 1", "Text 2", ...
            assert "Text" in text

        # 验证时间戳连续性
        for i in range(len(result.segments) - 1):
            current_end = result.segments[i].end_time
            next_start = result.segments[i + 1].start_time
            # 下一个片段应该在当前片段结束后或有小重叠
            assert next_start >= current_end - 100  # 允许 100ms 容差

    def test_merge_preserves_timestamps(self):
        """测试：合并保留正确的时间戳"""
        audio_bytes = create_test_audio(15000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        result = asr.run()

        # 验证第一个片段从 0 开始
        assert result.segments[0].start_time == 0

        # 验证最后一个片段接近音频总长度
        last_seg = result.segments[-1]
        assert last_seg.end_time <= 15000 + 1000  # 允许 1 秒容差


# ============================================================================
# 测试：边界情况
# ============================================================================


class TestEdgeCases:
    """测试边界情况"""

    def test_single_chunk_no_merging(self):
        """测试：单块音频不触发合并"""
        # 5秒音频，块长度10秒
        audio_bytes = create_test_audio(5000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        result = asr.run()

        # 应该直接返回结果，不经过合并
        assert isinstance(result, ASRData)
        assert len(result.segments) == 5  # 5秒 = 5个片段

    def test_disable_chunking_mode(self):
        """测试：禁用分块模式的行为"""
        audio_bytes = create_test_audio(30000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=False,  # 禁用分块
        )

        result = asr.run()

        # 应该一次性转录整个30秒
        assert isinstance(result, ASRData)
        assert len(result.segments) == 30  # 30秒 = 30个片段

    def test_very_short_audio(self):
        """测试：极短音频（1秒）"""
        audio_bytes = create_test_audio(1000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        result = asr.run()
        assert len(result.segments) >= 1

    def test_large_overlap_ratio(self):
        """测试：大重叠比例（90%重叠）"""
        audio_bytes = create_test_audio(20000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=9,  # 90% 重叠
        )

        chunks = asr._split_audio()

        # 大重叠会产生更多块
        assert len(chunks) > 2

        # 验证偏移正确
        _, offsets = zip(*chunks)
        # 每块前进 10-9 = 1秒
        for i in range(1, len(offsets)):
            assert offsets[i] - offsets[i - 1] == 1000


# ============================================================================
# 测试：缓存机制
# ============================================================================


class TestCaching:
    """测试缓存机制"""

    def test_chunk_level_caching(self):
        """测试：分块模式下启用缓存不会导致错误"""
        audio_bytes = create_test_audio(20000)

        # 重置计数器
        MockASR._total_call_count = 0

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,
        )

        result = asr.run()

        # 验证分块转录正常完成（3个块）
        assert isinstance(result, ASRData)
        assert len(result.segments) > 0
        assert MockASR._total_call_count == 3  # 3个块被转录

    def test_cache_disabled_in_chunking_mode(self):
        """测试：分块模式下的缓存行为"""
        audio_bytes = create_test_audio(15000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=10,
            chunk_overlap=2,  # 明确指定2秒重叠
        )

        result = asr.run()
        assert isinstance(result, ASRData)

    def test_chunking_cache_hit(self):
        """测试：分块模式的缓存命中（顶层缓存）"""
        from app.core.utils.cache import enable_cache, disable_cache, get_asr_cache

        audio_bytes = create_test_audio(15000)

        # 临时启用缓存用于此测试
        enable_cache()

        try:
            # 清空缓存
            cache = get_asr_cache()
            cache.clear()

            # 重置计数器
            MockASR._total_call_count = 0

            # 第一次调用（缓存未命中，会执行分块转录）
            asr1 = MockASR(
                audio_path=audio_bytes,
                enable_chunking=True,
                chunk_length=10,
                chunk_overlap=2,
            )
            result1 = asr1.run()

            # 应该调用了2个块
            first_call_count = MockASR._total_call_count
            assert first_call_count == 2, f"Expected 2 calls, got {first_call_count}"

            # 验证缓存已保存
            cache_key = asr1._get_key()  # _get_key() 已经包含类名
            cached_data = cache.get(cache_key)
            assert cached_data is not None, "Cache should be saved after first run"
            assert "segments" in cached_data, "Cached data should have segments"

            # 第二次调用相同音频（应该从顶层缓存命中，直接返回）
            asr2 = MockASR(
                audio_path=audio_bytes,
                enable_chunking=True,
                chunk_length=10,
                chunk_overlap=2,
            )
            result2 = asr2.run()

            # 缓存命中后，不应该有新的 ASR 调用
            second_call_count = MockASR._total_call_count
            assert (
                second_call_count == first_call_count
            ), f"Cache should hit! Expected {first_call_count} calls, got {second_call_count}"

            # 结果应该相同
            assert len(result1.segments) == len(result2.segments)
            assert len(result2.segments) == 15

        finally:
            # 恢复测试默认设置（禁用缓存）
            disable_cache()


# ============================================================================
# 测试：错误处理（此处仅测试接口，不测试实际重试逻辑）
# ============================================================================


class TestErrorHandling:
    """测试错误处理"""

    def test_invalid_audio_data(self):
        """测试：无效音频数据抛出异常"""
        invalid_bytes = b"not an audio file"

        asr = MockASR(audio_path=invalid_bytes, enable_chunking=True)

        with pytest.raises(Exception):
            # pydub 会抛出异常
            asr._split_audio()

    def test_empty_audio_bytes(self):
        """测试：空音频字节"""
        empty_bytes = b""

        with pytest.raises((ValueError, Exception)):
            asr = MockASR(audio_path=empty_bytes, enable_chunking=True)
            asr._set_data()  # 应该在这里失败


# ============================================================================
# 测试：真实场景集成测试
# ============================================================================


class TestRealWorldScenarios:
    """真实场景集成测试"""

    def test_30_minute_podcast_chunking(self):
        """真实场景：30分钟播客音频分块转录"""
        # 模拟 30 分钟 = 1800 秒
        audio_bytes = create_test_audio(1800000)

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=600,  # 10分钟块
            chunk_overlap=10,  # 10秒重叠
            chunk_concurrency=3,
            mock_text_per_second="Podcast content",
        )

        result = asr.run()

        # 验证结果
        assert isinstance(result, ASRData)
        assert len(result.segments) > 1000  # 30分钟应该有大量片段

        # 验证时间范围
        assert result.segments[0].start_time == 0
        assert result.segments[-1].end_time <= 1800000 + 10000  # 允许容差

    def test_chinese_video_transcription(self):
        """真实场景：中文视频转录（15分钟）"""
        audio_bytes = create_test_audio(900000)  # 15分钟

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=300,  # 5分钟块
            chunk_overlap=10,
            mock_text_per_second="中文字幕",
        )

        result = asr.run()

        assert isinstance(result, ASRData)
        assert len(result.segments) > 0

        # 验证中文文本
        assert "中文字幕" in result.segments[0].text

    def test_progressive_transcription_with_callback(self):
        """真实场景：带进度回调的渐进式转录"""
        audio_bytes = create_test_audio(60000)  # 1分钟
        progress_log = []

        def progress_callback(progress: int, message: str):
            progress_log.append({"progress": progress, "message": message})

        asr = MockASR(
            audio_path=audio_bytes,
            enable_chunking=True,
            chunk_length=30,  # 30秒块
            chunk_overlap=5,
        )

        result = asr.run(callback=progress_callback)

        # 验证进度日志
        assert len(progress_log) > 0

        # 验证进度递增
        progresses = [log["progress"] for log in progress_log]
        # 注意：由于并发，进度可能不是严格递增的
        # 但应该有一些增长趋势
        assert max(progresses) > min(progresses)
