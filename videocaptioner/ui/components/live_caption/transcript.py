# -*- coding: utf-8 -*-
"""转录时间线：左轨（声波圆点 + 时间）+ 右气泡（原文 / 译文）。

实时会话与历史详情共用：实时态末条为「当前句」（绿描边 + 未定稿尾巴变暗），详情态高亮播放中的一条。
显示模式双语 / 原文 / 译文，右键逐句复制。颜色走 app_palette。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.live_caption.typing import TYPE_INTERVAL_MS, next_visible
from videocaptioner.ui.components.workbench import apply_font

DISPLAY_BILINGUAL = "bilingual"
DISPLAY_SOURCE = "source"
DISPLAY_TARGET = "target"

_RAIL_W = 54
_DOT = 36


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _VoiceDot(QWidget):
    """头像轨上的声波圆点：圆形描边 + 4 根主题绿声波条。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(_DOT, _DOT)
        self._tone = "idle"  # idle / live / playing
        self._bars = (8, 14, 18, 11)

    def set_tone(self, tone: str) -> None:
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._tone == "live":
            bg, border = rgba(p.accent, 0.14), rgba(p.accent, 0.5)
        elif self._tone == "playing":
            bg, border = rgba(p.accent, 0.11), rgba(p.accent, 0.44)
        else:
            bg, border = rgba(p.accent, 0.10), rgba(p.accent, 0.32)
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QPainterPath, QPen

        path = QPainterPath()
        path.addEllipse(QRectF(self.rect().adjusted(1, 1, -1, -1)))
        painter.fillPath(path, QColor(*_rgba_tuple(bg)))
        painter.setPen(QPen(QColor(*_rgba_tuple(border)), 1))
        painter.drawPath(path)
        # 4 根声波竖条
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        painter.setBrush(QColor(p.accent))
        bar_w = 3
        gap = 3
        total = 4 * bar_w + 3 * gap
        x = (self.width() - total) / 2
        cy = self.height() / 2
        opac = (0.76, 1.0, 1.0, 0.82)
        for i, h in enumerate(self._bars):
            painter.setOpacity(opac[i])
            painter.drawRoundedRect(round(x), round(cy - h / 2), bar_w, h, 1.5, 1.5)
            x += bar_w + gap
        painter.setOpacity(1.0)


def _rgba_tuple(value: str):
    c = QColor()
    text = value.strip()
    if text.startswith("rgba"):
        parts = text[text.index("(") + 1 : text.rindex(")")].split(",")
        r, g, b = (int(float(x)) for x in parts[:3])
        return (r, g, b, round(float(parts[3]) * 255))
    c = QColor(text)
    return (c.red(), c.green(), c.blue(), c.alpha())


