"""Subtitle rendering module (ASS and rounded background styles)"""

from typing import Optional

from app.config import SUBTITLE_STYLE_PATH

from .ass_renderer import render_ass_preview, render_ass_video
from .ass_utils import (
    AssInfo,
    AssStyle,
    auto_wrap_ass_file,
    parse_ass_info,
    wrap_ass_text,
)
from .font_utils import (
    FontType,
    clear_font_cache,
    get_ass_to_pil_ratio,
    get_builtin_fonts,
    get_font,
)
from .rounded_renderer import render_preview, render_rounded_video
from .styles import RoundedBgStyle
from .text_utils import hex_to_rgba, is_mainly_cjk, wrap_text


def get_subtitle_style(style_name: str) -> Optional[str]:
    """Get subtitle style content"""
    style_path = SUBTITLE_STYLE_PATH / f"{style_name}.txt"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return None


__all__ = [
    "render_ass_video",
    "render_ass_preview",
    "auto_wrap_ass_file",
    "parse_ass_info",
    "wrap_ass_text",
    "AssInfo",
    "AssStyle",
    "render_preview",
    "render_rounded_video",
    "RoundedBgStyle",
    "get_subtitle_style",
    "FontType",
    "get_font",
    "get_ass_to_pil_ratio",
    "get_builtin_fonts",
    "clear_font_cache",
    "hex_to_rgba",
    "is_mainly_cjk",
    "wrap_text",
]
