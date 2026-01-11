import json
import math
import os
import platform
import re
from pathlib import Path
from typing import List, Optional, Tuple

from langdetect import LangDetectException, detect

from ..entities import SubtitleLayoutEnum
from ..utils.text_utils import is_mainly_cjk

# 多语言分词模式(支持词级和字符级语言)
_WORD_SPLIT_PATTERN = (
    r"[a-zA-Z\u00c0-\u00ff\u0100-\u017f']+"  # 拉丁字符(含扩展)
    r"|[\u0400-\u04ff]+"  # 西里尔字母(俄文)
    r"|[\u0370-\u03ff]+"  # 希腊字母
    r"|[\u0600-\u06ff]+"  # 阿拉伯文
    r"|[\u0590-\u05ff]+"  # 希伯来文
    r"|\d+"  # 数字
    r"|[\u4e00-\u9fff]"  # 中文
    r"|[\u3040-\u309f]"  # 日文平假名
    r"|[\u30a0-\u30ff]"  # 日文片假名
    r"|[\uac00-\ud7af]"  # 韩文
    r"|[\u0e00-\u0e7f][\u0e30-\u0e3a\u0e47-\u0e4e]*"  # 泰文
    r"|[\u0900-\u097f]"  # 天城文(印地语)
    r"|[\u0980-\u09ff]"  # 孟加拉文
    r"|[\u0e80-\u0eff]"  # 老挝文
    r"|[\u1000-\u109f]"  # 缅甸文
)


def handle_long_path(path: str) -> str:
    r"""Handle Windows long path limitation by adding \\?\ prefix.

    Args:
        path: Original file path

    Returns:
        Path with \\?\ prefix if needed (Windows only)
    """
    if (
        platform.system() == "Windows"
        and len(path) > 260
        and not path.startswith(r"\\?\ ")
    ):
        return rf"\\?\{os.path.abspath(path)}"
    return path


