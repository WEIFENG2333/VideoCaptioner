# -*- coding: utf-8 -*-
"""详情页底部的音频播放条：播放/暂停、点击/拖动 seek 的进度条、倍速。

按句跳转由转录时间线点句驱动（``seek_sentence``），当前播放句通过 ``sentenceChanged``
回传给转录时间线高亮。用 QMediaPlayer 播录制的 WAV。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.workbench import apply_font, draw_rounded_surface


def _fmt(ms: float) -> str:
    s = max(0, int(ms // 1000))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class _PlayButton(QFrame):
    """圆形主操作按钮：播放三角 / 暂停双竖条自绘。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None, diameter: int = 44) -> None:
        super().__init__(parent)
        self._d = diameter
        self._playing = False
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        from PyQt5.QtCore import QRectF

        path = QPainterPath()
        path.addEllipse(QRectF(self.rect().adjusted(1, 1, -1, -1)))
        painter.fillPath(path, QColor(p.accent))
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        painter.setBrush(QColor(p.accent_fg))
        cx, cy = self.width() / 2, self.height() / 2
        if self._playing:
            bw, bh, gap = 4, 14, 4
            painter.drawRoundedRect(round(cx - gap / 2 - bw), round(cy - bh / 2), bw, bh, 1.5, 1.5)
            painter.drawRoundedRect(round(cx + gap / 2), round(cy - bh / 2), bw, bh, 1.5, 1.5)
        else:
            tri = QPainterPath()
            tri.moveTo(cx - 6, cy - 8)
            tri.lineTo(cx + 9, cy)
            tri.lineTo(cx - 6, cy + 8)
            tri.closeSubpath()
            painter.fillPath(tri, QColor(p.accent_fg))


class _ProgressBar(QWidget):
    """进度轨道：已播放填充 + 播放头手柄 + 点击/拖动 seek；按句跳转走转录时间线点句（sentenceChanged 联动）。"""

    seekRatio = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setMouseTracking(True)
        self._ratio = 0.0
        self._dragging = False
        self._hover = False

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def _ratio_at(self, x: int) -> float:
        return max(0.0, min(1.0, x / max(1, self.width())))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:  # type: ignore[attr-defined]
            return
        self._dragging = True
        r = self._ratio_at(event.pos().x())
        self.set_ratio(r)
        self.seekRatio.emit(r)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            r = self._ratio_at(event.pos().x())
            self.set_ratio(r)  # 拖动时实时预览填充，松手即定位
            self.seekRatio.emit(r)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ARG002
        self._dragging = False

    def enterEvent(self, event) -> None:  # noqa: ARG002
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ARG002
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        track_h = 4
        # 底轨
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        painter.setBrush(QColor(*_t(rgba(p.text, 0.12))))
        painter.drawRoundedRect(0, round(cy - track_h / 2), self.width(), track_h, 2, 2)
        # 已播放
        fill = round(self.width() * self._ratio)
        if fill > 0:
            painter.setBrush(QColor(p.accent))
            painter.drawRoundedRect(0, round(cy - track_h / 2), fill, track_h, 2, 2)
        # 播放头手柄（hover / 拖动时放大），固定显示当前位置，支持拖动 scrub
        from PyQt5.QtCore import QPointF

        kr = 7.0 if (self._hover or self._dragging) else 5.0
        knob_x = min(max(self.width() * self._ratio, kr), self.width() - kr)
        painter.setBrush(QColor(p.accent))
        painter.drawEllipse(QPointF(knob_x, cy), kr, kr)


def _t(value: str):
    c = QColor()
    text = value.strip()
    if text.startswith("rgba"):
        parts = text[text.index("(") + 1 : text.rindex(")")].split(",")
        r, g, b = (int(float(x)) for x in parts[:3])
        return (r, g, b, round(float(parts[3]) * 255))
    c = QColor(text)
    return (c.red(), c.green(), c.blue(), c.alpha())


_SPEEDS = [1.0, 1.25, 1.5, 2.0, 0.75]


