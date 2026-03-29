"""Subtitle rendering module (ASS and rounded background styles)"""

from typing import Optional

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
from .style_manager import (
    SecondaryStyle,
    StyleMode,
    SubtitleStyle,
    available_style_names,
    list_styles,
    load_style,
)
from .styles import RoundedBgStyle
from .text_utils import hex_to_rgba, is_mainly_cjk, wrap_text


def get_subtitle_style(style_name: str) -> Optional[str]:
    """Get subtitle style as ASS string.

    Uses the unified style_manager (JSON-first, .txt fallback).
    """
    style = load_style(style_name)
    if style is None:
        return None
    return style.to_ass_string()


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
    "SubtitleStyle",
    "SecondaryStyle",
    "StyleMode",
    "load_style",
    "list_styles",
    "available_style_names",
    "FontType",
    "get_font",
    "get_ass_to_pil_ratio",
    "get_builtin_fonts",
    "clear_font_cache",
    "hex_to_rgba",
    "is_mainly_cjk",
    "wrap_text",
]
