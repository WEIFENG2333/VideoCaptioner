"""ChunkedASR 全面测试

测试策略：
1. 使用 Mock ASR 避免实际 API 调用
2. 覆盖所有核心功能（分块、并发、合并）
3. 测试边界情况（短音频、单块、错误等）
4. 验证进度回调机制
5. 确保线程安全和并发正确性

重构后设计：
- ChunkedASR 接收 ASR 类和参数，而非实例
- 为每个 chunk 创建独立的 ASR 实例
- 避免共享状态，支持真正的并发
"""

import io
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

import pytest
from pydub import AudioSegment

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.asr.base import BaseASR
from app.core.asr.chunked_asr import ChunkedASR

# ============================================================================
# Mock ASR 辅助类
# ============================================================================


class MockASR(BaseASR):
    """Mock ASR 用于测试，避免实际 API 调用

    支持接收 bytes 或 str 作为 audio_input（适配 ChunkedASR）
    """

    # 类变量：跨实例共享的调用计数（用于测试并发）
    global_run_count = 0

    def __init__(
        self,
        audio_input,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        # Mock 专用参数
        mock_text_per_second: str = "Mock",
        fail_on_run: bool = False,
    ):
        super().__init__(audio_input, use_cache, need_word_time_stamp)
        self.mock_text_per_second = mock_text_per_second
        self.fail_on_run = fail_on_run

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs
    ) -> dict:
        """模拟 ASR 转录，返回假数据"""
        MockASR.global_run_count += 1

        if self.fail_on_run:
            raise RuntimeError("Mock ASR failed")

        if callback:
            callback(50, "processing")
            callback(100, "completed")

        # 生成模拟的转录结果（每秒一个字）
        if self.file_binary:
            audio = AudioSegment.from_file(io.BytesIO(self.file_binary))
            duration_sec = len(audio) / 1000  # 毫秒转秒
            num_segments = max(1, int(duration_sec))

            segments = [
                {
                    "text": f"{self.mock_text_per_second}{i+1}",
                    "start": i,
                    "end": i + 1,
                }
                for i in range(num_segments)
            ]
        else:
            segments = [{"text": "Mock", "start": 0, "end": 1}]

        return {"segments": segments}

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        """将模拟数据转换为 ASRDataSeg"""
        return [
            ASRDataSeg(
                text=seg["text"],
                start_time=int(seg["start"] * 1000),
                end_time=int(seg["end"] * 1000),
            )
            for seg in resp_data["segments"]
        ]


def create_test_audio_file(duration_sec: int = 60) -> str:
    """创建测试用音频文件（静音）

    Args:
        duration_sec: 音频时长（秒）

    Returns:
        音频文件路径（临时文件）
    """
    # 创建静音音频
    audio = AudioSegment.silent(duration=duration_sec * 1000)

    # 保存到临时文件（delete=False 避免 Windows 权限问题）
    temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    temp_path = temp_file.name
    temp_file.close()  # 关闭文件句柄，让 pydub 可以写入
    audio.export(temp_path, format="mp3")
    return temp_path


# ============================================================================
# 测试 ChunkedASR 基础功能
# ============================================================================


