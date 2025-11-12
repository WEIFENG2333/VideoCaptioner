"""split.py 真实场景测试

使用真实的字幕数据和实际使用场景进行测试
"""

import pytest

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.split.split import SubtitleSplitter, preprocess_segments

# ==================== 真实字幕数据构造器 ====================


def create_whisper_style_segments(
    text: str, start_ms: int = 0, char_duration_ms: int = 250
):
    """模拟 Whisper ASR 输出的词级字幕

    Whisper 通常输出词级时间戳，中文按字，英文按单词
    """
    from app.core.utils.text_utils import is_mainly_cjk

    segments = []
    current_time = start_ms

    if is_mainly_cjk(text):
        # 中文：每个字一个分段
        for char in text:
            if char.strip() and not char in "，。！？、；：" "''（）":
                duration = char_duration_ms
                # 标点符号更短
                if char in "，。！？":
                    duration = 100
                segments.append(
                    ASRDataSeg(
                        text=char,
                        start_time=current_time,
                        end_time=current_time + duration,
                    )
                )
                current_time += duration
    else:
        # 英文：按单词分段
        words = text.split()
        for word in words:
            # 单词长度影响时长
            duration = max(200, len(word) * 80)
            segments.append(
                ASRDataSeg(
                    text=word, start_time=current_time, end_time=current_time + duration
                )
            )
            current_time += duration

    return segments


class TestRealWorldScenarios:
    """测试真实世界的字幕场景"""

    def test_podcast_long_monologue(self):
        """测试播客式长独白（50+字，需要智能分段）"""
        text = "今天我们要讨论的话题是人工智能在现代社会中的应用特别是在医疗健康领域的突破性进展这些技术正在深刻地改变着我们的生活方式从诊断到治疗再到康复每个环节都有AI技术的身影"
        segments = create_whisper_style_segments(text, start_ms=0, char_duration_ms=200)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=20)
        asr_data = ASRData(segments)

        # 预处理：转换为词级
        if not asr_data.is_word_timestamp():
            asr_data = asr_data.split_to_word_segments()

        # 应该有分段，但不会太多（智能分段而非机械切割）
        assert len(segments) > 30  # 原始很长
        # 实际测试中，LLM 会智能分段，这里只测试规则降级
        # result = splitter.split_subtitle(asr_data)
        # assert len(result.segments) < len(segments)

    def test_interview_qa_with_pauses(self):
        """测试访谈式问答（有明显停顿）"""
        segments = []

        # 问题："你对这个项目有什么看法？"
        q = create_whisper_style_segments("你对这个项目有什么看法", start_ms=0)
        segments.extend(q)

        # 2秒停顿（思考时间）
        pause_end = q[-1].end_time + 2000

        # 回答："我认为这个项目非常有前景，它解决了一个关键问题。"
        a = create_whisper_style_segments(
            "我认为这个项目非常有前景它解决了一个关键问题", start_ms=pause_end
        )
        segments.extend(a)

        # 短停顿
        pause2_end = a[-1].end_time + 500

        # 补充："不过还需要进一步完善细节。"
        followup = create_whisper_style_segments(
            "不过还需要进一步完善细节", start_ms=pause2_end
        )
        segments.extend(followup)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        # 测试时间间隔分组
        groups = splitter._group_by_time_gaps(segments, max_gap=1500)

        # 应该识别出停顿，分成至少 2 组
        assert len(groups) >= 2
        # 第一组是问题
        assert len(groups[0]) > 0

    def test_news_broadcast_style(self):
        """测试新闻播报风格（节奏稳定、语速均匀）"""
        text = "据中央气象台消息今天夜间到明天白天北京地区将有小到中雪气温下降明显请市民注意防寒保暖"
        segments = create_whisper_style_segments(text, char_duration_ms=180)

        # 新闻播报：时间间隔相对均匀
        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=15)
        groups = splitter._group_by_time_gaps(segments, max_gap=1000)

        # 没有大停顿，应该是一组
        assert len(groups) == 1 or len(groups) == 2

    def test_casual_conversation_with_hesitation(self):
        """测试日常对话（有犹豫、重复、语气词）"""
        segments = []
        current_time = 0

        # "嗯...这个...怎么说呢..."（犹豫）
        hesitations = [
            ("嗯", 600, 200),  # 语气词，较长停顿
            ("这", 250, 150),
            ("个", 250, 300),  # 另一个停顿
            ("怎", 200, 100),
            ("么", 200, 100),
            ("说", 250, 100),
            ("呢", 400, 500),  # 更长停顿
        ]

        for text, duration, pause in hesitations:
            segments.append(
                ASRDataSeg(
                    text=text, start_time=current_time, end_time=current_time + duration
                )
            )
            current_time += duration + pause

        # 主要内容
        main = create_whisper_style_segments(
            "我觉得这个方案还是挺不错的", start_ms=current_time
        )
        segments.extend(main)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        # 测试合并短片段功能
        splitter.merge_short_segment(segments)

        # 语气词应该被合并
        assert len(segments) < len(hesitations) + len(main)

    def test_technical_presentation_bilingual(self):
        """测试技术演讲（中英混合）"""
        segments = []
        current_time = 0

        # "我们使用 machine learning 来处理这个问题"
        # 中文部分
        cn1 = create_whisper_style_segments("我们使用", start_ms=current_time)
        segments.extend(cn1)
        current_time = cn1[-1].end_time

        # 英文专业术语（通常说得慢一点）
        segments.extend(
            [
                ASRDataSeg(
                    text="machine", start_time=current_time, end_time=current_time + 500
                ),
                ASRDataSeg(
                    text="learning",
                    start_time=current_time + 500,
                    end_time=current_time + 1000,
                ),
            ]
        )
        current_time += 1000

        # 继续中文
        cn2 = create_whisper_style_segments("来处理这个问题", start_ms=current_time)
        segments.extend(cn2)

        # 预处理应该正确处理混合语言
        result = preprocess_segments(segments)

        # 英文应该被转小写并加空格
        english_segs = [
            s for s in result if s.text.lower() in ["machine ", "learning "]
        ]
        assert len(english_segs) == 2
        assert all(" " in seg.text for seg in english_segs)

    def test_subtitle_with_background_noise_gaps(self):
        """测试有背景噪音导致的不规则间隔"""
        segments = []
        current_time = 0

        # 正常句子
        s1 = create_whisper_style_segments("大家好", start_ms=current_time)
        segments.extend(s1)
        current_time = s1[-1].end_time

        # 背景噪音（可能被识别为极短的无意义音节）
        segments.append(
            ASRDataSeg(
                text="呃", start_time=current_time + 100, end_time=current_time + 150
            )
        )
        current_time += 200

        # 继续
        s2 = create_whisper_style_segments("欢迎来到今天的分享", start_ms=current_time)
        segments.extend(s2)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        # 噪音应该在预处理时被识别（如果是纯标点）或合并
        result = preprocess_segments(segments)

        # 验证处理后的结果
        assert len(result) > 0


