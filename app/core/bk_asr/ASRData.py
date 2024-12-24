import json
import re
from typing import List, Tuple
from pathlib import Path
import math

class ASRDataSeg:
    def __init__(self, text: str, start_time: int, end_time: int):
        self.text = text
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

    def _ms_to_lrc_time(self, ms: int) -> str:
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
        # 去除 segments.text 为空的
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
    
    def is_word_timestamp(self) -> bool:
        """
        判断是否是字级时间戳
        规则：
        1. 对于英文，每个segment应该只包含一个单词
        2. 对于中文，每个segment应该只包含一个汉字
        3. 允许20%的误差率
        """
        if not self.segments:
            return False
            
        valid_segments = 0
        total_segments = len(self.segments)
        
        for seg in self.segments:
            text = seg.text.strip()
            # 检查是否只包含一个英文单词或一个汉字
            if (len(text.split()) == 1 and text.isascii()) or len(text.strip()) <= 4:
                valid_segments += 1
        return (valid_segments / total_segments) >= 0.8

    def split_to_word_segments(self) -> 'ASRData':
        """
        将当前ASRData中的每个segment按字词分割，并按音素计算时间戳
        每4个字符视为一个音素单位进行时间分配
        
        Returns:
            ASRData: 包含分割后字词级别segments的新ASRData实例
        """
        CHARS_PER_PHONEME = 4  # 每个音素包含的字符数
        new_segments = []
        
        for seg in self.segments:
            text = seg.text
            duration = seg.end_time - seg.start_time
            
            # 匹配所有有效字符（包括数字）
            pattern = r'[a-zA-Z\']+|\d+|[\u4e00-\u9fff]|[\u3040-\u309f]|[\u30a0-\u30ff]|[\uac00-\ud7af]|[\u0e00-\u0e7f]|[\u0600-\u06ff]|[\u0400-\u04ff]|[\u0590-\u05ff]|[\u1e00-\u1eff]|[\u3130-\u318f]'
            words = re.finditer(pattern, text)
            words_list = list(words)
            
            if not words_list:
                continue
                
            # 计算总音素数
            total_phonemes = sum(math.ceil(len(w.group()) / CHARS_PER_PHONEME) for w in words_list)
            time_per_phoneme = duration / max(total_phonemes, 1)  # 防止除零
            
            current_time = seg.start_time
            for word_match in words_list:
                word = word_match.group()
                # 计算当前词的音素数
                word_phonemes = math.ceil(len(word) / CHARS_PER_PHONEME)
                word_duration = int(time_per_phoneme * word_phonemes)
                
                # 创建新的字词级segment
                word_end_time = min(current_time + word_duration, seg.end_time)
                new_segments.append(ASRDataSeg(
                    text=word,
                    start_time=current_time,
                    end_time=word_end_time
                ))
                
                current_time = word_end_time
        
        self.segments = new_segments


    def save(self, save_path: str, ass_style: str = None, layout: str = "原文在上") -> None:
        """Save the ASRData to a file"""
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        if save_path.endswith('.srt'):
            self.to_srt(save_path=save_path, layout=layout)
        elif save_path.endswith('.txt'):
            self.to_txt(save_path=save_path, layout=layout)
        elif save_path.endswith('.json'):
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(self.to_json(), f, ensure_ascii=False)
        elif save_path.endswith('.ass'):
            self.to_ass(save_path=save_path, style_str=ass_style, layout=layout)
        else:
            raise ValueError(f"Unsupported file extension: {save_path}")

    def to_txt(self, save_path=None, layout: str = "原文在上") -> str:
        """Convert to plain text subtitle format (without timestamps)"""
        result = []
        for seg in self.segments:
            # 检查是否有换行符
            if "\n" in seg.transcript:
                original, translated = seg.transcript.split("\n", 1)
            else:
                original, translated = seg.transcript, ""

            # 根据字幕类型组织文本
            if layout == "原文在上":
                text = f"{original}\n{translated}" if translated else original
            elif layout == "译文在上":
                text = f"{translated}\n{original}" if translated else original
            elif layout == "仅原文":
                text = original
            elif layout == "仅译文":
                text = translated if translated else original
            else:
                text = seg.transcript
            result.append(text)
        text = "\n".join(result)
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(result))
        return text

    def to_srt(self, layout: str = "原文在上", save_path=None) -> str:
        """Convert to SRT subtitle format"""
        srt_lines = []
        for n, seg in enumerate(self.segments, 1):
            # 检查是否有换行符
            if "\n" in seg.transcript:
                original, translated = seg.transcript.split("\n", 1)
            else:
                original, translated = seg.transcript, ""

            # 根据字幕类型组织文本
            if layout == "原文在上":
                text = f"{original}\n{translated}" if translated else original
            elif layout == "译文在上":
                text = f"{translated}\n{original}" if translated else original
            elif layout == "仅原文":
                text = original
            elif layout == "仅译文":
                text = translated if translated else original
            else:
                text = seg.transcript

            srt_lines.append(f"{n}\n{seg.to_srt_ts()}\n{text}\n")

        srt_text = "\n".join(srt_lines)
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(srt_text)
        return srt_text

    def to_lrc(self, save_path=None) -> str:
        """Convert to LRC subtitle format"""
        lrc_text = "\n".join(
            f"{seg.to_lrc_ts()}{seg.transcript}" for seg in self.segments
        )
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(lrc_text)
        return lrc_text

    def to_json(self) -> dict:
        result_json = {}
        for i, segment in enumerate(self.segments, 1):
            # 检查是否有换行符
            if "\n" in segment.text:
                original_subtitle, translated_subtitle = segment.text.split("\n", 1)
            else:
                original_subtitle, translated_subtitle = segment.text, ""

            result_json[str(i)] = {
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "original_subtitle": original_subtitle,
                "translated_subtitle": translated_subtitle
            }
        return result_json

    def to_ass(self, style_str: str = None, layout: str = "原文在上", save_path: str = None) -> str:
        """转换为ASS字幕格式
        
        Args:
            style_str: ASS样式字符串,为空则使用默认样式
            layout: 字幕布局,可选值["译文在上", "原文在上", "仅原文", "仅译文"]
            
        Returns:
            ASS格式字幕内容
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
            "PlayResX: 1280\n"
            "PlayResY: 720\n\n"
            f"{style_str}\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        dialogue_template = 'Dialogue: 0,{},{},{},,0,0,0,,{}\n'
        for seg in self.segments:
            start_time, end_time = seg.to_ass_ts()
            if "\n" in seg.text:
                original, translate = seg.text.split("\n", 1)
                if layout == "译文在上" and translate:
                    ass_content += dialogue_template.format(start_time, end_time, "Secondary", original)
                    ass_content += dialogue_template.format(start_time, end_time, "Default", translate)
                elif layout == "原文在上" and translate:
                    ass_content += dialogue_template.format(start_time, end_time, "Secondary", translate)
                    ass_content += dialogue_template.format(start_time, end_time, "Default", original)
                elif layout == "仅原文":
                    ass_content += dialogue_template.format(start_time, end_time, "Default", original)
                elif layout == "仅译文" and translate:
                    ass_content += dialogue_template.format(start_time, end_time, "Default", translate)
            else:
                ass_content += dialogue_template.format(start_time, end_time, "Default", seg.text)
            
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(ass_content)
        return ass_content

    def merge_segments(self, start_index: int, end_index: int, merged_text: str = None):
            """合并从 start_index 到 end_index 的段（包含）。"""
            if start_index < 0 or end_index >= len(self.segments) or start_index > end_index:
                raise IndexError("无效的段索引。")
            merged_start_time = self.segments[start_index].start_time
            merged_end_time = self.segments[end_index].end_time
            if merged_text is None:
                merged_text = ''.join(seg.text for seg in self.segments[start_index:end_index+1])
            merged_seg = ASRDataSeg(merged_text, merged_start_time, merged_end_time)
            # 替换 segments[start_index:end_index+1] 为 merged_seg
            self.segments[start_index:end_index+1] = [merged_seg]

    def merge_with_next_segment(self, index: int) -> None:
        """合并指定索引的段与下一个段。"""
        if index < 0 or index >= len(self.segments) - 1:
            raise IndexError("索引超出范围或没有下一个段可合并。")
        current_seg = self.segments[index]
        next_seg = self.segments[index + 1]
        merged_text = f"{current_seg.text} {next_seg.text}"
        merged_seg = ASRDataSeg(merged_text, current_seg.start_time, next_seg.end_time)
        self.segments[index] = merged_seg
        # 删除下一个段
        del self.segments[index + 1]

    def __str__(self):
        return self.to_txt()
    

def from_subtitle_file(file_path: str) -> 'ASRData':
    """从文件路径加载ASRData实例
    
    Args:
        file_path: 字幕文件路径，支持.srt、.vtt、.ass、.json格式
        
    Returns:
        ASRData: 解析后的ASRData实例
        
    Raises:
        ValueError: 不支持的文件格式或文件读取错误
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
        
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = file_path.read_text(encoding='gbk')
        
    suffix = file_path.suffix.lower()
    
    if suffix == '.srt':
        return from_srt(content)
    elif suffix == '.vtt':
        if '<c>' in content:  # YouTube VTT格式包含字级时间戳
            return from_youtube_vtt(content)
        return from_vtt(content)
    elif suffix == '.ass':
        return from_ass(content)
    elif suffix == '.json':
        return from_json(json.loads(content))
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")

