# -*- coding: utf-8 -*-
"""浮窗的"窗内设置"弹层：段控 / 开关 / 滑块，沿用浮窗的暗色玻璃配色。"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore import QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.ui.components.caption_overlay import (
    BRAND,
    C_MUTED,
    C_SUBTLE,
    make_icon,
)
from videocaptioner.ui.components.workbench import apply_font

PANEL_BG = "rgba(26,28,29,0.99)"
PANEL_BORDER = "rgba(255,255,255,0.13)"


class _Seg(QFrame):
    """分段切换控件。"""

    changed = pyqtSignal(int)

    def __init__(self, options: List[str], active: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "_Seg{background:#1f2121;border:1px solid #353938;border-radius:8px;}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self._btns: List[QPushButton] = []
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
            apply_font(b, 12, 700)
            b.clicked.connect(lambda _=False, idx=i: self._select(idx))
            lay.addWidget(b, 1)
            self._btns.append(b)
        self._select(active, emit=False)

    def set_active(self, idx: int) -> None:
        """外部设置高亮（不发 changed，用于按当前状态刷新）。"""
        if 0 <= idx < len(self._btns):
            self._select(idx, emit=False)

    def _select(self, idx: int, emit: bool = True) -> None:
        for i, b in enumerate(self._btns):
            on = i == idx
            if on:
                b.setStyleSheet(
                    f"QPushButton{{border:0;border-radius:5px;color:#061810;"
                    f"background:{BRAND};}}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton{{border:0;border-radius:5px;color:{C_MUTED};"
                    f"background:transparent;}}"
                    "QPushButton:hover{background:rgba(255,255,255,0.05);}"
                )
            b.setChecked(on)
        if emit:
            self.changed.emit(idx)


class _Toggle(QWidget):
    """药丸开关。"""

    toggled = pyqtSignal(bool)

    def __init__(self, on: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._on = on
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

    def isOn(self) -> bool:
        return self._on

    def setOn(self, on: bool) -> None:
        self._on = on
        self.update()

    def mousePressEvent(self, event) -> None:
        self._on = not self._on
        self.update()
        self.toggled.emit(self._on)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)  # type: ignore[arg-type]
        p.setBrush(QColor(BRAND) if self._on else QColor("#3a3e3d"))
        p.drawRoundedRect(self.rect(), 11, 11)
        p.setBrush(QColor("#ffffff"))
        x = 19 if self._on else 3
        p.drawEllipse(QRect(x, 3, 16, 16))


class OverlaySettingsPopover(QWidget):
    """浮窗设置弹层（点齿轮弹出，独立顶层、不被卡片裁剪）。"""

    displayChanged = pyqtSignal(str)  # bilingual/target/source
    bgStyleChanged = pyqtSignal(str)  # translucent/outline/black
    fontScaleChanged = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint  # type: ignore[arg-type]
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore[arg-type]
        self._build()

    def paintEvent(self, event) -> None:
        # 底部朝下的三角尖角，指向字幕条上的齿轮（speech-bubble 尾巴）
        card_right = self.width() - 14
        card_bottom = self.height() - 18
        cx = card_right - 40
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tri = QPolygonF([
            QPointF(cx - 7, card_bottom - 0.5),
            QPointF(cx + 7, card_bottom - 0.5),
            QPointF(cx, card_bottom + 7),
        ])
        path = QPainterPath()
        path.addPolygon(tri)
        painter.fillPath(path, QColor(26, 28, 29, 252))
        painter.end()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 18)
        card = QFrame(self)
        card.setObjectName("panel")
        card.setStyleSheet(
            f"#panel{{background:{PANEL_BG};border:1px solid {PANEL_BORDER};border-radius:14px;}}"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        self.setFixedWidth(286 + 28)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(13)

        # 标题
        head = QHBoxLayout()
        head.setSpacing(7)
        icon = QLabel()
        icon.setPixmap(make_icon("gear", BRAND, size=14).pixmap(14, 14))
        title = QLabel("字幕设置")
        apply_font(title, 12, 800)
        title.setStyleSheet("color:#f5f7f6;background:transparent;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        lay.addWidget(self._row("显示内容"))
        self._disp = _Seg(["双语", "仅译文", "仅原文"], 0)
        self._disp.changed.connect(
            lambda i: self.displayChanged.emit(["bilingual", "target", "source"][i])
        )
        lay.addWidget(self._disp)

        lay.addWidget(self._row("底色样式"))
        self._bg = _Seg(["半透明", "纯描边", "纯黑"], 0)
        self._bg.changed.connect(
            lambda i: self.bgStyleChanged.emit(["translucent", "outline", "black"][i])
        )
        lay.addWidget(self._bg)

        lay.addWidget(self._row("字号", "中", C_MUTED))
        self._font = QSlider(Qt.Horizontal)  # type: ignore[arg-type]
        self._font.setRange(0, 100)
        self._font.setValue(60)
        self._font.setFixedHeight(16)
        self._font.setStyleSheet(
            "QSlider{background:transparent;}"
            "QSlider::groove:horizontal{height:6px;border-radius:3px;background:#3a3e3d;}"
            f"QSlider::sub-page:horizontal{{height:6px;border-radius:3px;background:{BRAND};}}"
            "QSlider::add-page:horizontal{height:6px;border-radius:3px;background:#3a3e3d;}"
            "QSlider::handle:horizontal{width:14px;height:14px;margin:-4px 0;border-radius:7px;background:#fff;}"
        )
        self._font.valueChanged.connect(self.fontScaleChanged.emit)
        lay.addWidget(self._font)

    def configure(self, *, display: str, bg_style: str, font_value: int) -> None:
        """打开前用当前真实状态刷新各控件高亮（避免弹层永远显示默认值）。"""
        self._disp.set_active({"bilingual": 0, "target": 1, "source": 2}.get(display, 0))
        self._bg.set_active({"translucent": 0, "outline": 1, "black": 2}.get(bg_style, 0))
        self._font.blockSignals(True)
        self._font.setValue(font_value)
        self._font.blockSignals(False)

    def _row(self, label: str, hint: str = "", hint_color: str = C_SUBTLE) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        apply_font(lbl, 12, 700)
        lbl.setStyleSheet(f"color:{C_SUBTLE};background:transparent;")
        h.addWidget(lbl)
        h.addStretch(1)
        if hint:
            hl = QLabel(hint)
            apply_font(hl, 11, 700)
            hl.setStyleSheet(f"color:{hint_color};background:transparent;")
            h.addWidget(hl)
        return w

    def _toggle_row(self, label: str, on: bool, signal):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        apply_font(lbl, 12, 650)
        lbl.setStyleSheet("color:#f5f7f6;background:transparent;")
        toggle = _Toggle(on)
        toggle.toggled.connect(signal.emit)
        h.addWidget(lbl)
        h.addStretch(1)
        h.addWidget(toggle)
        return w, toggle

    def open_at(self, anchor_global: QPoint) -> None:
        """把弹层右下角箭头对准锚点（齿轮按钮）上方弹出，并夹取到锚点所在屏幕。"""
        self.adjustSize()
        x = anchor_global.x() - self.width() + 40
        y = anchor_global.y() - self.height() + 8
        screen = QApplication.screenAt(anchor_global)  # 多屏：用锚点所在屏幕，别飞到主屏
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left() + 4, min(x, geo.right() - self.width() - 4))
            y = max(geo.top() + 4, min(y, geo.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()