class TestChunkedASRBasics:
    """测试 ChunkedASR 的基础功能"""

    def test_init_default_params(self):
        """测试默认参数初始化"""
        audio_input = create_test_audio_file(60)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR, audio_path=audio_input, asr_kwargs={}
            )

            assert chunked.asr_class is MockASR
            assert chunked.audio_path == audio_input
            assert chunked.chunk_length_ms == 600 * 1000  # 10 分钟
            assert chunked.chunk_overlap_ms == 10 * 1000  # 10 秒
            assert chunked.chunk_concurrency == 3
        finally:
            Path(audio_input).unlink()

    def test_init_custom_params(self):
        """测试自定义参数初始化"""
        audio_input = create_test_audio_file(60)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Test"},
                chunk_length=600,
                chunk_overlap=5,
                chunk_concurrency=5,
            )

            assert chunked.chunk_length_ms == 600 * 1000
            assert chunked.chunk_overlap_ms == 5 * 1000
            assert chunked.chunk_concurrency == 5
            assert chunked.asr_kwargs["mock_text_per_second"] == "Test"
        finally:
            Path(audio_input).unlink()

    def test_short_audio_no_chunking(self):
        """测试短音频（< chunk_length）不分块直接转录"""
        # 创建 5 分钟音频（小于默认的 8 分钟）
        audio_input = create_test_audio_file(300)
        try:
            MockASR.global_run_count = 0

            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Short"},
            )

            result = chunked.run()

            # 验证：只调用了一次 ASR（未分块）
            assert MockASR.global_run_count == 1
            assert len(result.segments) > 0
            assert result.segments[0].text.startswith("Short")
        finally:
            Path(audio_input).unlink()

    def test_long_audio_with_chunking(self):
        """测试长音频（> chunk_length）自动分块转录"""
        # 创建 20 分钟音频（会分成 3 块：0-8min, 8-16min, 16-20min）
        audio_input = create_test_audio_file(1200)
        try:
            MockASR.global_run_count = 0

            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Long"},
                chunk_length=480,  # 8分钟
                chunk_overlap=10,
            )

            result = chunked.run()

            # 验证：调用了 3 次 ASR（分成 3 块）
            # 计算公式：(1200s - 480s) / (480s - 10s) + 1 = 2.53... = 3 块
            assert MockASR.global_run_count == 3
            assert len(result.segments) > 0
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试音频分块逻辑
# ============================================================================


class TestAudioSplitting:
    """测试 _split_audio() 方法"""

    def test_split_exact_chunks(self):
        """测试精确分块（音频长度正好是块长度的倍数）"""
        # 16分钟 = 2块 × 8分钟
        audio_input = create_test_audio_file(960)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                chunk_length=480,
                chunk_overlap=0,
            )

            chunks = chunked._split_audio()

            assert len(chunks) == 2
            assert chunks[0][1] == 0  # 第一块 offset = 0ms
            assert chunks[1][1] == 480 * 1000  # 第二块 offset = 480s
        finally:
            Path(audio_input).unlink()

    def test_split_with_overlap(self):
        """测试带重叠的分块"""
        # 20分钟，8分钟/块，10秒重叠
        audio_input = create_test_audio_file(1200)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                chunk_length=480,
                chunk_overlap=10,
            )

            chunks = chunked._split_audio()

            # 计算块数：(1200 - 480) / (480 - 10) + 1 = 2.53 ≈ 3 块
            assert len(chunks) == 3

            # 验证 offset 正确
            assert chunks[0][1] == 0
            assert chunks[1][1] == 470 * 1000  # 480 - 10
            assert chunks[2][1] == 940 * 1000  # 470 + 470
        finally:
            Path(audio_input).unlink()

    def test_split_remainder_chunk(self):
        """测试剩余块（最后一块不足完整长度）"""
        # 10分钟，8分钟/块 -> 2块（第二块仅2分钟）
        audio_input = create_test_audio_file(600)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                chunk_length=480,
                chunk_overlap=0,
            )

            chunks = chunked._split_audio()

            assert len(chunks) == 2
            # 第二块应该只有 120 秒
            chunk2_audio = AudioSegment.from_file(io.BytesIO(chunks[1][0]))
            assert abs(len(chunk2_audio) - 120 * 1000) < 100  # 允许误差 100ms
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试并发转录
# ============================================================================


class TestConcurrentTranscription:
    """测试并发转录逻辑"""

    def test_concurrency_3_workers(self):
        """测试 3 个并发 worker"""
        # 20分钟 -> 3块
        audio_input = create_test_audio_file(1200)
        try:
            MockASR.global_run_count = 0

            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                chunk_length=480,
                chunk_concurrency=3,
            )

            result = chunked.run()

            # 验证：所有块都被转录
            assert MockASR.global_run_count == 3
            assert len(result.segments) > 0
        finally:
            Path(audio_input).unlink()

    def test_independent_asr_instances(self):
        """测试每个 chunk 使用独立的 ASR 实例"""
        # 20分钟 -> 3块
        audio_input = create_test_audio_file(1200)
        try:
            MockASR.global_run_count = 0

            # 使用不同的 mock_text_per_second 标记不同实例
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Chunk"},
                chunk_length=480,
            )

            result = chunked.run()

            # 验证：每个块都生成了结果
            assert MockASR.global_run_count == 3
            # 所有 segment 的文本都应该包含 "Chunk"
            for seg in result.segments:
                assert "Chunk" in seg.text
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试结果合并
# ============================================================================


