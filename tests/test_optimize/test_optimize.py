"""Subtitle optimizer tests.

Requires environment variables:
    OPENAI_BASE_URL: OpenAI-compatible API endpoint
    OPENAI_API_KEY: API key for authentication
    OPENAI_MODEL: Model name (optional, defaults to gpt-4o-mini)
"""

import os
from typing import Callable

import pytest

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.optimize.optimize import SubtitleOptimizer


@pytest.mark.integration
class TestSubtitleOptimizer:
    """Test suite for SubtitleOptimizer with agent loop."""

    @pytest.fixture
    def optimizer(self, mock_llm_client) -> SubtitleOptimizer:
        """Create SubtitleOptimizer instance (using mock LLM)."""
        model = "gpt-4o-mini"
        return SubtitleOptimizer(
            thread_num=2,
            batch_num=5,
            model=model,
            custom_prompt="",
        )

    @pytest.fixture
    def sample_asr_data(self) -> ASRData:
        """Create sample ASR data with typical errors: homophones, typos, filler words."""
        segments = [
            ASRDataSeg(
                text="大家好啊今天呢我们来讲一下这个机器学习的基础只是",
                start_time=0,
                end_time=3000,
            ),
            ASRDataSeg(
                text="那么它其实就是嗯人工治能的一个重要份支",
                start_time=3000,
                end_time=6000,
            ),
            ASRDataSeg(
                text="通过算发让计算机去从这个数据当中学习嘛",
                start_time=6000,
                end_time=9000,
            ),
        ]
        return ASRData(segments)

    def test_optimize_basic(
        self,
        optimizer: SubtitleOptimizer,
        sample_asr_data: ASRData,
        check_env_vars: Callable,
    ):
        """Test basic optimization functionality."""
        check_env_vars("OPENAI_BASE_URL", "OPENAI_API_KEY")

        result = optimizer.optimize_subtitle(sample_asr_data)

        print("\n" + "=" * 80)
        print(f"📝 字幕优化测试 - 共 {len(result.segments)} 段")
        print("=" * 80)
        print("原始 → 优化后:")
        for orig, opt in zip(sample_asr_data.segments, result.segments):
            print(f"  {orig.text}")
            print(f"  → {opt.text}")
        print("=" * 80)

        # 验证结果
        assert len(result.segments) == len(sample_asr_data.segments)
        assert all(seg.text for seg in result.segments)

        # 验证时间戳未被修改
        for orig, opt in zip(sample_asr_data.segments, result.segments):
            assert opt.start_time == orig.start_time
            assert opt.end_time == orig.end_time

    def test_agent_loop_validation(
        self,
        optimizer: SubtitleOptimizer,
        sample_asr_data: ASRData,
        check_env_vars: Callable,
    ):
        """Test agent loop validation and correction."""
        check_env_vars("OPENAI_BASE_URL", "OPENAI_API_KEY")

        result = optimizer.optimize_subtitle(sample_asr_data)

        print("\n" + "=" * 80)
        print("🔄 Agent Loop 验证测试")
        print("=" * 80)
        for orig, opt in zip(sample_asr_data.segments, result.segments):
            print(f"  原文: {orig.text}")
            print(f"  优化: {opt.text}")
        print("=" * 80)

        # 验证结果
        assert len(result.segments) == len(sample_asr_data.segments)
        assert all(seg.text for seg in result.segments)

    def test_optimize_empty_handling(self, optimizer: SubtitleOptimizer):
        """Test handling of empty segments."""
        segments = []
        asr_data = ASRData(segments)

        result = optimizer.optimize_subtitle(asr_data)

        assert len(result.segments) == 0
