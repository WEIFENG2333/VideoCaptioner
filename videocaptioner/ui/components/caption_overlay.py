# -*- coding: utf-8 -*-
"""程序外的实时字幕浮窗（无边框、置顶、半透明）。

两态：standard（紧凑，只显双色当前段落，适合盖视频）/ tall（时间线转录，看历史）。
颜色是浮窗自己的暗色玻璃体系，不随程序主题变化。分段由 core/realtime 负责，本模块只显示。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.ui.components.live_caption.typing import TYPE_INTERVAL_MS, next_visible
from videocaptioner.ui.components.workbench import apply_font

# ----- 暗色玻璃配色 -----
BRAND = "#28f08b"
BRAND_SOFT = "rgba(40,240,139,0.14)"
WARN = "#f5c451"
C_TEXT = "#f5f7f6"
C_MUTED = "#b9c0bd"
C_SUBTLE = "#8e9692"

CARD_BG = {
    "translucent": QColor(18, 20, 21, 224),  # 半透明（默认）
    "black": QColor(8, 9, 9, 248),  # 纯黑（不透明）
}
CARD_BORDER = QColor(255, 255, 255, 20)
CARD_BORDER_HOVER = QColor(255, 255, 255, 36)
CARD_BORDER_DRAG = QColor(40, 240, 139, 128)

# 译文恒单色（整句重译）；双色只属于原文：亮=已听准、暗=修正中。
TGT_COLOR = "rgba(245,247,246,0.92)"
SRC_BASE = "rgba(220,226,224,0.58)"
SRC_STABLE = "rgba(220,226,224,0.85)"

# ----- 模式 -----
MODE_STANDARD = "standard"
MODE_TALL = "tall"

DISPLAY_BILINGUAL = "bilingual"
DISPLAY_TARGET = "target"
DISPLAY_SOURCE = "source"

# 两态同宽：切历史时只变高、不左右抖。
_WIDTHS = {MODE_STANDARD: 540, MODE_TALL: 540}
_TGT_PX = {MODE_STANDARD: 20, MODE_TALL: 19}
_SRC_PX = {MODE_STANDARD: 15, MODE_TALL: 15}

MARGIN = 26  # 卡片四周留给阴影的透明边距
TOOLBAR_H = 40  # 工具条常驻高度
_STANDARD_H = 140  # 标准态默认/最小高度：容单句 + 工具条
_STANDARD_MAX_H = 300  # 标准态自适应上限：超出则内部滚动
_TALL_H = 340      # 转录态默认高度（用户可拖）
_STD_CHROME = TOOLBAR_H + 10  # 标准态非内容高度：工具条 + 历史区上下边距
_HIST_HMARGIN = 24            # 历史区左右边距（当前段落可用宽 = 卡宽 - 它）

# ----- 转录卡片配色（段落卡片：暗色玻璃描边；当前段落主题绿点缀） -----
ITEM_BG = QColor(255, 255, 255, 8)        # 历史段落卡片底（极淡）
ITEM_BORDER = QColor(255, 255, 255, 20)
CUR_BG = QColor(40, 240, 139, 22)         # 当前段落卡片底（主题绿淡染）
CUR_BORDER = QColor(40, 240, 139, 110)    # 当前段落描边（主题绿）
RAIL_LINE = QColor(255, 255, 255, 28)     # 时间线连线
RAIL_DOT = QColor(255, 255, 255, 40)      # 历史头像点底

# ----- 图标（描边 stroke 风格） -----
_ICON = {
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "play": '<path d="M8 5.5l11 6.5-11 6.5z"/>',
    "history": '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.4v4.8l3.4 2"/>',
    "pin": '<path d="M9 4h6l-1 6 3 3H7l3-3-1-6zM12 13v7"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4'
    "-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.4 2.7a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.5A7 7 0 0 0 5 12"
    'c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.4-2.7a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.5z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5h10"/>',
    "star": '<path d="M12 3.6l2.6 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z"/>',
    "chevron-up": '<path d="M7 14l5-5 5 5"/>',
    "resize": '<path d="M20 11v9h-9M20 18l-2 2M14 20l6-6"/>',
}


def make_icon(key: str, color: str, stroke: float = 1.9, size: int = 18) -> QIcon:
    """把描边图标渲染成 DPR 感知的 QIcon。"""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICON[key]}</svg>'
    )
    renderer = QSvgRenderer(bytearray(svg, encoding="utf-8"))
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)  # type: ignore[arg-type]
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    icon = QIcon(pm)
    return icon


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lh(escaped: str, color: str, percent: int = 150) -> str:
    """给已转义文本包一层行距+颜色的富文本（QLabel 默认行距太挤）。"""
    return f'<div style="line-height:{percent}%;color:{color}">{escaped or "&nbsp;"}</div>'


def _dual(stable: str, floaty: str, stable_color: str, floaty_color: str) -> str:
    """拼出「已听准（亮）+ 修正中（暗）」的双色富文本。"""
    out = ""
    if stable:
        out += f'<span style="color:{stable_color}">{_escape(stable)}</span>'
    if floaty:
        out += f'<span style="color:{floaty_color}">{_escape(floaty)}</span>'
    return out or '<span style="color:%s"></span>' % stable_color


@dataclass
class _Row:
    """浮窗内部维护的一条字幕显示数据。"""

    seg_id: str
    seq: int
    source_text: str
    source_stable_len: int
    target_text: str
    is_final: bool
    started_at: float  # 段落开始的真实时间（epoch 秒），显示为 HH:MM
    starred: bool = False


class ToolButton(QPushButton):
    """工具条/逐句操作的等距描边图标按钮。"""

    def __init__(
        self,
        key: str,
        size: int = 30,
        icon_size: int = 15,
        normal: str = C_MUTED,
        hover: str = C_TEXT,
        hover_bg: str = "rgba(255,255,255,0.08)",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._key = key
        self._icon_size = icon_size
        self._normal = normal
        self._hover = hover
        self._active = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setIconSize(self.iconSizeHint(icon_size))
        self.setStyleSheet(
            f"QPushButton{{border:0;border-radius:{round(size*0.26)}px;background:transparent;}}"
            f"QPushButton:hover{{background:{hover_bg};}}"
        )
        self._refresh(self._normal)

    @staticmethod
    def iconSizeHint(icon_size: int):
        from PyQt5.QtCore import QSize

        return QSize(icon_size, icon_size)

    def _refresh(self, color: str) -> None:
        self.setIcon(make_icon(self._key, color, size=self._icon_size))

    def set_key(self, key: str) -> None:
        """换图标（如暂停↔播放），保持当前 active/normal 配色。"""
        self._key = key
        self._refresh(BRAND if self._active else self._normal)

    def setActive(self, active: bool) -> None:
        self._active = active
        if active:
            self.setStyleSheet(
                f"QPushButton{{border:0;border-radius:{round(self.width()*0.26)}px;"
                f"background:{BRAND_SOFT};}}"
            )
            self._refresh(BRAND)
        else:
            self.setStyleSheet(
                f"QPushButton{{border:0;border-radius:{round(self.width()*0.26)}px;"
                f"background:transparent;}}"
                f"QPushButton:hover{{background:rgba(255,255,255,0.08);}}"
            )
            self._refresh(self._normal)

    def enterEvent(self, event) -> None:
        if not self._active:
            self._refresh(self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._active:
            self._refresh(self._normal)
        super().leaveEvent(event)


def _fmt_clock(epoch: float) -> str:
    """段落起始 epoch 秒 → HH:MM。"""
    try:
        return time.strftime("%H:%M", time.localtime(epoch)) if epoch else ""
    except Exception:
        return ""


class _TranscriptItem(QWidget):
    """时间线转录里的一条段落：左头像轨（连线 + 圆点）+ 右卡片（时间 / 原文 / 译文）。

    当前段落（``current``）主题绿高亮 + 双色；历史段落暗色玻璃描边。
    轨道、卡片底/描边全在 paintEvent 自绘（QWidget 的 QSS 圆角/描边不可靠）。
    """

    _RAIL_W = 36  # 左侧头像轨宽度

    def __init__(self, overlay: "CaptionOverlay", current: bool = False) -> None:
        super().__init__(overlay)
        self._overlay = overlay
        self._current = current
        self._first = False
        self._last = False
        self._placeholder = False  # 空态占位：不画卡片/轨道，仅一行暗字
        self._bare = False  # 标准态：无卡片底/轨道/时间，仅双色文字
        self._content_src = ""  # 算自适应高度用的完整原文
        self._content_tgt = ""  # 算自适应高度用的完整译文（按整段定高，打字时不抖）
        self._shown = 0  # 当前段原文已逐字揭示字数
        self._tgt_text = ""  # 译文逐字动画当前可见串（前缀不动、尾字原位改写、只前进）
        self._h_floor = 0  # 当前段卡高地板：动画期间只增不减，防重译变短时浮窗跳
        self._h_floor_w = -1  # 地板对应宽度；宽度变则重置
        self._last_seg = ""
        self._last_row: Optional["_Row"] = None
        self._typer = QTimer(self)
        self._typer.setInterval(TYPE_INTERVAL_MS)  # 速度集中在 typing.py
        self._typer.timeout.connect(self._advance_typing)
        self.setMouseTracking(True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 5, 2, 5)
        row.setSpacing(0)
        self._rail = QWidget(self)  # 头像轨占位（bare 时隐藏；连线/圆点在 paintEvent 自绘）
        self._rail.setFixedWidth(self._RAIL_W)
        row.addWidget(self._rail)

        self._card = QFrame(self)
        self._card.setStyleSheet("background:transparent;border:0;")
        self._cl = QVBoxLayout(self._card)
        cl = self._cl
        cl.setContentsMargins(16, 10, 16, 12)
        cl.setSpacing(5)
        self._time = QLabel(self._card)
        apply_font(self._time, 11, 700)
        self._time.setStyleSheet(f"color:{C_SUBTLE};background:transparent;")
        self._time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[operator]
        self._src = QLabel(self._card)
        self._src.setWordWrap(True)
        self._src.setTextFormat(Qt.RichText)  # type: ignore[arg-type]
        self._src.setStyleSheet("background:transparent;")
        self._tgt = QLabel(self._card)
        self._tgt.setWordWrap(True)
        self._tgt.setTextFormat(Qt.RichText)  # type: ignore[arg-type]
        self._tgt.setStyleSheet("background:transparent;")
        apply_font(self._src, 13, 500)
        apply_font(self._tgt, 16, 700)
        # 时间在 paintEvent 里画到左侧竖条；_time 仅作数据 holder（存文本/字体），永不可见。
        self._time.hide()
        cl.addWidget(self._src)
        cl.addWidget(self._tgt)
        row.addWidget(self._card, 1)

        # 卡片内容铺满浮窗会吞掉按下；装浮窗为事件过滤器，才能在文字上拖动/缩放。
        overlay._filter_item(self)

    # ----- 内容 -----

    def set_bare(self, bare: bool) -> None:
        """标准态：去掉卡片底/轨道/时间，只留双色文字（紧凑、盖视频）。"""
        self._bare = bare
        self._rail.setVisible(not bare)
        self._cl.setContentsMargins(*((8, 12, 12, 8) if bare else (16, 10, 16, 12)))
        self.update()

    def apply_fonts(self, src_px: int, tgt_px: int) -> None:
        """随浮窗形态/字号缩放刷新原文、译文字号（历史与当前段落统一）。"""
        apply_font(self._src, src_px, 500)
        apply_font(self._tgt, tgt_px, 700)
        self.update()

    def set_placeholder(self, text: str) -> None:
        """空态占位（如「监听中…」）：朴素一行暗字，无卡片底/描边/轨道。"""
        self._placeholder = True
        self._rail.setVisible(False)
        self._time.setVisible(False)
        self._src.setVisible(False)
        # 水平居中（无轨道→占满整宽）；竖直居中由 _set_centered 控制
        self._tgt.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._tgt.setText(_lh(_escape(text), C_SUBTLE, 150))
        self._tgt.setVisible(True)
        self._tgt.setMinimumHeight(0)
        self._content_src, self._content_tgt = "", text
        self._h_floor, self._h_floor_w = 0, -1  # 会话边界：卡高地板清零
        self.update()

    def set_content(self, row: "_Row", first: bool, last: bool) -> None:
        self._placeholder = False
        self._rail.setVisible(not self._bare)  # 从占位态切回内容时恢复轨道
        self._tgt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore[arg-type]  # 占位居中→内容左对齐
        self._first, self._last = first, last
        self._last_row = row
        # _time 永不显示，文本仅供 paintEvent 在左侧竖条里画。
        self._time.setText("" if self._bare else _fmt_clock(row.started_at))
        if self._current:
            if row.seg_id != self._last_seg:  # 新句：揭示/译文动画从头，卡高地板重置
                self._last_seg, self._shown, self._tgt_text = row.seg_id, 0, ""
                self._h_floor, self._h_floor_w = 0, -1
            self._shown = min(self._shown, len(row.source_text))
            if self._shown < len(row.source_text) or self._tgt_text != row.target_text:
                self._typer.start()
            else:
                self._typer.stop()
        else:
            self._tgt_text = row.target_text  # 历史段：译文整段直接显示
            self._typer.stop()

        display = self._overlay._display
        if self._current:  # 当前段落：原文双色 + 逐字揭示
            self._paint_src(row)
        else:
            self._src.setText(_lh(_escape(row.source_text), "rgba(220,226,224,0.56)", 150))
        has_tgt = bool(row.target_text) and row.target_text.strip() != row.source_text.strip()
        if has_tgt or self._tgt_text:
            self._tgt.setText(_lh(_escape(self._tgt_text), TGT_COLOR, 124))  # 渲染动画串而非整段
        else:
            self._tgt.setText("")

        show_src = display != DISPLAY_TARGET and bool(row.source_text)
        # 译文按「是否真有译文」显隐、不预留空行。固定窗高 + upsert 保留上次译文，故译文
        # 出现后不消失、不闪；被清空时仍让分叉后缀逐字删完再隐藏。
        show_tgt = display != DISPLAY_SOURCE and (has_tgt or bool(self._tgt_text))
        if not show_src and not show_tgt and row.source_text:
            show_src = True
        self._src.setVisible(show_src)
        self._tgt.setVisible(show_tgt)
        self._tgt.setMinimumHeight(0)
        self._content_src = row.source_text if show_src else ""
        # 高度按完整译文定（打字不抖）；清空/删后缀时退用可见串，避免高度先于文字塌
        self._content_tgt = (row.target_text or self._tgt_text) if show_tgt else ""
        self.update()

    def _paint_src(self, row: "_Row") -> None:
        """当前段原文按已揭示字数 _shown 渲染双色（亮=已听准、暗=修正中）。"""
        vis = row.source_text[: self._shown]
        cut = min(row.source_stable_len, len(vis))
        self._src.setText(_dual(vis[:cut], vis[cut:], SRC_STABLE, SRC_BASE))

    def _advance_typing(self) -> None:
        row = self._last_row
        if row is None or not self._current:
            self._typer.stop()
            return
        busy = False
        full = len(row.source_text)
        if self._shown < full:  # 原文逐字揭示
            remaining = full - self._shown
            # 日常 step=1；积压 >24 字时按比例加速消化，保实时
            self._shown = min(full, self._shown + (remaining // 6 if remaining > 24 else 1))
            self._paint_src(row)
            busy = True
        if self._tgt_text != row.target_text:  # 译文逐字补、只前进不缩短
            self._tgt_text = next_visible(self._tgt_text, row.target_text)
            self._tgt.setText(_lh(_escape(self._tgt_text), TGT_COLOR, 124))
            busy = True
        if not busy:
            self._typer.stop()

    def content_height(self, width: int) -> int:
        """内容在给定卡片宽度下的真实换行高度，供标准态自适应。

        用 QFontMetrics 算而非 heightForWidth（未布局返回 -1）；用内容意图字段判可见而非
        isVisible()（窗口未 show 时恒 False）。
        """
        m = self._cl.contentsMargins()
        inner = max(1, width - m.left() - m.right())
        h = m.top() + m.bottom()
        rows = []
        if self._time.text():
            rows.append((self._time.font(), self._time.text()))
        if self._content_src:
            rows.append((self._src.font(), self._content_src))
        if self._content_tgt:
            rows.append((self._tgt.font(), self._content_tgt))
        for i, (font, text) in enumerate(rows):
            rect = QFontMetrics(font).boundingRect(
                0, 0, inner, 100000, Qt.TextWordWrap, text  # type: ignore[attr-defined]
            )
            h += rect.height()
            if i:
                h += self._cl.spacing()
        # 当前段动画期间卡高只增不减（重译变短/删后缀时不塌）；宽度变则重置地板。
        if self._current:
            if width != self._h_floor_w:
                self._h_floor_w, self._h_floor = width, 0
            self._h_floor = max(self._h_floor, h)
            return self._h_floor
        return h

    def paintEvent(self, event) -> None:
        if self._placeholder or self._bare:  # 空态/标准态：不画卡片底与轨道，仅文字
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cr = self._card.geometry()
        # 卡片底 + 描边
        path = QPainterPath()
        path.addRoundedRect(cr.x() + 0.5, cr.y() + 0.5, cr.width() - 1, cr.height() - 1, 12, 12)
        p.fillPath(path, CUR_BG if self._current else ITEM_BG)
        p.setPen(QPen(CUR_BORDER if self._current else ITEM_BORDER, 1))
        p.drawPath(path)
        # 时间线：连线 + 圆点 + 圆点下方的时间（连线在时间处让开，不穿字）
        cx = self._RAIL_W // 2
        cy = cr.top() + 15
        has_time = (not self._bare) and bool(self._time.text())
        p.setPen(QPen(RAIL_LINE, 2))
        if not self._first:
            p.drawLine(cx, 0, cx, cy)
        if not self._last:
            p.drawLine(cx, cy + (26 if has_time else 8), cx, self.height())
        p.setPen(Qt.NoPen)  # type: ignore[arg-type]
        if self._current:
            p.setBrush(QColor(BRAND))
            p.drawEllipse(QPoint(cx, cy), 7, 7)
            p.setBrush(QColor(6, 24, 16))
            p.drawEllipse(QPoint(cx, cy), 3, 3)
        else:
            p.setBrush(RAIL_DOT)
            p.drawEllipse(QPoint(cx, cy), 5, 5)
        if has_time:
            p.setPen(QColor(C_SUBTLE))
            p.setFont(self._time.font())
            p.drawText(QRect(0, cy + 9, self._RAIL_W, 14),
                       Qt.AlignHCenter | Qt.AlignTop, self._time.text())  # type: ignore[operator]


class _Card(QFrame):
    """承载所有内容的圆角半透明卡片（自绘背景 + 边框）。"""

    def __init__(self, overlay: "CaptionOverlay") -> None:
        super().__init__(overlay)
        self._overlay = overlay
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(46)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)
        # 卡片不透明盖住浮窗本体，鼠标事件落不到浮窗：光标/拖拽全转交浮窗。
        # 开 tracking 才能在悬浮卡片上更新光标（边缘→缩放）。
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)  # type: ignore[attr-defined]

    def enterEvent(self, event) -> None:
        # 进入即定光标：macOS Tool 窗的静态光标要等下次移动才生效，主动 setCursor 才马上变。
        self._overlay._apply_hover_cursor(self.mapToParent(event.pos()))
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):  # type: ignore[attr-defined]
            self._overlay._apply_hover_cursor(self.mapToParent(event.pos()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self._overlay._begin_drag_or_resize(self.mapToParent(event.pos()))
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.setCursor(Qt.OpenHandCursor)  # type: ignore[attr-defined]
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 18
        path = QPainterPath()
        path.addRoundedRect(
            rect.x() + 0.5, rect.y() + 0.5, rect.width() - 1, rect.height() - 1, radius, radius
        )
        painter.fillPath(path, CARD_BG[self._overlay.bg_style])
        painter.setPen(QPen(self._overlay.current_border(), 1))
        painter.drawPath(path)


# 边缘缩放命中区（卡片坐标系，距边 px）。命中判定外延到 MARGIN 阴影区，让用户在看得见
# 的圆角边缘就能抓到缩放。
_EDGE = 14  # 中段边缘命中带（偏大，好抓）
_CORNER = 26  # 角落命中半径（整片圆角触发斜向缩放，对齐 MARGIN）
_LEFT, _RIGHT, _TOP, _BOTTOM = 1, 2, 4, 8


class CaptionOverlay(QWidget):
    """实时字幕浮窗。程序外独立顶层窗口，由控制页/线程管理生命周期。"""

    requestClose = pyqtSignal()  # 关闭 = 真停止
    pauseToggled = pyqtSignal(bool)
    pinToggled = pyqtSignal(bool)
    requestSettings = pyqtSignal()
    displayModeChanged = pyqtSignal(str)
    bgStyleChanged = pyqtSignal(str)
    fontScaleChanged = pyqtSignal(int)
    # 形态/尺寸持久化：用户切换展开/收纳或拖边缩放后，控制页存到配置，下次启动恢复
    modeChanged = pyqtSignal(str)
    sizeChanged = pyqtSignal(int, int)  # (卡片宽, 卡片高) 当前形态的用户尺寸

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint  # type: ignore[arg-type]
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore[arg-type]
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)  # type: ignore[attr-defined]  # 本体可拖 → 抓手

        self._mode = MODE_STANDARD
        self._display = DISPLAY_BILINGUAL
        self._bg_style = "translucent"
        self._hovered = False
        self._paused = False
        self._pinned = False

        self._rows: Dict[str, _Row] = {}
        self._starred: set[str] = set()
        self._hist_items: Dict[str, "_TranscriptItem"] = {}  # 历史段落卡片，按 seg_id 增量维护
        self._font_scale = 1.0
        self._settings_popover = None
        self._last_size: Optional[QSize] = None  # 仅在尺寸真变化时才 resize
        self._history_sig: tuple = ()  # 历史集合签名，变化才重建
        self._history_follow = True  # 历史是否自动跟到最新（用户上翻则停跟）
        self._interacting = False  # 拖动/缩放中（用于边框高亮）
        # 用户拖边的卡片尺寸按形态各记一份，回到该形态即恢复
        self._user_sizes: Dict[str, tuple] = {}
        self._applying_size = False  # 区分"我们改尺寸" vs "用户拖动缩放"
        self._drag_pos: Optional[QPoint] = None  # 原生移动不可用时的兜底
        # macOS 无边框 Tool 窗不支持系统级拖动/缩放（startSystemResize/Move 返回 False）→
        # 手动兜底：抓鼠标 + 按全局鼠标位移改窗几何。
        self._drag_mode: Optional[str] = None   # "move" / "resize" / None
        self._resize_edge = 0
        self._drag_origin = QPoint()            # 起手时的全局鼠标位
        self._drag_geo = QRect()                # 起手时的窗口几何

        # 合批渲染：流式 delta 很密，逐帧 resize 半透明置顶窗（含阴影重绘）会卡 → 聚合到 ~33ms。
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self._flush_layout)
        # 拖边缩放是逐像素事件，落盘去抖：停手 ~500ms 后才发 sizeChanged
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(500)
        self._persist_timer.timeout.connect(self._emit_size_changed)

        self._build()
        self._apply_mode()
        self._update_chrome()
        self._render_current()  # 立即显示占位，避免一开始是空细条

    # ----- 对外属性 -----

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def bg_style(self) -> str:
        return self._bg_style

    def current_border(self) -> QColor:
        if self._interacting:
            return CARD_BORDER_DRAG
        return CARD_BORDER_HOVER if self._hovered else CARD_BORDER

    # ----- 构建 -----

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self._card = _Card(self)
        outer.addWidget(self._card)

        col = QVBoxLayout(self._card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # 历史区（拉高 / 侧停才显示）
        self._history = QScrollArea(self._card)
        self._history.setWidgetResizable(True)
        self._history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self._history.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore[arg-type]
        self._history.setFrameShape(QFrame.NoFrame)
        self._history.setStyleSheet(
            "QScrollArea{background:transparent;border:0;}"
            "QScrollBar:vertical{width:6px;background:transparent;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.18);border-radius:3px;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
        )
        self._history_inner = QWidget()
        self._history_inner.setStyleSheet("background:transparent;")
        self._history_layout = QVBoxLayout(self._history_inner)
        self._history_layout.setContentsMargins(12, 4, 12, 6)
        self._history_layout.setSpacing(4)
        # 顶/底各一条 stretch：转录态底部 stretch=0 → 段落从下往上堆、最新一段贴底（聊天式）；
        # 标准态底部 stretch=1 → 当前单句在窗口内垂直居中。由 _set_centered 按形态切换底部因子。
        self._history_layout.addStretch(1)
        # 当前段落：常驻转录最底部的高亮卡片，随说话原地更新
        self._cur_item = _TranscriptItem(self, current=True)
        self._history_layout.addWidget(self._cur_item)
        self._history_layout.addStretch(0)
        self._history.setWidget(self._history_inner)
        col.addWidget(self._history, 1)
        # 历史自动跟随：内容增长(rangeChanged)且仍跟随就贴底；用户上翻(valueChanged 离底)停跟，
        # 滚回底部再恢复（聊天式）。
        _hsb = self._history.verticalScrollBar()
        _hsb.rangeChanged.connect(self._on_history_range)
        _hsb.valueChanged.connect(self._on_history_scroll)

        # 历史 / 当前句分隔线（仅拉高·侧停显示）
        self._sep = QFrame(self._card)
        self._sep.setFixedHeight(1)
        self._sep.setStyleSheet("background:rgba(255,255,255,0.09);border:0;")
        self._sep.hide()
        col.addWidget(self._sep)

        # 底部工具条：常驻、固定高度，hover 只显隐按钮（卡片高度不随 hover 变）。
        # 左 暂停/播放；右 历史 / 设置 / 关闭。
        self._toolbar = QWidget(self._card)
        self._toolbar.setFixedHeight(TOOLBAR_H)
        bar = QHBoxLayout(self._toolbar)
        bar.setContentsMargins(12, 5, 12, 7)
        bar.setSpacing(2)
        # 暂停指示：暂停时常显（不靠 hover），居中，显隐不挤动左右按钮。
        self._paused_label = QLabel("已暂停")
        apply_font(self._paused_label, 12, 750)
        self._paused_label.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._paused_label.setStyleSheet(f"color:{WARN};background:transparent;")
        self._paused_label.hide()
        self._btn_pause = ToolButton("pause")
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_hist = ToolButton("history")
        self._btn_hist.clicked.connect(self._toggle_history)
        self._btn_gear = ToolButton("gear")
        self._btn_gear.clicked.connect(self._show_settings)
        self._btn_close = ToolButton(
            "close", hover="#ff7a7f", hover_bg="rgba(255,122,127,0.12)"
        )
        self._btn_close.clicked.connect(self._on_close)
        bar.addWidget(self._btn_pause)
        bar.addStretch(1)
        bar.addWidget(self._paused_label)  # 居中
        bar.addStretch(1)
        for b in (self._btn_hist, self._btn_gear, self._btn_close):
            bar.addWidget(b)
        # hover 才显隐的按钮集合（暂停指示另行处理）
        self._chrome_buttons = (
            self._btn_pause, self._btn_hist, self._btn_gear, self._btn_close,
        )
        col.addWidget(self._toolbar)
        # 缩放靠拖任意边缘（见 _install_edge_filter），无右下角手柄角标。

    # ----- 模式 / 形态 -----

    def set_mode(self, mode: str) -> None:
        changed = mode != self._mode
        self._mode = mode
        self._apply_mode()
        self._update_chrome()
        self._render_current()
        if changed:
            self.modeChanged.emit(mode)  # 持久化

    def _set_centered(self, centered: bool) -> None:
        """转录区底部 stretch 因子：=1 与顶部对称 → 内容垂直居中（标准态 / 空态占位）；
        =0 → 底对齐（转录态时间线，最新一段贴底）。"""
        self._history_layout.setStretch(self._history_layout.count() - 1, 1 if centered else 0)

    def _apply_mode(self) -> None:
        mode = self._mode
        # 标准/转录共用同一滚动转录区（当前段落常驻底部，内容溢出则段内滚动，窗高固定）。
        # 标准态：当前段落 bare（无卡片/轨道，紧凑盖视频）、永不显示滚动条；转录态：完整时间线。
        self._history.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if mode == MODE_STANDARD else Qt.ScrollBarAsNeeded  # type: ignore[arg-type]
        )
        self._sep.setVisible(False)  # 转录用卡片间距分隔，不要细线
        self._cur_item.set_bare(mode == MODE_STANDARD)
        self._set_centered(mode == MODE_STANDARD)  # 标准态居中、转录态底对齐
        self._apply_item_fonts()
        self._relayout()

    def _apply_item_fonts(self) -> None:
        """把当前形态/字号缩放后的字号刷到所有转录段落卡片（当前 + 历史）。"""
        src_px = round(_SRC_PX[self._mode] * self._font_scale)
        tgt_px = round(_TGT_PX[self._mode] * self._font_scale)
        self._cur_item.apply_fonts(src_px, tgt_px)
        for w in self._hist_items.values():
            w.apply_fonts(src_px, tgt_px)

    def restore_size(self, mode: str, cw: int, ch: int) -> None:
        """从配置恢复某形态的用户拖边尺寸（>0 才生效），应在 set_mode 之后调用。"""
        if cw > 0 and ch > 0:
            self._user_sizes[mode] = (cw, ch)
            if mode == self._mode:
                self._relayout()

    def set_display_mode(self, display: str) -> None:
        # 双语/仅译文/仅原文由设置弹层切换
        self._display = display
        self._render_current()
        self.displayModeChanged.emit(display)

    def set_bg_style(self, style: str) -> None:
        if style in CARD_BG:
            self._bg_style = style
            self._card.update()
            self.bgStyleChanged.emit(style)

    # ----- 悬浮门控：静默只剩字幕，hover 才显隐按钮（卡片大小不变） -----

    def _update_chrome(self) -> None:
        show = self._hovered
        for btn in self._chrome_buttons:
            btn.setVisible(show)
        # 暂停指示常显（不靠 hover），位置已由常驻工具条预留，不改变尺寸
        self._paused_label.setVisible(self._paused)

    # ----- 布局重算 / 浮动件定位 -----

    def _card_size(self) -> tuple:
        """卡片尺寸：固定默认 / 用户拖动值，不随内容逐帧跳动（译文出现/定稿/换行都不 resize 整窗，
        内容溢出在转录区内部滚动）。标准态例外：卡高随内容自适应（见下）。"""
        mode = self._mode
        user = self._user_sizes.get(mode)
        cw = (user[0] if user else _WIDTHS.get(mode, 540))
        if mode == MODE_STANDARD and not user:
            # 标准态卡高按当前段落真实换行自适应：内容少收回 _STANDARD_H、超上限才内部滚动；
            # 译文保留不消失 + 无预留空行，故只随行数变、不逐帧抖。
            content = self._cur_item.content_height(cw - _HIST_HMARGIN)
            ch = max(_STANDARD_H, min(content + _STD_CHROME, _STANDARD_MAX_H))
            return cw, ch
        default_h = _TALL_H if mode == MODE_TALL else _STANDARD_H
        ch = user[1] if user else default_h
        return cw, ch

    def _relayout(self) -> None:
        cw, ch = self._card_size()
        # 显式固定卡片尺寸：_card.width() 立即正确，不依赖外层布局异步刷新
        if self._card.width() != cw or self._card.height() != ch:
            self._card.setFixedSize(cw, ch)
        # _cur_item 本体也吃「只增不减」地板：它无 sizeHint、高度由内部 QLabel 撑，否则重译
        # 变短时仍会缩（_card_size 的地板只护窗口外框）。
        self._cur_item.setMinimumHeight(self._cur_item.content_height(cw - _HIST_HMARGIN))
        target = QSize(cw + 2 * MARGIN, ch + 2 * MARGIN)
        # 尺寸没变就不 resize 顶层窗：逐帧 resize 半透明置顶窗 + 阴影会卡/闪。
        if target != self._last_size:
            prev = self._last_size
            old_bottom = self.y() + self.height()
            self._last_size = target
            self._applying_size = True
            self.setMinimumSize(260 + 2 * MARGIN, 56 + 2 * MARGIN)
            self.resize(target)
            # 底对齐增高：当前句+工具条留原地，向上长（不往下顶出屏幕）。首次布局(prev=None)不动。
            if prev is not None and target.height() != prev.height():
                new_y = old_bottom - target.height()
                # 多屏：夹到浮窗所在屏顶部，而非全局 0（全局 0 在主屏，会把副屏浮窗拽回主屏）。
                screen = QApplication.screenAt(self.frameGeometry().center())
                top = (screen or QApplication.primaryScreen()).availableGeometry().top()
                self.move(self.x(), max(top, new_y))
            self._applying_size = False
        self._card.layout().activate()

    # ----- 渲染当前句 / 历史 -----

    def _current_row(self) -> Optional[_Row]:
        if not self._rows:
            return None
        return max(self._rows.values(), key=lambda r: r.seq)

    def _render_current(self) -> None:
        """同步渲染：文字 + 历史 + 布局。供 set_mode/load_demo 等低频路径用。"""
        self._render_text()
        self._flush_layout()

    def _render_text(self) -> None:
        """只刷当前段落（廉价、即时）。高频 delta 走这里，历史重建交给合批。

        当前段落是转录区底部的卡片，原地更新（标准 bare、转录完整时间线）。
        """
        row = self._current_row()
        if row is None:
            self._cur_item.set_placeholder("监听中…")  # 空态朴素占位，不画卡片
            self._set_centered(True)  # 空态文字水平+垂直居中
            return
        self._set_centered(self._mode == MODE_STANDARD)  # 标准居中 / 转录底对齐
        # 转录态上方有历史卡片时不画顶端连线（first=False）；标准态恒为唯一一段
        has_hist = self._mode == MODE_TALL and any(
            r.seg_id != row.seg_id for r in self._rows.values()
        )
        self._cur_item.set_content(row, first=not has_hist, last=True)

    def _flush_layout(self) -> None:
        """合批：重建历史（带签名守卫）+ 重排（带尺寸守卫）。"""
        row = self._current_row()
        self._rebuild_history(exclude=row.seg_id if row else "")
        self._relayout()

    def _rebuild_history(self, exclude: str) -> None:
        """增量维护历史段落卡片：新段落追加到 _cur_item 之前、已有卡片就地更新，不整列重建
        （整列重建会闪、滚动乱跳）。仅转录态显示；seq 单调递增故只追加、已有卡片永不重排。
        """
        if self._mode != MODE_TALL:
            if self._hist_items:  # 退出转录态：清掉历史卡片，下次进来重建
                for w in self._hist_items.values():
                    w.setParent(None)
                    w.deleteLater()
                self._hist_items.clear()
                self._history_sig = ()
            return
        rows = sorted(
            (r for r in self._rows.values() if r.seg_id != exclude), key=lambda r: r.seq
        )
        sig = tuple((r.seg_id, r.target_text, r.is_final) for r in rows)
        if sig == self._history_sig:
            return
        self._history_sig = sig
        alive = {r.seg_id for r in rows}
        for sid in [s for s in self._hist_items if s not in alive]:  # 删掉已不在的（如 clear）
            w = self._hist_items.pop(sid)
            w.setParent(None)
            w.deleteLater()
        src_px = round(_SRC_PX[self._mode] * self._font_scale)
        tgt_px = round(_TGT_PX[self._mode] * self._font_scale)
        for i, r in enumerate(rows):
            item = self._hist_items.get(r.seg_id)
            if item is None:  # 新段落：建卡片插到 _cur_item 之前，永不重排已有卡片
                item = _TranscriptItem(self, current=False)
                item.apply_fonts(src_px, tgt_px)
                self._hist_items[r.seg_id] = item
                # 插到 [_cur_item, 底部 stretch] 之前 = count-2
                self._history_layout.insertWidget(self._history_layout.count() - 2, item)
            item.set_content(r, first=(i == 0), last=False)

    def _on_history_scroll(self, value: int) -> None:
        # 用户拖到底=跟随；上翻=停跟（让用户安心回看，不被新内容拽走）
        sb = self._history.verticalScrollBar()
        self._history_follow = value >= sb.maximum() - 8

    def _on_history_range(self, _min: int, maximum: int) -> None:
        # 历史增长时若仍在跟随，自动滚到最新一行
        if self._history_follow:
            self._history.verticalScrollBar().setValue(maximum)

    # ----- 公开 API -----

    def upsert_caption(self, entry) -> None:
        """按 seg_id 增量更新一条字幕（来自 CaptionEntry）。

        只更新数据 + 触发合批渲染：流式 delta 很密，逐帧渲染会卡，聚合到定时器一次。
        """
        # 防闪：当前帧 target 为空就保留上次译文，等新译文翻完再覆盖（避免译文行空↔有闪烁）。
        target = entry.target_text
        if not target:
            prev = self._rows.get(entry.seg_id)
            if prev is not None and prev.target_text:
                target = prev.target_text
        self._rows[entry.seg_id] = _Row(
            seg_id=entry.seg_id,
            seq=entry.seq,
            source_text=entry.source_text,
            source_stable_len=entry.source_stable_len,
            target_text=target,
            is_final=entry.is_final,
            started_at=entry.started_at,
            starred=entry.seg_id in self._starred,
        )
        self._render_text()  # 文字即时上屏（廉价）；历史/滚动/卡高等较重布局合批到 ~33ms 一次
        if not self._render_timer.isActive():
            self._render_timer.start()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        # 暂停→播放三角（点击=恢复）+ 主题绿高亮；运行→暂停两竖条。用图标切换表达状态。
        self._btn_pause.set_key("play" if paused else "pause")
        self._btn_pause.setActive(paused)
        self._update_chrome()

    def clear(self) -> None:
        self._rows.clear()
        self._render_current()

    # ----- 工具条动作 -----

    def _toggle_pause(self) -> None:
        self.set_paused(not self._paused)
        self.pauseToggled.emit(self._paused)

    def _toggle_history(self) -> None:
        self.set_mode(MODE_STANDARD if self._mode == MODE_TALL else MODE_TALL)

    def set_pinned(self, pinned: bool) -> None:
        """开/关鼠标穿透（由控制页的开关驱动；穿透后整窗点击失效）。"""
        self._pinned = pinned
        self.setAttribute(Qt.WA_TransparentForMouseEvents, pinned)  # type: ignore[arg-type]
        self.pinToggled.emit(pinned)

    def _show_settings(self) -> None:
        if self._settings_popover is None:
            from videocaptioner.ui.components.caption_overlay_settings import (
                OverlaySettingsPopover,
            )

            pop = OverlaySettingsPopover()
            pop.displayChanged.connect(self.set_display_mode)
            pop.bgStyleChanged.connect(self.set_bg_style)
            pop.fontScaleChanged.connect(self._on_font_scale)
            self._settings_popover = pop
        # 打开前用当前状态刷新弹层各控件高亮（否则永远显示默认值）
        font_value = round((self._font_scale - 0.8) / 0.6 * 100)
        self._settings_popover.configure(
            display=self._display,
            bg_style=self._bg_style,
            font_value=max(0, min(100, font_value)),
        )
        anchor = self._btn_gear.mapToGlobal(QPoint(self._btn_gear.width() // 2, 0))
        self._settings_popover.open_at(anchor)
        self.requestSettings.emit()

    def apply_font_scale(self, value: int) -> None:
        # 0~100 → 0.8x ~ 1.4x。供控制页从配置初始化（不回写）
        self._font_scale = 0.8 + value / 100.0 * 0.6
        self._apply_mode()
        self._render_current()

    def _on_font_scale(self, value: int) -> None:
        self.apply_font_scale(value)
        self.fontScaleChanged.emit(value)  # 持久化

    def _on_close(self) -> None:
        self.requestClose.emit()
        self.hide()

    # ----- 悬浮 / 拖动 / 缩放 -----

    def _refresh_hover(self) -> None:
        """按全局指针是否落在 frameGeometry 内更新 hover。

        不用 Qt 的 enter/leave：指针越过子控件时会在父窗口上误触发 leave → 工具条按钮忽隐忽现。
        """
        from PyQt5.QtGui import QCursor

        hovered = self.frameGeometry().contains(QCursor.pos())
        if hovered != self._hovered:
            self._hovered = hovered
            self._update_chrome()
            self._card.update()  # 边框 hover 高亮跟随

    def enterEvent(self, event) -> None:
        self._refresh_hover()
        self._apply_hover_cursor(event.pos())  # 进入即定光标（别等移动）
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._refresh_hover()  # 真移出窗口才隐藏；越过子控件不算离开
        super().leaveEvent(event)

    def _edge_at(self, pos: QPoint) -> int:
        r = self._card.geometry()
        # 命中区外延到阴影区：鼠标常落在卡片框外的圆角阴影里，外延后那里也算命中，才好抓。
        if not r.adjusted(-_CORNER, -_CORNER, _CORNER, _CORNER).contains(pos):
            return 0
        dl = abs(pos.x() - r.left())
        dr = abs(pos.x() - r.right())
        dt = abs(pos.y() - r.top())
        db = abs(pos.y() - r.bottom())
        edge = 0
        if dl <= _EDGE:
            edge |= _LEFT
        if dr <= _EDGE:
            edge |= _RIGHT
        if dt <= _EDGE:
            edge |= _TOP
        if db <= _EDGE:
            edge |= _BOTTOM
        near_l, near_r = dl <= _CORNER, dr <= _CORNER
        near_t, near_b = dt <= _CORNER, db <= _CORNER
        if near_t and near_l:  # 靠近某角则整片触发斜向缩放（补圆角中段判定抓不到）
            edge = _TOP | _LEFT
        elif near_t and near_r:
            edge = _TOP | _RIGHT
        elif near_b and near_l:
            edge = _BOTTOM | _LEFT
        elif near_b and near_r:
            edge = _BOTTOM | _RIGHT
        return edge

    def _cursor_for(self, edge: int):
        if edge in (_LEFT | _TOP, _RIGHT | _BOTTOM):
            return Qt.SizeFDiagCursor  # type: ignore[attr-defined]
        if edge in (_RIGHT | _TOP, _LEFT | _BOTTOM):
            return Qt.SizeBDiagCursor  # type: ignore[attr-defined]
        if edge & (_LEFT | _RIGHT):
            return Qt.SizeHorCursor  # type: ignore[attr-defined]
        if edge & (_TOP | _BOTTOM):
            return Qt.SizeVerCursor  # type: ignore[attr-defined]
        return Qt.OpenHandCursor  # type: ignore[attr-defined]  # 本体可拖 → 抓手

    def _qt_edges(self, edge: int):
        """把内部边缘位标志映射成 Qt.Edges（位值不同，必须显式映射）。"""
        qe = Qt.Edges()  # type: ignore[attr-defined]
        if edge & _LEFT:
            qe |= Qt.LeftEdge  # type: ignore[attr-defined]
        if edge & _RIGHT:
            qe |= Qt.RightEdge  # type: ignore[attr-defined]
        if edge & _TOP:
            qe |= Qt.TopEdge  # type: ignore[attr-defined]
        if edge & _BOTTOM:
            qe |= Qt.BottomEdge  # type: ignore[attr-defined]
        return qe

    def _apply_hover_cursor(self, pos) -> None:
        """悬浮时按位置设光标：贴边→缩放，本体→抓手。浮窗本体与卡片共用。"""
        cursor = self._cursor_for(self._edge_at(pos))
        self.setCursor(cursor)
        self._card.setCursor(cursor)

    def _begin_drag_or_resize(self, pos) -> None:
        """按下：贴边→缩放，本体→拖动整窗。优先系统级 ``startSystemResize/Move``（Wayland 必须用，
        客户端不能自己 setGeometry）；macOS 无边框 Tool 窗返回 False → 手动兜底（grabMouse + 改窗
        几何）；``hasattr`` 守卫让 Qt<5.15 也安全降级。
        """
        from PyQt5.QtGui import QCursor

        handle = self.windowHandle()
        edge = self._edge_at(pos)
        if edge:
            if (handle is not None and hasattr(handle, "startSystemResize")
                    and handle.startSystemResize(self._qt_edges(edge))):
                return  # 系统级缩放可用（Win/Linux）
            self._drag_mode = "resize"
            self._resize_edge = edge
        else:
            self._card.setCursor(Qt.ClosedHandCursor)  # type: ignore[attr-defined]
            if (handle is not None and hasattr(handle, "startSystemMove")
                    and handle.startSystemMove()):
                return  # 系统级移动可用（Win/Linux）
            self._drag_mode = "move"
        # 手动兜底：记录起点，抓鼠标（按下可能落在子件上，抓住后 move/release 都来本窗）
        self._drag_origin = QCursor.pos()
        self._drag_geo = QRect(self.geometry())
        self.grabMouse()

    def _apply_manual_resize(self, delta: QPoint) -> None:
        """手动缩放：按起手边缘 + 全局鼠标位移改窗几何，各边各自夹住最小尺寸。"""
        geo = QRect(self._drag_geo)
        e = self._resize_edge
        minw = 260 + 2 * MARGIN
        minh = 56 + 2 * MARGIN
        if e & _LEFT:
            geo.setLeft(min(geo.left() + delta.x(), geo.right() - minw))
        if e & _RIGHT:
            geo.setRight(max(geo.right() + delta.x(), geo.left() + minw))
        if e & _TOP:
            geo.setTop(min(geo.top() + delta.y(), geo.bottom() - minh))
        if e & _BOTTOM:
            geo.setBottom(max(geo.bottom() + delta.y(), geo.top() + minh))
        self.setGeometry(geo)

    def mousePressEvent(self, event) -> None:
        # 点在按钮/可交互子件上不会走到这里（子件已消费）；卡片本体的点击由 _Card 转交到此。
        if event.button() != Qt.LeftButton:  # type: ignore[attr-defined]
            return super().mousePressEvent(event)
        self._begin_drag_or_resize(event.pos())

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is not None:
            from PyQt5.QtGui import QCursor

            delta = QCursor.pos() - self._drag_origin
            if self._drag_mode == "move":
                self.move(self._drag_geo.topLeft() + delta)
            else:
                self._apply_manual_resize(delta)
            return
        if not (event.buttons() & Qt.LeftButton):  # type: ignore[attr-defined]
            self._apply_hover_cursor(event.pos())

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode is not None:  # 结束手动拖动/缩放：放鼠标、复位光标
            self._drag_mode = None
            self._resize_edge = 0
            self.releaseMouse()
            self._apply_hover_cursor(event.pos())
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 跳过「我们自己改的尺寸」：_applying_size 接同步投递；size==_last_size 接 Qt 异步排队的
        # 晚到 resizeEvent（否则误记成用户拖动，把自适应高度冻死）。
        if self._applying_size or self.size() == self._last_size:
            return
        # 用户原生拖边缩放：按形态记住卡片尺寸（切形态不丢），按新宽度重排（高度交给合批）
        cw = max(1, self.width() - 2 * MARGIN)
        ch = max(1, self.height() - 2 * MARGIN)
        self._user_sizes[self._mode] = (cw, ch)
        self._last_size = self.size()
        if not self._render_timer.isActive():
            self._render_timer.start()
        self._persist_timer.start()  # 去抖后落盘

    def _emit_size_changed(self) -> None:
        """拖边缩放停手后发尺寸持久化信号（当前形态的卡片宽高）。"""
        user = self._user_sizes.get(self._mode)
        if user is not None:
            self.sizeChanged.emit(user[0], user[1])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._configure_native_window()
        self._install_edge_filter()

    def _configure_native_window(self) -> None:
        """macOS 原生窗口微调（仅 cocoa），让浮窗像系统级 HUD（切 App/跨屏/跨 Space 常显）：

        1. ``setHasShadow_(False)``：已自绘阴影，系统那层在深色桌面像灰玻璃块。
        2. ``setHidesOnDeactivate_(False)``：``Qt.Tool`` 映射的 NSPanel 默认失焦即隐——「点另一块
           屏浮窗整个消失」的根因，必须关掉。
        3. ``setLevel_(3 = NSFloatingWindowLevel)``：浮在普通窗口之上，不挡菜单栏/系统弹窗。
        4. ``collectionBehavior = AllSpaces|Stationary|FullScreenAux``：每个 Space 都显、切 Space
           不被甩走、可浮在全屏 App 上、停在用户摆放位置不自动搬屏。
        """
        if sys.platform != "darwin":
            return

        if QApplication.platformName() != "cocoa":
            return  # offscreen/测试平台无真正的 NSView/NSWindow，碰 winId 会崩
        try:
            import objc  # PyObjC，macOS 自带

            view = objc.objc_object(c_void_p=int(self.winId()))
            win = view.window() if view is not None else None
            if win is not None:
                win.setHasShadow_(False)
                win.invalidateShadow()
                win.setHidesOnDeactivate_(False)
                win.setLevel_(3)  # NSFloatingWindowLevel
                win.setCollectionBehavior_(1 | 16 | 256)  # AllSpaces | Stationary | FullScreenAux
        except Exception:
            pass  # 拿不到原生窗口不影响功能

    def _install_edge_filter(self) -> None:
        """给铺满卡片的子件装事件过滤器（仅一次），否则按在子件上只触发其自身行为（滚动/选中），
        既拖不动也缩放不了。"""
        if getattr(self, "_edge_filter_installed", False):
            return
        self._edge_filter_installed = True
        targets = [
            self._card, self._history, self._history.viewport(), self._history_inner,
            self._sep, self._toolbar,
        ]
        for w in targets:
            if w is not None:
                w.setMouseTracking(True)
                w.installEventFilter(self)

    def _filter_item(self, item: "_TranscriptItem") -> None:
        """给段落卡片内容（卡片底/文字/时间/轨道）装事件过滤器，让按在文字上也能拖窗/缩放。"""
        for w in (item, item._card, item._rail, item._time, item._src, item._tgt):
            w.setMouseTracking(True)
            w.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        # 子件的左键按下统一交给浮窗：贴边→缩放，本体→拖动整窗（纯点击无副作用）。
        # 这样在转录文字/滚动区/卡片空白上都能拖动与缩放；未装过滤器的按钮点击照常生效。
        etype = event.type()
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self._begin_drag_or_resize(obj.mapTo(self, event.pos()))
            return True  # 吃掉，不让子件处理
        if etype == QEvent.MouseMove and not (event.buttons() & Qt.LeftButton):  # type: ignore[attr-defined]
            self.setCursor(self._cursor_for(self._edge_at(obj.mapTo(self, event.pos()))))
            self._refresh_hover()  # 在子控件上移动也算悬浮，保住工具条按钮显隐稳定
        elif etype in (QEvent.Enter, QEvent.Leave):  # type: ignore[attr-defined]
            self._refresh_hover()  # 进出子控件 → 按真实位置重判 hover，不被误隐
        return super().eventFilter(obj, event)

    # ----- 演示数据（截图 / 预览用） -----

    def load_demo(self, state: str) -> None:
        """复刻各态内容，供离屏截图与对比。state ∈ rest/hover/pause/tall。"""
        self._rows.clear()
        self._starred.clear()
        now = time.time()
        # 演示用中性自有文案
        history = [
            ("Hello everyone, welcome back.", "大家好，欢迎回来。", now - 49),
            ("Let's quickly review what we discussed last week.", "我们先快速回顾上周聊过的几个问题。", now - 28),
            ("The prototype got really positive feedback.", "原型得到了非常正面的反馈。", now - 15),
        ]
        seq = 0
        if state == "tall":
            for src, tgt, t in history:
                sid = f"demo#{seq}"
                self._rows[sid] = _Row(sid, seq, src, len(src), tgt, True, t)
                seq += 1
        # 当前段落
        if state == "pause":
            src = "weekends like this are relaxing."
            tgt = "这样的周末真让人放松。"
            slen = len(src)
            self._paused = True
            self._btn_pause.set_key("play")  # 暂停态显示播放三角
            self._btn_pause.setActive(True)
        else:
            src = "So the main goal for this sprint is to ship the live caption overlay."
            tgt = "这个迭代的主要目标是交付实时字幕浮窗，同时让记录页更好回看。"
            slen = len("So the main goal for this sprint is to ship the ")
        cur = f"demo#{seq}"
        self._rows[cur] = _Row(cur, seq, src, slen, tgt, state == "pause", now)

        mode = {
            "rest": MODE_STANDARD, "hover": MODE_STANDARD, "pause": MODE_STANDARD,
            "tall": MODE_TALL,
        }.get(state, MODE_STANDARD)
        self._hovered = state in ("hover", "tall", "pause")
        self._mode = mode
        self._apply_mode()
        self._update_chrome()
        self._render_current()

    def card_grab(self) -> QPixmap:
        """抓卡片本体（不含透明边距/阴影），与 HTML .cap 截图直接对比。"""
        return self._card.grab()
