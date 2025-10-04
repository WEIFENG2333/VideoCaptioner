from .text_utils import count_words


def optimize_subtitles(asr_data):
    """
    优化字幕分割，合并词数少于等于4且时间相邻的段落。

    参数:
        asr_data (ASRData): 包含字幕段落的 ASRData 对象。
    """
    segments = asr_data.segments
    for i in range(len(segments) - 1, 0, -1):
        seg = segments[i]
        prev_seg = segments[i - 1]

        # 判断前一个段落的词数是否小于等于4且时间相邻
        if (
            count_words(prev_seg.text) <= 4
            and abs(seg.start_time - prev_seg.end_time) < 100
            and count_words(seg.text) <= 10
        ):
            asr_data.merge_with_next_segment(i - 1)
