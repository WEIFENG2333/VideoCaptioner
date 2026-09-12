# coding:utf-8
"""第一方取色器（替代系统 QColorDialog）。

竖向布局：SV 取色方块 + 色相条 +（可选）透明度条 + 预览/HEX + 常用字幕色 + 最近使用。
与 workbench 设计语言一致，支持带 alpha 的颜色，最近使用持久化到配置。

入口：``ColorPickerDialog.get_color(initial, parent, alpha, title)``，用法对齐
``QColorDialog.getColor``，取消返回 None。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import AppLineEdit, apply_font
from videocaptioner.ui.i18n import tr

# 常用字幕色：取自真实字幕实践——白是最常见默认色、黑用于描边、经典电影黄(#FFFF00)，
# 加上 CEA-608/708 闭合字幕标准色（黄/青/绿/蓝/红/品红）与短视频常见柔色，而非泛色盘。
SUBTITLE_PRESET_COLORS: tuple[str, ...] = (
    # 基础白黑 + 经典字幕黄（最常用）
    "#ffffff", "#f2f2f2", "#000000", "#1a1a1a", "#ffff00", "#ffde00", "#ffd000", "#ffe36b",
    # 暖色强调（CC 红 + 橙粉，短视频常用）
    "#ffa500", "#ff7a45", "#ff4d4d", "#ff0000", "#ff69b4", "#ff4da6", "#ff00ff", "#b388ff",
    # 冷色（CC 青/绿/蓝标准色 + 柔变体）
    "#00ffff", "#2ee6a6", "#00ff00", "#08ec88", "#00bfff", "#1e90ff", "#0000ff", "#6bd0ff",
)
_RECENT_CAP = 8


def _paint_checker(painter: QPainter, rect: QRectF, cell: int = 6):
    """棋盘格背景，用于表现半透明颜色。"""
    painter.fillRect(rect, QColor("#c9c9c9"))
    painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
    painter.setBrush(QColor("#8f8f8f"))
    rows = int(rect.height() // cell) + 1
    cols = int(rect.width() // cell) + 1
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2:
                painter.drawRect(
                    QRectF(rect.left() + c * cell, rect.top() + r * cell, cell, cell)
                )


class _SVPlane(QWidget):
    """饱和度(横)/明度(纵)取色方块。"""

    changed = pyqtSignal(float, float)  # sat, val

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(168)
        self.setCursor(Qt.CrossCursor)  # type: ignore[arg-type]
        self._hue = 0.13
        self._sat = 0.5
        self._val = 0.9

    def setHue(self, hue: float):
        self._hue = max(0.0, hue)
        self.update()

    def setSV(self, sat: float, val: float):
        self._sat, self._val = sat, val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor.fromHsvF(self._hue, 1, 1))
        sat_grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        sat_grad.setColorAt(0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), QBrush(sat_grad))
        val_grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        val_grad.setColorAt(0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1, QColor(0, 0, 0, 255))
        painter.fillRect(self.rect(), QBrush(val_grad))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawPath(path)
        # 手柄
        x = rect.left() + self._sat * rect.width()
        y = rect.top() + (1 - self._val) * rect.height()
        painter.setBrush(QColor.fromHsvF(self._hue, self._sat, self._val))
        painter.setPen(QPen(QColor(255, 255, 255, 235), 2))
        painter.drawEllipse(QPointF(x, y), 8, 8)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawEllipse(QPointF(x, y), 9, 9)

    def _set_from_pos(self, pos):
        w, h = max(1, self.width()), max(1, self.height())
        self._sat = min(1.0, max(0.0, pos.x() / w))
        self._val = min(1.0, max(0.0, 1 - pos.y() / h))
        self.update()
        self.changed.emit(self._sat, self._val)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self._set_from_pos(event.pos())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:  # type: ignore[attr-defined]
            self._set_from_pos(event.pos())


class _Bar(QWidget):
    """横向条基类（色相/透明度），共用手柄绘制与拖拽。"""

    changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self._value = 0.0

    def setValue(self, value: float):
        self._value = min(1.0, max(0.0, value))
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    def _paint_knob(self, painter: QPainter, rect: QRectF):
        x = rect.left() + self._value * rect.width()
        x = min(rect.right() - 4, max(rect.left() + 4, x))
        knob = QRectF(x - 5, rect.top() - 2, 10, rect.height() + 4)
        kpath = QPainterPath()
        kpath.addRoundedRect(knob, 4, 4)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(kpath)

    def _set_from_pos(self, pos):
        w = max(1, self.width())
        self._value = min(1.0, max(0.0, pos.x() / w))
        self.update()
        self.changed.emit(self._value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self._set_from_pos(event.pos())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:  # type: ignore[attr-defined]
            self._set_from_pos(event.pos())


class _HueBar(_Bar):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self._track_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setClipPath(path)
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsvF(i / 6, 1, 1))
        painter.fillRect(self.rect(), QBrush(grad))
        painter.setClipping(False)
        self._paint_knob(painter, rect)


class _AlphaBar(_Bar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor("#ffe36b")

    def setColor(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self._track_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setClipPath(path)
        _paint_checker(painter, rect)
        c0 = QColor(self._color)
        c0.setAlpha(0)
        c1 = QColor(self._color)
        c1.setAlpha(255)
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad.setColorAt(0, c0)
        grad.setColorAt(1, c1)
        painter.fillRect(self.rect(), QBrush(grad))
        painter.setClipping(False)
        self._paint_knob(painter, rect)


class _Swatch(QWidget):
    """可点选色块（常用 / 最近 / 预览）。color=None 表示空位。"""

    clicked = pyqtSignal(QColor)

    def __init__(self, color: Optional[QColor] = None, height: int = 26, parent=None):
        super().__init__(parent)
        self._color = QColor(color) if color is not None else None
        self._selected = False
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(
            Qt.PointingHandCursor if self._color is not None else Qt.ArrowCursor  # type: ignore[arg-type]
        )

    def setColor(self, color: Optional[QColor]):
        self._color = QColor(color) if color is not None else None
        self.setCursor(
            Qt.PointingHandCursor if self._color is not None else Qt.ArrowCursor  # type: ignore[arg-type]
        )
        self.update()

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = app_palette()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        if self._color is None:
            # 稀疏虚线：用自定义点距，看起来像「空槽」而非实线
            pen = QPen(QColor(palette.subtle), 1.2)
            pen.setStyle(Qt.CustomDashLine)  # type: ignore[attr-defined]
            pen.setDashPattern([1.5, 3.5])
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
            painter.drawPath(path)
            return
        painter.setClipPath(path)
        if self._color.alpha() < 255:
            _paint_checker(painter, rect)
        painter.fillPath(path, self._color)
        painter.setClipping(False)
        ring = QColor(palette.accent) if self._selected else QColor(255, 255, 255, 32)
        painter.setPen(QPen(ring, 2 if self._selected else 1))
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if self._color is not None and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit(QColor(self._color))
            event.accept()


class _PreviewSwatch(QWidget):
    """当前颜色预览（带棋盘格表现透明度）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 40)
        self._color = QColor("#ffe36b")

    def setColor(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 11, 11)
        painter.setClipPath(path)
        if self._color.alpha() < 255:
            _paint_checker(painter, rect)
        painter.fillPath(path, self._color)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
        painter.drawPath(path)


