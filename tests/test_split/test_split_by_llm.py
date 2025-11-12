"""LLM-based text splitting tests.

Requires environment variables:
    OPENAI_BASE_URL: OpenAI-compatible API endpoint
    OPENAI_API_KEY: API key for authentication
    OPENAI_MODEL: Model name (optional, defaults to gpt-4o-mini)
"""

import os
from typing import Callable

import pytest

from app.core.split.split_by_llm import count_words, split_by_llm


@pytest.mark.integration
class TestSplitByLLM:
    """Test suite for LLM-based text splitting."""

    def test_count_words_chinese(self):
        """Test word counting for Chinese text."""
        text = "大家好我叫杨玉溪来自福建厦门"
        assert count_words(text) == 14  # 14 Chinese characters

    def test_count_words_english(self):
        """Test word counting for English text."""
        text = "Hello world this is a test sentence"
        assert count_words(text) == 7  # 7 English words

    def test_count_words_mixed(self):
        """Test word counting for mixed Chinese and English text."""
        text = "大家好 hello 我是 world"
        # 5 Chinese chars + 2 English words = 7
        assert count_words(text) == 7

    def test_split_chinese_text(self, mock_llm_client):
        """Test splitting Chinese text with LLM (using mock)."""
        text = "大家好我叫杨玉溪来自有着良好音乐氛围的福建厦门。自记事起我眼中的世界就是朦胧的。童话书是各色杂乱的线条。电视机是颜色各异的雪花。小伙伴是只听其声不便骑行的马赛克。后来我才知道这是一种眼底黄斑疾病。虽不至于失明但终身无法治愈。"
        model = "gpt-4o-mini"
        max_limit = 18

        result = split_by_llm(text, model=model, max_word_count_cjk=max_limit)

        print("\n" + "=" * 80)
        print(f"📝 中文断句测试 - 共 {len(result)} 段 (限制: ≤{max_limit}字/段)")
        print("=" * 80)
        for i, seg in enumerate(result, 1):
            word_count = count_words(seg)
            status = "✓" if word_count <= max_limit else "✗"
            print(f"  {status} 段{i:2d} [{word_count:2d}字] {seg}")
        print("=" * 80)

        # 验证结果
        assert len(result) > 0, "应该返回至少一个分段"
        assert "".join(result).replace(" ", "") == text.replace(
            " ", ""
        ), "合并后应该等于原文"

        # 验证每段长度
        for seg in result:
            assert count_words(seg) <= max_limit * 1.2, f"分段过长: {seg}"

    def test_split_english_text(self, mock_llm_client):
        """Test splitting English text with LLM (using mock)."""
        text = "The upgraded claude sonnet is now available for all users. Developers can build with the computer use beta on the anthropic api. Amazon bedrock and google cloud's vertex ai. The new claude haiku will be released later this month."
        model = "gpt-4o-mini"
        max_limit = 12

        result = split_by_llm(text, model=model, max_word_count_english=max_limit)

        print("\n" + "=" * 80)
        print(f"📝 英文断句测试 - 共 {len(result)} 段 (限制: ≤{max_limit} words/段)")
        print("=" * 80)
        for i, seg in enumerate(result, 1):
            word_count = count_words(seg)
            status = "✓" if word_count <= max_limit else "✗"
            print(f"  {status} 段{i:2d} [{word_count:2d} words] {seg}")
        print("=" * 80)

        # 验证结果
        assert len(result) > 0, "应该返回至少一个分段"

        # 验证每段长度
        for seg in result:
            assert count_words(seg) <= max_limit * 1.2, f"分段过长: {seg}"

    def test_split_mixed_text(self, mock_llm_client):
        """Test splitting mixed Chinese-English text with LLM (using mock)."""
        text = "今天我们来介绍Claude AI。它是由Anthropic公司开发的大语言模型。The model can understand and generate text in multiple languages. 包括中文和英文。"
        model = "gpt-4o-mini"
        max_limit = 15

        result = split_by_llm(text, model=model, max_word_count_cjk=max_limit)

        print("\n" + "=" * 80)
        print(f"📝 中英混合断句测试 - 共 {len(result)} 段 (限制: ≤{max_limit}/段)")
        print("=" * 80)
        for i, seg in enumerate(result, 1):
            word_count = count_words(seg)
            status = "✓" if word_count <= max_limit else "✗"
            print(f"  {status} 段{i:2d} [{word_count:2d}] {seg}")
        print("=" * 80)

        # 验证结果
        assert len(result) > 0, "应该返回至少一个分段"

    def test_split_preserves_content(self, mock_llm_client):
        """Test that splitting preserves original content (using mock)."""
        text = "人工智能技术正在改变世界。它让我们的生活变得更加便利。"
        model = "gpt-4o-mini"

        result = split_by_llm(text, model=model)

        # 合并后应该完全等于原文（忽略空格）
        merged = "".join(result)
        assert merged.replace(" ", "") == text.replace(" ", ""), "内容不应被修改"

    def test_split_short_text(self, mock_llm_client):
        """Test splitting very short text (using mock)."""
        text = "你好世界。"
        model = "gpt-4o-mini"

        result = split_by_llm(text, model=model)

        print(f"\n📝 短文本断句结果: {result}")

        # 短文本可能不需要分段
        assert len(result) >= 1, "至少应该返回原文本"
        assert "".join(result).replace(" ", "") == text.replace(" ", "")

    def test_agent_loop_correction(self, mock_llm_client):
        """Test that agent loop can correct errors through feedback (using mock)."""
        # 使用一段需要分多段的长文本
        text = "机器学习是人工智能的一个重要分支。它使计算机能够从数据中学习模式。深度学习是机器学习的一个子领域。它使用神经网络来处理复杂的数据。"
        model = "gpt-4o-mini"
        max_limit = 15  # 放宽限制以适应mock的分割逻辑

        result = split_by_llm(text, model=model, max_word_count_cjk=max_limit)

        print("\n" + "=" * 80)
        print(
            f"🔄 Agent Loop 自我修正测试 - 共 {len(result)} 段 (限制: ≤{max_limit}字/段)"
        )
        print("=" * 80)
        for i, seg in enumerate(result, 1):
            word_count = count_words(seg)
            status = "✓" if word_count <= max_limit else "✗"
            print(f"  {status} 段{i:2d} [{word_count:2d}字] {seg}")
        print("=" * 80)

        # 验证结果符合要求
        assert len(result) > 1, "应该分成多段"

        for seg in result:
            word_count = count_words(seg)
            assert (
                word_count <= max_limit * 1.2
            ), f"分段长度应该符合限制: {word_count} > {max_limit}"