class AudioPlayerBar(QFrame):
    """整条播放器面板。"""

    sentenceChanged = pyqtSignal(int)  # 当前播放到第 i 句（-1 无）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("lcPlayer")
        self.setFixedHeight(64)
        self._starts: List[float] = []
        self._duration_ms = 0
        self._speed_idx = 0
        self._cur_sentence = -1
        # 媒体未加载完时 setPosition 被 AVFoundation 丢弃 → 暂存目标、加载完成后补跳（否则首次点
        # 句子不跳）。
        self._pending_seek_ms: Optional[int] = None

        self._player = QMediaPlayer(self)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.stateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        # 单行播放条：播放/暂停 · 当前时间 · 进度条 · 总时长 · 倍速。
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(14)
        self._play = _PlayButton(self)
        self._play.clicked.connect(self.toggle)
        row.addWidget(self._play)
        self._cur = QLabel("00:00", self)
        self._total = QLabel("00:00", self)
        for lab in (self._cur, self._total):
            apply_font(lab, 13, 800)
        self._bar = _ProgressBar(self)
        self._bar.seekRatio.connect(self._seek_ratio)
        row.addWidget(self._cur)
        row.addWidget(self._bar, 1)
        row.addWidget(self._total)

        from videocaptioner.ui.components.workbench import CompactButton

        self._speed = CompactButton("1.0x", parent=self)
        self._speed.clicked.connect(self._cycle_speed)
        row.addWidget(self._speed)

        self._refresh_labels()

    # ----- 装载 -----

    def load(self, audio_path, starts: List[float], total_s: float) -> None:
        self._starts = list(starts)
        self._duration_ms = int(total_s * 1000)
        self._total.setText(_fmt(self._duration_ms))
        self._cur.setText("00:00")
        self._cur_sentence = 0 if self._starts else -1
        self._pending_seek_ms = None
        if audio_path is not None:
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(audio_path))))
        else:
            self._player.setMedia(QMediaContent())

    def has_audio(self) -> bool:
        return not self._player.media().isNull()

    def stop(self) -> None:
        self._player.stop()

    # ----- 控制 -----

    def toggle(self) -> None:
        if not self.has_audio():
            return
        if self._player.state() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def play(self) -> None:
        if self.has_audio() and self._player.state() != QMediaPlayer.PlayingState:
            self._player.play()

    def _apply_position(self, ms: int) -> None:
        """seek 统一入口：媒体已就绪直接定位；未就绪则暂存，由 ``_on_media_status`` 加载完后补跳。"""
        ms = int(max(0, ms))
        ready = self._player.mediaStatus() in (
            QMediaPlayer.LoadedMedia,
            QMediaPlayer.BufferingMedia,
            QMediaPlayer.BufferedMedia,
            QMediaPlayer.EndOfMedia,
        )
        self._pending_seek_ms = None if ready else ms
        self._player.setPosition(ms)

    def _on_media_status(self, status) -> None:
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if self._pending_seek_ms is not None:
                self._player.setPosition(self._pending_seek_ms)
                self._pending_seek_ms = None

    def seek_sentence(self, index: int) -> None:
        if 0 <= index < len(self._starts):
            self._apply_position(int(self._starts[index] * 1000))
            self._set_sentence(index)

    def seek_relative(self, delta_ms: int) -> None:
        """快捷键 ←/→ 相对快退/快进。"""
        if not self.has_audio():
            return
        pos = self._player.position() + delta_ms
        if self._duration_ms:
            pos = min(pos, self._duration_ms)
        self._apply_position(int(max(0, pos)))

    def step_sentence(self, delta: int) -> None:
        """快捷键 ↑/↓ 上一句 / 下一句。"""
        if not self._starts:
            return
        base = self._cur_sentence if self._cur_sentence >= 0 else 0
        self.seek_sentence(max(0, min(len(self._starts) - 1, base + delta)))

    def _seek_ratio(self, ratio: float) -> None:
        if self._duration_ms:
            self._apply_position(int(ratio * self._duration_ms))

    def _cycle_speed(self) -> None:
        self._speed_idx = (self._speed_idx + 1) % len(_SPEEDS)
        rate = _SPEEDS[self._speed_idx]
        self._player.setPlaybackRate(rate)
        self._speed.setText(f"{rate:g}x")

    # ----- 播放器回调 -----

    def _on_duration(self, dur: int) -> None:
        if dur > 0:
            self._duration_ms = dur
            self._total.setText(_fmt(dur))

    def _on_position(self, pos: int) -> None:
        self._cur.setText(_fmt(pos))
        if self._duration_ms:
            self._bar.set_ratio(pos / self._duration_ms)
        # 当前句 = 起点 <= pos 的最后一句
        sec = pos / 1000.0
        idx = -1
        for i, st in enumerate(self._starts):
            if st <= sec + 0.05:
                idx = i
            else:
                break
        if idx != self._cur_sentence:
            self._set_sentence(idx)

    def _on_state(self, state) -> None:
        self._play.set_playing(state == QMediaPlayer.PlayingState)

    def _set_sentence(self, index: int) -> None:
        self._cur_sentence = index
        self.sentenceChanged.emit(index)

    def _refresh_labels(self) -> None:
        p = app_palette()
        self._cur.setStyleSheet(f"color:{p.text};background:transparent;")
        self._total.setStyleSheet(f"color:{p.text};background:transparent;")

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        draw_rounded_surface(self, p.panel, p.line_soft, 14)
