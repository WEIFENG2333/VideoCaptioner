from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication
from qfluentwidgets.common.icon import FluentIconBase

from videocaptioner.config import ASSETS_PATH

CUSTOM_ICON_DIR = ASSETS_PATH / "icons"


class AppIcon(str, Enum):
    """App-owned SVG icons in resource/assets/icons.

    ``str, Enum`` 而非 ``enum.StrEnum``：后者仅 Python 3.11+，而本项目
    ``requires-python = ">=3.10"``，3.10 下 ``import StrEnum`` 会直接 ImportError，
    连带所有用到 AppIcon 的 UI 模块全部加载失败。``__str__`` 返回值以保持与
    StrEnum 一致（``str(AppIcon.X)`` 取图标名，供路径/缓存键使用）。
    """

    ADD = "add"
    ALIGNMENT = "alignment"
    ARROW_LEFT = "arrow-left"
    BRUSH = "brush"
    CANCEL = "cancel"
    CHEVRON_DOWN = "chevron-down"
    CLOSE = "close"
    COPY = "copy"
    DELETE = "delete"
    DIAGNOSTIC = "diagnostic"
    DOCUMENT = "document"
    DOWNLOAD = "download"
    EDIT = "edit"
    FILE = "file"
    FOLDER = "folder"
    FOLDER_ADD = "folder_add"
    FONT = "font"
    FONT_SIZE = "font_size"
    GITHUB = "github"
    GLOBE = "globe"
    HARDSUB = "hardsub"
    HEART = "heart"
    HISTORY = "history"
    HOME = "home"
    LANGUAGE = "language"
    LAYOUT = "layout"
    LINK = "link"
    MENU = "menu"
    MESSAGE = "message"
    MICROPHONE = "microphone"
    MUSIC = "music"
    PALETTE = "palette"
    PANEL_LEFT = "panel-left"
    PHOTO = "photo"
    PLAY = "play"
    RIGHT_ARROW = "right_arrow"
    ROBOT = "robot"
    SAVE = "save"
    SEARCH = "search"
    SETTING = "setting"
    SUBTITLE = "subtitle"
    SYNC = "sync"
    TERMINAL = "terminal"
    VIDEO = "video"
    VIEW = "view"
    VOLUME = "volume"
    ZOOM = "zoom"

    def __str__(self) -> str:
        return self.value


class AppFluentIcon(FluentIconBase):
    """把 app 自有 SVG 包成 FluentIconBase，使其能像 FluentIcon 一样随主题/选中态着色，

    可直接传给 qfluent 导航栏（addSubInterface）等需要 FluentIconBase 的接口。"""

    def __init__(self, name: AppIcon | str):
        self._name = str(name)

    def path(self, theme=None) -> str:  # type: ignore[override]
        return str(custom_icon_path(self._name))

    def render(self, painter, rect, theme=None, indexes=None, **attributes):  # type: ignore[override]
        from qfluentwidgets.common.icon import Theme, getIconColor
        if theme is None:
            theme = Theme.AUTO
        # 我们的 SVG 用 currentColor，需主动按主题填色（亮/暗对应黑/白），否则渲染成黑色不可见。
        attributes.setdefault("fill", getIconColor(theme))
        super().render(painter, rect, theme, indexes, **attributes)

    def icon(self, theme=None, color=None):  # type: ignore[override]
        from qfluentwidgets.common.icon import SvgIconEngine, Theme, getIconColor, writeSvg
        if theme is None:
            theme = Theme.AUTO
        fill = QColor(color).name() if color is not None else getIconColor(theme)
        return QIcon(SvgIconEngine(writeSvg(self.path(theme), fill=fill)))


def custom_icon_path(name: str | Path) -> Path:
    """Return the canonical path for an app-owned SVG icon."""
    path = Path(str(name))
    if not path.is_absolute():
        path = CUSTOM_ICON_DIR / path
    if not path.suffix:
        path = path.with_suffix(".svg")
    return path


def _color_name(color: str | QColor) -> str:
    qcolor = color if isinstance(color, QColor) else QColor(str(color))
    return qcolor.name() if qcolor.isValid() else str(color)


def _device_pixel_ratio() -> float:
    """Highest screen DPR; SVG icons must rasterize at physical resolution
    or they come out blurry on Retina displays."""
    app = QApplication.instance()
    if app is None:
        return 1.0
    ratios = [screen.devicePixelRatio() for screen in app.screens()]
    return max(ratios, default=1.0)


@lru_cache(maxsize=256)
def _render_svg_pixmap_cached(name: str, color: str, size: int, dpr: float) -> QPixmap:
    path = custom_icon_path(name)
    svg = path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    logical_size = max(1, int(size))
    physical_size = max(1, round(logical_size * dpr))
    pixmap = QPixmap(physical_size, physical_size)
    pixmap.fill(Qt.transparent)
    if renderer.isValid():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def render_svg_pixmap(
    icon: AppIcon | str | Path, color: str | QColor, size: int = 24
) -> QPixmap:
    """Render an app-owned SVG icon to a DPR-aware pixmap (crisp on Retina)."""
    return _render_svg_pixmap_cached(
        str(icon), _color_name(color), int(size), _device_pixel_ratio()
    )


def render_svg_icon(icon: AppIcon | str | Path, color: str | QColor, size: int = 24) -> QIcon:
    """Render an app-owned SVG icon using the requested theme color."""
    path = custom_icon_path(icon)
    if not path.exists():
        return QIcon(str(path))
    return QIcon(render_svg_pixmap(icon, color, size))


def to_qicon(icon: Any, color: str | QColor | None = None, size: int = 24) -> QIcon:
    """Convert a FluentIcon, QIcon, or app-owned SVG name/path to QIcon."""
    if isinstance(icon, QIcon):
        return icon

    icon_factory = getattr(icon, "icon", None)
    if callable(icon_factory):
        return icon_factory()

    if color is not None:
        return render_svg_icon(icon, color, size)

    return QIcon(str(custom_icon_path(icon)))