class _ClickLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()


class ColorPickerDialog(AppDialog):
    """第一方取色器弹窗。"""

    def __init__(
        self,
        initial: QColor | str | None = None,
        *,
        alpha: bool = False,
        title: str | None = None,
        parent=None,
    ):
        super().__init__(
            title if title is not None else tr("colorpicker.title"),
            icon=AppIcon.PALETTE,
            parent=parent,
            width=420,
        )
        self._alpha_enabled = alpha
        color = QColor(initial) if initial is not None else QColor("#ffffff")
        if not color.isValid():
            color = QColor("#ffffff")
        h, s, v, a = color.getHsvF()
        self._hue = h if h >= 0 else 0.0
        self._sat, self._val = s, v
        self._alpha = a if alpha else 1.0
        self._preset_swatches: List[_Swatch] = []
        self._recent_swatches: List[_Swatch] = []

        self._build()
        self._refresh()

        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(tr("common.cancel"))
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(tr("common.ok"), kind="accent")
        self.confirmButton.clicked.connect(lambda: self.done(1))

    # ----------------------------------------------------------------- build

    def _build(self):
        self.svPlane = _SVPlane(self.widget)
        self.svPlane.changed.connect(self._on_sv)
        self.bodyLayout.addWidget(self.svPlane)

        self.hueBar = _HueBar(self.widget)
        self.hueBar.changed.connect(self._on_hue)
        self.bodyLayout.addWidget(self.hueBar)

        self.alphaBar = _AlphaBar(self.widget)
        self.alphaBar.changed.connect(self._on_alpha)
        self.alphaBar.setVisible(self._alpha_enabled)
        self.bodyLayout.addWidget(self.alphaBar)

        # 预览 + HEX
        row = QHBoxLayout()
        row.setSpacing(11)
        self.preview = _PreviewSwatch(self.widget)
        row.addWidget(self.preview)
        self.hexEdit = AppLineEdit(parent=self.widget)
        self.hexEdit.setMaxLength(7)
        self.hexEdit.setClearButtonEnabled(False)
        self.hexEdit.textEdited.connect(self._on_hex_edited)
        row.addWidget(self.hexEdit, 1)
        self.alphaLabel = QLabel(self.widget)
        apply_font(self.alphaLabel, 13, 800)
        self.alphaLabel.setVisible(self._alpha_enabled)
        row.addWidget(self.alphaLabel)
        self.bodyLayout.addLayout(row)

        self.bodyLayout.addLayout(self._section(tr("colorpicker.section.presets")))
        self.bodyLayout.addLayout(self._preset_grid())

        recent_head = self._section(tr("colorpicker.section.recent"))
        self.clearRecent = _ClickLabel(tr("colorpicker.clear"))
        apply_font(self.clearRecent, 12, 760)
        self.clearRecent.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.clearRecent.clicked.connect(self._clear_recents)
        recent_head.addWidget(self.clearRecent)
        self.bodyLayout.addLayout(recent_head)
        self.bodyLayout.addLayout(self._recent_grid())

        self._apply_style()

    def _section(self, text: str) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setContentsMargins(2, 4, 2, 0)
        label = QLabel(text, self.widget)
        label.setObjectName("cpSectionLabel")
        apply_font(label, 12, 820)
        head.addWidget(label)
        head.addStretch(1)
        return head

    def _preset_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, hex_color in enumerate(SUBTITLE_PRESET_COLORS):
            sw = _Swatch(QColor(hex_color), parent=self.widget)
            sw.clicked.connect(self._on_pick)
            grid.addWidget(sw, i // 8, i % 8)
            self._preset_swatches.append(sw)
        return grid

    def _recent_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        recents = self._load_recents()
        for i in range(_RECENT_CAP):
            color = recents[i] if i < len(recents) else None
            sw = _Swatch(color, parent=self.widget)
            sw.clicked.connect(self._on_pick)
            grid.addWidget(sw, 0, i)
            self._recent_swatches.append(sw)
        return grid

    # --------------------------------------------------------------- signals

    def _on_sv(self, sat: float, val: float):
        self._sat, self._val = sat, val
        self._refresh()

    def _on_hue(self, hue: float):
        self._hue = hue
        self._refresh()

    def _on_alpha(self, alpha: float):
        self._alpha = alpha
        self._refresh()

    def _on_hex_edited(self, text: str):
        raw = text.strip().lstrip("#")
        if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
            color = QColor(f"#{raw}")
            h, s, v, _ = color.getHsvF()
            if h >= 0:
                self._hue = h
            self._sat, self._val = s, v
            self._refresh(skip_hex=True)

    def _on_pick(self, color: QColor):
        h, s, v, a = color.getHsvF()
        if h >= 0:
            self._hue = h
        self._sat, self._val = s, v
        if self._alpha_enabled:
            self._alpha = a
        self._refresh()

    # ----------------------------------------------------------------- sync

    def selectedColor(self) -> QColor:
        return QColor.fromHsvF(
            max(0.0, self._hue), self._sat, self._val, self._alpha if self._alpha_enabled else 1.0
        )

    def _refresh(self, skip_hex: bool = False):
        color = self.selectedColor()
        rgb = QColor.fromHsvF(max(0.0, self._hue), self._sat, self._val)
        self.svPlane.setHue(self._hue)
        self.svPlane.setSV(self._sat, self._val)
        self.hueBar.setValue(self._hue)
        self.alphaBar.setColor(rgb)
        self.alphaBar.setValue(self._alpha)
        self.preview.setColor(color)
        # 只在「来自 hex 输入框本身的编辑」时跳过回填，否则一旦 hex 框获得焦点，
        # 拖动取色方块/色相/透明度时 hex 不刷新 → 看起来「色值没变」。
        if not skip_hex:
            if self.hexEdit.hasFocus():
                self.hexEdit.clearFocus()
            self.hexEdit.setText(rgb.name(QColor.HexRgb)[1:].upper())
        self.alphaLabel.setText(f"{round(self._alpha * 100)}%")
        self._highlight(color)

    def _highlight(self, color: QColor):
        target = color.name(QColor.HexArgb)
        for sw in self._preset_swatches + self._recent_swatches:
            sw_color = sw._color
            sw.setSelected(sw_color is not None and sw_color.name(QColor.HexArgb) == target)

    # --------------------------------------------------------------- recents

    @staticmethod
    def _load_recents() -> List[QColor]:
        colors: List[QColor] = []
        for item in cfg.recent_colors.value or []:
            c = QColor(str(item))
            if c.isValid():
                colors.append(c)
        return colors

    def _clear_recents(self):
        cfg.set(cfg.recent_colors, [])
        for sw in self._recent_swatches:
            sw.setColor(None)

    @staticmethod
    def push_recent(color: QColor):
        if not color.isValid():
            return
        key = color.name(QColor.HexArgb)
        existing = [str(x) for x in (cfg.recent_colors.value or [])]
        existing = [x for x in existing if x.lower() != key.lower()]
        existing.insert(0, key)
        cfg.set(cfg.recent_colors, existing[:_RECENT_CAP])

    # ----------------------------------------------------------------- style

    def _apply_style(self):
        palette = app_palette()
        self.widget.setStyleSheet(
            self.widget.styleSheet()
            + f"\nQLabel#cpSectionLabel {{ color: {palette.muted}; background: transparent; }}"
        )
        self.alphaLabel.setStyleSheet(f"color: {palette.muted}; background: transparent;")
        self.clearRecent.setStyleSheet(
            f"color: {rgba(palette.accent, 0.92)}; background: transparent;"
        )

    # ------------------------------------------------------------- entry API

    @staticmethod
    def get_color(
        initial: QColor | str | None = None,
        parent=None,
        alpha: bool = False,
        title: str | None = None,
    ) -> Optional[QColor]:
        """打开取色器，返回选中颜色（取消返回 None）。对齐 QColorDialog.getColor。"""
        dialog = ColorPickerDialog(initial, alpha=alpha, title=title, parent=parent)
        if dialog.exec():
            color = dialog.selectedColor()
            ColorPickerDialog.push_recent(color)
            return color
        return None
