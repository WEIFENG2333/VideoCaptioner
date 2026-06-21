# -*- coding: utf-8 -*-
"""设计语言基础控件（workbench design language）。

页面通用的原子样式控件；颜色一律取自 theme_tokens.app_palette()，不允许
页面私造色值。

控件清单：

- StatusPill        状态胶囊（neutral/ok/warn/fail 四级）
- InfoChip          信息胶囊（只读元数据标签）
- HeaderLinkButton  面板头部的胶囊链接
- RoundIconButton   圆形图标按钮（面板头部设置入口）
- WorkbenchButton   按钮（默认 44 高 9 圆角，可带图标）
- CompactButton     紧凑按钮（32 高）
- ToggleSwitch      开关（48x28 自绘）
- PillSelect        胶囊下拉（取值胶囊，点击弹菜单换值）
- OptionCard        选项卡片（左标签右控件）
- DropZone          拖放导入空态（framed 虚线框 / 无框两种形态）
- FilePickLink      “点击选择文件”链接
- ProgressBarLine   8px 进度条
- AdaptiveTitleLabel / ElidedLabel  自适应标题 / 单行省略标签
- WorkbenchPanel    面板容器（14 圆角）
- PanelHeader       面板标题行（inline / bar，可加 underline）

所有圆角背景边框统一走 draw_rounded_surface 自绘（QSS 圆角无抗锯齿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Action, RoundMenu

from videocaptioner.core.entities import (
    SupportedAudioFormats,
    SupportedSubtitleFormats,
    SupportedVideoFormats,
)
from videocaptioner.ui.common.app_icons import AppIcon, render_svg_pixmap
from videocaptioner.ui.common.theme_tokens import app_palette, is_dark_theme, rgba
from videocaptioner.ui.i18n import tr

_VIDEO_EXTENSIONS = {fmt.value for fmt in SupportedVideoFormats}
_AUDIO_EXTENSIONS = {fmt.value for fmt in SupportedAudioFormats}
_SUBTITLE_EXTENSIONS = {fmt.value for fmt in SupportedSubtitleFormats}
_TEXT_EXTENSIONS = {"txt", "md", "json", "log"}


def file_type_icon(path: str | Path) -> AppIcon:
    """按扩展名归类文件图标：视频 / 音频 / 字幕 / 文本 / 通用文件。"""
    suffix = Path(str(path)).suffix.lower().lstrip(".")
    if suffix in _VIDEO_EXTENSIONS:
        return AppIcon.VIDEO
    if suffix in _AUDIO_EXTENSIONS:
        return AppIcon.MUSIC
    if suffix in _SUBTITLE_EXTENSIONS:
        return AppIcon.SUBTITLE
    if suffix in _TEXT_EXTENSIONS:
        return AppIcon.DOCUMENT
    return AppIcon.FILE


def _hover_colors() -> tuple[str, str]:
    """按主题返回控件 hover 的背景 / 边框色。"""
    if is_dark_theme():
        return "#303735", "#74807b"
    return "#e8ecea", "#9aa6a1"


def to_qcolor(value: str | QColor) -> QColor:
    """解析调色板里的颜色串：支持 #hex 与 rgba(r, g, b, a)。"""
    if isinstance(value, QColor):
        return value
    text = str(value).strip()
    if text.startswith("rgba"):
        parts = text[text.index("(") + 1 : text.rindex(")")].split(",")
        red, green, blue = (int(float(p)) for p in parts[:3])
        alpha = float(parts[3])
        return QColor(red, green, blue, round(alpha * 255))
    return QColor(text)


def draw_rounded_surface(
    widget,
    bg: str | QColor,
    border: str | QColor,
    radius: float,
) -> None:
    """抗锯齿地画控件的圆角背景和 1px 边框。

    QSS 的 border-radius 渲染不做抗锯齿，胶囊形控件边缘会有明显锯齿；
    统一改为 QPainter 自绘，QSS 只负责文字颜色。
    """
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    effective_radius = min(radius, rect.height() / 2)
    path = QPainterPath()
    path.addRoundedRect(rect, effective_radius, effective_radius)
    painter.fillPath(path, to_qcolor(bg))
    painter.setPen(QPen(to_qcolor(border), 1))
    painter.drawPath(path)


def qt_font_weight(css_weight: int) -> int:
    """把 CSS font-weight（400-900）映射到 Qt5 字重（50-87）。"""
    return max(1, min(99, round(50 + (css_weight - 400) * 37 / 500)))


def apply_font(
    widget, pixel_size: int, css_weight: int = 400, families: Optional[list[str]] = None
) -> None:
    font = QFont(widget.font())
    font.setPixelSize(pixel_size)
    font.setWeight(qt_font_weight(css_weight))
    if families:
        font.setFamilies(families)
    widget.setFont(font)


def icon_pixmap(icon: AppIcon, color: str, size: int):
    """DPR 感知的图标位图；直接返回物理分辨率渲染结果，Retina 上不发糊。"""
    return render_svg_pixmap(icon, color, size)


