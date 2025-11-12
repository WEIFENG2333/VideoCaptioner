"""ASRData 核心功能测试 - 严格边缘用例"""

import tempfile
from pathlib import Path

import pytest

from app.core.asr.asr_data import ASRData, ASRDataSeg


class TestASRDataSegEdgeCases:
    """测试 ASRDataSeg 边缘情况"""

    def test_zero_duration_segment(self):
        """测试零时长字幕段"""
        seg = ASRDataSeg("Instant", 1000, 1000)
        assert seg.start_time == seg.end_time
        timestamp = seg.to_srt_ts()
        assert timestamp == "00:00:01,000 --> 00:00:01,000"

    def test_negative_duration(self):
        """测试倒序时间戳(start > end)"""
        seg = ASRDataSeg("Reversed", 2000, 1000)
        assert seg.start_time > seg.end_time  # 不应自动修正

    def test_very_long_timestamp(self):
        """测试超长时间戳(超过24小时)"""
        seg = ASRDataSeg("Long", 90000000, 90001000)  # 25小时
        timestamp = seg.to_srt_ts()
        assert "25:00:00,000" in timestamp

    def test_unicode_text_extreme(self):
        """测试极端Unicode文本"""
        # Emoji + 中文 + 日文 + 韩文 + 阿拉伯文
        text = "😀你好こんにちは안녕مرحبا"
        seg = ASRDataSeg(text, 0, 1000)
        assert seg.text == text

    def test_empty_translation(self):
        """测试空翻译与无翻译的区别"""
        seg1 = ASRDataSeg("Test", 0, 1000)
        seg2 = ASRDataSeg("Test", 0, 1000, translated_text="")
        assert seg1.translated_text == seg2.translated_text == ""

    def test_multiline_text(self):
        """测试多行文本"""
        text = "Line 1\nLine 2\nLine 3"
        seg = ASRDataSeg(text, 0, 1000)
        assert "\n" in seg.text
        assert seg.text.count("\n") == 2


class TestASRDataEdgeCases:
    """测试 ASRData 边缘情况"""

    def test_mixed_empty_and_whitespace(self):
        """测试混合空字符串和纯空格"""
        segments = [
            ASRDataSeg("Valid", 0, 1000),
            ASRDataSeg("", 1000, 2000),
            ASRDataSeg("   ", 2000, 3000),
            ASRDataSeg("\t\n", 3000, 4000),
            ASRDataSeg("  Valid  ", 4000, 5000),  # 前后空格应保留
        ]
        asr_data = ASRData(segments)
        assert len(asr_data) == 2
        assert asr_data.segments[1].text == "  Valid  "

    def test_overlapping_timestamps(self):
        """测试重叠的时间戳"""
        segments = [
            ASRDataSeg("First", 0, 2000),
            ASRDataSeg("Overlap", 1000, 3000),  # 重叠
            ASRDataSeg("Third", 2500, 4000),
        ]
        asr_data = ASRData(segments)
        # 应按start_time排序，但不修正重叠
        assert asr_data.segments[0].text == "First"
        assert asr_data.segments[1].text == "Overlap"

    def test_unsorted_large_dataset(self):
        """测试大量乱序数据"""
        segments = [
            ASRDataSeg(f"Text{i}", i * 1000, (i + 1) * 1000) for i in range(1000, 0, -1)
        ]
        asr_data = ASRData(segments)
        # 应该正确排序
        for i in range(len(asr_data) - 1):
            assert (
                asr_data.segments[i].start_time <= asr_data.segments[i + 1].start_time
            )

    def test_duplicate_timestamps(self):
        """测试完全相同的时间戳"""
        segments = [
            ASRDataSeg("First", 1000, 2000),
            ASRDataSeg("Second", 1000, 2000),
            ASRDataSeg("Third", 1000, 2000),
        ]
        asr_data = ASRData(segments)
        assert len(asr_data) == 3  # 都应保留

    def test_single_segment(self):
        """测试单个字幕段的边界情况"""
        segments = [ASRDataSeg("Only", 0, 1000)]
        asr_data = ASRData(segments)
        # 各种操作不应崩溃
        asr_data.optimize_timing()
        assert len(asr_data) == 1


