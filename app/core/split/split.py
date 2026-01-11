import atexit
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.split.split_by_llm import split_by_llm
from app.core.utils.logger import setup_logger
from app.core.utils.text_utils import (
    count_words,
    is_mainly_cjk,
    is_pure_punctuation,
    is_space_separated_language,
)

logger = setup_logger("subtitle_splitter")

# ==================== 配置常量 ====================

# 字数限制
MAX_WORD_COUNT_CJK = 25  # CJK文本单行最大字数
MAX_WORD_COUNT_ENGLISH = 18  # 英文文本单行最大单词数

# 分段阈值
SEGMENT_WORD_THRESHOLD = 500  # 长文本分段阈值(字数)

# 时间间隔
MAX_GAP = 1500  # 允许的最大时间间隔(毫秒)
MERGE_SHORT_GAP = 200  # 短分段合并时间阈值(毫秒)
MERGE_VERY_SHORT_GAP = 500  # 极短分段合并时间阈值(毫秒)

# 短分段合并阈值
MERGE_MIN_WORDS = 5  # 短分段最小字数阈值
MERGE_VERY_SHORT_WORDS = 3  # 极短分段字数阈值

# 分割相关
SPLIT_SEARCH_RANGE = 30  # 分割点前后搜索范围
TIME_GAP_WINDOW_SIZE = 5  # 时间间隔窗口大小
TIME_GAP_MULTIPLIER = 3  # 大间隔判断倍数
MIN_GROUP_SIZE = 5  # 最小分组大小

# 规则分割
RULE_SPLIT_GAP = 500  # 规则分割时间间隔阈值(毫秒)
RULE_MIN_SEGMENT_SIZE = 4  # 规则分割最小分段大小

# 常见词分割
PREFIX_WORD_RATIO = 0.6  # 前缀词分割比例
SUFFIX_WORD_RATIO = 0.4  # 后缀词分割比例

# 匹配相关
MATCH_SIMILARITY_THRESHOLD = 0.5  # 文本匹配相似度阈值
MATCH_MAX_SHIFT = 30  # 匹配滑动窗口最大偏移
MATCH_MAX_UNMATCHED = 5  # 允许的最大未匹配句子数
MATCH_LARGE_SHIFT = 100  # 未匹配时的大偏移量


def preprocess_segments(
    segments: List[ASRDataSeg], need_lower: bool = True
) -> List[ASRDataSeg]:
    """预处理ASR分段

    1. 移除纯标点符号的分段
    2. 为需要空格分隔的语言添加空格（英语、俄语、阿拉伯语等，不包括CJK）

    Args:
        segments: ASR数据分段列表
        need_lower: 是否转小写（仅对拉丁和西里尔字母有效）

    Returns:
        处理后的分段列表
    """
    new_segments = []
    for seg in segments:
        if not is_pure_punctuation(seg.text):
            text = seg.text.strip()
            # 检查是否为需要空格分隔的语言（不包括CJK）
            if is_space_separated_language(text):
                if need_lower:
                    text = text.lower()
                seg.text = text + " "
            new_segments.append(seg)
    return new_segments


