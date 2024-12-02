import difflib
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List
from retry import retry

from .split_by_llm import split_by_llm, MAX_WORD_COUNT
from ..bk_asr.ASRData import ASRData, from_srt, ASRDataSeg
from ..utils.logger import setup_logger

logger = setup_logger("subtitle_spliter")

SEGMENT_THRESHOLD = 500  # 每个分段的最大字数
FIXED_NUM_THREADS = 1  # 固定的线程数量
SPLIT_RANGE = 30  # 在分割点前后寻找最大时间间隔的范围
MAX_GAP = 1500  # 允许每个词语之间的最大时间间隔 ms
USE_CACHE = True  # 是否使用缓存

MAX_WORD_COUNT_ENGLISH = 12  # 英文最大单词数
MAX_WORD_COUNT_CJK = 20     # 中日韩文字最大字数

class SubtitleProcessError(Exception):
    """字幕处理相关的异常"""
    pass

def is_pure_punctuation(s: str) -> bool:
    """
    检查字符串是否仅由标点符号组成
    """
    return not re.search(r'\w', s, flags=re.UNICODE)


def count_words(text: str) -> int:
    """
    统计多语言文本中的字符/单词数
    支持:
    - 英文（按空格分词）
    - CJK文字（中日韩统一表意文字）
    - 韩文/谚文
    - 泰文
    - 阿拉伯文
    - 俄文西里尔字母
    - 希伯来文
    - 越南文
    每个字符都计为1个单位，英文按照空格分词计数
    """
    # 定义各种语言的Unicode范围
    patterns = [
        r'[\u4e00-\u9fff]',           # 中日韩统一表意文字
        r'[\u3040-\u309f]',           # 平假名
        r'[\u30a0-\u30ff]',           # 片假名
        r'[\uac00-\ud7af]',           # 韩文音节
        r'[\u0e00-\u0e7f]',           # 泰文
        r'[\u0600-\u06ff]',           # 阿拉伯文
        r'[\u0400-\u04ff]',           # 西里尔字母（俄文等）
        r'[\u0590-\u05ff]',           # 希伯来文
        r'[\u1e00-\u1eff]',           # 越南文
        r'[\u3130-\u318f]',           # 韩文兼容字母
    ]
    
    # 统计所有非英文字符
    non_english_chars = 0
    remaining_text = text
    
    for pattern in patterns:
        # 计算当前语言的字符数
        chars = len(re.findall(pattern, remaining_text))
        non_english_chars += chars
        # 从文本中移除已计数的字符
        remaining_text = re.sub(pattern, ' ', remaining_text)
    
    # 计算英文单词数（处理剩余的文本）
    english_words = len(remaining_text.strip().split())
    
    return non_english_chars + english_words


def preprocess_text(s: str) -> str:
    """
    通过转换为小写并规范化空格来标准化文本
    """
    return ' '.join(s.lower().split())