class TestWordTimestampEdgeCases:
    """测试词级时间戳检测边缘情况"""

    def test_exactly_80_percent_threshold(self):
        """测试恰好80%阈值"""
        # 10个片段，8个词级，2个句子级
        segments = [ASRDataSeg(f"word{i}", i * 100, (i + 1) * 100) for i in range(8)]
        segments.extend(
            [
                ASRDataSeg("This is sentence", 800, 900),
                ASRDataSeg("Another sentence", 900, 1000),
            ]
        )
        asr_data = ASRData(segments)
        assert asr_data.is_word_timestamp()  # 80% 应该通过

    def test_79_percent_below_threshold(self):
        """测试略低于80%阈值"""
        # 10个片段，7个词级，3个句子级
        segments = [ASRDataSeg(f"word{i}", i * 100, (i + 1) * 100) for i in range(7)]
        segments.extend(
            [
                ASRDataSeg("This is sentence", 700, 800),
                ASRDataSeg("Another sentence", 800, 900),
                ASRDataSeg("Third sentence", 900, 1000),
            ]
        )
        asr_data = ASRData(segments)
        assert not asr_data.is_word_timestamp()  # 70% 不应通过

    def test_mixed_cjk_latin_single_chars(self):
        """测试混合CJK和拉丁单字符"""
        segments = [
            ASRDataSeg("你", 0, 100),  # CJK单字
            ASRDataSeg("好", 100, 200),
            ASRDataSeg("a", 200, 300),  # 拉丁单字符
            ASRDataSeg("b", 300, 400),
        ]
        asr_data = ASRData(segments)
        assert asr_data.is_word_timestamp()

    def test_three_char_cjk(self):
        """测试3字符CJK(边界情况)"""
        segments = [ASRDataSeg("你好吗", 0, 1000)]  # 3个字符，不是词级
        asr_data = ASRData(segments)
        assert not asr_data.is_word_timestamp()