class ASRDataSeg:
    def __init__(
        self, text: str, start_time: int, end_time: int, translated_text: str = ""
    ):
        self.text = text
        self.translated_text = translated_text
        self.start_time = start_time
        self.end_time = end_time

    def to_srt_ts(self) -> str:
        """Convert to SRT timestamp format"""
        return f"{self._ms_to_srt_time(self.start_time)} --> {self._ms_to_srt_time(self.end_time)}"

    def to_lrc_ts(self) -> str:
        """Convert to LRC timestamp format"""
        return f"[{self._ms_to_lrc_time(self.start_time)}]"

    def to_ass_ts(self) -> Tuple[str, str]:
        """Convert to ASS timestamp format"""
        return self._ms_to_ass_ts(self.start_time), self._ms_to_ass_ts(self.end_time)

    @staticmethod
    def _ms_to_lrc_time(ms: int) -> str:
        """Convert milliseconds to LRC time format (MM:SS.cc)"""
        seconds = ms / 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02}:{seconds:.2f}"

    @staticmethod
    def _ms_to_srt_time(ms: int) -> str:
        """Convert milliseconds to SRT time format (HH:MM:SS,mmm)"""
        total_seconds, milliseconds = divmod(ms, 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{int(milliseconds):03}"

    @staticmethod
    def _ms_to_ass_ts(ms: int) -> str:
        """Convert milliseconds to ASS timestamp format (H:MM:SS.cc)"""
        total_seconds, milliseconds = divmod(ms, 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        centiseconds = int(milliseconds / 10)
        return f"{int(hours):01}:{int(minutes):02}:{int(seconds):02}.{centiseconds:02}"

    @property
    def transcript(self) -> str:
        """Return segment text"""
        return self.text

    def __str__(self) -> str:
        return f"ASRDataSeg({self.text}, {self.start_time}, {self.end_time})"


class ASRData:
    def __init__(self, segments: List[ASRDataSeg]):
        filtered_segments = [seg for seg in segments if seg.text and seg.text.strip()]
        filtered_segments.sort(key=lambda x: x.start_time)
        self.segments = filtered_segments

    def __iter__(self):
        return iter(self.segments)

    def __len__(self) -> int:
        return len(self.segments)

    def has_data(self) -> bool:
        """Check if there are any utterances"""
        return len(self.segments) > 0

    def _is_word_level_segment(self, segment: ASRDataSeg) -> bool:
        """判断单个片段是否为词级

        Args:
            segment: 待判断的字幕片段

        Returns:
            True 如果片段符合词级模式
        """
        text = segment.text.strip()

        # CJK语言：1-2个字符
        if is_mainly_cjk(text):
            return len(text) <= 2

        # 非CJK语言（如英文）：单个单词
        words = text.split()
        return len(words) == 1

    def is_word_timestamp(self) -> bool:
        """检查时间戳是否为词级(非句子级)

        词级判定标准:
        - 英文: 单个单词
        - CJK/亚洲语言: 1-2个字符
        - 允许20%误差容忍

        Returns:
            True 如果80%+的片段符合词级模式
        """
        if not self.segments:
            return False

        # 统计符合词级模式的片段数量
        word_level_count = sum(
            1 for seg in self.segments if self._is_word_level_segment(seg)
        )

        WORD_LEVEL_THRESHOLD = 0.8
        word_level_ratio = word_level_count / len(self.segments)

        return word_level_ratio >= WORD_LEVEL_THRESHOLD

    def split_to_word_segments(self) -> "ASRData":
        """将句子级字幕分割为词级字幕,并按音素估算分配时间戳

        时间戳分配基于音素估算(每4个字符约1个音素)

        Returns:
            修改后的ASRData实例
        """
        CHARS_PER_PHONEME = 4
        new_segments = []

        for seg in self.segments:
            text = seg.text
            duration = seg.end_time - seg.start_time

            # 使用统一的多语言分词模式
            words_list = list(re.finditer(_WORD_SPLIT_PATTERN, text))

            if not words_list:
                continue

            # 计算总音素数
            total_phonemes = sum(
                math.ceil(len(w.group()) / CHARS_PER_PHONEME) for w in words_list
            )
            time_per_phoneme = duration / max(total_phonemes, 1)

            # 为每个词分配时间戳
            current_time = seg.start_time
            for word_match in words_list:
                word = word_match.group()
                word_phonemes = math.ceil(len(word) / CHARS_PER_PHONEME)
                word_duration = int(time_per_phoneme * word_phonemes)

                word_end_time = min(current_time + word_duration, seg.end_time)
                new_segments.append(
                    ASRDataSeg(
                        text=word, start_time=current_time, end_time=word_end_time
                    )
                )
                current_time = word_end_time

        self.segments = new_segments
        return self

    def remove_punctuation(self) -> "ASRData":
        """Remove trailing Chinese punctuation (comma, period) from segments."""
        punctuation = r"[，。]"
        for seg in self.segments:
            seg.text = re.sub(f"{punctuation}+$", "", seg.text.strip())
            seg.translated_text = re.sub(
                f"{punctuation}+$", "", seg.translated_text.strip()
            )
        return self

    def save(
        self,
        save_path: str,
        ass_style: Optional[str] = None,
        layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP,
    ) -> None:
        """Save ASRData to file in specified format.

        Args:
            save_path: Output file path
            ass_style: ASS style string (optional, uses default if None)
            layout: Subtitle layout mode
        """
        save_path = handle_long_path(save_path)
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        if save_path.endswith(".srt"):
            self.to_srt(save_path=save_path, layout=layout)
        elif save_path.endswith(".txt"):
            self.to_txt(save_path=save_path, layout=layout)
        elif save_path.endswith(".json"):
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False)
        elif save_path.endswith(".ass"):
            self.to_ass(save_path=save_path, style_str=ass_style, layout=layout)
        else:
            raise ValueError(f"Unsupported file extension: {save_path}")

    def to_txt(
        self,
        save_path=None,
        layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP,
    ) -> str:
        """Convert to plain text subtitle format (without timestamps)"""
        result = []
        for seg in self.segments:
            original = seg.text
            translated = seg.translated_text

            if layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP:
                text = f"{original}\n{translated}" if translated else original
            elif layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP:
                text = f"{translated}\n{original}" if translated else original
            elif layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
                text = original
            else:  # ONLY_TRANSLATE
                text = translated if translated else original
            result.append(text)
        text = "\n".join(result)
        if save_path:
            save_path = handle_long_path(save_path)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write("\n".join(result))
        return text

    def to_srt(
        self,
        layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP,
        save_path=None,
    ) -> str:
        """Convert to SRT subtitle format"""
        srt_lines = []
        for n, seg in enumerate(self.segments, 1):
            original = seg.text
            translated = seg.translated_text

            if layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP:
                text = f"{original}\n{translated}" if translated else original
            elif layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP:
                text = f"{translated}\n{original}" if translated else original
            elif layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
                text = original
            else:  # ONLY_TRANSLATE
                text = translated if translated else original

            srt_lines.append(f"{n}\n{seg.to_srt_ts()}\n{text}\n")

        srt_text = "\n".join(srt_lines)
        if save_path:
            save_path = handle_long_path(save_path)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(srt_text)
        return srt_text

    def to_lrc(self, save_path=None) -> str:
        """Convert to LRC subtitle format"""
        raise NotImplementedError("LRC format is not supported")

    def to_json(self) -> dict:
        """Convert to JSON format"""
        result_json = {}
        for i, segment in enumerate(self.segments, 1):
            result_json[str(i)] = {
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "original_subtitle": segment.text,
                "translated_subtitle": segment.translated_text,
            }
        return result_json

    def to_ass(
        self,
        style_str: Optional[str] = None,
        layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP,
        save_path: Optional[str] = None,
        video_width: int = 1280,
        video_height: int = 720,
    ) -> str:
        """Convert to ASS subtitle format

        Args:
            style_str: ASS style string (optional, uses default if None)
            layout: Subtitle layout mode
            save_path: Save path for ASS file (optional)
            video_width: Video width (default 1280)
            video_height: Video height (default 720)

        Returns:
            ASS format subtitle content
        """
        if not style_str:
            style_str = (
                "[V4+ Styles]\n"
                "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
                "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
                "Alignment,MarginL,MarginR,MarginV,Encoding\n"
                "Style: Default,MicrosoftYaHei-Bold,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,"
                "0,0,1,2,0,2,10,10,15,1\n"
                "Style: Secondary,MicrosoftYaHei-Bold,30,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,"
                "0,0,1,2,0,2,10,10,15,1"
            )

        ass_content = (
            "[Script Info]\n"
            "; Script generated by VideoCaptioner\n"
            "; https://github.com/weifeng2333\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {video_width}\n"
            f"PlayResY: {video_height}\n\n"
            f"{style_str}\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        dialogue_template = "Dialogue: 0,{},{},{},,0,0,0,,{}\n"
        for seg in self.segments:
            start_time, end_time = seg.to_ass_ts()
            original = seg.text
            translated = seg.translated_text
            has_translation = bool(translated and translated.strip())

            if layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP:
                if has_translation:
                    # 先写译文(Default)显示在上，后写原文(Secondary)显示在下
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Default", translated
                    )
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Secondary", original
                    )
                else:
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Default", original
                    )
            elif layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP:
                if has_translation:
                    # 先写原文(Default)显示在上，后写译文(Secondary)显示在下
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Default", original
                    )
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Secondary", translated
                    )
                else:
                    ass_content += dialogue_template.format(
                        start_time, end_time, "Default", original
                    )
            elif layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
                ass_content += dialogue_template.format(
                    start_time, end_time, "Default", original
                )
            else:  # ONLY_TRANSLATE
                text = translated if has_translation else original
                ass_content += dialogue_template.format(
                    start_time, end_time, "Default", text
                )

        if save_path:
            save_path = handle_long_path(save_path)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
        return ass_content

    def to_vtt(self, save_path=None) -> str:
        """Convert to WebVTT subtitle format

        Args:
            save_path: Optional save path

        Returns:
            WebVTT format subtitle content
        """
        raise NotImplementedError("WebVTT format is not supported")
        # # WebVTT头部
        # vtt_lines = ["WEBVTT\n"]

        # for n, seg in enumerate(self.segments, 1):
        #     # 转换时间戳格式从毫秒到 HH:MM:SS.mmm
        #     start_time = seg._ms_to_srt_time(seg.start_time).replace(",", ".")
        #     end_time = seg._ms_to_srt_time(seg.end_time).replace(",", ".")

        #     # 添加序号（可选）和时间戳
        #     vtt_lines.append(f"{n}\n{start_time} --> {end_time}\n{seg.transcript}\n")

        # vtt_text = "\n".join(vtt_lines)

        # if save_path:
        #     with open(save_path, "w", encoding="utf-8") as f:
        #         f.write(vtt_text)

        # return vtt_text

    def merge_segments(
        self, start_index: int, end_index: int, merged_text: Optional[str] = None
    ):
        """Merge segments from start_index to end_index (inclusive)."""
        if (
            start_index < 0
            or end_index >= len(self.segments)
            or start_index > end_index
        ):
            raise IndexError("Invalid segment index")
        merged_start_time = self.segments[start_index].start_time
        merged_end_time = self.segments[end_index].end_time
        if merged_text is None:
            merged_text = "".join(
                seg.text for seg in self.segments[start_index : end_index + 1]
            )
        merged_seg = ASRDataSeg(merged_text, merged_start_time, merged_end_time)
        self.segments[start_index : end_index + 1] = [merged_seg]

    def merge_with_next_segment(self, index: int) -> None:
        """Merge segment at index with next segment."""
        if index < 0 or index >= len(self.segments) - 1:
            raise IndexError("Index out of range or no next segment to merge")
        current_seg = self.segments[index]
        next_seg = self.segments[index + 1]
        merged_text = f"{current_seg.text} {next_seg.text}"
        merged_seg = ASRDataSeg(merged_text, current_seg.start_time, next_seg.end_time)
        self.segments[index] = merged_seg
        del self.segments[index + 1]

    def optimize_timing(self, threshold_ms: int = 1000) -> "ASRData":
        """Optimize subtitle display timing by adjusting adjacent segment boundaries.

        If gap between adjacent segments is below threshold, adjust the boundary
        to 3/4 point between them (reduces flicker).

        Args:
            threshold_ms: Time gap threshold in milliseconds (default 1000ms)

        Returns:
            Self for method chaining
        """
        if self.is_word_timestamp() or not self.segments:
            return self

        for i in range(len(self.segments) - 1):
            current_seg = self.segments[i]
            next_seg = self.segments[i + 1]
            time_gap = next_seg.start_time - current_seg.end_time

            if time_gap < threshold_ms:
                mid_time = (
                    current_seg.end_time + next_seg.start_time
                ) // 2 + time_gap // 4
                current_seg.end_time = mid_time
                next_seg.start_time = mid_time

        return self

    def __str__(self):
        return self.to_txt()

    @staticmethod
    def from_subtitle_file(file_path: str) -> "ASRData":
        """Load ASRData from subtitle file.

        Args:
            file_path: Subtitle file path (supports .srt, .vtt, .ass, .json)

        Returns:
            Parsed ASRData instance

        Raises:
            FileNotFoundError: File does not exist
            ValueError: Unsupported file format
        """
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path_obj}")

        try:
            content = file_path_obj.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path_obj.read_text(encoding="gbk")

        suffix = file_path_obj.suffix.lower()

        if suffix == ".srt":
            return ASRData.from_srt(content)
        elif suffix == ".vtt":
            if "<c>" in content:
                return ASRData.from_youtube_vtt(content)
            return ASRData.from_vtt(content)
        elif suffix == ".ass":
            return ASRData.from_ass(content)
        elif suffix == ".json":
            return ASRData.from_json(json.loads(content))
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    @staticmethod
    def from_json(json_data: dict) -> "ASRData":
        """Create ASRData from JSON data"""
        segments = []
        for i in sorted(json_data.keys(), key=int):
            segment_data = json_data[i]
            segment = ASRDataSeg(
                text=segment_data["original_subtitle"],
                translated_text=segment_data["translated_subtitle"],
                start_time=segment_data["start_time"],
                end_time=segment_data["end_time"],
            )
            segments.append(segment)
        return ASRData(segments)

    @staticmethod
    def from_srt(srt_str: str) -> "ASRData":
        """Create ASRData from SRT format string.

        Uses language detection to distinguish between bilingual subtitles
        (original + translation) and multiline single-language subtitles.

        Args:
            srt_str: SRT format subtitle string

        Returns:
            Parsed ASRData instance
        """
        segments = []
        srt_time_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})\s-->\s(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})"
        )
        blocks = re.split(r"\n\s*\n", srt_str.strip())

        # Detect bilingual mode: all 4-line + 70% different languages
        def is_different_lang(block: str) -> bool:
            lines = block.splitlines()
            if len(lines) != 4:
                return False
            try:
                return detect(lines[2]) != detect(lines[3])
            except LangDetectException:
                return False

        all_four_lines = all(len(b.splitlines()) == 4 for b in blocks)
        is_bilingual = (
            all_four_lines and sum(map(is_different_lang, blocks[:50])) / 50 >= 0.7
        )

        # Process all blocks based on detected mode
        for block in blocks:
            lines = block.splitlines()
            if len(lines) < 3:
                continue

            match = srt_time_pattern.match(lines[1])
            if not match:
                continue

            time_parts = list(map(int, match.groups()))
            start_time = sum(
                [
                    time_parts[0] * 3600000,
                    time_parts[1] * 60000,
                    time_parts[2] * 1000,
                    time_parts[3],
                ]
            )
            end_time = sum(
                [
                    time_parts[4] * 3600000,
                    time_parts[5] * 60000,
                    time_parts[6] * 1000,
                    time_parts[7],
                ]
            )

            if is_bilingual and len(lines) == 4:
                segments.append(ASRDataSeg(lines[2], start_time, end_time, lines[3]))
            else:
                segments.append(ASRDataSeg(" ".join(lines[2:]), start_time, end_time))

        return ASRData(segments)

    @staticmethod
    def from_vtt(vtt_str: str) -> "ASRData":
        """Create ASRData from VTT format string.

        Args:
            vtt_str: VTT format subtitle string

        Returns:
            ASRData instance
        """
        segments = []
        content = vtt_str.split("\n\n")[2:]

        timestamp_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
        )

        for block in content:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            timestamp_line = lines[1]
            match = timestamp_pattern.match(timestamp_line)
            if not match:
                continue

            time_parts = list(map(int, match.groups()))
            start_time = sum(
                [
                    time_parts[0] * 3600000,
                    time_parts[1] * 60000,
                    time_parts[2] * 1000,
                    time_parts[3],
                ]
            )
            end_time = sum(
                [
                    time_parts[4] * 3600000,
                    time_parts[5] * 60000,
                    time_parts[6] * 1000,
                    time_parts[7],
                ]
            )

            text_line = " ".join(lines[2:])
            cleaned_text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", text_line)
            cleaned_text = re.sub(r"</?c>", "", cleaned_text)
            cleaned_text = cleaned_text.strip()

            if cleaned_text and cleaned_text != " ":
                segments.append(ASRDataSeg(cleaned_text, start_time, end_time))

        return ASRData(segments)

    @staticmethod
    def from_youtube_vtt(vtt_str: str) -> "ASRData":
        """Create ASRData from YouTube VTT format with word-level timestamps.

        Args:
            vtt_str: YouTube VTT format subtitle string (contains <c> tags)

        Returns:
            Parsed ASRData with word-level segments
        """

        def parse_timestamp(ts: str) -> int:
            """Convert timestamp string to milliseconds"""
            h, m, s = ts.split(":")
            return int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)

        def split_timestamped_text(text: str) -> List[ASRDataSeg]:
            """Extract word segments from timestamped text"""
            pattern = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>([^<]*)")
            matches = list(pattern.finditer(text))
            word_segments = []

            for i in range(len(matches) - 1):
                current_match = matches[i]
                next_match = matches[i + 1]

                start_time = parse_timestamp(current_match.group(1))
                end_time = parse_timestamp(next_match.group(1))
                word = current_match.group(2).strip()

                if word:
                    word_segments.append(ASRDataSeg(word, start_time, end_time))

            return word_segments

        segments = []
        blocks = re.split(r"\n\n+", vtt_str.strip())

        timestamp_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{2}\.\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}\.\d{3})"
        )
        for block in blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue

            match = timestamp_pattern.match(lines[0])
            if not match:
                continue

            text = "\n".join(lines)

            timestamp_row = re.search(r"\n(.*?<c>.*?</c>.*)", block)
            if timestamp_row:
                text = re.sub(r"<c>|</c>", "", timestamp_row.group(1))
                block_start_time_string = (
                    f"{match.group(1)}:{match.group(2)}:{match.group(3)}"
                )
                block_end_time_string = (
                    f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
                )
                text = f"<{block_start_time_string}>{text}<{block_end_time_string}>"

                word_segments = split_timestamped_text(text)
                segments.extend(word_segments)

        return ASRData(segments)

    @staticmethod
    def from_ass(ass_str: str) -> "ASRData":
        """Create ASRData from ASS format string.

        Args:
            ass_str: ASS format subtitle string

        Returns:
            ASRData instance
        """
        segments = []
        ass_time_pattern = re.compile(
            r"Dialogue: \d+,(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2}),(.*?),.*?,\d+,\d+,\d+,.*?,(.*?)$"
        )

        def parse_ass_time(time_str: str) -> int:
            """Convert ASS timestamp to milliseconds"""
            hours, minutes, seconds = time_str.split(":")
            seconds, centiseconds = seconds.split(".")
            return (
                int(hours) * 3600000
                + int(minutes) * 60000
                + int(seconds) * 1000
                + int(centiseconds) * 10
            )

        # 检查是否有翻译：同时存在Default和Secondary样式
        has_default = "Dialogue:" in ass_str and ",Default," in ass_str
        has_secondary = ",Secondary," in ass_str
        has_translation = has_default and has_secondary
        temp_segments = {}

        for line in ass_str.splitlines():
            if line.startswith("Dialogue:"):
                match = ass_time_pattern.match(line)
                if match:
                    start_time = parse_ass_time(match.group(1))
                    end_time = parse_ass_time(match.group(2))
                    style = match.group(3).strip()
                    text = match.group(4)

                    text = re.sub(r"\{[^}]*\}", "", text)
                    text = text.replace("\\N", "\n")
                    text = text.strip()

                    if not text:
                        continue

                    if has_translation:
                        time_key = f"{start_time}-{end_time}"
                        if time_key in temp_segments:
                            if style == "Default":
                                temp_segments[time_key].translated_text = text
                            else:
                                temp_segments[time_key].text = text
                            segments.append(temp_segments[time_key])
                            del temp_segments[time_key]
                        else:
                            segment = ASRDataSeg(
                                text="", start_time=start_time, end_time=end_time
                            )
                            if style == "Default":
                                segment.translated_text = text
                            else:
                                segment.text = text
                            temp_segments[time_key] = segment
                    else:
                        segments.append(ASRDataSeg(text, start_time, end_time))

        for segment in temp_segments.values():
            segments.append(segment)

        return ASRData(segments)