def merge_segments_based_on_sentences(segments: List[ASRDataSeg], sentences: List[str], max_unmatched: int = 5) -> List[ASRDataSeg]:
    """
    基于提供的句子列表合并ASR分段
    
    Args:
        asr_data: ASR数据对象
        sentences: 句子列表
        max_unmatched: 允许的最大未匹配句子数量，超过此数量将抛出异常
        
    Returns:
        合并后的 ASRDataSeg 列表
        
    Raises:
        SubtitleProcessError: 当未匹配句子数量超过阈值时抛出
    """
    asr_texts = [seg.text for seg in segments]
    asr_len = len(asr_texts)
    asr_index = 0  # 当前分段索引位置
    threshold = 0.5  # 相似度阈值
    max_shift = 30  # 滑动窗口的最大偏移量
    unmatched_count = 0  # 未匹配句子计数

    new_segments = []

    # logger.debug(f"ASR分段: {asr_texts}")

    for sentence in sentences:
        logger.debug(f"==========")
        logger.debug(f"处理句子: {sentence}")
        logger.debug("后续句子:" + "".join(asr_texts[asr_index: asr_index+10]))

        sentence_proc = preprocess_text(sentence)
        word_count = count_words(sentence_proc)
        best_ratio = 0.0
        best_pos = None
        best_window_size = 0

        # 滑动窗口大小，优先考虑接近句子词数的窗口
        max_window_size = min(word_count * 2, asr_len - asr_index)
        min_window_size = max(1, word_count // 2)
        window_sizes = sorted(range(min_window_size, max_window_size + 1), key=lambda x: abs(x - word_count))
        # logger.debug(f"window_sizes: {window_sizes}")

        for window_size in window_sizes:
            max_start = min(asr_index + max_shift + 1, asr_len - window_size + 1)
            for start in range(asr_index, max_start):
                substr = ''.join(asr_texts[start:start + window_size])
                substr_proc = preprocess_text(substr)
                ratio = difflib.SequenceMatcher(None, sentence_proc, substr_proc).ratio()
                # logger.debug(f"-----")
                # logger.debug(f"sentence_proc: {sentence_proc}, substr_proc: {substr_proc}, ratio: {ratio}")

                if ratio > best_ratio:
                    best_ratio = ratio
                    best_pos = start
                    best_window_size = window_size
                if ratio == 1.0:
                    break  # 完全匹配
            if best_ratio == 1.0:
                break  # 完全匹配

        if best_ratio >= threshold and best_pos is not None:
            start_seg_index = best_pos
            end_seg_index = best_pos + best_window_size - 1
            
            segs_to_merge = segments[start_seg_index:end_seg_index + 1]

            # 按照时间切分避免合并跨度大的
            seg_groups = merge_by_time_gaps(segs_to_merge, max_gap=MAX_GAP)
            # logger.debug(f"分段组: {len(seg_groups)}")

            for group in seg_groups:
                merged_text = ''.join(seg.text for seg in group)
                merged_start_time = group[0].start_time
                merged_end_time = group[-1].end_time
                merged_seg = ASRDataSeg(merged_text, merged_start_time, merged_end_time)
                
                logger.debug(f"合并分段: {merged_seg.text}")
                
                # 考虑最大词数的拆分
                split_segs = split_long_segment(group)
                new_segments.extend(split_segs)
            max_shift = 30
            asr_index = end_seg_index + 1  # 移动到下一个未处理的分段
        else:
            logger.warning(f"无法匹配句子: {sentence}")
            unmatched_count += 1
            if unmatched_count > max_unmatched:
                raise SubtitleProcessError(f"未匹配句子数量超过阈值，处理终止")
            max_shift = 100
            asr_index = min(asr_index + 1, asr_len - 1)  # 确保不会超出范围

    return new_segments


def is_mainly_cjk(text: str) -> bool:
    """
    判断文本是否主要由中日韩文字组成
    
    Args:
        text: 输入文本
    Returns:
        bool: 如果CJK字符占比超过50%则返回True
    """
    # 定义CJK字符的Unicode范围
    cjk_patterns = [
        r'[\u4e00-\u9fff]',           # 中日韩统一表意文字
        r'[\u3040-\u309f]',           # 平假名
        r'[\u30a0-\u30ff]',           # 片假名
        r'[\uac00-\ud7af]',           # 韩文音节
    ]
    
    # 计算CJK字符数
    cjk_count = 0
    for pattern in cjk_patterns:
        cjk_count += len(re.findall(pattern, text))
    
    # 计算总字符数（不包括空白字符）
    total_chars = len(''.join(text.split()))
    
    # 如果CJK字符占比超过50%，则认为主要是CJK文本
    return cjk_count / total_chars > 0.5 if total_chars > 0 else False


def split_long_segment(segs_to_merge: List[ASRDataSeg]) -> List[ASRDataSeg]:
    """
    基于最大时间间隔拆分长分段，根据文本类型使用不同的最大词数限制
    """
    result_segs = []
    
    # 添加空列表检查
    if not segs_to_merge:
        return result_segs
        
    merged_text = ''.join(seg.text for seg in segs_to_merge)

    # 根据文本类型确定最大词数限制
    max_word_count = MAX_WORD_COUNT_CJK if is_mainly_cjk(merged_text) else MAX_WORD_COUNT_ENGLISH
    # logger.debug(f"正在拆分分段: {merged_text}")

    # 基本情况：如果分段足够短或无法进一步拆分
    if count_words(merged_text) <= max_word_count or len(segs_to_merge) == 1:
        merged_seg = ASRDataSeg(
            merged_text.strip(),
            segs_to_merge[0].start_time,
            segs_to_merge[-1].end_time
        )
        result_segs.append(merged_seg)
        return result_segs
    
    # logger.debug(f"正在拆分长分段: {merged_text}")

    # 检查时间间隔是否都相等
    n = len(segs_to_merge)
    gaps = [segs_to_merge[i+1].start_time - segs_to_merge[i].end_time for i in range(n-1)]
    all_equal = all(abs(gap - gaps[0]) < 1e-6 for gap in gaps)

    if all_equal:
        # 如果时间间隔都相等，在中间位置断句
        split_index = n // 2
    else:
        # 在分段中间2/3部分寻找最大时间间隔点
        start_idx = n // 6
        end_idx = (5 * n) // 6
        split_index = max(
            range(start_idx, end_idx),
            key=lambda i: segs_to_merge[i + 1].start_time - segs_to_merge[i].end_time,
            default=n // 2
        )

    first_segs = segs_to_merge[:split_index + 1]
    second_segs = segs_to_merge[split_index + 1:]
    # logger.debug(f"分段1: {''.join(seg.text for seg in first_segs)}")
    # logger.debug(f"分段2: {''.join(seg.text for seg in second_segs)}")
    # logger.debug(f"-------")
    # 递归拆分
    result_segs.extend(split_long_segment(first_segs))
    result_segs.extend(split_long_segment(second_segs))

    return result_segs


def split_asr_data(asr_data: ASRData, num_segments: int) -> List[ASRData]:
    """
    长文本发送LLM前进行进行分割，根据ASR分段中的时间间隔，将ASRData拆分成多个部分。

    处理步骤：
    1. 计算总字数，并确定每个分段的字数范围。
    2. 确定平均分割点。
    3. 在分割点前后一定范围内，寻找时间间隔最大的点作为实际的分割点。
    """
    total_segs = len(asr_data.segments)
    total_word_count = count_words(asr_data.to_txt())
    words_per_segment = total_word_count // num_segments
    split_indices = []

    if num_segments <= 1 or total_segs <= num_segments:
        return [asr_data]

    # 计算每个分段的大致字数 根据每段字数计算分割点
    split_indices = [i * words_per_segment for i in range(1, num_segments)]
    # 调整分割点：在每个平均分割点附近寻找时间间隔最大的点
    adjusted_split_indices = []
    for split_point in split_indices:
        # 定义搜索范围
        start = max(0, split_point - SPLIT_RANGE)
        end = min(total_segs - 1, split_point + SPLIT_RANGE)
        # 在范围内找到时间间隔最大的点
        max_gap = -1
        best_index = split_point
        for j in range(start, end):
            gap = asr_data.segments[j + 1].start_time - asr_data.segments[j].end_time
            if gap > max_gap:
                max_gap = gap
                best_index = j
        adjusted_split_indices.append(best_index)
    # 移除重复的分割点
    adjusted_split_indices = sorted(list(set(adjusted_split_indices)))

    # 根据调整后的分割点拆分ASRData
    segments = []
    prev_index = 0
    for index in adjusted_split_indices:
        part = ASRData(asr_data.segments[prev_index:index + 1])
        segments.append(part)
        prev_index = index + 1
    # 添加最后一部分
    if prev_index < total_segs:
        part = ASRData(asr_data.segments[prev_index:])
        segments.append(part)
    return segments


def merge_short_segment(segments: List[ASRDataSeg]) -> None:
    """
    经过LLM断句后，继续优化字幕，合并词数少于等于5且时间相邻的段落。
    
    Args:
        segments: 字幕段落列表，将直接在此列表上进行修改
    """
    if not segments:  # 添加空列表检查
        return
        
    i = 0  # 从头开始遍历
    while i < len(segments) - 1:  # 修改遍历方式
        current_seg = segments[i]
        next_seg = segments[i + 1]
        
        # 判断是否需要合并:
        # 1. 时间间隔小于300ms
        # 2. 当前段落或下一段落词数小于5
        # 3. 合并后总词数不超过限制
        time_gap = abs(next_seg.start_time - current_seg.end_time)
        current_words = count_words(current_seg.text)
        next_words = count_words(next_seg.text)
        total_words = current_words + next_words
        max_word_count = MAX_WORD_COUNT_CJK if is_mainly_cjk(current_seg.text) else MAX_WORD_COUNT_ENGLISH

        if time_gap < 300 and (current_words < 5 or next_words <= 5) and total_words <= max_word_count:
            # 执行合并操作
            logger.debug(f"优化：合并相邻分段: {current_seg.text} --- {next_seg.text} -> {time_gap}")
            
            # 更新当前段落的文本和结束时间
            current_seg.text = current_seg.text + next_seg.text
            current_seg.end_time = next_seg.end_time
            
            # 从列表中移除下一个段落
            segments.pop(i + 1)
            # 不增加i，因为需要继续检查合并后的段落
        else:
            i += 1


def determine_num_segments(word_count: int, threshold: int = 1000) -> int:
    """
    根据字数计算分段数，每1000个字为一个分段，至少为1
    """
    num_segments = word_count // threshold
    # 如果存在余数，增加一个分段
    if word_count % threshold > 0:
        num_segments += 1
    return max(1, num_segments)


def preprocess_segments(segments: List[ASRDataSeg], need_lower=True) -> List[ASRDataSeg]:
    """
    预处理ASR数据分段:
    1. 移除纯标点符号的分段
    2. 对仅包含字母、数字和撇号的文本进行小写处理并添加空格
    
    Args:
        segments: ASR数据分段列表
    Returns:
        处理后的分段列表
    """
    new_segments = []
    for seg in segments:
        if not is_pure_punctuation(seg.text):
            # 如果文本只包含字母、数字和撇号，则将其转换为小写并添加一个空格
            if re.match(r'^[a-zA-Z0-9\']+$', seg.text.strip()):
                if need_lower:
                    seg.text = seg.text.lower() + " "
                else:
                    seg.text = seg.text + " "
            new_segments.append(seg)
    return new_segments


def merge_by_time_gaps(segments: List[ASRDataSeg], max_gap: int = MAX_GAP, check_large_gaps: bool = False) -> List[List[ASRDataSeg]]:
    """
    检查字幕分段之间的时间间隔，如果超过阈值则分段
    
    Args:
        segments: 待检查的分段列表
        max_gap: 最大允许的时间间隔（ms）
        check_large_gaps: 是否检查连续的大时间间隔
        
    Returns:
        分段后的列表的列表
    """
    if not segments:
        return []
    
    result = []
    current_group = [segments[0]]
    recent_gaps = []  # 存储最近的时间间隔
    WINDOW_SIZE = 5   # 检查最近5个间隔
    
    for i in range(1, len(segments)):
        time_gap = segments[i].start_time - segments[i-1].end_time
        
        if check_large_gaps:
            recent_gaps.append(time_gap)
            if len(recent_gaps) > WINDOW_SIZE:
                recent_gaps.pop(0)
            if len(recent_gaps) == WINDOW_SIZE:
                avg_gap = sum(recent_gaps) / len(recent_gaps)
                # 如果当前间隔大于平均值的3倍
                if time_gap > avg_gap*3 and len(current_group) > 5:
                    logger.debug(f"检测到大间隔: {time_gap}ms, 平均间隔: {avg_gap}ms")
                    result.append(current_group)
                    current_group = []
                    recent_gaps = []  # 重置间隔记录
        
        if time_gap > max_gap:
            logger.debug(f"超过阈值，分组: {''.join(seg.text for seg in current_group)}")
            result.append(current_group)
            current_group = []
            recent_gaps = []  # 重置间隔记录
            
        current_group.append(segments[i])
    
    if current_group:
        result.append(current_group)
    
    return result


def merge_common_words(segments: List[ASRDataSeg]) -> List[List[ASRDataSeg]]:
    """
    在常见连接词前后进行分割，确保分割后的每个分段都至少有5个单词
    假设每个segment就是一个词
    
    Args:
        segments: ASR数据分段列表，每个segment包含一个词
    Returns:
        分组后的分段列表的列表
    """
    # 定义在词语前面分割的常见词（prefix_split_words）
    prefix_split_words = {
        # 英文冠词
        "a", "an", "the",
        # 英文连接词和介词
        "and", "or", "but", "if", "then", "because", "as", "until", "while",
        "when", "where", "nor", "yet", "so", "for", "however", "moreover",
        "furthermore", "therefore", "thus", "although", "though", "nevertheless",
        "meanwhile", "consequently", "additionally", "besides", "instead", "unless",
        "since", "before", "after", "during", "within", "without", "up", "down",
        "out", "off", "into", "onto", "upon", "toward", "against", "near",
        "inside", "outside", "across", "around", "behind", "beyond", "beside",
        "beneath", "except",
        # 英文代词（主格和宾格）
        "i", "you", "he", "she", "it", "we", "they",
        "me", "him", "her", "us", "them",
        # 英文物主代词和指示代词
        "my", "your", "his", "her", "its", "our", "their",
        "that", "this", "these", "those",
        "what", "who", "whom", "whose", "which", "why", "how",
        # 英文介词
        "in", "on", "at", "to", "for", "with", "by", "from",
        "about", "above", "below", "under", "over",
        "through", "between", "among",
        # 中文并列连词
        "和", "及", "与", "但", "而", "或","因"
        # 中文人称代词
        "我", "你", "他", "她", "它", "咱", "您","这", "那", "哪"
    }

    # 定义在词语后面分割的常见词（suffix_split_words）
    suffix_split_words = {
        # 标点符号
        ".", ",", "!", "?", "。", "，", "！", "？",
        # 英文所有格代词
        "mine", "yours", "his", "hers", "its", "ours", "theirs",
        # 英文副词
        "too", "either", "neither",
        # 中文语气词和助词
        "的", "了", "着", "过", "吗", "呢", "吧", "啊", "呀", "哦", "哈", "嘛", "啦"
    }

    
    result = []
    current_group = []
    
    for i, seg in enumerate(segments):
        # 如果当前词是前缀词且前面已经累积了至少7个词
        # logger.debug(seg.text)
        max_word_count = MAX_WORD_COUNT_CJK if is_mainly_cjk(seg.text) else MAX_WORD_COUNT_ENGLISH
        if any(seg.text.lower().startswith(word) for word in prefix_split_words) and len(current_group) >= int(max_word_count*0.6):
            # 合并当前组并添加到结果
            result.append(current_group)
            logger.debug(f"在前缀词 {seg.text} 前分割 - {''.join(seg.text for seg in current_group)}")
            current_group = []
        
        # 如果前一个词是后缀词且当前组至少有5个词
        if i > 0 and any(segments[i-1].text.lower().endswith(word) for word in suffix_split_words) and len(current_group) >= int(max_word_count*0.4):
            # 添加当前组到结果
            result.append(current_group)
            logger.debug(f"在后缀词 {segments[i-1].text} 后分割 - {''.join(seg.text for seg in current_group)}")

            current_group = []
        
        current_group.append(seg)
    
    # 处理最后剩余的分组
    if current_group:
        result.append(current_group)
    
    return result


def process_by_rules(segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
    """
    使用规则进行基础的句子分割
    
    规则包括:
    1. 考虑时间间隔，超过阈值的进行分割
    2. 在常见连接词前后进行分割（保证分割后两个分段都大于5个单词）
    3. 分割大于 MAX_WORD_COUNT 个单词的分段

    Args:
        segments: ASR数据分段列表
    Returns:
        处理后的分段列表
    """
    print(f"分段: {len(segments)}")
    # 1. 先按时间间隔分组
    segment_groups = merge_by_time_gaps(segments, max_gap=500, check_large_gaps=True)
    print(f"按时间间隔分组分组: {len(segment_groups)}")

    # ====接下来遍历每个分组====
    # 2. 按常用词分割, 只处理长句
    common_result_groups = []
    for group in segment_groups:
        # logger.debug("".join(seg.text for seg in group))
        max_word_count = MAX_WORD_COUNT_CJK if is_mainly_cjk("".join(seg.text for seg in group)) else MAX_WORD_COUNT_ENGLISH
        if count_words("".join(seg.text for seg in group)) > max_word_count:    
            segments = merge_common_words(group)
            common_result_groups.extend(segments)
        else:
            common_result_groups.append(group)

    result_segments = []
    # 3. 处理过长的分段，并合并group为seg
    for group in common_result_groups:
        result_segments.extend(split_long_segment(group))
    
    return result_segments


def process_by_llm(segments: List[ASRDataSeg], 
                   model: str = "gpt-4o-mini",
                   max_word_count_cjk: int = MAX_WORD_COUNT_CJK,
                   max_word_count_english: int = MAX_WORD_COUNT_ENGLISH) -> List[ASRDataSeg]:

    """
    使用LLM拆分句子

    示例：
    segments = [ASRDataSeg("Hello"), ASRDataSeg("world!")]
    result = [ASRDataSeg("Hello world")]
    """
    txt = "".join([seg.text for seg in segments])
    # 使用LLM拆分句子
    sentences = split_by_llm(txt, 
                             model=model, 
                             use_cache=USE_CACHE,
                             max_word_count_cjk=max_word_count_cjk,
                             max_word_count_english=max_word_count_english)
    logger.info(f"分段的句子提取完成，共 {len(sentences)} 句")
    # 对当前分段进行合并处理
    merged_segments = merge_segments_based_on_sentences(segments, sentences)
    return merged_segments


def merge_segments(asr_data: ASRData, 
                   model: str = "gpt-4o-mini", 
                   num_threads: int = FIXED_NUM_THREADS, 
                   max_word_count_cjk: int = MAX_WORD_COUNT_CJK, 
                   max_word_count_english: int = MAX_WORD_COUNT_ENGLISH) -> ASRData:
    """
    合并ASR数据分段
    
    Args:
        asr_data: ASR数据对象
        model: 使用的LLM模型名称
        num_threads: 并行处理的线程数
        max_word_count: 每个分段的最大字数限制，会覆盖默认值
    Returns:
        处理后的ASR数据对象
    """
    # 更新全局的MAX_WORD_COUNT
    global MAX_WORD_COUNT_CJK, MAX_WORD_COUNT_ENGLISH
    MAX_WORD_COUNT_CJK = max_word_count_cjk
    MAX_WORD_COUNT_ENGLISH = max_word_count_english

    # 预处理ASR数据，移除纯标点符号的分段，并处理仅包含字母和撇号的文本
    asr_data.segments = preprocess_segments(asr_data.segments, need_lower=False)
    txt = asr_data.to_txt().replace("\n", "")
    total_word_count = count_words(txt)

    # 确定分段数，分割ASRData
    num_segments = determine_num_segments(total_word_count, threshold=SEGMENT_THRESHOLD)
    logger.info(f"根据字数 {total_word_count}，确定分段数: {num_segments}")
    asr_data_segments = split_asr_data(asr_data, num_segments)

    # 多线程处理每个分段
    logger.info("开始并行处理每个分段...")
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        def process_segment(asr_data_part):
            try:
                # raise Exception("test")
                return process_by_llm(asr_data_part.segments, model=model)
            except Exception as e:
                logger.warning(f"LLM处理失败，使用规则based方法进行分割: {str(e)}")
                return process_by_rules(asr_data_part.segments)

        # 并行处理所有分段
        processed_segments = list(executor.map(process_segment, asr_data_segments))

    # 合并所有处理后的分段
    final_segments = []
    for segment in processed_segments:
        final_segments.extend(segment)

    final_segments.sort(key=lambda seg: seg.start_time)

    merge_short_segment(final_segments)

    # 创建最终的ASRData对象
    final_asr_data = ASRData(final_segments)

    return final_asr_data