class TestSplitToWordsEdgeCases:
    """测试分词边缘情况"""

    def test_split_empty_text(self):
        """测试空文本分词"""
        segments = [ASRDataSeg("", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        assert len(asr_data.segments) == 0

    def test_split_only_punctuation(self):
        """测试纯标点分词"""
        segments = [ASRDataSeg("..., !!!", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        assert len(asr_data.segments) == 0  # 标点不应匹配

    def test_split_very_long_word(self):
        """测试超长单词"""
        long_word = "a" * 1000
        segments = [ASRDataSeg(long_word, 0, 10000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        assert len(asr_data.segments) == 1
        assert asr_data.segments[0].text == long_word

    def test_split_mixed_scripts(self):
        """测试混合多种文字系统"""
        # 拉丁+中文+日文+韩文+阿拉伯文+俄文
        text = "Hello你好こんにちは안녕مرحباПривет"
        segments = [ASRDataSeg(text, 0, 7000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        # 应该正确分割各种文字
        assert len(asr_data.segments) > 5
        texts = [seg.text for seg in asr_data.segments]
        assert "Hello" in texts
        assert "Привет" in texts

    def test_split_numbers_and_words(self):
        """测试数字和单词混合"""
        segments = [ASRDataSeg("version 3.14 build 2024", 0, 3000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        texts = [seg.text for seg in asr_data.segments]
        assert "version" in texts
        assert "3" in texts or "14" in texts  # 数字应被分开
        assert "build" in texts
        assert "2024" in texts

    def test_split_thai_with_combining_chars(self):
        """测试泰文带组合字符"""
        thai_text = "สวัสดี"  # 泰文 "你好"
        segments = [ASRDataSeg(thai_text, 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        assert len(asr_data.segments) > 0  # 应该能匹配泰文

    def test_split_zero_duration_distribution(self):
        """测试零时长的时间分配"""
        segments = [ASRDataSeg("Hello world", 1000, 1000)]
        asr_data = ASRData(segments)
        asr_data.split_to_word_segments()
        # 零时长应该不崩溃
        assert all(seg.start_time == 1000 for seg in asr_data.segments)
        assert all(seg.end_time == 1000 for seg in asr_data.segments)


class TestMergeEdgeCases:
    """测试合并边缘情况"""

    def test_merge_single_segment(self):
        """测试合并单个片段(自己和自己)"""
        segments = [ASRDataSeg("Only", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.merge_segments(0, 0)
        assert len(asr_data.segments) == 1
        assert asr_data.segments[0].text == "Only"

    def test_merge_all_segments(self):
        """测试合并所有片段"""
        segments = [ASRDataSeg(f"T{i}", i * 100, (i + 1) * 100) for i in range(10)]
        asr_data = ASRData(segments)
        asr_data.merge_segments(0, 9)
        assert len(asr_data.segments) == 1
        assert "T0" in asr_data.segments[0].text
        assert "T9" in asr_data.segments[0].text

    def test_merge_invalid_indices(self):
        """测试无效的合并索引"""
        segments = [ASRDataSeg("A", 0, 1000), ASRDataSeg("B", 1000, 2000)]
        asr_data = ASRData(segments)

        with pytest.raises(IndexError):
            asr_data.merge_segments(-1, 1)  # 负索引
        with pytest.raises(IndexError):
            asr_data.merge_segments(0, 5)  # 超出范围
        with pytest.raises(IndexError):
            asr_data.merge_segments(1, 0)  # start > end

    def test_merge_with_next_at_boundary(self):
        """测试在边界位置合并"""
        segments = [ASRDataSeg("Only", 0, 1000)]
        asr_data = ASRData(segments)

        with pytest.raises(IndexError):
            asr_data.merge_with_next_segment(0)  # 没有下一个

    def test_merge_with_unicode(self):
        """测试合并Unicode文本"""
        segments = [
            ASRDataSeg("😀你好", 0, 1000),
            ASRDataSeg("🌍world", 1000, 2000),
        ]
        asr_data = ASRData(segments)
        asr_data.merge_with_next_segment(0)
        assert "😀" in asr_data.segments[0].text
        assert "🌍" in asr_data.segments[0].text


class TestOptimizeTimingEdgeCases:
    """测试时间优化边缘情况"""

    def test_optimize_negative_gap(self):
        """测试负间隔(重叠)"""
        segments = [
            ASRDataSeg("First", 0, 2000),
            ASRDataSeg("Overlap", 1500, 3000),  # 重叠500ms
        ]
        asr_data = ASRData(segments)
        asr_data.optimize_timing()
        # 负间隔不应优化(或根据实现调整)
        assert asr_data.segments[0].end_time == 2000

    def test_optimize_exact_threshold(self):
        """测试恰好在阈值边界"""
        segments = [
            ASRDataSeg("First sentence", 0, 1000),
            ASRDataSeg("Second sentence", 2000, 3000),  # 恰好1000ms gap
        ]
        asr_data = ASRData(segments)
        asr_data.optimize_timing(threshold_ms=1000)
        # 恰好等于阈值不优化(需要 < threshold)
        gap = asr_data.segments[1].start_time - asr_data.segments[0].end_time
        assert gap == 1000  # 应该保持不变

    def test_optimize_word_level_no_change(self):
        """测试词级时间戳不优化"""
        segments = [
            ASRDataSeg("Word1", 0, 500),
            ASRDataSeg("Word2", 1000, 1500),
        ]
        asr_data = ASRData(segments)
        original_end = asr_data.segments[0].end_time

        asr_data.optimize_timing()
        # 词级应该跳过优化
        assert asr_data.segments[0].end_time == original_end


class TestRemovePunctuationEdgeCases:
    """测试移除标点边缘情况"""

    def test_remove_multiple_punctuation(self):
        """测试连续多个标点"""
        segments = [ASRDataSeg("你好，，，。。。", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.remove_punctuation()
        assert asr_data.segments[0].text == "你好"

    def test_remove_punctuation_only(self):
        """测试纯标点文本"""
        segments = [ASRDataSeg("，。，。", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.remove_punctuation()
        assert asr_data.segments[0].text == ""

    def test_remove_punctuation_middle(self):
        """测试中间的标点不移除"""
        segments = [ASRDataSeg("你好，世界。", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.remove_punctuation()
        assert asr_data.segments[0].text == "你好，世界"  # 只删尾部

    def test_remove_non_chinese_punctuation(self):
        """测试非中文标点不移除"""
        segments = [ASRDataSeg("Hello, world!", 0, 1000)]
        asr_data = ASRData(segments)
        asr_data.remove_punctuation()
        assert asr_data.segments[0].text == "Hello, world!"  # 不变


class TestFormatConversionEdgeCases:
    """测试格式转换边缘情况"""

    def test_srt_layout_modes_all(self):
        """测试所有SRT布局模式"""
        from app.core.entities import SubtitleLayoutEnum

        segments = [ASRDataSeg("Hello", 0, 1000, translated_text="你好")]
        asr_data = ASRData(segments)

        srt1 = asr_data.to_srt(layout=SubtitleLayoutEnum.ORIGINAL_ON_TOP)
        assert "Hello\n你好" in srt1

        srt2 = asr_data.to_srt(layout=SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        assert "你好\nHello" in srt2

        srt3 = asr_data.to_srt(layout=SubtitleLayoutEnum.ONLY_ORIGINAL)
        assert "Hello" in srt3
        assert "你好" not in srt3

        srt4 = asr_data.to_srt(layout=SubtitleLayoutEnum.ONLY_TRANSLATE)
        assert "你好" in srt4

    def test_srt_no_translation_all_layouts(self):
        """测试无翻译时的所有布局"""
        segments = [ASRDataSeg("Hello", 0, 1000)]
        asr_data = ASRData(segments)

        for layout in ["原文在上", "译文在上", "仅原文", "仅译文"]:
            srt = asr_data.to_srt(layout=layout)
            assert "Hello" in srt  # 所有模式都应显示原文

    def test_json_large_dataset(self):
        """测试大数据集JSON转换"""
        segments = [
            ASRDataSeg(f"Text{i}", i * 1000, (i + 1) * 1000) for i in range(1000)
        ]
        asr_data = ASRData(segments)
        json_data = asr_data.to_json()
        assert len(json_data) == 1000
        assert "1" in json_data
        assert "1000" in json_data

    def test_txt_multiline_segments(self):
        """测试多行文本转换"""
        segments = [
            ASRDataSeg("Line1\nLine2", 0, 1000),
            ASRDataSeg("Line3", 1000, 2000),
        ]
        asr_data = ASRData(segments)
        txt = asr_data.to_txt()
        assert "Line1\nLine2" in txt


class TestFileIOEdgeCases:
    """测试文件读写边缘情况"""

    def test_save_unsupported_format(self):
        """测试不支持的格式"""
        segments = [ASRDataSeg("Test", 0, 1000)]
        asr_data = ASRData(segments)

        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Unsupported file extension"):
                asr_data.save(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_load_nonexistent_file(self):
        """测试加载不存在的文件"""
        with pytest.raises(FileNotFoundError):
            ASRData.from_subtitle_file("/nonexistent/path/file.srt")

    def test_save_load_unicode_path(self):
        """测试Unicode文件路径"""
        segments = [ASRDataSeg("测试", 0, 1000)]
        asr_data = ASRData(segments)

        with tempfile.TemporaryDirectory() as tmpdir:
            unicode_path = Path(tmpdir) / "测试文件名.srt"
            asr_data.save(str(unicode_path))
            loaded = ASRData.from_subtitle_file(str(unicode_path))
            assert loaded.segments[0].text == "测试"


class TestParseEdgeCases:
    """测试解析边缘情况"""

    def test_parse_malformed_srt(self):
        """测试畸形SRT"""
        malformed = """1
00:00:00,000 --> INVALID
Hello

2
INVALID TIMESTAMP
World
"""
        asr_data = ASRData.from_srt(malformed)
        assert len(asr_data.segments) == 0  # 应跳过无效块

    def test_parse_srt_missing_text(self):
        """测试缺少文本的SRT块"""
        srt = """1
00:00:00,000 --> 00:00:01,000

2
00:00:01,000 --> 00:00:02,000
Valid
"""
        asr_data = ASRData.from_srt(srt)
        assert len(asr_data.segments) == 1
        assert asr_data.segments[0].text == "Valid"

    def test_parse_srt_97_percent_translation(self):
        """测试97%翻译(低于98%阈值)"""
        # 100个块，97个有翻译
        blocks = []
        for i in range(97):
            blocks.append(
                f"{i+1}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\nText{i}\nTrans{i}\n"
            )
        for i in range(97, 100):
            blocks.append(
                f"{i+1}\n00:00:{i:02d},000 --> 00:00:{i+1:02d},000\nText{i}\n"
            )

        srt = "\n".join(blocks)
        asr_data = ASRData.from_srt(srt)
        # 低于98%不应识别为翻译格式
        assert not asr_data.segments[0].translated_text

    def test_parse_json_non_numeric_keys(self):
        """测试JSON非数字键"""
        json_data = {
            "a": {
                "original_subtitle": "Test",
                "translated_subtitle": "",
                "start_time": 0,
                "end_time": 1000,
            }
        }
        with pytest.raises(ValueError):
            ASRData.from_json(json_data)

    def test_parse_vtt_empty_blocks(self):
        """测试VTT空块"""
        vtt = """WEBVTT

HEADER


1
00:00:01.000 --> 00:00:02.000
Text1


"""
        asr_data = ASRData.from_vtt(vtt)
        assert len(asr_data.segments) == 1
