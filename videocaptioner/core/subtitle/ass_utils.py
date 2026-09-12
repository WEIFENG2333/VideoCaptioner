"""ASS 字幕的解析与自动断行。

libass 只按空格换行，对无空格的 CJK 长句无能为力，超宽文本会直接
渲染出画面。预览图与视频合成在送入 FFmpeg 前都先经 auto_wrap_ass_file
把每行对话按可用宽度写好 \\N 硬换行；断行算法见 text_utils.wrap_text。
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .font_utils import get_ass_to_pil_ratio, get_font
from .text_utils import wrap_text

# 像素测量与 libass 实渲存在 ±1% 级差异（kerning/hinting），可用宽度收一档兜底
_SAFETY = 0.98


@dataclass
class AssStyle:
    """一条 Style 定义中与断行相关的字段子集。"""

    name: str
    font_name: str = "Arial"
    font_size: int = 40
    margin_l: int = 10
    margin_r: int = 10
    spacing: float = 0.0


@dataclass
class AssInfo:
    """一个 ASS 文件的画布尺寸与样式表。"""

    video_width: int
    video_height: int
    styles: dict[str, AssStyle]

    def get_style(self, style_name: str) -> AssStyle:
        fallback = self.styles.get("Default", AssStyle(name="Default"))
        return self.styles.get(style_name, fallback)


def parse_ass_info(ass_content: str) -> AssInfo:
    """解析 PlayResX/PlayResY 与 [V4+ Styles] 区块（按 Format 行确定字段顺序）。"""

    def search_int(pattern: str, default: int) -> int:
        match = re.search(pattern, ass_content)
        return int(match.group(1)) if match else default

    video_width = search_int(r"PlayResX:\s*(\d+)", 1280)
    video_height = search_int(r"PlayResY:\s*(\d+)", 720)

    styles: dict[str, AssStyle] = {}
    section = re.search(r"\[V4\+ Styles\](.*?)(?=^\[|\Z)", ass_content, re.DOTALL | re.MULTILINE)
    format_line = section and re.search(r"Format:(.*)$", section.group(1), re.MULTILINE)
    if section and format_line:
        index = {name.strip(): i for i, name in enumerate(format_line.group(1).split(","))}
        for style_line in re.finditer(r"Style:(.*)$", section.group(1), re.MULTILINE):
            parts = [p.strip() for p in style_line.group(1).split(",")]

            def field(name: str, cast: Callable, default):
                i = index.get(name)
                if i is None or i >= len(parts):
                    return default
                try:
                    return cast(parts[i])
                except ValueError:
                    return default

            name = field("Name", str, "")
            if not name:
                continue
            styles[name] = AssStyle(
                name=name,
                font_name=field("Fontname", str, "Arial"),
                font_size=field("Fontsize", lambda v: int(float(v)), 40),
                margin_l=field("MarginL", lambda v: int(float(v)), 10),
                margin_r=field("MarginR", lambda v: int(float(v)), 10),
                spacing=field("Spacing", float, 0.0),
            )

    return AssInfo(video_width, video_height, styles)


def wrap_ass_text(
    text: str, max_width: float, font_name: str, font_size: int, spacing: float = 0.0
) -> str:
    """按实际字体渲染宽度断行，返回以 \\N 连接的文本。

    font_size 是 ASS 字号（Windows 行高语义），测量前先换算成 PIL 字号。
    已含 \\N 的视为手工断行；含 override 标签的无法测量（标签会计入宽度），
    两者都原样返回。
    """
    if not text or "\\N" in text or "{" in text:
        return text

    ratio = get_ass_to_pil_ratio(font_name)
    font = get_font(int(round(font_size / ratio)), font_name)
    lines = wrap_text(text, font, max_width * _SAFETY, spacing=spacing)
    return "\\N".join(lines)


# Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
_DIALOGUE_RE = re.compile(
    r"Dialogue:\s*[^,]*,[^,]*,[^,]*,(?P<style>[^,]*),[^,]*,"
    r"(?P<ml>[^,]*),(?P<mr>[^,]*),[^,]*,[^,]*,(?P<text>.*?)$",
    re.MULTILINE,
)


def auto_wrap_ass_file(
    input_file: str,
    output_file: Optional[str] = None,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
) -> str:
    """对 ASS 文件的每行对话自动断行，返回输出路径（缺省原地覆写）。

    可用宽度 = PlayResX − MarginL − MarginR；边距优先取 Dialogue 行的
    覆写值（0 表示沿用样式定义）。
    """
    if output_file is None:
        output_file = input_file

    with open(input_file, "r", encoding="utf-8") as f:
        ass_content = f.read()

    ass_info = parse_ass_info(ass_content)
    play_res_x = video_width or ass_info.video_width

    def margin(override: str, fallback: int) -> int:
        try:
            value = int(float(override))
        except ValueError:
            value = 0
        return value if value > 0 else fallback

    def process_dialogue_line(match: re.Match) -> str:
        full_line = match.group(0)
        style = ass_info.get_style(match.group("style").strip())
        margin_l = margin(match.group("ml"), style.margin_l)
        margin_r = margin(match.group("mr"), style.margin_r)
        available = play_res_x - margin_l - margin_r
        if available <= 0:
            return full_line

        text_part = match.group("text")
        wrapped = wrap_ass_text(
            text_part, available, style.font_name, style.font_size, style.spacing
        )
        if wrapped == text_part:
            return full_line
        return full_line[: match.start("text") - match.start()] + wrapped

    processed_content = _DIALOGUE_RE.sub(process_dialogue_line, ass_content)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(processed_content)

    return output_file