def from_json(json_data: dict) -> 'ASRData':
    """从JSON数据创建ASRData实例"""
    segments = []
    for i in sorted(json_data.keys(), key=int):
        segment_data = json_data[i]
        text = segment_data['original_subtitle']
        if segment_data['translated_subtitle']:
            text += '\n' + segment_data['translated_subtitle']
        segment = ASRDataSeg(
            text=text,
            start_time=segment_data['start_time'],
            end_time=segment_data['end_time']
        )
        segments.append(segment)
    return ASRData(segments)

def from_srt(srt_str: str) -> 'ASRData':
    """
    从SRT格式的字符串创建ASRData实例。

    :param srt_str: 包含SRT格式字幕的字符串。
    :return: 解析后的ASRData实例。
    """
    segments = []
    srt_time_pattern = re.compile(
        r'(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})\s-->\s(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})'
    )
    blocks = re.split(r'\n\s*\n', srt_str.strip())

    # 如果超过90%的块都超过4行，说明可能包含翻译文本
    blocks_lines_count = [len(block.splitlines()) for block in blocks]
    if all(count <= 4 for count in blocks_lines_count) and sum(count == 4 for count in blocks_lines_count) / len(blocks_lines_count) > 0.9:
        has_translated_subtitle = True
    else:
        has_translated_subtitle = False

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue

        match = srt_time_pattern.match(lines[1])
        if not match:
            continue

        time_parts = list(map(int, match.groups()))
        start_time = sum([
            time_parts[0] * 3600000,
            time_parts[1] * 60000,
            time_parts[2] * 1000,
            time_parts[3]
        ])
        end_time = sum([
            time_parts[4] * 3600000,
            time_parts[5] * 60000,
            time_parts[6] * 1000,
            time_parts[7]
        ])

        if has_translated_subtitle:
            text = '\n'.join(lines[2:]).strip()
        else:
            text = ' '.join(lines[2:])

        segments.append(ASRDataSeg(text, start_time, end_time))

    return ASRData(segments)

