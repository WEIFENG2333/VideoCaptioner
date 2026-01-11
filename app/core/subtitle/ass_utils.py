"""ASS subtitle utilities with accurate text width calculation"""

import re
from dataclasses import dataclass
from typing import Optional

from .font_utils import get_ass_to_pil_ratio, get_font
from .text_utils import is_mainly_cjk, wrap_text


@dataclass
class AssStyle:
    """ASS style information"""

    name: str  # Style name
    font_name: str  # Font family
    font_size: int  # Font size
    primary_color: str = "&H00FFFFFF"  # Primary text color
    secondary_color: str = "&H000000FF"  # Secondary text color
    outline_color: str = "&H00000000"  # Outline color
    back_color: str = "&H00000000"  # Shadow color
    bold: int = 0  # Bold (-1 or 0)
    italic: int = 0  # Italic (-1 or 0)
    border_style: int = 1  # Border style (1 or 3)
    outline: float = 2.0  # Outline width
    shadow: float = 0.0  # Shadow depth
    alignment: int = 2  # Subtitle alignment (1-9)
    margin_l: int = 10  # Left margin
    margin_r: int = 10  # Right margin
    margin_v: int = 10  # Vertical margin
    spacing: float = 0.0  # Character spacing


@dataclass
class AssInfo:
    """ASS file information"""

    video_width: int  # PlayResX
    video_height: int  # PlayResY
    styles: dict[str, AssStyle]  # {style_name: AssStyle}

    def get_style(self, style_name: str) -> AssStyle:
        """Get style by name, fallback to Default"""
        default_style = AssStyle(
            name="Default",
            font_name="Arial",
            font_size=40,
        )
        return self.styles.get(style_name, self.styles.get("Default", default_style))


def parse_ass_info(ass_content: str) -> AssInfo:
    """
    Parse ASS file information including video resolution and styles

    Returns:
        AssInfo with video dimensions and all style definitions
    """
    video_width = 1280
    video_height = 720
    styles = {}

    # 提取视频分辨率
    res_x_match = re.search(r"PlayResX:\s*(\d+)", ass_content)
    if res_x_match:
        video_width = int(res_x_match.group(1))

    res_y_match = re.search(r"PlayResY:\s*(\d+)", ass_content)
    if res_y_match:
        video_height = int(res_y_match.group(1))

    # 提取样式区块 [V4+ Styles]
    style_section = re.search(r"\[V4\+ Styles\].*?\[", ass_content, re.DOTALL)
    if style_section:
        style_content = style_section.group(0)

        # 解析 Format 行，建立字段名到索引的映射
        format_match = re.search(r"Format:(.*?)$", style_content, re.MULTILINE)

        if format_match:
            fields = [f.strip() for f in format_match.group(1).split(",")]
            field_map = {field: idx for idx, field in enumerate(fields)}

            # 逐行解析 Style 定义
            for style_line in re.finditer(r"Style:(.*?)$", style_content, re.MULTILINE):
                parts = [p.strip() for p in style_line.group(1).split(",")]

                try:
                    style = AssStyle(
                        name=parts[field_map["Name"]],
                        font_name=parts[field_map["Fontname"]],
                        font_size=int(parts[field_map["Fontsize"]]),
                        primary_color=(
                            parts[field_map.get("PrimaryColour", -1)]
                            if "PrimaryColour" in field_map
                            else "&H00FFFFFF"
                        ),
                        secondary_color=(
                            parts[field_map.get("SecondaryColour", -1)]
                            if "SecondaryColour" in field_map
                            else "&H000000FF"
                        ),
                        outline_color=(
                            parts[field_map.get("OutlineColour", -1)]
                            if "OutlineColour" in field_map
                            else "&H00000000"
                        ),
                        back_color=(
                            parts[field_map.get("BackColour", -1)]
                            if "BackColour" in field_map
                            else "&H00000000"
                        ),
                        bold=(
                            int(parts[field_map.get("Bold", -1)])
                            if "Bold" in field_map
                            else 0
                        ),
                        italic=(
                            int(parts[field_map.get("Italic", -1)])
                            if "Italic" in field_map
                            else 0
                        ),
                        border_style=(
                            int(parts[field_map.get("BorderStyle", -1)])
                            if "BorderStyle" in field_map
                            else 1
                        ),
                        outline=(
                            float(parts[field_map.get("Outline", -1)])
                            if "Outline" in field_map
                            else 2.0
                        ),
                        shadow=(
                            float(parts[field_map.get("Shadow", -1)])
                            if "Shadow" in field_map
                            else 0.0
                        ),
                        alignment=(
                            int(parts[field_map.get("Alignment", -1)])
                            if "Alignment" in field_map
                            else 2
                        ),
                        margin_l=(
                            int(parts[field_map.get("MarginL", -1)])
                            if "MarginL" in field_map
                            else 10
                        ),
                        margin_r=(
                            int(parts[field_map.get("MarginR", -1)])
                            if "MarginR" in field_map
                            else 10
                        ),
                        margin_v=(
                            int(parts[field_map.get("MarginV", -1)])
                            if "MarginV" in field_map
                            else 10
                        ),
                        spacing=(
                            float(parts[field_map.get("Spacing", -1)])
                            if "Spacing" in field_map
                            else 0.0
                        ),
                    )
                    styles[style.name] = style
                except (ValueError, IndexError, KeyError):
                    pass

    # 确保至少有一个 Default 样式
    if "Default" not in styles:
        styles["Default"] = AssStyle(
            name="Default",
            font_name="Arial",
            font_size=40,
        )

    return AssInfo(video_width, video_height, styles)