class SubtitleSplitter:
    """字幕智能分割器

    使用LLM进行语义分段,支持缓存、并发处理和规则降级。
    """

    def __init__(
        self,
        thread_num,
        model,
        max_word_count_cjk: int = MAX_WORD_COUNT_CJK,
        max_word_count_english: int = MAX_WORD_COUNT_ENGLISH,
    ):
        """初始化分割器

        Args:
            thread_num: 并发线程数
            model: LLM模型名称
            max_word_count_cjk: CJK最大字数
            max_word_count_english: 英文最大单词数
        """
        self.thread_num = thread_num
        self.model = model
        self.max_word_count_cjk = max_word_count_cjk
        self.max_word_count_english = max_word_count_english
        self.is_running = True
        self._init_thread_pool()

    def _init_thread_pool(self):
        """初始化线程池并注册清理"""
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    def split_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
        """分割字幕(主入口)

        处理流程:
        1. 读取并预处理字幕
        2. 按字数分段
        3. 并发调用LLM处理
        4. 合并结果并优化

        Args:
            subtitle_data: 字幕文件路径或ASRData对象

        Returns:
            分割后的ASRData对象

        Raises:
            RuntimeError: 分割失败时抛出
        """
        try:
            # 1. 读取字幕
            if isinstance(subtitle_data, str):
                asr_data = ASRData.from_subtitle_file(subtitle_data)
            else:
                asr_data = subtitle_data

            if not asr_data.is_word_timestamp():
                asr_data = asr_data.split_to_word_segments()

            # 2. 预处理
            asr_data.segments = preprocess_segments(asr_data.segments, need_lower=False)
            txt = asr_data.to_txt().replace("\n", "")

            # 3. 确定分段数并分割
            total_word_count = count_words(txt)
            num_segments = self._determine_num_segments(total_word_count)
            logger.info(f"根据字数 {total_word_count},确定断句分段数: {num_segments}")

            asr_data_list = self._split_asr_data(asr_data, num_segments)

            # 4. 并发处理
            processed_segments = self._process_segments(asr_data_list)

            # 5. 合并并优化
            final_segments = self._merge_processed_segments(processed_segments)

            return ASRData(final_segments)

        except Exception as e:
            logger.error(f"分割失败:{str(e)}")
            raise RuntimeError(f"分割失败:{str(e)}")

    def _determine_num_segments(
        self, word_count: int, threshold: int = SEGMENT_WORD_THRESHOLD
    ) -> int:
        """根据字数确定分段数

        Args:
            word_count: 总字数
            threshold: 每段目标字数

        Returns:
            分段数(最小为1)
        """
        num_segments = word_count // threshold
        if word_count % threshold > 0:
            num_segments += 1
        return max(1, num_segments)

    def _split_asr_data(self, asr_data: ASRData, num_segments: int) -> List[ASRData]:
        """按时间间隔智能分割长文本

        策略:
        1. 计算平均分割点
        2. 在分割点附近寻找最大时间间隔
        3. 在间隔处切分以保证语义完整

        Args:
            asr_data: ASR数据对象
            num_segments: 目标分段数

        Returns:
            分割后的ASRData列表
        """
        total_segs = len(asr_data.segments)
        total_word_count = count_words(asr_data.to_txt())
        words_per_segment = total_word_count // num_segments

        if num_segments <= 1 or total_segs <= num_segments:
            return [asr_data]

        # 计算初始分割点
        split_indices = [i * words_per_segment for i in range(1, num_segments)]

        # 调整分割点:在附近寻找最大时间间隔
        adjusted_split_indices = []
        for split_point in split_indices:
            start = max(0, split_point - SPLIT_SEARCH_RANGE)
            end = min(total_segs - 1, split_point + SPLIT_SEARCH_RANGE)

            # 寻找最大间隔点
            max_gap = -1
            best_index = split_point

            for j in range(start, end):
                gap = (
                    asr_data.segments[j + 1].start_time - asr_data.segments[j].end_time
                )
                if gap > max_gap:
                    max_gap = gap
                    best_index = j

            adjusted_split_indices.append(best_index)

        # 去重并排序
        adjusted_split_indices = sorted(list(set(adjusted_split_indices)))

        # 执行分割
        segments = []
        prev_index = 0
        for index in adjusted_split_indices:
            part = ASRData(asr_data.segments[prev_index : index + 1])
            segments.append(part)
            prev_index = index + 1

        if prev_index < total_segs:
            part = ASRData(asr_data.segments[prev_index:])
            segments.append(part)

        return segments

    def _process_segments(self, asr_data_list: List[ASRData]) -> List[List[ASRDataSeg]]:
        """并发处理所有分段"""
        futures = []
        for asr_data in asr_data_list:
            if not self.executor:
                raise ValueError("线程池未初始化")
            future = self.executor.submit(self._process_single_segment, asr_data)
            futures.append(future)

        processed_segments = []
        for future in as_completed(futures):
            if not self.is_running:
                break
            try:
                result = future.result()
                processed_segments.append(result)
            except Exception as e:
                logger.error(f"处理分段失败:{str(e)}")

        return processed_segments

    def _process_single_segment(self, asr_data_part: ASRData) -> List[ASRDataSeg]:
        """处理单个分段(带重试和降级)"""
        if not asr_data_part.segments:
            return []
        try:
            return self._process_by_llm(asr_data_part.segments)
        except Exception as e:
            logger.warning(f"LLM处理失败,使用规则降级: {str(e)}")
            return self._process_by_rules(asr_data_part.segments)

    def _process_by_llm(self, segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        """使用LLM进行智能分段

        Args:
            segments: ASR分段列表

        Returns:
            处理后的分段列表
        """
        txt = "".join([seg.text for seg in segments])
        logger.info(f"开始调用API进行分段,文本长度: {count_words(txt)}")

        sentences = split_by_llm(
            text=txt,
            model=self.model,
            max_word_count_cjk=self.max_word_count_cjk,
            max_word_count_english=self.max_word_count_english,
        )

        return self._merge_segments_based_on_sentences(segments, sentences)

    def _process_by_rules(self, segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        """使用规则进行基础分割(LLM降级方案)

        规则:
        1. 按时间间隔分组
        2. 按常见词分割长句
        3. 拆分超长分段

        Args:
            segments: ASR分段列表

        Returns:
            处理后的分段列表
        """
        logger.info(f"分段: {len(segments)}")

        # 1. 按时间间隔分组
        segment_groups = self._group_by_time_gaps(
            segments, max_gap=RULE_SPLIT_GAP, check_large_gaps=True
        )
        logger.info(f"按时间间隔分组: {len(segment_groups)}")

        # 2. 按常见词分割长句
        common_result_groups = []
        for group in segment_groups:
            max_word_count = (
                self.max_word_count_cjk
                if is_mainly_cjk("".join(seg.text for seg in group))
                else self.max_word_count_english
            )
            if count_words("".join(seg.text for seg in group)) > max_word_count:
                split_groups = self._split_by_common_words(group)
                common_result_groups.extend(split_groups)
            else:
                common_result_groups.append(group)

        # 3. 拆分超长分段
        result_segments = []
        for group in common_result_groups:
            result_segments.extend(self._split_long_segment(group))

        return result_segments

    def _group_by_time_gaps(
        self,
        segments: List[ASRDataSeg],
        max_gap: int = MAX_GAP,
        check_large_gaps: bool = False,
    ) -> List[List[ASRDataSeg]]:
        """按时间间隔分组

        Args:
            segments: 分段列表
            max_gap: 最大允许间隔(ms)
            check_large_gaps: 是否检查异常大间隔

        Returns:
            分组后的列表
        """
        if not segments:
            return []

        result = []
        current_group = [segments[0]]
        recent_gaps = []

        for i in range(1, len(segments)):
            time_gap = segments[i].start_time - segments[i - 1].end_time

            # 检查异常大间隔
            if check_large_gaps:
                recent_gaps.append(time_gap)
                if len(recent_gaps) > TIME_GAP_WINDOW_SIZE:
                    recent_gaps.pop(0)
                if len(recent_gaps) == TIME_GAP_WINDOW_SIZE:
                    avg_gap = sum(recent_gaps) / len(recent_gaps)
                    if (
                        time_gap > avg_gap * TIME_GAP_MULTIPLIER
                        and len(current_group) > MIN_GROUP_SIZE
                    ):
                        result.append(current_group)
                        current_group = []
                        recent_gaps = []

            # 超过最大间隔则分组
            if time_gap > max_gap:
                result.append(current_group)
                current_group = []
                recent_gaps = []

            current_group.append(segments[i])

        if current_group:
            result.append(current_group)

        return result

    def _split_by_common_words(
        self, segments: List[ASRDataSeg]
    ) -> List[List[ASRDataSeg]]:
        """在常见连接词处分割

        Args:
            segments: ASR分段列表

        Returns:
            分割后的分组列表
        """
        # 前缀分割词(在这些词前面分割)
        prefix_split_words = {
            # 英文
            "and",
            "or",
            "but",
            "if",
            "then",
            "because",
            "as",
            "until",
            "while",
            "what",
            "when",
            "where",
            "nor",
            "yet",
            "so",
            "for",
            "however",
            "moreover",
            # 中文
            "和",
            "及",
            "与",
            "但",
            "而",
            "或",
            "因",
            "我",
            "你",
            "他",
            "她",
            "它",
            "咱",
            "您",
            "这",
            "那",
            "哪",
        }

        # 后缀分割词(在这些词后面分割)
        suffix_split_words = {
            # 标点
            ".",
            ",",
            "!",
            "?",
            "。",
            "，",
            "！",
            "？",
            # 中文语气词
            "的",
            "了",
            "着",
            "过",
            "吗",
            "呢",
            "吧",
            "啊",
            "呀",
            "嘛",
            "啦",
            # 英文代词
            "mine",
            "yours",
            "hers",
            "its",
            "ours",
            "theirs",
            "either",
            "neither",
        }

        result = []
        current_group = []

        for i, seg in enumerate(segments):
            max_word_count = (
                self.max_word_count_cjk
                if is_mainly_cjk(seg.text)
                else self.max_word_count_english
            )

            # 前缀词分割
            if any(
                seg.text.lower().startswith(word) for word in prefix_split_words
            ) and len(current_group) >= int(max_word_count * PREFIX_WORD_RATIO):
                result.append(current_group)
                logger.debug(f"在前缀词 {seg.text} 前分割")
                current_group = []

            # 后缀词分割
            if (
                i > 0
                and any(
                    segments[i - 1].text.lower().endswith(word)
                    for word in suffix_split_words
                )
                and len(current_group) >= int(max_word_count * SUFFIX_WORD_RATIO)
            ):
                result.append(current_group)
                logger.debug(f"在后缀词 {segments[i - 1].text} 后分割")
                current_group = []

            current_group.append(seg)

        if current_group:
            result.append(current_group)

        return result

    def _split_long_segment(self, segments: List[ASRDataSeg]) -> List[ASRDataSeg]:
        """拆分超长分段

        策略:寻找最大时间间隔点进行拆分

        Args:
            segments: 分段列表

        Returns:
            拆分后的分段列表
        """
        result_segs = []
        segments_to_process = [segments]

        while segments_to_process:
            current_segments = segments_to_process.pop(0)

            if not current_segments:
                continue

            merged_text = "".join(seg.text for seg in current_segments)
            max_word_count = (
                self.max_word_count_cjk
                if is_mainly_cjk(merged_text)
                else self.max_word_count_english
            )
            n = len(current_segments)

            # 分段足够短或无法继续拆分
            if count_words(merged_text) <= max_word_count or n < RULE_MIN_SEGMENT_SIZE:
                merged_seg = ASRDataSeg(
                    merged_text.strip(),
                    current_segments[0].start_time,
                    current_segments[-1].end_time,
                )
                result_segs.append(merged_seg)
                continue

            # 检查时间间隔
            gaps = [
                current_segments[i + 1].start_time - current_segments[i].end_time
                for i in range(n - 1)
            ]
            all_equal = all(abs(gap - gaps[0]) < 1e-6 for gap in gaps)

            if all_equal:
                # 间隔相等:中间分割
                split_index = n // 2
            else:
                # 间隔不等:寻找最大间隔点
                start_idx = max(n // 6, 1)
                end_idx = min((5 * n) // 6, n - 2)
                split_index = max(
                    range(start_idx, end_idx),
                    key=lambda i: current_segments[i + 1].start_time
                    - current_segments[i].end_time,
                    default=n // 2,
                )
                if split_index == 0 or split_index == n - 1:
                    split_index = n // 2

            # 分割并加入处理队列
            first_segs = current_segments[: split_index + 1]
            second_segs = current_segments[split_index + 1 :]
            segments_to_process.extend([first_segs, second_segs])

        # 按时间排序
        result_segs.sort(key=lambda seg: seg.start_time)
        return result_segs

    def _merge_processed_segments(
        self, processed_segments: List[List[ASRDataSeg]]
    ) -> List[ASRDataSeg]:
        """合并所有处理后的分段并排序"""
        final_segments = []
        for segments in processed_segments:
            final_segments.extend(segments)

        final_segments.sort(key=lambda seg: seg.start_time)
        return final_segments

    def merge_short_segment(self, segments: List[ASRDataSeg]) -> None:
        """deprecated
        合并短分段优化

        合并条件:
        1. 时间间隔小 + 字数少
        2. 合并后不超过最大字数限制

        Args:
            segments: 分段列表(原地修改)
        """
        if not segments:
            return

        i = 0
        while i < len(segments) - 1:
            current_seg = segments[i]
            next_seg = segments[i + 1]

            time_gap = abs(next_seg.start_time - current_seg.end_time)
            current_words = count_words(current_seg.text)
            next_words = count_words(next_seg.text)
            total_words = current_words + next_words
            max_word_count = (
                self.max_word_count_cjk
                if is_mainly_cjk(current_seg.text)
                else self.max_word_count_english
            )

            # 判断是否合并
            should_merge = (
                time_gap < MERGE_SHORT_GAP
                and (current_words < MERGE_MIN_WORDS or next_words < MERGE_MIN_WORDS)
                and total_words <= max_word_count
            ) or (
                time_gap < MERGE_VERY_SHORT_GAP
                and (
                    current_words < MERGE_VERY_SHORT_WORDS
                    or next_words < MERGE_VERY_SHORT_WORDS
                )
                and total_words <= max_word_count
            )

            if should_merge:
                logger.debug(
                    f"合并短分段: {current_seg.text} + {next_seg.text} (间隔:{time_gap}ms)"
                )

                # 合并文本
                if is_mainly_cjk(current_seg.text):
                    current_seg.text += next_seg.text
                else:
                    current_seg.text += " " + next_seg.text
                current_seg.end_time = next_seg.end_time

                segments.pop(i + 1)
            else:
                i += 1

    def _merge_segments_based_on_sentences(
        self,
        segments: List[ASRDataSeg],
        sentences: List[str],
        max_unmatched: int = MATCH_MAX_UNMATCHED,
    ) -> List[ASRDataSeg]:
        """基于LLM返回的句子列表合并ASR分段

        使用滑动窗口匹配算法:
        1. 对每个LLM句子,寻找最佳匹配的ASR分段序列
        2. 使用相似度算法进行匹配
        3. 合并匹配的分段

        Args:
            segments: ASR分段列表
            sentences: LLM返回的句子列表
            max_unmatched: 允许的最大未匹配句子数

        Returns:
            合并后的分段列表

        Raises:
            ValueError: 未匹配句子数超过阈值时
        """

        def preprocess_text(s: str) -> str:
            """文本标准化:小写+空格规范化"""
            return " ".join(s.lower().split())

        asr_texts = [seg.text for seg in segments]
        asr_len = len(asr_texts)
        asr_index = 0
        threshold = MATCH_SIMILARITY_THRESHOLD
        max_shift = MATCH_MAX_SHIFT
        unmatched_count = 0

        new_segments = []

        for sentence in sentences:
            logger.debug("==========")
            logger.debug(f"处理句子: {sentence}")
            logger.debug("后续句子:" + "".join(asr_texts[asr_index : asr_index + 10]))

            sentence_proc = preprocess_text(sentence)
            word_count = count_words(sentence_proc)
            best_ratio = 0.0
            best_pos = None
            best_window_size = 0

            # 滑动窗口大小
            max_window_size = min(word_count * 2, asr_len - asr_index)
            min_window_size = max(1, word_count // 2)
            window_sizes = sorted(
                range(min_window_size, max_window_size + 1),
                key=lambda x: abs(x - word_count),
            )

            # 滑动窗口匹配
            for window_size in window_sizes:
                max_start = min(asr_index + max_shift + 1, asr_len - window_size + 1)
                for start in range(asr_index, max_start):
                    substr = "".join(asr_texts[start : start + window_size])
                    substr_proc = preprocess_text(substr)
                    ratio = difflib.SequenceMatcher(
                        None, sentence_proc, substr_proc
                    ).ratio()

                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_pos = start
                        best_window_size = window_size
                    if ratio == 1.0:
                        break
                if best_ratio == 1.0:
                    break

            # 处理匹配结果
            if best_ratio >= threshold and best_pos is not None:
                start_seg_index = best_pos
                end_seg_index = best_pos + best_window_size - 1

                segs_to_merge = segments[start_seg_index : end_seg_index + 1]

                # 按时间切分避免跨度过大
                seg_groups = self._group_by_time_gaps(segs_to_merge, max_gap=MAX_GAP)

                for group in seg_groups:
                    merged_text = "".join(seg.text for seg in group)
                    merged_start_time = group[0].start_time
                    merged_end_time = group[-1].end_time
                    merged_seg = ASRDataSeg(
                        merged_text, merged_start_time, merged_end_time
                    )

                    logger.debug(f"合并分段: {merged_seg.text}")

                    # 拆分超长分段
                    split_segs = self._split_long_segment(group)
                    new_segments.extend(split_segs)

                max_shift = MATCH_MAX_SHIFT
                asr_index = end_seg_index + 1
            else:
                logger.warning(f"无法匹配句子: {sentence}")
                unmatched_count += 1
                if unmatched_count > max_unmatched:
                    raise ValueError(f"未匹配句子数超过阈值 {max_unmatched},处理终止")
                max_shift = MATCH_LARGE_SHIFT
                asr_index = min(asr_index + 1, asr_len - 1)

        return new_segments

    def stop(self):
        """停止分割器并清理资源"""
        if not self.is_running:
            return
        self.is_running = False
        if hasattr(self, "executor") and self.executor is not None:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.error(f"关闭线程池时出错:{str(e)}")
            finally:
                self.executor = None