class ClickableFrame(QFrame):
    """可点击容器：左键发 clicked 信号，卡片/行类组件的通用基座。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
        super().mousePressEvent(event)


class AdaptiveTitleLabel(QLabel):
    """自适应标题：一行放得下用大字号；放不下降字号排两行；仍超出则省略。

    避免长文件名被单行省略掉大半，同时不留大片空白。
    """

    def __init__(
        self,
        base_size: int = 24,
        base_weight: int = 860,
        compact_size: int = 19,
        parent=None,
    ):
        super().__init__(parent)
        self._full = ""
        self._base_size = base_size
        self._base_weight = base_weight
        self._compact_size = compact_size
        self.setWordWrap(False)
        apply_font(self, base_size, base_weight)

    def setFullText(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._relayout()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = max(40, self.width())
        apply_font(self, self._base_size, self._base_weight)
        if self.fontMetrics().horizontalAdvance(self._full) <= width:
            self.setText(self._full)
            return
        # 一行放不下：降字号排两行（按字符贪心断行，中文文件名为主）。
        apply_font(self, self._compact_size, self._base_weight)
        metrics = self.fontMetrics()
        line1_end = len(self._full)
        for index in range(1, len(self._full) + 1):
            if metrics.horizontalAdvance(self._full[:index]) > width:
                line1_end = index - 1
                break
        line1 = self._full[:line1_end]
        rest = self._full[line1_end:]
        line2 = metrics.elidedText(rest, Qt.ElideRight, width)  # type: ignore[arg-type]
        self.setText(f"{line1}\n{line2}")


class ElidedLabel(QLabel):
    """单行省略标签：超宽时尾部省略号，悬浮提示完整文本。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(60)
        super().setText(text)

    def setText(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = self.fontMetrics()
        super().setText(
            metrics.elidedText(self._full, Qt.ElideRight, max(40, self.width()))  # type: ignore[arg-type]
        )


class StatusPill(QLabel):
    """状态胶囊：等待文件 / 转录中 / 转录失败 / 完成 等。"""

    LEVELS = ("neutral", "ok", "warn", "fail")

    def __init__(self, text: str = "", level: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setObjectName("wbStatusPill")
        self._level = level
        self.setFixedHeight(31)
        self.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self, 13, 760)
        self.syncStyle()

    def level(self) -> str:
        return self._level

    def setLevel(self, level: str):
        assert level in self.LEVELS, level
        self._level = level
        self.syncStyle()

    def setState(self, text: str, level: str):
        self.setText(text)
        self.setLevel(level)

    def syncStyle(self):
        palette = app_palette()
        styles = {
            "neutral": (palette.control, palette.line, palette.muted),
            "ok": (palette.accent_soft, rgba(palette.accent, 0.72), palette.accent_text),
            "warn": (palette.warn_soft, rgba(palette.warn, 0.70), palette.warn_fg),
            "fail": (palette.danger_soft, rgba(palette.danger, 0.75), palette.danger_fg),
        }
        self._bg, self._border, fg = styles[self._level]
        self.setStyleSheet(
            f"""
            QLabel#wbStatusPill {{
                color: {fg};
                background: transparent;
                border: none;
                padding: 0 12px;
            }}
            """
        )
        self.update()

    def paintEvent(self, event):
        draw_rounded_surface(self, self._bg, self._border, 15)
        super().paintEvent(event)


class InfoChip(QLabel):
    """只读信息胶囊：分辨率、时长、文件大小、格式等元数据。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("wbInfoChip")
        self.setFixedHeight(31)
        self.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self, 13, 760)
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        self._bg, self._border = palette.control, palette.line
        self.setStyleSheet(
            f"""
            QLabel#wbInfoChip {{
                color: {palette.muted};
                background: transparent;
                border: none;
                padding: 0 12px;
            }}
            """
        )
        self.update()

    def paintEvent(self, event):
        draw_rounded_surface(self, self._bg, self._border, 15)
        super().paintEvent(event)


class HeaderLinkButton(QFrame):
    """面板头部的胶囊链接：更换文件、转录配置。"""

    clicked = pyqtSignal()

    def __init__(self, text: str, icon: AppIcon | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("wbHeaderLink")
        self._icon = icon
        self.setFixedHeight(31)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 0, 11, 0)
        layout.setSpacing(7)
        self.iconLabel = QLabel(self)
        self.iconLabel.setVisible(icon is not None)
        layout.addWidget(self.iconLabel)
        self.textLabel = QLabel(text, self)
        self.textLabel.setObjectName("wbHeaderLinkText")
        apply_font(self.textLabel, 13, 820)
        layout.addWidget(self.textLabel)
        self.syncStyle()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def syncStyle(self):
        palette = app_palette()
        if self._icon is not None:
            self.iconLabel.setPixmap(icon_pixmap(self._icon, palette.accent_text, 17))
        self._bg = rgba(palette.accent, 0.08)
        self._border = rgba(palette.accent, 0.46)
        self._hover_bg = rgba(palette.accent, 0.14)
        self._hover_border = rgba(palette.accent, 0.82)
        self.setStyleSheet(
            f"""
            QFrame#wbHeaderLink {{ background: transparent; border: none; }}
            QLabel#wbHeaderLinkText {{
                color: {palette.accent_text};
                background: transparent;
                border: none;
            }}
            """
        )
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        hovered = self.underMouse()
        draw_rounded_surface(
            self,
            self._hover_bg if hovered else self._bg,
            self._hover_border if hovered else self._border,
            15,
        )
        super().paintEvent(event)


class WorkbenchButton(QFrame):
    """按钮：44 高、9 圆角、可带 17px 图标。"""

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str,
        icon: AppIcon | None = None,
        primary: bool = False,
        height: int = 44,
        parent=None,
        tone: str | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("wbButton")
        self._icon = icon
        self._height = height
        # tone: primary / default / danger / warn。不传时由 primary 推断，向后兼容。
        self._tone = tone or ("primary" if primary else "default")
        self._primary = self._tone == "primary"
        self.setFixedHeight(height)
        self.setMinimumWidth(126)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.iconLabel = QLabel(self)
        # 自带透明底：父级 setStyleSheet 后，未声明背景的子 QLabel 会回退到调色板底色，
        # 在按钮上糊出一块方块（与 CompactButton 同款修复）。
        self.iconLabel.setStyleSheet("background: transparent; border: none;")
        self.iconLabel.setVisible(icon is not None)
        layout.addWidget(self.iconLabel)
        self.textLabel = QLabel(text, self)
        self.textLabel.setObjectName("wbButtonText")
        layout.addWidget(self.textLabel)
        layout.addStretch(1)
        self.syncStyle()

    def text(self) -> str:
        return self.textLabel.text()

    def setText(self, text: str):
        self.textLabel.setText(text)

    def setIcon(self, icon: AppIcon | None):
        self._icon = icon
        self.iconLabel.setVisible(icon is not None)
        self.syncStyle()

    def setPrimary(self, primary: bool):
        self._tone = "primary" if primary else "default"
        self._primary = primary
        self.syncStyle()

    def setTone(self, tone: str):
        self._tone = tone
        self._primary = tone == "primary"
        self.syncStyle()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.setCursor(
            Qt.PointingHandCursor if enabled else Qt.ArrowCursor  # type: ignore[arg-type]
        )
        self.syncStyle()

    def click(self):
        """QPushButton 兼容：供 .click() 直接触发（测试/脚本/程序化调用）。"""
        if self.isEnabled():
            self.clicked.emit()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def syncStyle(self):
        palette = app_palette()
        tone = self._tone
        weight = 860 if tone == "primary" else 780
        if not self.isEnabled():
            # disabled 态是整体 45% 透明度，QSS 做不到，按等效色近似。
            if tone == "primary":
                bg = border = rgba(palette.accent, 0.30)
                fg = rgba(palette.accent_fg, 0.55)
            else:
                bg, border, fg = palette.control, palette.line, palette.subtle
            hover_bg, hover_border = bg, border
            icon_color = palette.subtle
        elif tone == "primary":
            bg = border = palette.accent
            fg = palette.accent_fg
            # hover 提亮基于主题色派生，自定义主题色时跟随变化
            hover_bg = hover_border = to_qcolor(palette.accent).lighter(112).name()
            icon_color = palette.accent_fg
        elif tone == "danger":
            bg, border = rgba(palette.danger, 0.10), rgba(palette.danger, 0.55)
            fg = icon_color = palette.danger_fg
            hover_bg, hover_border = rgba(palette.danger, 0.16), rgba(palette.danger, 0.70)
        elif tone == "warn":
            bg, border = rgba(palette.warn, 0.12), rgba(palette.warn, 0.50)
            fg = icon_color = palette.warn
            hover_bg, hover_border = rgba(palette.warn, 0.18), rgba(palette.warn, 0.66)
        else:
            bg, border, fg = palette.control, palette.line, palette.text
            hover_bg, hover_border = _hover_colors()
            icon_color = palette.text
        apply_font(self.textLabel, 16, weight)
        if self._icon is not None:
            self.iconLabel.setPixmap(icon_pixmap(self._icon, icon_color, 17))
        self._bg, self._border = bg, border
        self._hover_bg, self._hover_border = hover_bg, hover_border
        self.setStyleSheet(
            f"""
            QFrame#wbButton {{ background: transparent; border: none; }}
            QLabel#wbButtonText {{
                color: {fg};
                background: transparent;
                border: none;
            }}
            """
        )
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        hovered = self.underMouse() and self.isEnabled()
        draw_rounded_surface(
            self,
            self._hover_bg if hovered else self._bg,
            self._hover_border if hovered else self._border,
            9,
        )
        super().paintEvent(event)


class ToggleSwitch(QFrame):
    """开关：48x28 自绘胶囊 + 20px 圆形滑块。"""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(48, 28)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.setChecked(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._checked:
            track_bg = QColor(palette.accent)
            track_bg.setAlphaF(0.14)
            track_border = QColor(palette.accent)
            track_border.setAlphaF(0.78)
            knob = QColor(palette.accent)
            knob_x = self.width() - 3 - 20
        else:
            track_bg = QColor("#222927" if is_dark_theme() else "#e2e7e5")
            track_border = QColor(palette.line)
            knob = QColor("#b8c6c0" if is_dark_theme() else "#7d8a85")
            knob_x = 3
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(track_border, 1))
        painter.setBrush(track_bg)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(knob_x, 4, 20, 20))


class FilePickLink(QFrame):
    """“点击选择文件”链接：图标 + 文案 + 渐变下划线。"""

    clicked = pyqtSignal()

    def __init__(self, text: str, icon: AppIcon = AppIcon.FOLDER, parent=None):
        super().__init__(parent)
        self._icon = icon
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 6)
        layout.setSpacing(7)
        self.iconLabel = QLabel(self)
        layout.addWidget(self.iconLabel)
        self.textLabel = QLabel(text, self)
        apply_font(self.textLabel, 16, 850)
        layout.addWidget(self.textLabel)
        self.syncStyle()

    def _hover_accent(self) -> str:
        """hover 高亮：深色主题提亮一档，浅色主题加深一档（提亮会糊在浅底上）。"""
        palette = app_palette()
        if is_dark_theme():
            return to_qcolor(palette.accent).lighter(125).name()
        return to_qcolor(palette.accent_text).darker(115).name()

    def _rest_accent(self) -> str:
        """静默态降一档存在感，hover 跳到高亮才有明确反馈。

        深色主题用半透明压暗；浅色主题用可读的加深主题色
        （原色亮绿在浅底上对比不足）。
        """
        palette = app_palette()
        if is_dark_theme():
            accent = to_qcolor(palette.accent)
            accent.setAlphaF(0.72)
            return accent.name(QColor.HexArgb)
        return palette.accent_text

    def syncStyle(self):
        color = self._hover_accent() if self.underMouse() else self._rest_accent()
        self.iconLabel.setPixmap(icon_pixmap(self._icon, color, 17))
        self.textLabel.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
        )

    def enterEvent(self, event):
        self.syncStyle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.syncStyle()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        palette = app_palette()
        hovered = self.underMouse()
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        accent = to_qcolor(self._hover_accent() if hovered else palette.accent)
        accent.setAlphaF(1.0 if hovered else 0.30)
        gradient.setColorAt(0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.5, accent)
        gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(0, self.height() - 2, self.width(), 2), gradient)


class DropZone(QFrame):
    """拖放导入空态。

    framed=True：虚线边框 + 顶部辉光（转录页样式）；
    framed=False：无边框，仅居中引导内容（字幕页表格空态样式）。
    两种形态拖拽悬停时边框都会点亮为主题色；整个区域可点击选择文件。
    """

    browseRequested = pyqtSignal()

    def __init__(
        self,
        *,
        icon: AppIcon,
        title: str,
        pick_text: str,
        pick_icon: AppIcon = AppIcon.FOLDER,
        formats_line: str = "",
        framed: bool = True,
        accent_icon: bool = False,
        icon_box: int = 92,
        icon_size: int = 48,
        title_size: int = 34,
        parent=None,
    ):
        super().__init__(parent)
        self._framed = framed
        self._drag_active = False
        self._icon = icon
        self._icon_size = icon_size
        self._accent_icon = accent_icon
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 34, 34, 34)
        layout.setSpacing(0)
        layout.addStretch(1)

        self.iconBox = QFrame(self)
        self.iconBox.setObjectName("dropIcon")
        self.iconBox.setFixedSize(icon_box, icon_box)
        icon_layout = QVBoxLayout(self.iconBox)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self.iconBox)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        icon_layout.addWidget(self.iconLabel)
        layout.addWidget(self.iconBox, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        layout.addSpacing(20)

        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("dropTitle")
        self.titleLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.titleLabel, title_size, 880)
        layout.addWidget(self.titleLabel)
        layout.addSpacing(14)

        pick_row = QHBoxLayout()
        pick_row.setSpacing(8)
        pick_row.addStretch(1)
        self.orLabel = QLabel(tr("workbench.drop.or"), self)
        self.orLabel.setObjectName("dropOr")
        apply_font(self.orLabel, 16, 400)
        pick_row.addWidget(self.orLabel)
        self.pickLink = FilePickLink(pick_text, pick_icon, self)
        self.pickLink.clicked.connect(self.browseRequested)
        pick_row.addWidget(self.pickLink)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)

        self.formatLabel = QLabel(formats_line, self)
        self.formatLabel.setObjectName("dropFormats")
        self.formatLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.formatLabel, 14, 720)
        self.formatLabel.setVisible(bool(formats_line))
        if formats_line:
            layout.addSpacing(22)
        layout.addWidget(self.formatLabel)
        layout.addStretch(1)
        self.syncStyle()

    def setDragActive(self, active: bool):
        if active != self._drag_active:
            self._drag_active = active
            self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.browseRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def syncStyle(self):
        palette = app_palette()
        icon_color = palette.accent if self._accent_icon else palette.muted
        self.iconLabel.setPixmap(icon_pixmap(self._icon, icon_color, self._icon_size))
        self.setStyleSheet(
            f"""
            QFrame#dropIcon {{
                background: {palette.control};
                border: 1px solid {rgba("#ffffff", 0.04) if is_dark_theme() else palette.line_soft};
                border-radius: 22px;
            }}
            QLabel#dropTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#dropOr {{ color: {palette.subtle}; background: transparent; }}
            QLabel#dropFormats {{ color: {palette.faint}; background: transparent; }}
            """
        )

    def paintEvent(self, event):
        palette = app_palette()
        dark = is_dark_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)

        if self._framed:
            clip = QPainterPath()
            clip.addRoundedRect(rect, 16, 16)
            painter.setClipPath(clip)
            # 下沉式内嵌：内部比所在面板更深一档，拖放区与周围明确区分。
            painter.fillRect(
                self.rect(), QColor(0, 0, 0, 64) if dark else QColor(0, 0, 0, 12)
            )
            glow = QRadialGradient(
                self.width() * 0.5, self.height() * 0.18, self.width() * 0.34
            )
            accent = QColor(palette.accent)
            accent.setAlphaF(0.16)
            glow.setColorAt(0, accent)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(self.rect(), glow)
            painter.setClipping(False)

        hovered = self.underMouse()
        if self._drag_active:
            border, width = QColor(palette.accent), 2
        elif self._framed:
            if hovered:
                border = to_qcolor(rgba(palette.accent, 0.55))
            else:
                border = QColor("#53615c") if dark else QColor(palette.line)
            width = 1
        elif hovered:
            border, width = to_qcolor(rgba(palette.accent, 0.45)), 1
        else:
            super().paintEvent(event)
            return
        pen = QPen(border, width, Qt.DashLine)  # type: ignore[arg-type]
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawRoundedRect(rect, 16, 16)
        super().paintEvent(event)


class ProgressBarLine(QFrame):
    """8px 进度条。

    tone 控制填充色：accent（默认）/ warn（处理中黄）/ fail（失败红）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._tone = "accent"
        self.setFixedHeight(8)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        self._value = max(0, min(100, value))
        self.update()

    def setTone(self, tone: str):
        assert tone in ("accent", "warn", "fail"), tone
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        painter.setBrush(QColor(palette.disabled))
        painter.drawRoundedRect(self.rect(), 4, 4)
        if self._value > 0:
            fill = QRectF(0, 0, self.width() * self._value / 100, self.height())
            # 浅色主题下黄/红原色与浅底对比不足，用加深的前景色
            dark = is_dark_theme()
            color = {
                "accent": palette.accent,
                "warn": palette.warn if dark else palette.warn_fg,
                "fail": palette.danger if dark else palette.danger_fg,
            }[self._tone]
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(fill, 4, 4)