class TestChunkMerging:
    """测试 _merge_results() 方法"""

    def test_merge_preserves_order(self):
        """测试合并后时间戳顺序正确"""
        # 20分钟 -> 3块
        audio_input = create_test_audio_file(1200)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR, audio_path=audio_input, chunk_length=480
            )

            result = chunked.run()

            # 验证时间戳递增
            for i in range(len(result.segments) - 1):
                assert result.segments[i].end_time <= result.segments[i + 1].start_time
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试边界情况
# ============================================================================


class TestEdgeCases:
    """测试边界情况"""

    def test_very_short_audio(self):
        """测试极短音频（1秒）"""
        audio_input = create_test_audio_file(1)
        try:
            chunked = ChunkedASR(asr_class=MockASR, audio_path=audio_input)

            result = chunked.run()

            assert len(result.segments) >= 1
        finally:
            Path(audio_input).unlink()

    def test_zero_overlap(self):
        """测试零重叠"""
        audio_input = create_test_audio_file(1000)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                chunk_length=480,
                chunk_overlap=0,
            )

            chunks = chunked._split_audio()

            # 验证无重叠：每个 chunk 的 offset 是前一个的结束位置
            assert len(chunks) >= 2
            assert chunks[1][1] == 480 * 1000
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试错误处理
# ============================================================================


class TestErrorHandling:
    """测试错误处理"""

    def test_asr_failure_propagates(self):
        """测试 ASR 失败时错误正确传播"""
        audio_input = create_test_audio_file(1000)
        try:
            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"fail_on_run": True},
                chunk_length=480,
            )

            with pytest.raises(RuntimeError, match="Mock ASR failed"):
                chunked.run()
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 测试进度回调
# ============================================================================


class TestProgressCallback:
    """测试进度回调机制"""

    def test_callback_invoked(self):
        """测试回调函数被正确调用"""
        audio_input = create_test_audio_file(1000)
        try:
            callback_calls = []

            def mock_callback(progress: int, message: str):
                callback_calls.append((progress, message))

            chunked = ChunkedASR(
                asr_class=MockASR, audio_path=audio_input, chunk_length=480
            )

            chunked.run(callback=mock_callback)

            # 验证回调被调用
            assert len(callback_calls) > 0
            # 验证进度在 0-100 之间
            for progress, _ in callback_calls:
                assert 0 <= progress <= 100
        finally:
            Path(audio_input).unlink()


# ============================================================================
# 集成测试
# ============================================================================


class TestIntegration:
    """端到端集成测试"""

    def test_full_pipeline_short_audio(self):
        """测试完整流程：短音频（不分块）"""
        audio_input = create_test_audio_file(300)
        try:
            MockASR.global_run_count = 0

            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Test"},
            )

            result = chunked.run()

            assert MockASR.global_run_count == 1
            assert len(result.segments) > 0
            assert all("Test" in seg.text for seg in result.segments)
        finally:
            Path(audio_input).unlink()

    def test_full_pipeline_long_audio(self):
        """测试完整流程：长音频（分块）"""
        audio_input = create_test_audio_file(1200)
        try:
            MockASR.global_run_count = 0

            chunked = ChunkedASR(
                asr_class=MockASR,
                audio_path=audio_input,
                asr_kwargs={"mock_text_per_second": "Long"},
                chunk_length=480,
                chunk_overlap=10,
                chunk_concurrency=3,
            )

            result = chunked.run()

            # 验证分块转录
            assert MockASR.global_run_count == 3

            # 验证结果完整性
            assert len(result.segments) > 0
            assert all("Long" in seg.text for seg in result.segments)

            # 验证时间戳顺序
            for i in range(len(result.segments) - 1):
                assert result.segments[i].end_time <= result.segments[i + 1].start_time
        finally:
            Path(audio_input).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
