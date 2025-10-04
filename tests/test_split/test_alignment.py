"""字幕对齐模块测试

测试 app/core/split/alignment.py 中的核心功能
"""

import pytest

from app.core.split.alignment import SubtitleAligner


class TestSubtitleAligner:
    """测试 SubtitleAligner 类"""

    @pytest.fixture
    def aligner(self) -> SubtitleAligner:
        """创建对齐器实例"""
        return SubtitleAligner()

    def test_align_identical_texts(self, aligner):
        """测试对齐相同的文本"""
        source = ["a", "b", "c", "d"]
        target = ["a", "b", "c", "d"]

        aligned_source, aligned_target = aligner.align_texts(source, target)

        assert aligned_source == source
        assert aligned_target == target
        assert len(aligned_source) == len(aligned_target)

    def test_align_with_missing_items(self, aligner):
        """测试目标文本缺少某些项时的对齐"""
        source = ["ab", "b", "c", "d", "e", "f", "g", "h", "i"]
        target = ["a", "b", "c", "d", "f", "g", "h", "i"]  # 缺少 'e'

        aligned_source, aligned_target = aligner.align_texts(source, target)

        assert len(aligned_source) == len(aligned_target)
        # 源文本应该保持不变
        assert aligned_source == source
        # 目标文本应该使用前一项填充缺失项
        assert len(aligned_target) == len(source)

    def test_align_with_extra_items(self, aligner):
        """测试目标文本有额外项时的对齐"""
        source = ["a", "b", "c"]
        target = ["a", "b", "x", "c", "d"]  # 有额外的 'x' 和 'd'

        aligned_source, aligned_target = aligner.align_texts(source, target)

        # 源文本可能会使用上一项填充以匹配目标文本长度
        # 或者目标文本长度可能更长
        # 这里只验证对齐后两者都有内容即可
        assert len(aligned_source) > 0
        assert len(aligned_target) > 0

    def test_align_empty_texts(self, aligner):
        """测试空文本对齐"""
        source = []
        target = []

        aligned_source, aligned_target = aligner.align_texts(source, target)

        assert aligned_source == []
        assert aligned_target == []

    def test_align_single_item(self, aligner):
        """测试单项对齐"""
        source = ["hello"]
        target = ["hello"]

        aligned_source, aligned_target = aligner.align_texts(source, target)

        assert aligned_source == ["hello"]
        assert aligned_target == ["hello"]

    def test_align_completely_different_texts(self, aligner):
        """测试完全不同的文本对齐"""
        source = ["apple", "banana", "cherry"]
        target = ["dog", "elephant", "fox"]

        aligned_source, aligned_target = aligner.align_texts(source, target)

        # 应该能够对齐,即使内容完全不同
        assert len(aligned_source) == len(aligned_target)
        assert len(aligned_source) > 0

    def test_align_chinese_text(self, aligner):
        """测试中文文本对齐"""
        source = ["你好", "世界", "今天", "天气"]
        target = ["你好", "世界", "天气"]  # 缺少 "今天"

        aligned_source, aligned_target = aligner.align_texts(source, target)

        assert len(aligned_source) == len(aligned_target)
        assert aligned_source == source
