"""Subtitle style configurations"""

from dataclasses import dataclass

from app.core.entities import SubtitleLayoutEnum


@dataclass
class RoundedBgStyle:
    """Rounded background subtitle style"""

    font_name: str = ""
    font_size: int = 52

    # 颜色配置（支持 hex 格式，如 #RRGGBB 或 #RRGGBBAA）
    bg_color: str = "#191919C8"  # 背景颜色
    text_color: str = "#FFFFFF"  # 文字颜色

    # 圆角和间距
    corner_radius: int = 12  # 圆角半径
    padding_h: int = 28  # 水平内边距
    padding_v: int = 14  # 垂直内边距
    margin_bottom: int = 60  # 底部外边距
    line_spacing: int = 10  # 行间距
    letter_spacing: int = 0  # 字符间距

    # 字幕布局
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ONLY_ORIGINAL