class RoundIconButton(QFrame):
    """圆形图标按钮：面板头部的设置入口等，与胶囊 tag 形成视觉区分。"""

    clicked = pyqtSignal()

    def __init__(self, icon: AppIcon, diameter: int = 34, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        layout.addWidget(self.iconLabel)
        self.syncStyle()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        draw_rounded_surface(
            self,
            rgba(palette.accent, 0.14) if hovered else rgba(palette.accent, 0.08),
            rgba(palette.accent, 0.82) if hovered else rgba(palette.accent, 0.46),
            self._diameter / 2,
        )
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconLabel.setPixmap(
            icon_pixmap(self._icon, palette.accent_text, int(self._diameter * 0.5))
        )
        self.setStyleSheet("background: transparent; border: none;")
        self.update()


class _FilterTab(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, text: str, parent=None):
        super().__init__(text, parent)
        self.key = key
        self._active = False
        self.setFixedHeight(30)
        self.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        apply_font(self, 13, 800)
        self.syncStyle()

    def setActive(self, active: bool):
        if active != self._active:
            self._active = active
            self.syncStyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit(self.key)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if self._active:
            palette = app_palette()
            draw_rounded_surface(self, palette.accent, palette.accent, 7)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        color = palette.accent_fg if self._active else palette.muted
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none; padding: 0 12px;"
        )
        self.update()


