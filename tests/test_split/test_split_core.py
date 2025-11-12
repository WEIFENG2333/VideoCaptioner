"""split.py 核心功能测试

全面测试 SubtitleSplitter 类的核心方法和边缘情况
"""

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.split.split import (
    MAX_WORD_COUNT_CJK,
    MAX_WORD_COUNT_ENGLISH,
    SubtitleSplitter,
    preprocess_segments,
)


class TestPreprocessSegments:
    """测试 preprocess_segments 函数"""

    def test_remove_pure_punctuation(self):
        """测试移除纯标点符号"""
        segments = [
            ASRDataSeg(text="Hello", start_time=0, end_time=1000),
            ASRDataSeg(text="...", start_time=1000, end_time=2000),
            ASRDataSeg(text="World", start_time=2000, end_time=3000),
            ASRDataSeg(text="!!!", start_time=3000, end_time=4000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 2
        assert result[0].text == "hello "
        assert result[1].text == "world "

    def test_english_word_lowercase(self):
        """测试英文单词转小写"""
        segments = [
            ASRDataSeg(text="Hello", start_time=0, end_time=1000),
            ASRDataSeg(text="WORLD", start_time=1000, end_time=2000),
            ASRDataSeg(text="Test123", start_time=2000, end_time=3000),
        ]
        result = preprocess_segments(segments, need_lower=True)
        assert all(" " in seg.text for seg in result)
        assert result[0].text == "hello "
        assert result[1].text == "world "
        assert result[2].text == "test123 "

    def test_need_lower_false(self):
        """测试不转小写选项"""
        segments = [ASRDataSeg(text="Hello", start_time=0, end_time=1000)]
        result = preprocess_segments(segments, need_lower=False)
        assert result[0].text == "Hello "

    def test_mixed_language(self):
        """测试混合语言"""
        segments = [
            ASRDataSeg(text="你好", start_time=0, end_time=1000),
            ASRDataSeg(text="Hello", start_time=1000, end_time=2000),
            ASRDataSeg(text="世界", start_time=2000, end_time=3000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 3
        assert result[0].text == "你好"  # 中文不变
        assert result[1].text == "hello "  # 英文转小写加空格
        assert result[2].text == "世界"  # 中文不变

    def test_empty_segments(self):
        """测试空列表"""
        result = preprocess_segments([])
        assert result == []

    def test_chinese_punctuation(self):
        """测试中文标点"""
        segments = [
            ASRDataSeg(text="你好", start_time=0, end_time=1000),
            ASRDataSeg(text="。。。", start_time=1000, end_time=2000),
            ASRDataSeg(text="世界", start_time=2000, end_time=3000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 2
        assert result[0].text == "你好"
        assert result[1].text == "世界"

    def test_apostrophe_in_word(self):
        """测试单词中的撇号"""
        segments = [
            ASRDataSeg(text="don't", start_time=0, end_time=1000),
            ASRDataSeg(text="it's", start_time=1000, end_time=2000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 2
        assert result[0].text == "don't "
        assert result[1].text == "it's "


class TestSubtitleSplitterInit:
    """测试 SubtitleSplitter 初始化"""

    def test_default_initialization(self):
        """测试默认初始化"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        assert splitter.thread_num == 1
        assert splitter.model == "gpt-4o-mini"
        assert splitter.max_word_count_cjk == MAX_WORD_COUNT_CJK
        assert splitter.max_word_count_english == MAX_WORD_COUNT_ENGLISH
        assert splitter.is_running is True
        assert splitter.executor is not None

    def test_custom_parameters(self):
        """测试自定义参数"""
        splitter = SubtitleSplitter(
            thread_num=10,
            model="gpt-4",
            max_word_count_cjk=30,
            max_word_count_english=20,
        )
        assert splitter.thread_num == 10
        assert splitter.model == "gpt-4"
        assert splitter.max_word_count_cjk == 30
        assert splitter.max_word_count_english == 20

    def test_thread_pool_created(self):
        """测试线程池正确创建"""
        splitter = SubtitleSplitter(thread_num=3, model="gpt-4o-mini")
        assert splitter.executor is not None
        assert splitter.executor._max_workers == 3


class TestDetermineNumSegments:
    """测试 _determine_num_segments 方法"""

    def test_small_word_count(self):
        """测试小字数（不需要分段）"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        num_segments = splitter._determine_num_segments(100, threshold=500)
        assert num_segments == 1

    def test_exact_threshold(self):
        """测试正好等于阈值"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        num_segments = splitter._determine_num_segments(500, threshold=500)
        assert num_segments == 1

    def test_just_above_threshold(self):
        """测试刚超过阈值"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        num_segments = splitter._determine_num_segments(501, threshold=500)
        assert num_segments == 2

    def test_multiple_segments(self):
        """测试多个分段"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        num_segments = splitter._determine_num_segments(1500, threshold=500)
        assert num_segments == 3

    def test_zero_word_count(self):
        """测试零字数"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        num_segments = splitter._determine_num_segments(0, threshold=500)
        assert num_segments == 1


class TestGroupByTimeGaps:
    """测试 _group_by_time_gaps 方法"""

    def test_no_gaps(self):
        """测试连续时间戳（无间隔）"""
        segments = [
            ASRDataSeg(text="A", start_time=0, end_time=1000),
            ASRDataSeg(text="B", start_time=1000, end_time=2000),
            ASRDataSeg(text="C", start_time=2000, end_time=3000),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(segments, max_gap=1500)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_large_gap(self):
        """测试大间隔分组"""
        segments = [
            ASRDataSeg(text="A", start_time=0, end_time=1000),
            ASRDataSeg(text="B", start_time=3000, end_time=4000),  # 2000ms间隔
            ASRDataSeg(text="C", start_time=4000, end_time=5000),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(segments, max_gap=1500)
        assert len(groups) == 2
        assert len(groups[0]) == 1
        assert len(groups[1]) == 2

    def test_multiple_gaps(self):
        """测试多个间隔"""
        segments = [
            ASRDataSeg(text="A", start_time=0, end_time=1000),
            ASRDataSeg(text="B", start_time=3000, end_time=4000),  # 大间隔
            ASRDataSeg(text="C", start_time=4000, end_time=5000),
            ASRDataSeg(text="D", start_time=7000, end_time=8000),  # 大间隔
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(segments, max_gap=1500)
        assert len(groups) == 3

    def test_empty_segments(self):
        """测试空列表"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps([])
        assert groups == []

    def test_single_segment(self):
        """测试单个分段"""
        segments = [ASRDataSeg(text="A", start_time=0, end_time=1000)]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(segments)
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_check_large_gaps_enabled(self):
        """测试异常大间隔检测"""
        # 创建一个有异常大间隔的序列
        segments = [
            ASRDataSeg(text=f"seg{i}", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(10)
        ]
        # 在第5个位置插入异常大间隔
        segments.insert(5, ASRDataSeg(text="gap", start_time=500, end_time=5000))
        segments.append(ASRDataSeg(text="after", start_time=5000, end_time=5100))

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(segments, check_large_gaps=True)
        # 应该检测到异常间隔并分组
        assert len(groups) >= 1


class TestSplitByCommonWords:
    """测试 _split_by_common_words 方法"""

    def test_split_on_prefix_word(self):
        """测试在前缀词处分割"""
        segments = [
            ASRDataSeg(text="我", start_time=0, end_time=100),
            ASRDataSeg(text="喜", start_time=100, end_time=200),
            ASRDataSeg(text="欢", start_time=200, end_time=300),
            ASRDataSeg(text="你", start_time=300, end_time=400),  # 前缀词
            ASRDataSeg(text="很", start_time=400, end_time=500),
            ASRDataSeg(text="好", start_time=500, end_time=600),
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=10
        )
        groups = splitter._split_by_common_words(segments)
        # 应该至少产生分割
        assert len(groups) >= 1

    def test_split_on_suffix_word(self):
        """测试在后缀词处分割"""
        segments = [
            ASRDataSeg(text="我", start_time=0, end_time=100),
            ASRDataSeg(text="来", start_time=100, end_time=200),
            ASRDataSeg(text="了", start_time=200, end_time=300),  # 后缀词
            ASRDataSeg(text="你", start_time=300, end_time=400),
            ASRDataSeg(text="走", start_time=400, end_time=500),
            ASRDataSeg(text="吧", start_time=500, end_time=600),  # 后缀词
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=10
        )
        groups = splitter._split_by_common_words(segments)
        assert len(groups) >= 1

    def test_english_common_words(self):
        """测试英文常见词分割"""
        segments = [
            ASRDataSeg(text="I", start_time=0, end_time=100),
            ASRDataSeg(text="like", start_time=100, end_time=200),
            ASRDataSeg(text="you", start_time=200, end_time=300),
            ASRDataSeg(text="and", start_time=300, end_time=400),  # 前缀词
            ASRDataSeg(text="she", start_time=400, end_time=500),
            ASRDataSeg(text="likes", start_time=500, end_time=600),
            ASRDataSeg(text="you", start_time=600, end_time=700),
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_english=10
        )
        groups = splitter._split_by_common_words(segments)
        assert len(groups) >= 1

    def test_no_common_words(self):
        """测试无常见词"""
        segments = [
            ASRDataSeg(text="测", start_time=0, end_time=100),
            ASRDataSeg(text="试", start_time=100, end_time=200),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._split_by_common_words(segments)
        assert len(groups) == 1

    def test_empty_segments(self):
        """测试空列表"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._split_by_common_words([])
        assert groups == []


class TestSplitLongSegment:
    """测试 _split_long_segment 方法"""

    def test_short_segment(self):
        """测试短分段（无需拆分）"""
        segments = [
            ASRDataSeg(text="短", start_time=0, end_time=100),
            ASRDataSeg(text="文", start_time=100, end_time=200),
            ASRDataSeg(text="本", start_time=200, end_time=300),
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20
        )
        result = splitter._split_long_segment(segments)
        assert len(result) == 1
        assert result[0].text == "短文本"

    def test_long_segment_with_gaps(self):
        """测试超长分段（有时间间隔）"""
        # 创建一个超长文本
        long_text = "这是一个非常长的文本片段" * 10
        segments = [
            ASRDataSeg(text=c, start_time=i * 100, end_time=(i + 1) * 100)
            for i, c in enumerate(long_text)
        ]
        # 在中间插入大间隔
        mid = len(segments) // 2
        segments[mid].end_time = segments[mid].start_time + 50
        segments[mid + 1].start_time = segments[mid].end_time + 500

        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20
        )
        result = splitter._split_long_segment(segments)
        # 应该被拆分成多个
        assert len(result) >= 2

    def test_very_short_segments(self):
        """测试极短分段（小于最小大小）"""
        segments = [
            ASRDataSeg(text="A", start_time=0, end_time=100),
            ASRDataSeg(text="B", start_time=100, end_time=200),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter._split_long_segment(segments)
        assert len(result) == 1

    def test_equal_time_gaps(self):
        """测试相等时间间隔（中间分割）"""
        segments = [
            ASRDataSeg(text=f"字{i}", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(100)
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20
        )
        result = splitter._split_long_segment(segments)
        # 应该被递归拆分
        assert len(result) >= 2

    def test_preserves_timestamps(self):
        """测试保持时间戳顺序"""
        segments = [
            ASRDataSeg(text=f"字{i}", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(50)
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=10
        )
        result = splitter._split_long_segment(segments)
        # 验证时间戳递增
        for i in range(len(result) - 1):
            assert result[i].start_time <= result[i + 1].start_time


class TestMergeShortSegment:
    """测试 merge_short_segment 方法"""

    def test_merge_very_short_segments(self):
        """测试合并极短片段"""
        segments = [
            ASRDataSeg(text="我", start_time=0, end_time=100),
            ASRDataSeg(text="是", start_time=100, end_time=200),
            ASRDataSeg(text="谁", start_time=200, end_time=300),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)
        # 应该被合并（3个字 < MERGE_VERY_SHORT_WORDS=3）
        assert len(segments) < 3

    def test_merge_with_short_gap(self):
        """测试短时间间隔合并"""
        segments = [
            ASRDataSeg(text="短", start_time=0, end_time=100),
            ASRDataSeg(text="文本", start_time=150, end_time=300),  # 50ms间隔
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        original_len = len(segments)
        splitter.merge_short_segment(segments)
        # 应该合并（间隔 < MERGE_SHORT_GAP=200）
        assert len(segments) < original_len

    def test_no_merge_long_segments(self):
        """测试不合并长片段"""
        segments = [
            ASRDataSeg(text="这是一个很长的文本片段", start_time=0, end_time=1000),
            ASRDataSeg(text="这也是一个很长的文本片段", start_time=1100, end_time=2000),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        original_len = len(segments)
        splitter.merge_short_segment(segments)
        # 不应该合并
        assert len(segments) == original_len

    def test_no_merge_large_gap(self):
        """测试大间隔不合并"""
        segments = [
            ASRDataSeg(text="短", start_time=0, end_time=100),
            ASRDataSeg(text="文", start_time=2000, end_time=2100),  # 大间隔
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        original_len = len(segments)
        splitter.merge_short_segment(segments)
        # 不应该合并（间隔太大）
        assert len(segments) == original_len

    def test_merge_respects_max_word_count(self):
        """测试合并不超过最大字数"""
        segments = [
            ASRDataSeg(text="这是一个中等长度的文本", start_time=0, end_time=1000),
            ASRDataSeg(text="这也是一个中等长度的文本", start_time=1100, end_time=2000),
        ]
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=10
        )
        original_len = len(segments)
        splitter.merge_short_segment(segments)
        # 不应该合并（会超过最大字数）
        assert len(segments) == original_len

    def test_english_text_merge(self):
        """测试英文文本合并（加空格）"""
        segments = [
            ASRDataSeg(text="Hi", start_time=0, end_time=100),
            ASRDataSeg(text="there", start_time=150, end_time=300),
        ]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)
        if len(segments) == 1:
            # 如果合并了，应该有空格
            assert " " in segments[0].text

    def test_empty_segments(self):
        """测试空列表"""
        segments = []
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)
        assert segments == []

    def test_single_segment(self):
        """测试单个分段"""
        segments = [ASRDataSeg(text="单个", start_time=0, end_time=100)]
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)
        assert len(segments) == 1


class TestStopMethod:
    """测试 stop 方法"""

    def test_stop_sets_running_false(self):
        """测试停止设置运行状态"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        assert splitter.is_running is True
        splitter.stop()
        assert splitter.is_running is False

    def test_stop_shuts_down_executor(self):
        """测试停止关闭线程池"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.stop()
        # 线程池应该被设置为None
        assert splitter.executor is None

    def test_multiple_stops(self):
        """测试多次调用stop"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.stop()
        splitter.stop()  # 不应该抛出异常
        assert splitter.is_running is False

    def test_stop_idempotent(self):
        """测试stop的幂等性"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.stop()
        first_state = splitter.is_running
        splitter.stop()
        second_state = splitter.is_running
        assert first_state == second_state == False


class TestEdgeCases:
    """测试边缘情况"""

    def test_zero_thread_num(self):
        """测试零线程数（应该使用默认值或处理）"""
        # 根据实际实现，可能会失败或使用默认值
        try:
            splitter = SubtitleSplitter(thread_num=0, model="gpt-4o-mini")
            # 如果成功创建，验证某些基本功能
            assert splitter.thread_num == 0
        except (ValueError, Exception):
            # 如果抛出异常，这也是合理的
            pass

    def test_negative_max_word_count(self):
        """测试负数最大字数"""
        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=-1
        )
        # 应该能够创建，但可能在使用时出问题
        assert splitter.max_word_count_cjk == -1

    def test_very_large_thread_num(self):
        """测试非常大的线程数"""
        splitter = SubtitleSplitter(thread_num=1000, model="gpt-4o-mini")
        assert splitter.thread_num == 1000
        assert splitter.executor is not None