def from_vtt(vtt_str: str) -> 'ASRData':
    """
    从YouTube VTT格式的字符串创建ASRData实例。
    
    :param vtt_str: YouTube VTT格式的字幕字符串
    :return: ASRData实例
    """
    segments = []
    # 跳过头部元数据
    content = vtt_str.split('\n\n')[2:]
    
    for block in content:
        lines = block.strip().split('\n')
        if not lines:
            continue
            
        # 解析时间戳行
        timestamp_line = lines[0]
        if '-->' not in timestamp_line:
            continue
            
        # 提取开始和结束时间
        times = timestamp_line.split(' --> ')[0]
        hours, minutes, seconds = times.split(':')
        seconds, milliseconds = seconds.split('.')
        start_time = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(milliseconds)
        
        times = timestamp_line.split(' --> ')[1].split()[0]
        hours, minutes, seconds = times.split(':')
        seconds, milliseconds = seconds.split('.')
        end_time = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(milliseconds)
        
        if len(lines) > 1:
            text_line = lines[1]
            cleaned_text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text_line)
            cleaned_text = re.sub(r'</?c>', '', cleaned_text)
            cleaned_text = cleaned_text.strip()
            
            if cleaned_text and cleaned_text != " ":
                segments.append(ASRDataSeg(cleaned_text, start_time, end_time))
    
    return ASRData(segments)