class FilterTabs(QFrame):
    """分段筛选：批量队列过滤、配音声线筛选等通用。"""

    changed = pyqtSignal(str)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("batchFilterTabs")
        # 固定高度：否则在头部行里被拉伸贴边，圆角容器糊到面板边缘
        self.setFixedHeight(38)
        self._current = items[0][0]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        self._tabs: list[_FilterTab] = []
        for key, text in items:
            tab = _FilterTab(key, text, self)
            tab.clicked.connect(self.setCurrent)
            layout.addWidget(tab)
            self._tabs.append(tab)
        self.setStyleSheet("QFrame#batchFilterTabs { background: transparent; border: none; }")
        self._sync()

    def current(self) -> str:
        return self._current

    def setCurrent(self, key: str):
        if key == self._current:
            return
        self._current = key
        self._sync()
        self.changed.emit(key)

    def _sync(self):
        for tab in self._tabs:
            tab.setActive(tab.key == self._current)

    def syncStyle(self):
        for tab in self._tabs:
            tab.syncStyle()
        self.update()

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 10)
        super().paintEvent(event)


class SelectableCard(QFrame):
    """可选卡：左侧可选图标盒 + 标题/说明，
    选中态主题色描边+底色，hover 轻描边。批量处理模式卡、配音提供商卡共用，
    全自绘圆角（QSS 圆角无抗锯齿）。点击发 clicked(key)。"""

    clicked = pyqtSignal(str)

    def __init__(
        self,
        key: str,
        title: str,
        desc: str,
        icon: Optional[AppIcon] = None,
        parent=None,
        min_height: int = 84,
    ):
        super().__init__(parent)
        self.setObjectName("selectableCard")
        self.key = key
        self._icon = icon
        self._active = False
        self.setMinimumHeight(min_height)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(13)
        self.iconBox: Optional[QFrame] = None
        self.iconLabel: Optional[QLabel] = None
        if icon is not None:
            self.iconBox = QFrame(self)
            self.iconBox.setObjectName("selectableCardIcon")
            self.iconBox.setFixedSize(40, 40)
            icon_layout = QVBoxLayout(self.iconBox)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            self.iconLabel = QLabel(self.iconBox)
            self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
            icon_layout.addWidget(self.iconLabel)
            layout.addWidget(self.iconBox)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        text_box.addStretch(1)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("selectableCardTitle")
        apply_font(self.titleLabel, 15, 870)
        text_box.addWidget(self.titleLabel)
        self.descLabel = QLabel(desc, self)
        self.descLabel.setObjectName("selectableCardDesc")
        self.descLabel.setWordWrap(True)
        apply_font(self.descLabel, 12, 700)
        text_box.addWidget(self.descLabel)
        text_box.addStretch(1)
        layout.addLayout(text_box, 1)
        self.syncStyle()

    def setActive(self, active: bool):
        if active != self._active:
            self._active = active
            self.syncStyle()

    def isActive(self) -> bool:
        return self._active

    def setBadge(self, text: str, level: str = "neutral"):
        """卡片右侧状态胶囊（如配音提供商的「免 Key / 需 Key / 可克隆」）。"""
        if getattr(self, "_badge", None) is None:
            self._badge = StatusPill(text, level, self)
            self.layout().addWidget(self._badge, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        else:
            self._badge.setState(text, level)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit(self.key)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        if self._active:
            bg, border = rgba(palette.accent, 0.075), rgba(palette.accent, 0.72)
        elif self.underMouse() and self.isEnabled():
            bg, border = palette.panel, rgba(palette.accent, 0.4)
        else:
            bg, border = palette.panel, palette.line_soft
        draw_rounded_surface(self, bg, border, 13)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        icon_css = ""
        if self.iconLabel is not None and self._icon is not None:
            icon_color = palette.accent if self._active else palette.muted
            icon_bg = rgba(palette.accent, 0.12) if self._active else palette.control
            self.iconLabel.setPixmap(icon_pixmap(self._icon, icon_color, 20))
            icon_css = (
                f"QFrame#selectableCardIcon {{ background: {icon_bg};"
                f" border: none; border-radius: 11px; }}"
            )
        self.setStyleSheet(
            f"""
            QFrame#selectableCard {{ background: transparent; border: none; }}
            {icon_css}
            QLabel#selectableCardTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#selectableCardDesc {{ color: {palette.subtle}; background: transparent; }}
            """
        )
        self.update()


class ErrorCard(QFrame):
    """错误卡：danger_soft 底 + danger 描边 + 可选标题 + 可选中正文。

    转录/字幕/合成/任务创建四页统一用它（过去各页一份 QSS 复制，边框透明度/
    内边距/字号各自漂移）。全自绘圆角；正文可选中复制，方便用户反馈。
    """

    def __init__(self, text: str = "", title: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("wbErrorCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)
        self.titleLabel: Optional[QLabel] = None
        if title is not None:
            self.titleLabel = QLabel(title, self)
            self.titleLabel.setObjectName("wbErrorTitle")
            apply_font(self.titleLabel, 15, 820)
            layout.addWidget(self.titleLabel)
        self.messageLabel = QLabel(text, self)
        self.messageLabel.setObjectName("wbErrorMessage")
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore[arg-type]
        apply_font(self.messageLabel, 14, 720)
        layout.addWidget(self.messageLabel)
        self.syncStyle()

    def setText(self, text: str):
        self.messageLabel.setText(text)

    def text(self) -> str:
        return self.messageLabel.text()

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.danger_soft, rgba(palette.danger, 0.70), 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        css = "QFrame#wbErrorCard { background: transparent; border: none; }"
        if self.titleLabel is not None:
            css += f" QLabel#wbErrorTitle {{ color: {palette.text}; background: transparent; }}"
        css += f" QLabel#wbErrorMessage {{ color: {palette.danger_fg}; background: transparent; }}"
        self.setStyleSheet(css)
        self.update()


class SectionLabel(QLabel):
    """小节标题：弱化色 + 12px/800，面板内分组小标题统一用它。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("wbSectionLabel")
        apply_font(self, 12, 800)
        self.syncStyle()

    def syncStyle(self):
        self.setStyleSheet(
            f"color: {app_palette().subtle}; background: transparent; border: none;"
        )


class PrimaryIconButton(QFrame):
    """圆形实心主操作图标按钮：主题绿底 + 深色图标，靠图标与悬浮提示表意。"""

    clicked = pyqtSignal()

    def __init__(self, icon: AppIcon, diameter: int = 52, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        layout.addWidget(self.iconLabel)
        self.syncStyle()

    def setIcon(self, icon: AppIcon):
        if icon != self._icon:
            self._icon = icon
            self.syncStyle()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.setCursor(
            Qt.PointingHandCursor if enabled else Qt.ArrowCursor  # type: ignore[arg-type]
        )
        self.syncStyle()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        if not self.isEnabled():
            bg = rgba(palette.accent, 0.30)
        elif self.underMouse():
            bg = to_qcolor(palette.accent).lighter(112).name()
        else:
            bg = palette.accent
        draw_rounded_surface(self, bg, bg, self._diameter / 2)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        color = (
            palette.accent_fg
            if self.isEnabled()
            else rgba(palette.accent_fg, 0.55)
        )
        self.iconLabel.setPixmap(
            icon_pixmap(self._icon, color, int(self._diameter * 0.42))
        )
        self.setStyleSheet("background: transparent; border: none;")
        self.update()


class AppLineEdit(QLineEdit):
    """第一方单行输入框：自绘抗锯齿圆角底 + 聚焦主题色描边，去掉 qfluent 的底部下划线，

    与 workbench 其余控件同一套设计语言。用于弹窗 / 取色器等所有单行文本输入。"""

    def __init__(self, text: str = "", parent=None, height: int = 36):
        super().__init__(text, parent)
        self.setObjectName("appLineEdit")
        self.setFrame(False)
        self.setFixedHeight(height)
        self.setCursor(Qt.IBeamCursor)  # type: ignore[arg-type]
        self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        if self.hasFocus():
            border = palette.accent
        elif self.underMouse() and self.isEnabled():
            border = palette.accent_border
        else:
            border = palette.line_soft
        draw_rounded_surface(self, palette.field, border, 9)
        super().paintEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def syncStyle(self):
        palette = app_palette()
        apply_font(self, 14, 720)
        self.setStyleSheet(
            f"""
            QLineEdit#appLineEdit {{
                background: transparent;
                border: none;
                padding: 0 12px;
                color: {palette.text};
                selection-background-color: {rgba(palette.accent, 0.35)};
                selection-color: {palette.text};
            }}
            """
        )
        self.update()


class AppTextEdit(QPlainTextEdit):
    """第一方多行输入框：与 AppLineEdit 同一套圆角 + 聚焦/悬浮主题色描边，去掉 qfluent 下划线。

    文稿提示、配音文案、克隆参考文本等多行输入统一用它。"""

    def __init__(self, text: str = "", parent=None, min_height: int = 96, radius: int = 12):
        super().__init__(parent)
        self.setObjectName("appTextEdit")
        self._radius = radius
        self.setFrameShape(QFrame.NoFrame)  # type: ignore[attr-defined]
        self.setMinimumHeight(min_height)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore[attr-defined]
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[attr-defined]
        # 文本内边距走 documentMargin：QSS 的 padding 到不了 QPlainTextEdit 文本区
        # （文字会贴边），documentMargin 才能稳定把文字从边缘推开。
        self.document().setDocumentMargin(12)
        apply_font(self, 14, 720)  # 只设一次；调用方可在构造后用 apply_font 覆盖字号
        if text:
            self.setPlainText(text)
        self.syncStyle()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.syncStyle()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        if self.hasFocus():
            border = palette.accent
        elif self.underMouse() and self.isEnabled():
            border = palette.accent_border
        else:
            border = palette.line_soft
        # 文本区背景/文字色走 QPalette：QSS 的 background 在某些父级样式表下到不了
        # QPlainTextEdit 的 viewport（会露出 Qt 默认白底），调色板直控更可靠。
        # 用 panel_deep（比 panel 更暗）做下沉式输入框的深色底，
        # 避免用 field（比面板更亮）时输入框显得「浮起/和面板分不清」。
        pal = self.palette()
        pal.setColor(QPalette.Base, QColor(palette.panel_deep))
        pal.setColor(QPalette.Text, QColor(palette.text))
        self.setPalette(pal)
        self.setStyleSheet(
            f"""
            QPlainTextEdit#appTextEdit {{
                background: {palette.panel_deep};
                border: 1px solid {border};
                border-radius: {self._radius}px;
                color: {palette.text};
                selection-background-color: {rgba(palette.accent, 0.35)};
                selection-color: {palette.text};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 4px 2px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {palette.line}; border-radius: 3px; min-height: 28px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            """
        )
        self.update()


class CompactButton(QFrame):
    """紧凑按钮：32 高、图标 + 文案，表格头部操作用。"""

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str,
        icon: AppIcon | None = None,
        parent=None,
        icon_only: bool = False,
        pad_h: int = 11,
    ):
        super().__init__(parent)
        self.setObjectName("wbCompactButton")
        self._icon = icon
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(pad_h, 0, pad_h, 0)
        layout.setSpacing(6)
        self.iconLabel = QLabel(self)
        # 自带透明底：父级一旦 setStyleSheet，未显式声明背景的子 QLabel 会回退到调色板
        # 底色，在按钮上糊出一块深色方块（图标背后的黑块就是这么来的）。
        self.iconLabel.setStyleSheet("background: transparent; border: none;")
        self.iconLabel.setVisible(icon is not None)
        layout.addWidget(self.iconLabel)
        self.textLabel = QLabel(text, self)
        self.textLabel.setObjectName("wbCompactText")
        apply_font(self.textLabel, 13, 850)
        layout.addWidget(self.textLabel)
        if icon_only:
            # 仅图标按钮：收起文字与间距并居中图标，适合窄列内的卡片动作（配 tooltip）。
            self.textLabel.hide()
            layout.setSpacing(0)
            layout.insertStretch(0, 1)
            layout.addStretch(1)
        self.syncStyle()

    def text(self) -> str:
        return self.textLabel.text()

    def setText(self, text: str):
        self.textLabel.setText(text)

    def setIcon(self, icon: AppIcon | None):
        self._icon = icon
        self.iconLabel.setVisible(icon is not None)
        self.syncStyle()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.setCursor(
            Qt.PointingHandCursor if enabled else Qt.ArrowCursor  # type: ignore[arg-type]
        )
        self.syncStyle()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hover_bg, hover_border = _hover_colors()
        hovered = self.underMouse() and self.isEnabled()
        draw_rounded_surface(
            self,
            hover_bg if hovered else palette.field,
            hover_border if hovered else palette.line,
            9,
        )
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        fg = palette.text if self.isEnabled() else palette.subtle
        if self._icon is not None:
            self.iconLabel.setPixmap(
                icon_pixmap(self._icon, fg if self.isEnabled() else palette.subtle, 16)
            )
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbCompactButton {{ background: transparent; border: none; }}
            QLabel#wbCompactText {{ color: {fg}; background: transparent; border: none; }}
            """
        )


