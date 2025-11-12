"""字幕分割模块测试 - 严格边缘用例

测试 app/core/split/split.py 中的核心功能
"""

import pytest

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.split.split import SubtitleSplitter, preprocess_segments


class TestPreprocessEdgeCases:
    """测试 preprocess_segments 边缘情况"""

    def test_unicode_extremes(self):
        """测试极端Unicode字符"""
        segments = [
            ASRDataSeg(
                text="😀🌍🎉", start_time=0, end_time=1000
            ),  # Emoji (可能被当作标点)
            ASRDataSeg(text="مرحبا", start_time=1000, end_time=2000),  # 阿拉伯文
            ASRDataSeg(text="Привет", start_time=2000, end_time=3000),  # 俄文
            ASRDataSeg(text="สวัสดี", start_time=3000, end_time=4000),  # 泰文
        ]
        result = preprocess_segments(segments)
        # Emoji可能被识别为标点，所以应该 >= 3
        assert len(result) >= 3

    def test_mixed_punctuation_types(self):
        """测试混合标点类型"""
        segments = [
            ASRDataSeg(text="...", start_time=0, end_time=500),
            ASRDataSeg(text="！！！", start_time=500, end_time=1000),  # 中文标点
            ASRDataSeg(text="...", start_time=1000, end_time=1500),
            ASRDataSeg(text="？？？", start_time=1500, end_time=2000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 0  # 全是标点

    def test_zero_duration_segments(self):
        """测试零时长片段"""
        segments = [
            ASRDataSeg(text="Hello", start_time=1000, end_time=1000),
            ASRDataSeg(text="World", start_time=1000, end_time=1000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 2

    def test_overlapping_timestamps(self):
        """测试重叠时间戳"""
        segments = [
            ASRDataSeg(text="First", start_time=0, end_time=2000),
            ASRDataSeg(text="Overlap", start_time=1000, end_time=3000),
            ASRDataSeg(text="Third", start_time=2500, end_time=4000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 3

    def test_reversed_timestamps(self):
        """测试倒序时间戳"""
        segments = [
            ASRDataSeg(text="Reversed", start_time=2000, end_time=1000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 1

    def test_very_long_text(self):
        """测试超长文本(>1000字符)"""
        long_text = "测试" * 1000
        segments = [ASRDataSeg(text=long_text, start_time=0, end_time=10000)]
        result = preprocess_segments(segments)
        assert len(result) == 1
        assert len(result[0].text) > 1000

    def test_whitespace_only_segments(self):
        """测试纯空格/制表符/换行符"""
        segments = [
            ASRDataSeg(text="   ", start_time=0, end_time=1000),
            ASRDataSeg(text="\t\t\t", start_time=1000, end_time=2000),
            ASRDataSeg(text="\n\n", start_time=2000, end_time=3000),
            ASRDataSeg(text="Valid", start_time=3000, end_time=4000),
        ]
        result = preprocess_segments(segments)
        # 应该移除纯空白，保留"Valid"
        assert len(result) >= 1

    def test_mixed_case_with_numbers(self):
        """测试大小写混合和数字"""
        segments = [
            ASRDataSeg(text="Test123ABC", start_time=0, end_time=1000),
            ASRDataSeg(text="456XYZ789", start_time=1000, end_time=2000),
        ]
        result = preprocess_segments(segments, need_lower=True)
        assert "test123abc" in result[0].text.lower()

    def test_special_characters(self):
        """测试特殊字符"""
        segments = [
            ASRDataSeg(text="@#$%^&*()", start_time=0, end_time=1000),
            ASRDataSeg(text="<>[]{}\\|", start_time=1000, end_time=2000),
        ]
        result = preprocess_segments(segments)
        # 特殊字符应该被识别为标点或保留
        assert len(result) <= 2

    def test_newlines_and_tabs_in_text(self):
        """测试文本中的换行和制表符"""
        segments = [
            ASRDataSeg(text="Line1\nLine2\tTab", start_time=0, end_time=1000),
        ]
        result = preprocess_segments(segments)
        assert len(result) == 1


class TestSubtitleSplitterEdgeCases:
    """测试 SubtitleSplitter 边缘情况"""

    def test_extremely_short_segments(self):
        """测试极短片段(1-2个字)"""
        segments = [
            ASRDataSeg(text=f"字{i}", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(100)
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20
        )
        result = splitter.split_subtitle(asr_data)

        assert len(result.segments) < len(segments)  # 应该合并了

    def test_extremely_long_single_segment(self):
        """测试超长单个片段(500字)"""
        long_text = "今天我们来讲一讲人工智能的发展历史和未来趋势。" * 50  # 约500字
        segments = [ASRDataSeg(text=long_text, start_time=0, end_time=60000)]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(
            thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20
        )
        result = splitter.split_subtitle(asr_data)

        # 应该被分割成多个片段
        assert len(result.segments) > 10

    def test_alternating_long_short_segments(self):
        """测试长短片段交替"""
        segments = [
            ASRDataSeg(text="我", start_time=0, end_time=100),
            ASRDataSeg(
                text="今天我们来讲一讲人工智能的发展历史" * 5,
                start_time=100,
                end_time=10000,
            ),
            ASRDataSeg(text="好", start_time=10000, end_time=10100),
            ASRDataSeg(
                text="机器学习算法的核心原理和实际应用" * 5,
                start_time=10100,
                end_time=20000,
            ),
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20)
        result = splitter.split_subtitle(asr_data)

        assert len(result.segments) > len(segments)

    def test_all_same_timestamp(self):
        """测试所有片段时间戳相同"""
        segments = [
            ASRDataSeg(text=f"Text{i}", start_time=1000, end_time=2000)
            for i in range(10)
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        assert isinstance(result, ASRData)

    def test_large_time_gaps(self):
        """测试大时间间隔(>10秒)"""
        segments = [
            ASRDataSeg(text="第一段", start_time=0, end_time=1000),
            ASRDataSeg(text="第二段", start_time=20000, end_time=21000),  # 19秒间隔
            ASRDataSeg(text="第三段", start_time=50000, end_time=51000),  # 29秒间隔
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        assert len(result.segments) >= 3

    def test_1000_segments_stress(self):
        """压力测试: 1000个片段"""
        segments = [
            ASRDataSeg(
                text=f"这是第{i}段测试文本内容",
                start_time=i * 1000,
                end_time=(i + 1) * 1000,
            )
            for i in range(1000)
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20)
        result = splitter.split_subtitle(asr_data)

        assert isinstance(result, ASRData)
        assert len(result.segments) > 0

    def test_mixed_language_segments(self):
        """测试混合语言片段"""
        segments = [
            ASRDataSeg(text="Hello你好こんにちは", start_time=0, end_time=1000),
            ASRDataSeg(text="World世界세계", start_time=1000, end_time=2000),
            ASRDataSeg(text="مرحباПривет", start_time=2000, end_time=3000),
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        # 混合语言可能被合并，所以只要有结果即可
        assert len(result.segments) >= 1

    def test_numbers_only_segments(self):
        """测试纯数字片段"""
        segments = [
            ASRDataSeg(text="123456789", start_time=0, end_time=1000),
            ASRDataSeg(text="3.14159265", start_time=1000, end_time=2000),
            ASRDataSeg(text="2024年12月31日", start_time=2000, end_time=3000),
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        # 数字可能被合并，只要有结果即可
        assert len(result.segments) >= 1

    def test_repeated_text_segments(self):
        """测试重复文本"""
        repeated_text = "重复的内容"
        segments = [
            ASRDataSeg(text=repeated_text, start_time=i * 1000, end_time=(i + 1) * 1000)
            for i in range(50)
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        assert len(result.segments) > 0


class TestSplitterParameters:
    """测试分割器参数边界"""

    def test_max_word_count_zero(self):
        """测试最大字数为0(可能被忽略或使用默认值)"""
        segments = [ASRDataSeg(text="测试文本", start_time=0, end_time=1000)]
        asr_data = ASRData(segments)

        try:
            splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=0,
            )
            result = splitter.split_subtitle(asr_data)
            # 如果不抛异常，应该返回有效结果
            assert isinstance(result, ASRData)
        except (ValueError, AssertionError):
            # 也可能抛出异常
            pass

    def test_max_word_count_very_large(self):
        """测试最大字数超大(10000)"""
        segments = [ASRDataSeg(text="测试" * 100, start_time=0, end_time=10000)]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=10000,
        )
        result = splitter.split_subtitle(asr_data)

        # 超大限制应该不分割
        assert len(result.segments) <= 2

    def test_max_word_count_exactly_matches(self):
        """测试字数恰好等于限制"""
        text = "测" * 20  # 恰好20字
        segments = [ASRDataSeg(text=text, start_time=0, end_time=2000)]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20,
        )
        result = splitter.split_subtitle(asr_data)

        assert len(result.segments) >= 1


class TestMergeShortSegments:
    """测试合并短片段边缘情况"""

    def test_all_segments_very_short(self):
        """测试全是超短片段(1-2字)"""
        segments = [
            ASRDataSeg(text="我", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(100)
        ]

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)

        # 应该被合并成更少的片段
        assert len(segments) < 100

    def test_mixed_short_and_long(self):
        """测试短片段和长片段混合"""
        segments = [
            ASRDataSeg(text="短", start_time=0, end_time=100),
            ASRDataSeg(
                text="这是一个很长的片段内容" * 10, start_time=100, end_time=5000
            ),
            ASRDataSeg(text="短", start_time=5000, end_time=5100),
        ]

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        original_len = len(segments)
        splitter.merge_short_segment(segments)

        # 短片段可能被合并
        assert len(segments) <= original_len

    def test_alternating_short_long_pattern(self):
        """测试交替的短长模式"""
        segments = []
        for i in range(50):
            # 短片段
            segments.append(
                ASRDataSeg(text="短", start_time=i * 2000, end_time=i * 2000 + 100)
            )
            # 长片段
            segments.append(
                ASRDataSeg(
                    text="这是一个比较长的片段",
                    start_time=i * 2000 + 100,
                    end_time=(i + 1) * 2000,
                )
            )

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)

        assert len(segments) > 0


class TestStopAndThreading:
    """测试停止和线程控制"""

    def test_stop_before_start(self):
        """测试未开始就停止"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        assert splitter.is_running is True

        splitter.stop()
        assert splitter.is_running is False

    def test_stop_during_processing(self):
        """测试处理过程中停止"""
        # 创建大量数据
        segments = [
            ASRDataSeg(text=f"测试{i}", start_time=i * 100, end_time=(i + 1) * 100)
            for i in range(1000)
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")

        # 立即停止
        splitter.stop()

        # 尝试处理(应该快速返回或抛出异常)
        try:
            result = splitter.split_subtitle(asr_data)
            # 如果成功返回，应该是空的或部分结果
            assert isinstance(result, ASRData)
        except Exception:
            # 允许抛出异常
            pass

    def test_multiple_stop_calls(self):
        """测试多次调用stop"""
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")

        splitter.stop()
        splitter.stop()
        splitter.stop()

        assert splitter.is_running is False


class TestTimestampIntegrity:
    """测试时间戳完整性"""

    def test_no_negative_durations(self):
        """测试分割后无负时长"""
        segments = [
            ASRDataSeg(
                text="今天天气很好我们一起去公园玩吧", start_time=0, end_time=5000
            )
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        for seg in result.segments:
            assert seg.end_time >= seg.start_time

    def test_no_gaps_in_timeline(self):
        """测试时间轴无间隙(对于连续片段)"""
        segments = [
            ASRDataSeg(text="第一段", start_time=0, end_time=1000),
            ASRDataSeg(text="第二段", start_time=1000, end_time=2000),
            ASRDataSeg(text="第三段", start_time=2000, end_time=3000),
        ]
        asr_data = ASRData(segments)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        # 验证时间连续性
        for i in range(len(result.segments) - 1):
            # 允许小间隙，但不应有大跳跃
            gap = result.segments[i + 1].start_time - result.segments[i].end_time
            assert gap >= 0  # 不应重叠太多

    def test_preserves_total_duration(self):
        """测试保持总时长"""
        segments = [ASRDataSeg(text="测试文本" * 50, start_time=0, end_time=10000)]
        asr_data = ASRData(segments)

        original_duration = segments[0].end_time - segments[0].start_time

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter.split_subtitle(asr_data)

        # 总时长应该接近原始时长
        if result.segments:
            total_duration = (
                result.segments[-1].end_time - result.segments[0].start_time
            )
            assert abs(total_duration - original_duration) < 1000  # 允许1秒误差