def wrap_ass_text(
    text: str, max_width: int, font_name: str, font_size: int, spacing: float = 0.0
) -> str:
    """
    Wrap text using actual font rendering (accurate width calculation)

    Note: ASS font size is based on Windows line height, while PIL uses em square.
    We need to convert ASS font size to PIL font size for accurate measurement.

    For most fonts: PIL_size = ASS_size / ratio, where ratio ≈ 1.4-1.5

    Args:
        text: Text to wrap
        max_width: Maximum width in pixels
        font_name: Font name for rendering
        font_size: Font size (ASS font size, will be converted to PIL size)
        spacing: Character spacing in ASS (affects text width)

    Returns:
        Wrapped text with \\N line breaks
    """
    # 已有换行符或空文本，直接返回
    if not text or "\\N" in text:
        return text

    # 只处理 CJK 文本（英文由 FFmpeg ASS 引擎自动换行）
    if not is_mainly_cjk(text):
        return text

    # Convert ASS font size to PIL font size
    # ASS uses Windows line height, PIL uses em square
    ratio = get_ass_to_pil_ratio(font_name)
    pil_font_size = int(round(font_size / ratio))

    # Load font with converted size and call wrap function
    # Pass spacing directly to wrap_text for accurate width calculation
    font = get_font(pil_font_size, font_name)
    lines = wrap_text(text, font, max_width, spacing=spacing)

    # 用 \N 连接各行（ASS 格式的换行符）
    return "\\N".join(lines)


def auto_wrap_ass_file(
    input_file: str,
    output_file: Optional[str] = None,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
) -> str:
    """
    Auto-wrap text in ASS file using accurate font rendering

    Args:
        input_file: Input ASS file path
        output_file: Output file path (overwrites input if None)
        video_width: Video width (overrides ASS settings if provided)
        video_height: Video height (not used, kept for compatibility)

    Returns:
        Output file path
    """
    if output_file is None:
        output_file = input_file

    with open(input_file, "r", encoding="utf-8") as f:
        ass_content = f.read()

    # 解析 ASS 文件信息
    ass_info = parse_ass_info(ass_content)

    if video_width is None:
        video_width = ass_info.video_width

    # 使用95%宽度作为最大文本宽度
    max_text_width = int(video_width * 0.95)

    def process_dialogue_line(match):
        """处理每一行对话"""
        full_line = match.group(0)

        # 提取样式名称（Dialogue 行的第4个字段）
        style_pattern = r"Dialogue:[^,]*,[^,]*,[^,]*,([^,]*),"
        style_match = re.search(style_pattern, full_line)
        style_name = style_match.group(1).strip() if style_match else "Default"

        # 获取该样式对应的字体信息
        style = ass_info.get_style(style_name)
        text_part = match.group(1)

        # 使用实际字体渲染进行换行（考虑字符间距）
        wrapped_text = wrap_ass_text(
            text_part, max_text_width, style.font_name, style.font_size, style.spacing
        )

        return full_line.replace(text_part, wrapped_text)

    # 匹配所有对话行的文本部分（第10个字段）
    # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
    pattern = r"Dialogue:[^,]*(?:,[^,]*){8},(.*?)$"
    processed_content = re.sub(
        pattern, process_dialogue_line, ass_content, flags=re.MULTILINE
    )

    # 写入处理后的文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(processed_content)

    return output_file
