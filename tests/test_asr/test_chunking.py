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
from typing import Callable, List, Optional

from pydub import AudioSegment
from pydub.generators import Sine

from app.core.asr.asr_data import ASRDataSeg
from app.core.asr.base import BaseASR
from app.core.asr.chunked_asr import ChunkedASR

# ============================================================================
# 测试用 Mock ASR 实现
# ============================================================================


class MockASR(BaseASR):
    """Mock ASR 用于测试，模拟真实 API 调用"""

    # 类变量，用于跟踪所有实例的总调用次数
    _total_call_count = 0

    def __init__(
        self,
        audio_input,
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
            audio_input=audio_input,
            need_word_time_stamp=need_word_time_stamp,
        )
        self.enable_chunking = enable_chunking
        self.chunk_length = chunk_length
        self.chunk_overlap = chunk_overlap
        self.chunk_concurrency = chunk_concurrency
        self.mock_text_per_second = mock_text_per_second
        self.fail_on_chunk = fail_on_chunk

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs
    ) -> dict:
        """模拟 ASR 调用，生成基于音频长度的假数据"""
        from pydub import AudioSegment

        # 解析音频长度
        assert self.file_binary is not None, "file_binary should be set by _set_data()"
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


def create_test_audio_file(duration_sec: int) -> str:
    """创建测试用音频文件（静音）

    Args:
        duration_sec: 音频时长（秒）

    Returns:
        音频文件路径（临时文件）
    """
    import tempfile

    # 创建静音音频
    audio = AudioSegment.silent(duration=duration_sec * 1000)

    # 保存到临时文件
    temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    temp_path = temp_file.name
    temp_file.close()
    audio.export(temp_path, format="mp3")
    return temp_path


# ============================================================================
# 测试：音频切割功能
# ============================================================================


class TestAudioSplitting:
    """测试 pydub 音频切割功能"""

    def test_split_long_audio_into_chunks(self):
        """测试：长音频正确切割为重叠块"""
        # 创建 30 秒音频，切成 10 秒块，2 秒重叠
        audio_path = create_test_audio_file(30)

        try:
            chunked_asr = ChunkedASR(
                asr_class=MockASR,
                audio_input=audio_path,
                asr_kwargs={},
                chunk_length=10,  # 10秒
                chunk_overlap=2,  # 2秒重叠
            )

            chunks = chunked_asr._split_audio()

            # 验证块数：30秒，每块10秒，重叠2秒
            # chunk1: 0-10s, chunk2: 8-18s, chunk3: 16-26s, chunk4: 24-30s
            assert len(chunks) == 4

            # 验证每个块的偏移
            _, offsets = zip(*chunks)
            assert offsets == (0, 8000, 16000, 24000)

            # 验证每个块都是有效的音频
            for chunk_bytes, _ in chunks:
                audio_segment = AudioSegment.from_file(io.BytesIO(chunk_bytes))
                assert len(audio_segment) > 0
        finally:
            import os

            if os.path.exists(audio_path):
                os.unlink(audio_path)

    def test_split_short_audio_no_chunks(self):
        """测试：短音频不需要切割"""
        # 5 秒音频，块长度 10 秒
        audio_path = create_test_audio_file(5)

        try:
            chunked_asr = ChunkedASR(
                asr_class=MockASR,
                audio_input=audio_path,
                asr_kwargs={},
                chunk_length=10,
                chunk_overlap=2,
            )

            chunks = chunked_asr._split_audio()

            # 只有一个块
            assert len(chunks) == 1
            assert chunks[0][1] == 0  # offset=0
        finally:
            import os

            if os.path.exists(audio_path):
                os.unlink(audio_path)

    def test_split_exact_chunk_length(self):
        """测试：音频长度恰好等于块长度"""
        audio_path = create_test_audio_file(10)

        try:
            chunked_asr = ChunkedASR(
                asr_class=MockASR,
                audio_input=audio_path,
                asr_kwargs={},
                chunk_length=10,
                chunk_overlap=2,
            )

            chunks = chunked_asr._split_audio()
            assert len(chunks) == 1
        finally:
            import os

            if os.path.exists(audio_path):
                os.unlink(audio_path)

    def test_split_with_zero_overlap(self):
        """测试：零重叠的切割"""
        audio_path = create_test_audio_file(20)

        try:
            chunked_asr = ChunkedASR(
                asr_class=MockASR,
                audio_input=audio_path,
                asr_kwargs={},
                chunk_length=10,
                chunk_overlap=0,
            )

            chunks = chunked_asr._split_audio()

            # 20秒 / 10秒 = 2块
            assert len(chunks) == 2
            _, offsets = zip(*chunks)
            assert offsets == (0, 10000)
        finally:
            import os

            if os.path.exists(audio_path):
                os.unlink(audio_path)


# ============================================================================
# 测试：并发转录功能（已被 test_chunked_asr.py 覆盖）
# ============================================================================
# 注意：以下测试已过时，依赖旧API (MockASR的enable_chunking参数)
# 现在使用 ChunkedASR 包装器模式，相关测试已在 test_chunked_asr.py 中实现
# ============================================================================

'''
# class TestConcurrentTranscription:
#     """测试并发转录功能"""
#     # 已过时 - 依赖 MockASR(enable_chunking=True) 旧API
#     # 现在应使用 ChunkedASR(asr_class=MockASR, ...)
#     # 相关测试已在 test_chunked_asr.py 中实现
'''


# ============================================================================
# 测试：结果合并功能（已被 test_chunk_merger.py 覆盖）
# ============================================================================

"""
# class TestChunkMerging:
#     # 已过时 - 合并功能已由 test_chunk_merger.py 专门测试
"""


# ============================================================================
# 测试：边界情况（已被 test_chunked_asr.py 覆盖）
# ============================================================================

"""
# class TestEdgeCases:
#     # 已过时 - 边界情况已在 test_chunked_asr.py 测试
"""


# ============================================================================
# 测试：缓存机制（已被 test_chunked_asr.py 覆盖）
# ============================================================================

"""
# class TestCaching:
#     # 已过时 - 缓存机制已重构
"""


# ============================================================================
# 测试：错误处理（已被 test_chunked_asr.py 覆盖）
# ============================================================================

"""
# class TestErrorHandling:
#     # 已过时 - 错误处理已在 test_chunked_asr.py 测试
"""


# ============================================================================
# 测试：真实场景集成测试（已被 test_chunked_asr.py 覆盖）
# ============================================================================

'''
class TestRealWorldScenarios:
    """真实场景集成测试"""

    def test_30_minute_podcast_chunking(self):
        """真实场景：30分钟播客音频分块转录"""
        # 模拟 30 分钟 = 1800 秒
        audio_bytes = create_test_audio(1800000)

        asr = MockASR(
            audio_input=audio_bytes,
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
            audio_input=audio_bytes,
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
            audio_input=audio_bytes,
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
'''


# ============================================================================
# 注意: 以上测试类已过时,被 test_chunked_asr.py 覆盖
# TestConcurrentTranscription - 已由 test_chunked_asr.py 测试
# TestChunkMerging - 已由 test_chunk_merger.py 测试
# TestEdgeCases - 已由 test_chunked_asr.py 测试
# TestCaching - 缓存功能已重构
# TestErrorHandling - 已由 test_chunked_asr.py 测试
# TestRealWorldScenarios - 已由 test_chunked_asr.py 测试
# ============================================================================