class TranscriptEntry(QFrame):
    """一条字幕气泡（时间线节点）。"""

    clicked = pyqtSignal()
    copyAllRequested = pyqtSignal()  # 右键「复制全部」→ 由 TranscriptList 处理

    def __init__(self, parent=None, selectable: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("lcEntry")
        self._selectable = selectable
        self._current = False
        self._playing = False
        self._last = False
        self._display = DISPLAY_BILINGUAL
        self._source = ""
        self._target = ""
        self._stable_len: Optional[int] = None
        self._shown = 0  # 当前句原文已逐字揭示的字数
        self._tgt_text = ""  # 译文动画当前可见串（公共前缀不动、尾字原位改写、只前进不缩短）
        self._typer = QTimer(self)
        self._typer.setInterval(TYPE_INTERVAL_MS)  # 速度集中在 typing.py 调
        self._typer.timeout.connect(self._advance_typing)
        self._vis_src = ""  # 算高度用的「完整」原文（按整段定高，打字时不抖）
        self._vis_tgt = ""  # 算高度用的「完整」译文
        self._h_floor = 0  # 当前句高度地板：动画期间只增不减（重译变短/删后缀时不塌）
        self._h_floor_w = -1  # 地板对应宽度；宽度变则按新宽重置
        # 高度按内容精确（sizeHint 自算），避免顶部 stretch 把 wordwrap 误差吸收成「中段一大片空白」
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 14)  # 条目间距
        row.setSpacing(0)

        rail = QWidget(self)
        rail.setFixedWidth(_RAIL_W)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(6, 3, 6, 0)
        rl.setSpacing(5)
        self._dot = _VoiceDot(rail)
        rl.addWidget(self._dot, 0, Qt.AlignTop | Qt.AlignHCenter)  # type: ignore[operator]
        # 时间放在左侧竖条节点下方
        self._time = QLabel(rail)
        apply_font(self._time, 11, 760)
        self._time.setAlignment(Qt.AlignHCenter)  # type: ignore[arg-type]
        rl.addWidget(self._time, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        rl.addStretch(1)
        row.addWidget(rail)

        self._bubble = QFrame(self)
        self._bubble.setObjectName("lcBubble")
        bl = QVBoxLayout(self._bubble)
        bl.setContentsMargins(18, 13, 18, 13)
        bl.setSpacing(5)
        self._src = QLabel(self._bubble)
        self._src.setWordWrap(True)
        self._src.setTextFormat(Qt.RichText)  # type: ignore[arg-type]
        apply_font(self._src, 14, 650)
        self._tgt = QLabel(self._bubble)
        self._tgt.setWordWrap(True)
        self._tgt.setTextFormat(Qt.RichText)  # type: ignore[arg-type]
        apply_font(self._tgt, 18, 850)
        # 换行标签按内容求最小高度，长原文/译文末行不被裁
        for lbl in (self._src, self._tgt):
            lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            lbl.setMinimumHeight(0)
        bl.addWidget(self._src)
        bl.addWidget(self._tgt)
        row.addWidget(self._bubble, 1)

        # 整条可点击跳转，需子件透传鼠标事件（否则点击被吞）。selectable 时原文/译文可选中复制
        # （IBeam，不透传），点圆点/竖条/气泡空白仍跳转；非 selectable 全透传，纯点跳转。
        transparent = [self._bubble, self._time, self._dot, rail]
        if selectable:
            for lbl in (self._src, self._tgt):
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore[arg-type]
                lbl.setCursor(Qt.IBeamCursor)  # type: ignore[arg-type]
                # 右键透传到本条目，由 contextMenuEvent 弹「复制」菜单
                lbl.setContextMenuPolicy(Qt.PreventContextMenu)  # type: ignore[arg-type]
        else:
            transparent += [self._src, self._tgt]
        for w in transparent:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # type: ignore[arg-type]
        self.setMouseTracking(True)
        self._refresh_styles()

    # ----- 复制（右键逐句） -----

    def _own_text(self) -> str:
        """本句纯文本（原文 + 译文）。"""
        src = (self._source or "").strip()
        tgt = (self._target or "").strip()
        return f"{src}\n{tgt}" if (src and tgt and tgt != src) else (src or tgt)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """右键逐句复制：复制本句 / 复制全部。"""
        if not self._selectable:
            return super().contextMenuEvent(event)
        from PyQt5.QtWidgets import QApplication, QMenu

        menu = QMenu(self)
        act_one = menu.addAction(self.tr("复制本句"))
        act_all = menu.addAction(self.tr("复制全部"))
        chosen = menu.exec_(event.globalPos())
        if chosen is act_one:
            text = self._own_text()
            if text:
                QApplication.clipboard().setText(text)
        elif chosen is act_all:
            self.copyAllRequested.emit()

    # ----- 数据 -----

    def set_last(self, last: bool) -> None:
        self._last = last
        self.update()

    def set_state(self, current: bool = False, playing: bool = False) -> None:
        was_current = self._current
        self._current, self._playing = current, playing
        self._dot.set_tone("live" if current else ("playing" if playing else "idle"))
        if not current and was_current:  # 当前句变历史：停止揭示、整段立即显示
            self._shown = len(self._source)
            self._tgt_text = self._target
            self._h_floor, self._h_floor_w = 0, -1  # 沉淀为历史：高度地板清零，收缩到实际
            self._typer.stop()
            self._render_text()
        self._refresh_styles()

    def set_display(self, display: str) -> None:
        self._display = display
        self._render_text()

    def set_data(
        self, time_text: str, source: str, target: str, stable_len: Optional[int] = None
    ) -> None:
        self._time.setText(time_text)
        self._source, self._target, self._stable_len = source, target, stable_len
        if self._current and stable_len is not None:
            # 当前生长句：原文逐字揭示 + 译文动画。原文被改写变短/重置时回退 shown，不超过新长度。
            self._shown = min(self._shown, len(source))
            if self._shown < len(source) or self._tgt_text != target:
                self._typer.start()
            else:
                self._typer.stop()
        else:
            self._shown = len(source)  # 历史/定稿句：原文 + 译文整段直接显示
            self._tgt_text = target
            self._typer.stop()
        self._render_text()

    def _advance_typing(self) -> None:
        busy = False
        full = len(self._source)
        if self._shown < full:  # 原文逐字揭示
            remaining = full - self._shown
            # 文本大跳（重置/积压 >24 字）按比例加速消化，避免越落越远
            self._shown = min(full, self._shown + (remaining // 6 if remaining > 24 else 1))
            busy = True
        if self._tgt_text != self._target:  # 译文逐字补，只前进不缩短
            self._tgt_text = next_visible(self._tgt_text, self._target)
            busy = True
        if not busy:
            self._typer.stop()
            return
        self._render_text()

    def current_target(self) -> str:
        return self._target

    # ----- 渲染 -----

    def _render_text(self) -> None:
        p = app_palette()
        has_tgt = bool(self._target) and self._target.strip() != self._source.strip()
        show_src = self._display != DISPLAY_TARGET and bool(self._source)
        # has_tgt or _tgt_text：译文被清空时仍让分叉后缀逐字删完再隐藏，不硬切
        show_tgt = self._display != DISPLAY_SOURCE and (has_tgt or bool(self._tgt_text))
        if not show_src and not show_tgt and self._source:
            show_src = True

        if show_src:
            src_color = rgba(p.text, 0.92) if not show_tgt else "rgba(220,226,224,0.64)"
            if self._current and self._stable_len is not None:
                vis = self._source[: self._shown]  # 只显示已揭示的字
                cut = min(self._stable_len, len(vis))
                stable = _escape(vis[:cut])
                tail = _escape(vis[cut:])
                html = (
                    f'<span style="color:{src_color}">{stable}</span>'
                    f'<span style="color:rgba(245,247,246,0.43)">{tail}</span>'
                )
            else:
                html = f'<span style="color:{src_color}">{_escape(self._source)}</span>'
            self._src.setText(html)
        self._src.setVisible(show_src)

        if show_tgt:
            self._tgt.setText(f'<span style="color:{p.text}">{_escape(self._tgt_text)}</span>')
        self._tgt.setVisible(show_tgt)

        self._vis_src = self._source if show_src else ""
        # 高度按「完整」译文定（打字时不抖）；译文被清空、后缀还在删时退用可见串，避免高度先于文字塌
        self._vis_tgt = (self._target or self._tgt_text) if show_tgt else ""
        self.updateGeometry()  # 内容变则重算 sizeHint

    def _content_h(self, width: int) -> int:
        """按可见文本 + 当前宽度算精确高度（QFontMetrics 换行，离屏/真机一致），让 sizeHint 准确。"""
        avail = max(1, width - _RAIL_W - 36)  # 减 rail 与气泡左右内边距(18+18)
        h = 26  # 气泡上下内边距(13+13)
        rows = []
        if self._vis_src:
            rows.append((self._src.font(), self._vis_src))
        if self._vis_tgt:
            rows.append((self._tgt.font(), self._vis_tgt))
        for i, (font, text) in enumerate(rows):
            rect = QFontMetrics(font).boundingRect(
                0, 0, avail, 100000, Qt.TextWordWrap, text)  # type: ignore[attr-defined]
            h += rect.height()
            if i:
                h += 5  # 气泡内 spacing
        h = max(h, _DOT + 6) + 14  # 不低于头像点高；+14 = row 底部条目间距
        # 当前句动画期间高度只增不减（重译变短/删后缀时不塌、不缩一行又涨回引发列表重排）；
        # 宽度变则重置地板。
        if self._current:
            if width != self._h_floor_w:
                self._h_floor_w, self._h_floor = width, 0
            self._h_floor = max(self._h_floor, h)
            return self._h_floor
        return h

    def sizeHint(self) -> QSize:
        w = self.width() if self.width() > 1 else 600
        return QSize(w, self._content_h(w))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _refresh_styles(self) -> None:
        p = app_palette()
        time_color = p.accent_text if (self._current or self._playing) else p.subtle
        self._time.setStyleSheet(f"color:{time_color};background:transparent;")
        self._src.setStyleSheet("background:transparent;")
        self._tgt.setStyleSheet("background:transparent;")
        self.update()

    def resizeEvent(self, event) -> None:
        self.updateGeometry()  # 宽度变化时按新宽重算换行高度，长原文/译文末行不被裁
        super().resizeEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # ----- 自绘：连线 + 气泡底 -----

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 时间线连线（节点之间）
        if not self._last:
            from PyQt5.QtGui import QPen

            painter.setPen(QPen(QColor(*_rgba_tuple(rgba(p.muted, 0.14))), 1))
            cx = _RAIL_W // 2
            top_y = self._time.geometry().bottom() + 5 if self._time.text() else _DOT + 8
            painter.drawLine(cx, top_y, cx, self.height())
        # 气泡底 + 描边
        from PyQt5.QtGui import QPainterPath, QPen

        br = self._bubble.geometry()
        path = QPainterPath()
        path.addRoundedRect(br.x() + 0.5, br.y() + 0.5, br.width() - 1, br.height() - 1, 15, 15)
        if self._current or self._playing:
            painter.fillPath(path, QColor(*_rgba_tuple(rgba(p.accent, 0.035))))
            painter.setPen(QPen(QColor(*_rgba_tuple(rgba(p.accent, 0.46))), 1))
        else:
            painter.fillPath(path, QColor(*_rgba_tuple(rgba(p.text, 0.022))))
            painter.setPen(QPen(QColor(*_rgba_tuple(p.line_soft)), 1))
        painter.drawPath(path)


class TranscriptList(QFrame):
    """竖排转录时间线，内含滚动。实时态 ``upsert`` 增量；详情态 ``set_segments`` 静态。"""

    entryActivated = pyqtSignal(int)  # 详情：点击第 i 条 → 跳到该句

    def __init__(self, parent=None, selectable: bool = False) -> None:
        super().__init__(parent)
        from PyQt5.QtWidgets import QScrollArea

        self._selectable = selectable  # 条目文字是否可选中复制（详情/会话页 True）
        self._display = DISPLAY_BILINGUAL
        self._entries: List[TranscriptEntry] = []
        self._by_seg: dict = {}
        self._follow = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:0;}"
            "QScrollBar:vertical{width:7px;background:transparent;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(170,183,178,0.28);border-radius:3px;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
        )
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(4, 2, 8, 2)
        self._col.setSpacing(0)
        self._col.addStretch(1)
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)

        sb = self._scroll.verticalScrollBar()
        sb.rangeChanged.connect(self._on_range)
        sb.valueChanged.connect(self._on_scroll)

    def set_display(self, display: str) -> None:
        self._display = display
        for e in self._entries:
            e.set_display(display)

    def copy_text(self) -> str:
        """整段转录纯文本（每句：原文 + 译文，句间空行），供「复制」按钮一键复制。"""
        blocks = []
        for e in self._entries:
            src = (e._source or "").strip()
            tgt = (e._target or "").strip()
            seg = f"{src}\n{tgt}" if (src and tgt and tgt != src) else (src or tgt)
            if seg:
                blocks.append(seg)
        return "\n\n".join(blocks)

    def clear(self) -> None:
        for e in self._entries:
            self._col.removeWidget(e)
            e.deleteLater()
        self._entries.clear()
        self._by_seg.clear()

    # ----- 详情：静态加载 -----

    def set_segments(self, segments, time_fmt) -> None:
        """segments: 有 .start/.source/.target 的对象列表；time_fmt(start)->字符串。"""
        self.clear()
        for i, seg in enumerate(segments):
            entry = self._make_entry()
            entry.set_data(time_fmt(seg.start), seg.source, seg.target)
            entry.set_display(self._display)
            idx = i
            entry.clicked.connect(lambda _i=idx: self.entryActivated.emit(_i))
            self._append(entry)
        self._mark_last()

    def set_playing(self, index: int) -> None:
        for i, e in enumerate(self._entries):
            e.set_state(playing=(i == index))

    # ----- 实时：增量 -----

    def upsert(self, entry_data, rel_start: float, time_fmt) -> None:
        """entry_data: CaptionEntry；rel_start 是相对会话起点的秒。按 seg_id 原地更新，末条为当前句。"""
        seg_id = entry_data.seg_id
        ent = self._by_seg.get(seg_id)
        if ent is None:
            ent = self._make_entry()
            self._by_seg[seg_id] = ent
            ent.set_display(self._display)
            self._append(ent)
        # 先标 current 再 set_data：状态先于内容就位，新句才能从 0 逐字揭示
        self._mark_last()
        self._mark_current(seg_id)
        # 译文防闪：新帧译文为空时保留上次译文（后端会先发空译文），等真有译文再覆盖
        target = entry_data.target_text or ent.current_target()
        ent.set_data(
            time_fmt(max(0.0, rel_start)),
            entry_data.source_text,
            target,
            stable_len=entry_data.source_stable_len if not entry_data.is_final else None,
        )

    def _mark_current(self, latest_seg: str) -> None:
        for sid, e in self._by_seg.items():
            e.set_state(current=(sid == latest_seg))

    def finalize_all(self) -> None:
        """会话结束：所有段落变普通历史条（去掉「当前句」绿高亮）。"""
        for e in self._by_seg.values():
            e.set_state(current=False)

    # ----- 共用 -----

    def _make_entry(self) -> TranscriptEntry:
        entry = TranscriptEntry(self._inner, selectable=self._selectable)
        entry.copyAllRequested.connect(self._copy_all_to_clipboard)  # 右键「复制全部」
        return entry

    def _copy_all_to_clipboard(self) -> None:
        from PyQt5.QtWidgets import QApplication

        text = self.copy_text()
        if text:
            QApplication.clipboard().setText(text)

    def _append(self, entry: TranscriptEntry) -> None:
        # 底对齐：stretch 常驻 index 0，条目追加其后 → 内容少时整体贴底（避免下方大片空白），
        # 超屏则 stretch 收为 0，正常滚动 + _pin_bottom 贴底。
        self._col.addWidget(entry)
        self._entries.append(entry)

    def _mark_last(self) -> None:
        for i, e in enumerate(self._entries):
            e.set_last(i == len(self._entries) - 1)

    def scroll_to_index(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            e = self._entries[index]
            self._scroll.ensureWidgetVisible(e, 0, 40)

    def _on_scroll(self, value: int) -> None:
        sb = self._scroll.verticalScrollBar()
        self._follow = value >= sb.maximum() - 8

    def _on_range(self, _min: int, maximum: int) -> None:
        # rangeChanged 的 maximum 可能是布局未结算的旧值（直接 setValue 会停半空），用 singleShot(0)
        # 等本轮布局结算后再读最终值贴底。
        if self._follow:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self._pin_bottom)

    def _pin_bottom(self) -> None:
        if self._follow:
            sb = self._scroll.verticalScrollBar()
            sb.setValue(sb.maximum())