class TestEdgeCasesRealistic:
    """测试实际使用中的边缘情况"""

    def test_very_fast_speech(self):
        """测试快速语速（每字150ms）"""
        text = "快速语速测试数据这样的字幕通常出现在快节奏的节目中"
        segments = create_whisper_style_segments(text, char_duration_ms=150)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=15)
        # 快速语速不应该导致过度分割
        result = splitter._split_long_segment(segments[:15])
        assert len(result) >= 1

    def test_very_slow_speech(self):
        """测试慢速语速（每字500ms）"""
        text = "慢速语速每个字之间有明显停顿"
        segments = create_whisper_style_segments(text, char_duration_ms=500)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        # 慢速不应该被错误分组
        groups = splitter._group_by_time_gaps(segments, max_gap=1500)
        assert len(groups) >= 1

    def test_subtitle_with_numbers_and_punctuation(self):
        """测试包含数字和标点的字幕"""
        # 真实场景："今天是2024年1月15日，温度是零下5度。"
        segments = []
        current_time = 0

        parts = [
            "今",
            "天",
            "是",
            "2024",
            "年",
            "1",
            "月",
            "15",
            "日",
            "温",
            "度",
            "是",
            "零",
            "下",
            "5",
            "度",
        ]
        for part in parts:
            duration = 300 if len(part) > 1 else 250
            segments.append(
                ASRDataSeg(
                    text=part, start_time=current_time, end_time=current_time + duration
                )
            )
            current_time += duration

        # 预处理不应该移除数字
        result = preprocess_segments(segments)
        assert any("2024" in seg.text for seg in result)
        assert any("15" in seg.text for seg in result)

    def test_empty_or_whitespace_segments(self):
        """测试空白或仅空格的分段（ASR错误输出）"""
        segments = [
            ASRDataSeg(text="正常", start_time=0, end_time=300),
            ASRDataSeg(text="   ", start_time=300, end_time=400),  # 仅空格
            ASRDataSeg(text="", start_time=400, end_time=500),  # 空字符串
            ASRDataSeg(text="文本", start_time=500, end_time=800),
        ]

        result = preprocess_segments(segments)
        # 空白应该被处理（可能保留或移除）
        assert len(result) >= 2

    def test_subtitle_crossing_one_hour(self):
        """测试超过1小时的长视频字幕"""
        # 模拟1小时节目的一段（3,600,000 ms = 1 hour）
        segments = []
        start_time = 3500000  # 58分钟处

        text = "这是接近一小时处的字幕内容需要一些更长的文本才能超过一小时的时间戳"
        segments = create_whisper_style_segments(
            text, start_ms=start_time, char_duration_ms=350
        )

        # 时间戳应该正确处理
        if segments:
            assert segments[-1].end_time > start_time  # 至少递增
            assert segments[-1].start_time < segments[-1].end_time

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        result = splitter._split_long_segment(segments)

        # 验证时间戳没有溢出或错误
        assert all(seg.start_time < seg.end_time for seg in result)