class AccentButton(CompactButton):
    """主操作迷你按钮：主题色描边与文字。"""

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        if self.isEnabled():
            bg = rgba(palette.accent, 0.16 if hovered else 0.10)
            border = rgba(palette.accent, 0.72)
        else:
            bg, border = palette.disabled, palette.line
        draw_rounded_surface(self, bg, border, 9)

    def syncStyle(self):
        palette = app_palette()
        fg = palette.accent_text if self.isEnabled() else palette.subtle
        if self._icon is not None:
            self.iconLabel.setPixmap(icon_pixmap(self._icon, fg, 16))
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbCompactButton {{ background: transparent; border: none; }}
            QLabel#wbCompactText {{ color: {fg}; background: transparent; border: none; }}
            """
        )


class DangerButton(CompactButton):
    """危险操作迷你按钮：删除等不可逆操作。"""

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        bg = rgba(palette.danger, 0.16 if hovered else 0.08)
        draw_rounded_surface(self, bg, rgba(palette.danger, 0.55), 9)

    def syncStyle(self):
        palette = app_palette()
        fg = palette.danger_fg if self.isEnabled() else palette.subtle
        if self._icon is not None:
            self.iconLabel.setPixmap(icon_pixmap(self._icon, fg, 16))
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbCompactButton {{ background: transparent; border: none; }}
            QLabel#wbCompactText {{ color: {fg}; background: transparent; border: none; }}
            """
        )


