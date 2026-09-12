from dataclasses import dataclass

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication


@dataclass(frozen=True)
class AppPalette:
    accent: str
    accent_fg: str
    # 用作"文字/小图标"的主题色：深色 = accent 原色；浅色加深到
    # 白底可读（亮薄荷绿在白底上对比率只有 ~1.5，不能直接当文字色）
    accent_text: str
    bg: str
    bg_alt: str
    panel: str
    panel_deep: str
    field: str
    control: str
    control_hover: str
    control_border: str
    control_border_strong: str
    header: str
    line: str
    line_soft: str
    accent_soft: str
    accent_border: str
    text: str
    muted: str
    subtle: str
    faint: str
    disabled: str
    warn: str
    warn_fg: str
    warn_soft: str
    danger: str
    danger_fg: str
    danger_soft: str
    selected: str
    # 内层卡/行的极淡叠色（在 panel 之上再抬一层），各页统一从这两个 token 取值。
    card_surface: str
    card_surface_hover: str


# 窗口/页面底色（深、浅主题）。main_window.setCustomBackgroundColor 与
# app_palette().bg 必须取同一对值，否则页面区域像浮在窗口上的色块。
BG_DARK = "#111514"
BG_LIGHT = "#f5f5f5"


def app_palette() -> AppPalette:
    """Design-language tokens, dark values aligned with docs/dev page mocks."""
    accent = theme_color_hex()
    dark = is_dark_theme()
    return AppPalette(
        accent=accent,
        accent_fg="#06110d",
        accent_text=accent if dark else _darken_for_light_text(accent),
        bg=BG_DARK if dark else BG_LIGHT,
        bg_alt="#0f1312" if dark else "#f7f8f8",
        panel="#202624" if dark else "#ffffff",
        panel_deep="#1a201f" if dark else "#f1f4f3",
        field="#242b29" if dark else "#f8faf9",
        control="#252c2a" if dark else "#f0f1f1",
        control_hover=rgba("#ffffff", 0.075) if dark else rgba("#000000", 0.06),
        control_border=rgba("#ffffff", 0.24) if dark else rgba("#000000", 0.10),
        control_border_strong=rgba("#ffffff", 0.26) if dark else rgba("#000000", 0.16),
        header="#171b1a" if dark else "#eef1f0",
        line="#3a4440" if dark else "#d8dddd",
        line_soft="#2c3531" if dark else "#e5e8e8",
        accent_soft=rgba(accent, 0.14),
        accent_border=rgba(accent, 0.72),
        text="#f4f7f5" if dark else "#1f2523",
        muted="#cbd4d0" if dark else "#64706b",
        subtle="#9ba7a2" if dark else "#68736e",
        faint="#71807a" if dark else "#8d9792",
        disabled="#2a312f" if dark else "#eef1f0",
        warn="#e8c96a",
        warn_fg="#f2d77b" if dark else "#8a6d1f",
        warn_soft=rgba("#e8c96a", 0.14),
        danger="#ff7f6d",
        danger_fg="#ffcfc8" if dark else "#7a211d",
        danger_soft=rgba("#ff7f6d", 0.15),
        selected=rgba(accent, 0.14 if dark else 0.13),
        card_surface=rgba("#ffffff", 0.025) if dark else rgba("#000000", 0.02),
        card_surface_hover=rgba("#ffffff", 0.04) if dark else rgba("#000000", 0.035),
    )


def _darken_for_light_text(accent: str) -> str:
    """把主题色加深到在白底上达到正文可读对比（WCAG ≥ 4.5）。"""
    color = QColor(accent)
    for factor in (170, 200, 230, 260):
        candidate = QColor(accent).darker(factor)
        if _contrast_on_white(candidate) >= 4.5:
            return candidate.name()
        color = candidate
    return color.name()


def _contrast_on_white(color: QColor) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )
    return 1.05 / (luminance + 0.05)


def theme_color_hex() -> str:
    from videocaptioner.ui.common.config import cfg

    color = cfg.themeColor.value
    if isinstance(color, QColor):
        return color.name(QColor.HexRgb)
    parsed = QColor(str(color))
    return parsed.name(QColor.HexRgb) if parsed.isValid() else "#28f08b"


def is_dark_theme() -> bool:
    from videocaptioner.ui.common.config import ThemeMode, cfg

    theme = cfg.themeMode.value
    if theme == ThemeMode.DARK:
        return True
    if theme == ThemeMode.LIGHT:
        return False

    app = QApplication.instance()
    if app is None:
        return True
    return app.palette().window().color().lightness() < 128


def rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#28f08b")
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"