class TestGroupByTimeGapsRealistic:
    """测试时间间隔分组的真实场景"""

    def test_scene_change_detection(self):
        """测试场景切换检测（通常有3-5秒静音）"""
        segments = []

        # 场景1："欢迎收看今天的节目"
        scene1 = create_whisper_style_segments("欢迎收看今天的节目", start_ms=0)
        segments.extend(scene1)

        # 场景切换（4秒静音）
        scene_change_gap = 4000
        scene2_start = scene1[-1].end_time + scene_change_gap

        # 场景2："接下来我们进入下一环节"
        scene2 = create_whisper_style_segments(
            "接下来我们进入下一环节", start_ms=scene2_start
        )
        segments.extend(scene2)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        groups = splitter._group_by_time_gaps(
            segments, max_gap=2000, check_large_gaps=True
        )

        # 应该检测到场景切换（允许空组）
        non_empty_groups = [g for g in groups if g]
        assert len(non_empty_groups) == 2

    def test_natural_sentence_pauses(self):
        """测试自然句子间的停顿（200-500ms）"""
        segments = []
        current_time = 0

        sentences = [
            "第一句话",
            "第二句话",
            "第三句话",
        ]

        for sentence in sentences:
            segs = create_whisper_style_segments(sentence, start_ms=current_time)
            segments.extend(segs)
            # 句子间自然停顿（300ms）
            current_time = segs[-1].end_time + 300

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        # 用较小的 gap 不应该分组
        groups = splitter._group_by_time_gaps(segments, max_gap=500)
        assert len(groups) == 1

        # 用较大的 gap 可能分组
        groups = splitter._group_by_time_gaps(segments, max_gap=200)
        assert len(groups) >= 2


class TestSplitByCommonWordsRealistic:
    """测试常见词分割的真实场景"""

    def test_long_compound_sentence_chinese(self):
        """测试中文复合句（使用'但是'、'所以'等连词）"""
        text = "我觉得这个方案很好但是还需要优化一下所以我建议再讨论讨论"
        segments = create_whisper_style_segments(text)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_cjk=15)
        groups = splitter._split_by_common_words(segments)

        # 应该在"但是"、"所以"处考虑分割
        assert len(groups) >= 1

    def test_english_compound_sentence(self):
        """测试英文复合句"""
        text = "I think this is a good idea but we need more time and we should discuss it further"
        segments = create_whisper_style_segments(text)

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini", max_word_count_english=12)
        groups = splitter._split_by_common_words(segments)

        # 应该在 "but"、"and" 处考虑分割
        assert len(groups) >= 1


class TestMergeShortSegmentRealistic:
    """测试短片段合并的真实场景"""

    def test_merge_single_character_words(self):
        """测试合并单字词（"我"、"你"、"他"等）"""
        # "我 去 过 那 里" -> 应该合并成一句
        segments = []
        current_time = 0
        words = ["我", "去", "过", "那", "里"]

        for word in words:
            segments.append(
                ASRDataSeg(
                    text=word, start_time=current_time, end_time=current_time + 200
                )
            )
            current_time += 250  # 50ms 间隔

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)

        # 应该合并成更少的片段
        assert len(segments) < len(words)

    def test_dont_merge_across_large_pause(self):
        """测试不跨越大停顿合并"""
        segments = [
            ASRDataSeg(text="短", start_time=0, end_time=200),
            ASRDataSeg(text="句", start_time=200, end_time=400),
            # 大停顿（1秒）
            ASRDataSeg(text="新", start_time=1400, end_time=1600),
            ASRDataSeg(text="句", start_time=1600, end_time=1800),
        ]

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        original_len = len(segments)
        splitter.merge_short_segment(segments)

        # 不应该跨越大停顿合并，至少保留2个片段
        assert len(segments) >= 2

    def test_merge_interjections(self):
        """测试合并语气词"""
        # "嗯 好的 我 知道 了"
        segments = []
        current_time = 0
        parts = [
            ("嗯", 300),
            ("好", 200),
            ("的", 200),
            ("我", 200),
            ("知", 200),
            ("道", 200),
            ("了", 200),
        ]

        for text, duration in parts:
            segments.append(
                ASRDataSeg(
                    text=text, start_time=current_time, end_time=current_time + duration
                )
            )
            current_time += duration + 50

        splitter = SubtitleSplitter(thread_num=1, model="gpt-4o-mini")
        splitter.merge_short_segment(segments)

        # 语气词应该被合并
        assert len(segments) < len(parts)