class IconBox(QFrame):
    """图标盒：半透明圆角块内嵌图标。

    tone 决定底色与图标色：
    - ``surface``（默认）：淡叠色底 + line_soft 边 + muted 图标；
    - ``accent``：主题色 0.08 底 + 无边 + accent_text 图标（流水线阶段 / 生成计划步骤）。
    """

    def __init__(self, icon: AppIcon, parent=None, size: int = 38, tone: str = "surface"):
        super().__init__(parent)
        self._icon = icon
        self._tone = tone
        self.setFixedSize(size, size)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        layout.addWidget(self.iconLabel)
        self.syncStyle()

    def setIcon(self, icon: AppIcon):
        self._icon = icon
        self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        if self._tone == "accent":
            tint = rgba(palette.accent, 0.08)
            draw_rounded_surface(self, tint, tint, 10)
        else:
            draw_rounded_surface(self, palette.card_surface_hover, palette.line_soft, 10)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        color = palette.accent_text if self._tone == "accent" else palette.muted
        self.iconLabel.setPixmap(icon_pixmap(self._icon, color, 17))
        self.setStyleSheet("background: transparent; border: none;")


class PillSelect(QFrame):
    """胶囊下拉取值胶囊：点击弹 RoundMenu 换值。"""

    currentTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("wbPillSelect")
        self._items: list[str] = []
        self._current = ""
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 0, 10, 0)
        layout.setSpacing(6)
        self.textLabel = QLabel(self)
        self.textLabel.setObjectName("wbPillSelectText")
        apply_font(self.textLabel, 13, 780)
        layout.addWidget(self.textLabel)
        # 常驻下拉箭头：让取值胶囊一眼可辨「可点选」，区别于只读 InfoChip 元数据胶囊
        self.chevronLabel = QLabel(self)
        # 自带透明底：父级 setStyleSheet 后未声明背景的子 QLabel 会回退调色板底色 → 箭头后糊一块方块
        self.chevronLabel.setStyleSheet("background: transparent; border: none;")
        self.chevronLabel.setFixedSize(14, 14)
        layout.addWidget(self.chevronLabel, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        self.syncStyle()

    def setItems(self, items: list[str], current: str | None = None):
        self._items = list(items)
        if current is not None:
            self.setCurrentText(current)
        elif self._items and self._current not in self._items:
            self.setCurrentText(self._items[0])

    def items(self) -> list[str]:
        return list(self._items)

    def currentText(self) -> str:
        return self._current

    def setCurrentText(self, text: str):
        if text == self._current:
            return
        self._current = text
        self.textLabel.setText(text)
        self.currentTextChanged.emit(text)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton and self._items:  # type: ignore[attr-defined]
            menu = RoundMenu(parent=self)
            for item in self._items:
                action = Action(item)
                action.triggered.connect(
                    lambda _=False, text=item: self.setCurrentText(text)
                )
                menu.addAction(action)
            # 候选很多时（如字体）限制可见行数并滚动，避免菜单顶到屏幕高度。
            menu.setMaxVisibleItems(14)
            menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
            event.accept()
            return
        super().mousePressEvent(event)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.syncStyle()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        # 静息态就用主题色描边（而非 line），与只读 InfoChip 拉开差异 → 用户知道这是可点控件
        border = rgba(palette.accent, 0.75 if hovered else 0.42) if self.isEnabled() else palette.line
        draw_rounded_surface(self, palette.control, border, 15)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        fg = palette.text if self.isEnabled() else palette.subtle
        self.chevronLabel.setPixmap(
            icon_pixmap(AppIcon.CHEVRON_DOWN, fg if self.isEnabled() else palette.subtle, 14)
        )
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbPillSelect {{ background: transparent; border: none; }}
            QLabel#wbPillSelectText {{ color: {fg}; background: transparent; border: none; }}
            """
        )


class _StepButton(QFrame):
    """步进器左右的加减格子（自绘圆角）。按住可连续触发并随按住时间加速。"""

    clicked = pyqtSignal()

    # 首次延迟后开始连发，连发间隔随按住时长逐级加快（毫秒）。
    _HOLD_DELAY = 380
    _REPEAT_STEPS = ((6, 110), (16, 60), (10**9, 28))

    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(symbol, self)
        self.label.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.label, 16, 760)
        layout.addWidget(self.label)
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.timeout.connect(self._on_repeat)
        self._repeat_count = 0
        self.syncStyle()

    def _on_repeat(self):
        if not self.isEnabled():
            return
        self._repeat_count += 1
        self.clicked.emit()
        interval = next(ms for limit, ms in self._REPEAT_STEPS if self._repeat_count < limit)
        self._repeat_timer.start(interval)

    def _stop_repeat(self):
        self._repeat_timer.stop()
        self._repeat_count = 0

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            self._repeat_count = 0
            self._repeat_timer.start(self._HOLD_DELAY)  # 按住超过延迟才开始连发
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._stop_repeat()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._stop_repeat()  # 移出按钮即停止连发，避免“跑飞”
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        border = rgba(palette.accent, 0.6) if hovered else palette.line_soft
        draw_rounded_surface(self, palette.card_surface_hover, border, 7)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        fg = palette.muted if self.isEnabled() else palette.subtle
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self.label.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        self.update()


class StepperControl(QFrame):
    """数值步进器：[−] 值 单位 [+]。

    参数面板里所有数值项统一用它（字号、描边、边距、圆角半径…），
    支持整数/小数（``decimals``）、范围与步长，全自绘圆角。
    """

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        value: float = 0,
        minimum: float = 0,
        maximum: float = 100,
        step: float = 1,
        decimals: int = 0,
        suffix: str = "",
        parent=None,
        width: int = 150,
    ):
        super().__init__(parent)
        self.setObjectName("wbStepper")
        self._min = minimum
        self._max = maximum
        self._step = step
        self._decimals = decimals
        self._suffix = suffix
        self._value = self._clamp(value)
        self.setFixedHeight(34)
        self.setFixedWidth(width)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 0, 7, 0)
        layout.setSpacing(6)
        self.minusButton = _StepButton("−", self)
        self.minusButton.clicked.connect(lambda: self._nudge(-self._step))
        layout.addWidget(self.minusButton)

        self.valueLabel = QLabel(self)
        self.valueLabel.setObjectName("wbStepperValue")
        self.valueLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.valueLabel, 13, 850)
        layout.addWidget(self.valueLabel, 1)

        self.plusButton = _StepButton("+", self)
        self.plusButton.clicked.connect(lambda: self._nudge(self._step))
        layout.addWidget(self.plusButton)
        self._refreshText()
        self.syncStyle()

    def _clamp(self, value: float) -> float:
        return max(self._min, min(self._max, round(float(value), self._decimals)))

    def value(self) -> float:
        return self._value

    def setValue(self, value: float, *, emit: bool = False):
        clamped = self._clamp(value)
        changed = clamped != self._value
        self._value = clamped
        self._refreshText()
        if changed and emit:
            self.valueChanged.emit(self._value)

    def _nudge(self, delta: float):
        before = self._value
        self._value = self._clamp(self._value + delta)
        if self._value != before:
            self._refreshText()
            self.valueChanged.emit(self._value)

    def _refreshText(self):
        if self._decimals > 0:
            text = f"{self._value:.{self._decimals}f}"
        else:
            text = str(int(self._value))
        if self._suffix:
            text = f"{text} {self._suffix}"
        self.valueLabel.setText(text)

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.field, palette.line, 9)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet("QFrame#wbStepper { background: transparent; border: none; }")
        self.valueLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )
        self.minusButton.syncStyle()
        self.plusButton.syncStyle()
        self.update()


class ToggleCard(QFrame):
    """输出内容卡：标题 + 说明 + 开关，开启时主题色描边。"""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, desc: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("wbToggleCard")
        self.setMinimumHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)
        column = QVBoxLayout()
        column.setSpacing(3)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("wbToggleCardTitle")
        apply_font(self.titleLabel, 14, 850)
        column.addWidget(self.titleLabel)
        self.descLabel = QLabel(desc, self)
        self.descLabel.setObjectName("wbToggleCardDesc")
        apply_font(self.descLabel, 12, 700)
        column.addWidget(self.descLabel)
        layout.addLayout(column, 1)
        self.switch = ToggleSwitch(checked, self)
        self.switch.toggled.connect(self._on_toggled)
        layout.addWidget(self.switch)
        self.syncStyle()

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool):
        self.switch.setChecked(checked)

    def _on_toggled(self, checked: bool):
        self.update()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        # 整卡可点切换，符合开关卡的常见交互。
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.switch.setChecked(not self.switch.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        active = self.switch.isChecked()
        surface = (
            rgba(palette.accent, 0.07)
            if active
            else (palette.card_surface)
        )
        border = rgba(palette.accent, 0.62) if active else palette.line_soft
        draw_rounded_surface(self, surface, border, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbToggleCard {{ background: transparent; border: none; }}
            QLabel#wbToggleCardTitle {{ color: {palette.text}; background: transparent; border: none; }}
            QLabel#wbToggleCardDesc {{ color: {palette.subtle}; background: transparent; border: none; }}
            """
        )