def from_youtube_vtt(vtt_str: str) -> 'ASRData':
    """
    从YouTube VTT格式的字符串创建ASRData实例，提取字级时间戳。
    
    :param vtt_str: 包含VTT格式字幕的字符串
    :return: 解析后的ASRData实例
    """
    def parse_timestamp(ts: str) -> int:
        """将时间戳字符串转换为毫秒"""
        h, m, s = ts.split(':')
        return int(float(h) * 3600000 + float(m) * 60000 + float(s) * 1000)
    
    def split_timestamped_text(text: str) -> List[ASRDataSeg]:
        """分离带时间戳的文本为单词段"""
        pattern = re.compile(r'<(\d{2}:\d{2}:\d{2}\.\d{3})>([^<]*)')
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
    blocks = re.split(r'\n\n+', vtt_str.strip())
    
    timestamp_pattern = re.compile(
        r'(\d{2}):(\d{2}):(\d{2}\.\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}\.\d{3})'
    )    
    for block in blocks:
        lines = block.strip().split('\n')
        if not lines:
            continue
            
        match = timestamp_pattern.match(lines[0])
        if not match:
            continue
            
        block_start_time = (
            int(match.group(1)) * 3600000 +
            int(match.group(2)) * 60000 +
            float(match.group(3)) * 1000
        )
        block_end_time = (
            int(match.group(4)) * 3600000 +
            int(match.group(5)) * 60000 +
            float(match.group(6)) * 1000
        )
        
        # 获取文本内容
        text = '\n'.join(lines)
        
        timestamp_row = re.search(r'\n(.*?<c>.*?</c>.*)', block)
        if timestamp_row:
            text = re.sub(r'<c>|</c>', '', timestamp_row.group(1))
            block_start_time_string = f"{match.group(1)}:{match.group(2)}:{match.group(3)}"
            block_end_time_string = f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
            text = f"<{block_start_time_string}>{text}<{block_end_time_string}>"
            
            # 分离每个带时间戳的单词
            word_segments = split_timestamped_text(text)
            segments.extend(word_segments)
    
    return ASRData(segments)

def from_ass(ass_str: str) -> 'ASRData':
    """
    从ASS格式的字符串创建ASRData实例。
    
    :param ass_str: 包含ASS格式字幕的字符串
    :return: ASRData实例
    """
    segments = []
    ass_time_pattern = re.compile(r'Dialogue: \d+,(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2}),(.*?),.*?,\d+,\d+,\d+,.*?,(.*?)$')
    
    def parse_ass_time(time_str: str) -> int:
        """将ASS时间戳转换为毫秒"""
        hours, minutes, seconds = time_str.split(':')
        seconds, centiseconds = seconds.split('.')
        return (int(hours) * 3600000 + 
                int(minutes) * 60000 + 
                int(seconds) * 1000 + 
                int(centiseconds) * 10)
    
    # 检查是否是VideoCaptioner生成的字幕
    has_translation = "Script generated by VideoCaptioner" in ass_str
    
    # 用于临时存储相同时间戳的字幕
    temp_segments = {}
    
    # 按行处理ASS文件
    for line in ass_str.splitlines():
        if line.startswith('Dialogue:'):
            match = ass_time_pattern.match(line)
            if match:
                start_time = parse_ass_time(match.group(1))
                end_time = parse_ass_time(match.group(2))
                style = match.group(3).strip()
                text = match.group(4)
                
                text = re.sub(r'\{[^}]*\}', '', text)
                text = text.replace('\\N', '\n')
                text = text.strip()
                
                if not text:
                    continue
                    
                if has_translation:
                    # 使用时间戳作为键
                    time_key = f"{start_time}-{end_time}"
                    if time_key in temp_segments:
                        # 如果已存在相同时间戳的字幕，合并原文和译文
                        if style == "Default":
                            temp_segments[time_key] = f"{text}\n{temp_segments[time_key]}"
                        else:
                            temp_segments[time_key] = f"{temp_segments[time_key]}\n{text}"
                        # 创建新的字幕段并清除临时存储
                        segments.append(ASRDataSeg(temp_segments[time_key], start_time, end_time))
                        del temp_segments[time_key]
                    else:
                        temp_segments[time_key] = text
                else:
                    segments.append(ASRDataSeg(text, start_time, end_time))
    
    # 处理剩余的未配对字幕
    for time_key, text in temp_segments.items():
        start_time, end_time = map(int, time_key.split('-'))
        segments.append(ASRDataSeg(text, start_time, end_time))

    return ASRData(segments)


if __name__ == '__main__':
    from pathlib import Path

    # 示例：从SRT文件创建ASRData并转换为ASS格式
    srt_file_path = "示例路径/字幕文件.srt"
    asr_data = from_srt(Path(srt_file_path).read_text(encoding="utf-8"))
    print(asr_data.to_ass(style_str="示例样式字符串", save_path=srt_file_path.replace(".srt", ".ass")))