class OptionCard(QFrame):
    """选项卡片：左标签 + 右控件（开关 / 取值胶囊等）。"""

    def __init__(self, label: str, control: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("wbOptionCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(12)
        self.label = QLabel(label, self)
        self.label.setObjectName("wbOptionCardLabel")
        apply_font(self.label, 14, 850)
        layout.addWidget(self.label, 1, Qt.AlignVCenter)  # type: ignore[arg-type]
        self.control = control
        layout.addWidget(control, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        # 高度由内容驱动：复合控件（如 音色胶囊+音色库按钮）超过 30px 时
        # 卡片随之长高，绝不压缩边距把控件底边裁掉。
        self.setMinimumHeight(max(48, control.sizeHint().height() + 18))
        self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#wbOptionCard {{ background: transparent; border: none; }}
            QLabel#wbOptionCardLabel {{ color: {palette.text}; background: transparent; border: none; }}
            """
        )


class MediaThumb(QFrame):
    """媒体缩略图：有封面画封面，没有就画音/视频占位图。

    转录页媒体卡与合成页结果预览共用。
    """

    # 音频波形折线的折点（180x28 坐标系），绘制时按尺寸缩放。
    _WAVE_POINTS = [
        (2, 15), (24, 6), (44, 22), (64, 9), (84, 18),
        (104, 4), (124, 23), (144, 10), (178, 16),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._audio = False

    def setMedia(self, thumbnail_path: str | None, is_audio: bool):
        self._audio = is_audio
        self._pixmap = None
        if thumbnail_path and Path(thumbnail_path).exists():
            pixmap = QPixmap(thumbnail_path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

    def clear(self):
        self._pixmap = None
        self._audio = False
        self.update()

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 10, 10)
        painter.setClipPath(clip)

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,  # type: ignore[arg-type]
                Qt.SmoothTransformation,  # type: ignore[arg-type]
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#23302c"))
            gradient.setColorAt(1, QColor("#18201d"))
            painter.fillRect(self.rect(), gradient)

            glow = QRadialGradient(self.width() * 0.5, self.height() * 0.42, self.width() * 0.31)
            accent_glow = QColor(palette.accent)
            accent_glow.setAlphaF(0.18)
            glow.setColorAt(0, accent_glow)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(self.rect(), glow)

            box = min(68, int(self.height() * 0.58))
            box_rect = QRectF(
                (self.width() - box) / 2, (self.height() - box) / 2 - (6 if self._audio else 0),
                box, box,
            )
            painter.setPen(QPen(QColor(203, 212, 208, 46), 1))
            painter.setBrush(QColor(8, 17, 14, 107))
            painter.drawRoundedRect(box_rect, 16, 16)
            icon = AppIcon.MUSIC if self._audio else AppIcon.VIDEO
            icon_size = int(box * 0.5)
            pixmap = icon_pixmap(icon, palette.accent, icon_size)
            painter.drawPixmap(
                int(box_rect.x() + (box - icon_size) / 2),
                int(box_rect.y() + (box - icon_size) / 2),
                pixmap,
            )
            if self._audio:
                self._draw_waveform(painter, palette.accent)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(palette.line_soft), 1))
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawRoundedRect(rect, 10, 10)

    def _draw_waveform(self, painter: QPainter, accent: str):
        inset, height = 18, 28
        width = self.width() - inset * 2
        top = self.height() - inset - height
        pen = QPen(QColor(accent), 3)
        pen.setCapStyle(Qt.RoundCap)  # type: ignore[arg-type]
        painter.setPen(pen)
        path = QPainterPath()
        points = [
            (inset + x / 180 * width, top + y / 28 * height)
            for x, y in self._WAVE_POINTS
        ]
        path.moveTo(*points[0])
        for index in range(1, len(points)):
            prev_x, prev_y = points[index - 1]
            x, y = points[index]
            mid = (prev_x + x) / 2
            path.cubicTo(mid, prev_y, mid, y, x, y)
        painter.drawPath(path)


class WorkbenchPanel(QFrame):
    """面板容器：14 圆角、1px 边框。布局由调用方自己放。"""

    def __init__(self, parent=None, padded: bool = True):
        super().__init__(parent)
        self.setObjectName("wbPanel")
        self.bodyLayout = QVBoxLayout(self)
        if padded:
            self.bodyLayout.setContentsMargins(22, 22, 22, 22)
        else:
            self.bodyLayout.setContentsMargins(0, 0, 0, 0)
        self.bodyLayout.setSpacing(0)
        # 子类通常覆写 syncStyle 并引用自己的成员，构造期只应用基类样式。
        WorkbenchPanel.syncStyle(self)

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.panel, palette.line, 14)
        super().paintEvent(event)

    def syncStyle(self):
        self.update()
        self.setStyleSheet(
            """
            QFrame#wbPanel { background: transparent; border: none; }
            QFrame#wbPanel QLabel {
                background: transparent;
                border: none;
            }
            """
        )


class CollapsibleSideHost(QFrame):
    """可折叠右栏宿主：展开显示内容面板，折叠完全收起。

    - 折叠/展开带宽度动画（220ms InOutCubic），收起后整体隐藏，
      不留占位竖条；展开入口由页面放在左侧面板头部
    - 折叠状态由页面负责持久化（监听 collapsedChanged 写配置）
    """

    collapsedChanged = pyqtSignal(bool)

    def __init__(
        self,
        content: QWidget,
        expanded_min: int = 280,
        expanded_max: int = 330,
        parent=None,
    ):
        super().__init__(parent)
        self._content = content
        self._expanded_min = expanded_min
        self._expanded_max = expanded_max
        self._collapsed = False
        self._animation: QParallelAnimationGroup | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        content.setParent(self)
        layout.addWidget(content)

        self.setMinimumWidth(expanded_min)
        self.setMaximumWidth(expanded_max)

    def isCollapsed(self) -> bool:
        return self._collapsed

    def setCollapsed(self, collapsed: bool, animate: bool = True):
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed

        if self._animation is not None:
            self._animation.stop()
            self._animation = None

        target_min = 0 if collapsed else self._expanded_min
        target_max = 0 if collapsed else self._expanded_max
        if collapsed:
            self._content.hide()
        else:
            self.show()

        def finish():
            if self._collapsed:
                self.hide()
            else:
                self._content.show()

        if animate:
            group = QParallelAnimationGroup(self)
            for prop, end in ((b"minimumWidth", target_min), (b"maximumWidth", target_max)):
                animation = QPropertyAnimation(self, prop, self)
                animation.setDuration(220)
                animation.setEasingCurve(QEasingCurve.InOutCubic)
                animation.setEndValue(end)
                group.addAnimation(animation)
            group.finished.connect(finish)
            self._animation = group  # 持有引用避免被回收
            group.start()
        else:
            self.setMinimumWidth(target_min)
            self.setMaximumWidth(target_max)
            finish()
        self.collapsedChanged.emit(collapsed)


class PanelHeader(QFrame):
    """面板标题行。

    inline=True：放在带内边距面板顶部（默认无分隔线，underline=True 加线）；
    inline=False：独立标题栏（56 高、左右 22 内边距、底部分隔线）。
    """

    def __init__(
        self,
        title: str,
        inline: bool = True,
        bar_height: int = 56,
        underline: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("wbPanelHeader")
        self._inline = inline
        self._underline = underline

        layout = QHBoxLayout(self)
        if inline:
            layout.setContentsMargins(0, 0, 0, 14 if underline else 18)
        else:
            self.setFixedHeight(bar_height)
            layout.setContentsMargins(22, 0, 22, 0)
        layout.setSpacing(9)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("wbPanelTitle")
        apply_font(self.titleLabel, 20, 860)
        layout.addWidget(self.titleLabel)
        layout.addStretch(1)
        self._actions = layout
        self.syncStyle()

    def addRight(self, widget: QWidget):
        self._actions.addWidget(widget)

    def setTitle(self, title: str):
        self.titleLabel.setText(title)

    def setInline(self, inline: bool):
        """运行时切换形态：bar（56 高 + 底部分隔线）<-> inline（无分隔线）。"""
        if inline == self._inline:
            return
        self._inline = inline
        if inline:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.layout().setContentsMargins(22, 22, 22, 0)
        else:
            self.setMaximumHeight(56)
            self.setFixedHeight(56)
            self.layout().setContentsMargins(22, 0, 22, 0)
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        show_line = (not self._inline) or self._underline
        border = f"1px solid {palette.line_soft}" if show_line else "none"
        self.setStyleSheet(
            f"""
            QFrame#wbPanelHeader {{
                background: transparent;
                border: none;
                border-bottom: {border};
            }}
            QLabel#wbPanelTitle {{
                color: {palette.text};
                background: transparent;
                border: none;
            }}
            """
        )
