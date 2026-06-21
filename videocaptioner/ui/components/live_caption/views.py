# -*- coding: utf-8 -*-
"""实时字幕三视图：会话 / 历史 / 详情。

颜色走 ``app_palette()``，按钮/胶囊/图标盒复用 ``ui/components/workbench``。视图只负责呈现 +
发信号，线程 / 浮窗 / 录制等生命周期由宿主 ``LiveCaptionInterface`` 编排。
"""

from __future__ import annotations

from collections import deque
from typing import List, Optional

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.core.realtime.recording.history import LiveCaptionRecord
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.live_caption.player import AudioPlayerBar
from videocaptioner.ui.components.live_caption.transcript import (
    DISPLAY_BILINGUAL,
    DISPLAY_SOURCE,
    DISPLAY_TARGET,
    TranscriptList,
)
from videocaptioner.ui.components.workbench import (
    CompactButton,
    ErrorCard,
    FilterTabs,
    IconBox,
    OptionCard,
    PillSelect,
    RoundIconButton,
    ToggleSwitch,
    WorkbenchButton,
    apply_font,
    draw_rounded_surface,
)
from videocaptioner.ui.i18n import tr

MODE_READY = "ready"
MODE_LIVE = "live"
MODE_PAUSED = "paused"
MODE_ENDED = "ended"
MODE_ERROR = "error"


def _fmt_pos(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class _Panel(QFrame):
    """统一面板底：圆角 14 + panel 底 + line_soft 描边。"""

    def __init__(self, parent=None, radius: int = 14) -> None:
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        draw_rounded_surface(self, p.panel, p.line_soft, self._radius)


class _RecentCard(QFrame):
    """会话首页「最近记录」一项：记录名 + 元信息 + 打开按钮。"""

    opened = pyqtSignal(object)

    def __init__(self, record: LiveCaptionRecord, parent=None) -> None:
        super().__init__(parent)
        self._record = record
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 12, 11)
        lay.setSpacing(12)
        p = app_palette()
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        name = QLabel(record.name, self)
        apply_font(name, 14, 820)
        name.setStyleSheet(f"color:{p.text};background:transparent;")
        meta = QLabel(record.summary, self)
        apply_font(meta, 12, 600)
        meta.setStyleSheet(f"color:{p.subtle};background:transparent;")
        col.addWidget(name)
        col.addWidget(meta)
        lay.addLayout(col, 1)
        self._btn = RoundIconButton(AppIcon.DOCUMENT, 32, self)
        self._btn.clicked.connect(lambda: self.opened.emit(self._record))
        lay.addWidget(self._btn, 0, Qt.AlignVCenter)  # type: ignore[arg-type]

    def enterEvent(self, event) -> None:  # noqa: ARG002
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ARG002
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.opened.emit(self._record)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        bg = p.control_hover if self._hover else rgba(p.text, 0.022)
        draw_rounded_surface(self, bg, p.line_soft, 12)


class _HistoryRow(QFrame):
    """历史列表一行（卡片式，自有排版，非原始表格）。"""

    opened = pyqtSignal(object)
    renameRequested = pyqtSignal(object)
    exportRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)

    def __init__(self, record: LiveCaptionRecord, parent=None) -> None:
        super().__init__(parent)
        self._record = record
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        p = app_palette()
        self._mark = IconBox(AppIcon.MICROPHONE, self, size=40, tone="accent")
        lay.addWidget(self._mark, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        name = QLabel(record.name, self)
        apply_font(name, 14, 820)
        name.setStyleSheet(f"color:{p.text};background:transparent;")
        meta = QLabel(f"{record.source} · {record.duration_label} · {record.created_label}", self)
        apply_font(meta, 12, 600)
        meta.setStyleSheet(f"color:{p.subtle};background:transparent;")
        col.addWidget(name)
        col.addWidget(meta)
        lay.addLayout(col, 1)
        # 带文字的动作按钮：纯图标看不出干啥，行内也有空间，直接标清「打开/重命名/导出/删除」
        self._open = CompactButton(tr("liveview.action.open"), AppIcon.DOCUMENT, self)
        self._open.clicked.connect(lambda: self.opened.emit(self._record))
        self._rename = CompactButton(tr("liveview.action.rename"), AppIcon.EDIT, self)
        self._rename.clicked.connect(lambda: self.renameRequested.emit(self._record))
        self._exp = CompactButton(tr("liveview.action.export"), AppIcon.DOWNLOAD, self)
        self._exp.clicked.connect(lambda: self.exportRequested.emit(self._record))
        self._del = CompactButton(tr("common.delete"), AppIcon.DELETE, self)
        self._del.clicked.connect(lambda: self.deleteRequested.emit(self._record))
        for b in (self._open, self._rename, self._exp, self._del):
            lay.addWidget(b, 0, Qt.AlignVCenter)  # type: ignore[arg-type]

    def enterEvent(self, event) -> None:  # noqa: ARG002
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ARG002
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.opened.emit(self._record)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = app_palette()
        bg = p.control_hover if self._hover else rgba(p.text, 0.022)
        draw_rounded_surface(self, bg, p.line_soft, 12)


def _h2(text: str, parent=None) -> QLabel:
    lab = QLabel(text, parent)
    apply_font(lab, 24, 900)
    lab.setStyleSheet(f"color:{app_palette().text};background:transparent;")
    return lab


class _ScrollList(QFrame):
    """竖排卡片列表 + 内置滚动（最近记录 / 历史记录共用）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PyQt5.QtWidgets import QScrollArea

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
        self._col.setContentsMargins(0, 0, 6, 0)
        self._col.setSpacing(8)
        self._col.addStretch(1)
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)
        self._widgets: List[QWidget] = []

    def clear(self) -> None:
        for w in self._widgets:
            self._col.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

    def add(self, widget: QWidget) -> None:
        self._col.insertWidget(self._col.count() - 1, widget)
        self._widgets.append(widget)

    def count(self) -> int:
        return len(self._widgets)


class _EmptyState(QWidget):
    """顶部锚定的空态：图标 + 标题 + 副文。靠上呈现，不在高面板正中漂浮（避免大片空洞像渲染坏了）。"""

    def __init__(self, icon: AppIcon, title: str, detail: str, parent=None,
                 top: int = 60) -> None:
        super().__init__(parent)
        p = app_palette()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addSpacing(top)
        box = IconBox(icon, self, size=52, tone="surface")
        lay.addWidget(box, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        self._title = QLabel(title, self)
        apply_font(self._title, 18, 900)
        self._title.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._title.setStyleSheet(f"color:{p.text};background:transparent;")
        self._detail = QLabel(detail, self)
        apply_font(self._detail, 13, 600)
        self._detail.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f"color:{p.subtle};background:transparent;")
        lay.addWidget(self._title)
        lay.addWidget(self._detail)
        lay.addStretch(1)

    def set_text(self, title: str, detail: str) -> None:
        self._title.setText(title)
        self._detail.setText(detail)


class _LevelMeter(QWidget):
    """会话页拾音电平波形：一排细竖条按近期音量起伏滚动，绿=有声、暗=静音。
    小巧、不占空间，让用户一眼看出有没有拾到声音。"""

    _BARS = 28
    _STRIDE = 3  # 每 3 个音频块（~300ms）才滚一格：滚动慢 3 倍、更顺眼

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._levels = deque([0.0] * self._BARS, maxlen=self._BARS)
        self._pending = 0.0
        self._tick = 0

    def push(self, level: float) -> None:
        # 攒够 _STRIDE 块才滚一格、取这期间峰值 → 滚动慢而平稳，又不漏掉音量起伏
        self._pending = max(self._pending, max(0.0, min(1.0, float(level))))
        self._tick += 1
        if self._tick >= self._STRIDE:
            self._levels.append(self._pending)
            self._pending = 0.0
            self._tick = 0
            self.update()

    def reset(self) -> None:
        self._levels = deque([0.0] * self._BARS, maxlen=self._BARS)
        self._pending = 0.0
        self._tick = 0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        n = len(self._levels)
        if n == 0 or self.width() <= 0:
            return
        p = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        live = QColor(p.accent)
        idle = QColor(p.muted)
        idle.setAlpha(64)
        gap = 3.0
        bw = max(2.0, (self.width() - (n - 1) * gap) / n)
        cy = self.height() / 2.0
        painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
        for i, lv in enumerate(self._levels):
            bh = max(2.0, lv * (self.height() - 2))
            x = i * (bw + gap)
            painter.setBrush(live if lv > 0.04 else idle)
            painter.drawRoundedRect(QRectF(x, cy - bh / 2.0, bw, bh), bw / 2.0, bw / 2.0)


class SessionView(QWidget):
    """会话页：ready / live / paused / ended / error 五态。"""

    startClicked = pyqtSignal()
    pauseClicked = pyqtSignal()
    resumeClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    historyClicked = pyqtSignal()
    recordOpened = pyqtSignal(object)
    configClicked = pyqtSignal()
    exportClicked = pyqtSignal()
    deviceChanged = pyqtSignal(object)
    translateToggled = pyqtSignal(bool)
    targetLanguageChanged = pyqtSignal(object)  # 发 TargetLanguage 成员
    sourceLanguageChanged = pyqtSignal(str)  # 发识别语言 code（auto 或 provider 支持的语言码）
    overlayToggled = pyqtSignal(bool)
    newSessionClicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = MODE_READY
        self.transcript = TranscriptList(selectable=True)  # 转录文字可选中复制
        self._build()
        self.set_mode(MODE_READY)

    # ----- 构建 -----

    def _build(self) -> None:
        p = app_palette()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(_h2(tr("liveview.title.session"), self))

        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(16)

        # 主面板
        self._main = _Panel(self)
        ml = QVBoxLayout(self._main)
        ml.setContentsMargins(20, 18, 20, 18)
        ml.setSpacing(14)
        # 记录头（mic + 标题 + 导出）只在「有录制内容」时显示（录制中/暂停/已结束）；就绪态左侧
        # 只放历史记录。包进 self._head 容器整体显隐。
        self._head = QWidget(self._main)
        head = QHBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        self._mark = IconBox(AppIcon.MICROPHONE, self._head, size=40, tone="accent")
        head.addWidget(self._mark, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self._title = QLabel(self._head)
        apply_font(self._title, 16, 850)
        self._title.setStyleSheet(f"color:{p.text};background:transparent;")
        self._sub = QLabel(self._head)
        apply_font(self._sub, 13, 600)
        self._sub.setStyleSheet(f"color:{p.subtle};background:transparent;")
        tcol.addWidget(self._title)
        tcol.addWidget(self._sub)
        head.addLayout(tcol, 1)
        self._btn_export = CompactButton(tr("liveview.action.export"), AppIcon.DOWNLOAD, self._head)
        self._btn_export.clicked.connect(self.exportClicked.emit)
        head.addWidget(self._btn_export, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        ml.addWidget(self._head)

        # 错误横幅：错误态不接管整页/藏侧栏，只在头部下方叠一条紧凑提示（侧栏保留设备选择+重试，
        # 便于当场修复）。
        self._error_banner = ErrorCard("", parent=self._main)
        self._error_banner.setVisible(False)
        ml.addWidget(self._error_banner)

        # 内容堆叠：最近记录 / 转录流 / 错误
        from PyQt5.QtWidgets import QStackedWidget

        self._stack = QStackedWidget(self._main)
        # 0 最近记录
        recent = QWidget()
        rl = QVBoxLayout(recent)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        rhead = QHBoxLayout()
        rt = QLabel(tr("liveview.recent.title"), recent)
        apply_font(rt, 14, 820)
        rt.setStyleSheet(f"color:{p.muted};background:transparent;")
        self._view_all = CompactButton(tr("liveview.recent.view_all"), AppIcon.HISTORY, recent)
        self._view_all.clicked.connect(self.historyClicked.emit)
        rhead.addWidget(rt)
        rhead.addStretch(1)
        rhead.addWidget(self._view_all)
        rl.addLayout(rhead)
        self._recent = _ScrollList(recent)
        rl.addWidget(self._recent, 1)
        self._recent_empty = _EmptyState(AppIcon.MICROPHONE, tr("liveview.recent.empty.title"),
                                         tr("liveview.recent.empty.detail"), recent)
        rl.addWidget(self._recent_empty)
        self._recent_empty.setVisible(False)
        self._stack.addWidget(recent)
        # 1 转录流
        self._stack.addWidget(self.transcript)
        ml.addWidget(self._stack, 1)
        workspace.addWidget(self._main, 1)

        # 侧栏
        from PyQt5.QtWidgets import QScrollArea
        self._side = QWidget(self)
        self._side.setFixedWidth(300)
        # 侧栏放进滚动区：内容超高时侧栏自身滚动，不把主窗口最小高度顶出屏幕。
        _side_outer = QVBoxLayout(self._side)
        _side_outer.setContentsMargins(0, 0, 0, 0)
        _side_scroll = QScrollArea(self._side)
        _side_scroll.setWidgetResizable(True)
        _side_scroll.setFrameShape(QFrame.NoFrame)
        _side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        _side_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:0;}"
            "QScrollBar:vertical{width:6px;background:transparent;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(170,183,178,0.28);border-radius:3px;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
        )
        _side_outer.addWidget(_side_scroll)
        _side_inner = QWidget()
        _side_inner.setStyleSheet("background:transparent;")
        _side_scroll.setWidget(_side_inner)
        sl = QVBoxLayout(_side_inner)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        # 控制卡
        self._control = _Panel(self._side)
        # 6 个控制按钮常驻、按态显隐；构造态会把全部按钮高度计入、把最小高度顶到超屏，而同时最多
        # 只显 2 个，故给控制卡封顶。
        self._control.setMaximumHeight(290)
        cl = QVBoxLayout(self._control)
        cl.setContentsMargins(22, 22, 22, 22)
        cl.setSpacing(18)
        self._timer = QLabel(self._control)
        apply_font(self._timer, 52, 900)
        self._timer.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._timer.setStyleSheet(f"color:{p.text};background:transparent;")
        self._timer_label = QLabel(self._control)
        apply_font(self._timer_label, 13, 760)
        self._timer_label.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self._timer_label.setStyleSheet(f"color:{p.subtle};background:transparent;")
        tbox = QVBoxLayout()
        tbox.setSpacing(4)
        tbox.addWidget(self._timer)
        tbox.addWidget(self._timer_label)
        self._meter = _LevelMeter(self._control)  # 拾音电平波形：录制中显示有没有听到声音
        tbox.addSpacing(8)
        tbox.addWidget(self._meter)
        cl.addLayout(tbox)
        self._controls = QVBoxLayout()
        self._controls.setSpacing(10)
        cl.addLayout(self._controls)
        # 控制按钮（建一次，按态显隐）——统一用项目 WorkbenchButton（primary/warn/danger/default）
        self._b_start = WorkbenchButton(tr("liveview.btn.start"), AppIcon.PLAY, primary=True)
        self._b_start.clicked.connect(self.startClicked.emit)
        self._b_pause = WorkbenchButton(tr("liveview.btn.pause"), tone="warn")
        self._b_pause.clicked.connect(self.pauseClicked.emit)
        self._b_resume = WorkbenchButton(tr("liveview.btn.resume"), AppIcon.PLAY, primary=True)
        self._b_resume.clicked.connect(self.resumeClicked.emit)
        self._b_stop = WorkbenchButton(tr("liveview.btn.stop"), tone="danger")
        self._b_stop.clicked.connect(self.stopClicked.emit)
        self._b_view = WorkbenchButton(tr("liveview.btn.view_record"), AppIcon.DOCUMENT, primary=True)
        self._b_view.clicked.connect(self._open_current)
        self._b_new = WorkbenchButton(tr("liveview.btn.new_session"), AppIcon.SYNC)
        self._b_new.clicked.connect(self.newSessionClicked.emit)
        for b in (self._b_start, self._b_pause, self._b_resume, self._b_stop,
                  self._b_view, self._b_new):
            self._controls.addWidget(b)
        sl.addWidget(self._control)

        # 设置卡
        self._settings = _Panel(self._side)
        stl = QVBoxLayout(self._settings)
        stl.setContentsMargins(20, 18, 20, 18)
        stl.setSpacing(14)
        sthead = QHBoxLayout()
        stt = QLabel(tr("liveview.settings.title"), self._settings)
        apply_font(stt, 15, 850)
        stt.setStyleSheet(f"color:{p.text};background:transparent;")
        self._btn_config = CompactButton(tr("liveview.settings.config"), AppIcon.SETTING, self._settings)
        self._btn_config.clicked.connect(self.configClicked.emit)
        sthead.addWidget(stt)
        sthead.addStretch(1)
        sthead.addWidget(self._btn_config)
        stl.addLayout(sthead)
        self._device_items: List[tuple] = []
        self._device_pill = PillSelect(self._settings)
        self._device_pill.currentTextChanged.connect(self._on_device_text)
        self._src_lang_items: List[tuple] = []
        self._src_lang_pill = PillSelect(self._settings)
        self._src_lang_pill.currentTextChanged.connect(self._on_src_lang_text)
        self._lang_items: List[tuple] = []
        self._lang_pill = PillSelect(self._settings)
        self._lang_pill.currentTextChanged.connect(self._on_lang_text)
        self._translate_sw = ToggleSwitch(True, self._settings)
        self._translate_sw.toggled.connect(self.translateToggled.emit)
        self._overlay_sw = ToggleSwitch(True, self._settings)
        self._overlay_sw.toggled.connect(self.overlayToggled.emit)
        for card in (
            OptionCard(tr("liveview.option.audio_source"), self._device_pill, self._settings),
            OptionCard(tr("liveview.option.source_language"), self._src_lang_pill, self._settings),
            OptionCard(tr("liveview.option.live_translate"), self._translate_sw, self._settings),
            OptionCard(tr("liveview.option.target_language"), self._lang_pill, self._settings),
            OptionCard(tr("liveview.option.overlay"), self._overlay_sw, self._settings),
        ):
            stl.addWidget(card)
        sl.addWidget(self._settings)
        sl.addStretch(1)
        workspace.addWidget(self._side)
        root.addLayout(workspace, 1)
        self._current_record: Optional[LiveCaptionRecord] = None

    # ----- 对外 API -----

    def set_devices(self, items: List[tuple], current=None) -> None:
        self._device_items = list(items)
        labels = [label for _v, label in items]
        cur = next((label for v, label in items if v == current),
                   labels[0] if labels else "")
        self._device_pill.blockSignals(True)
        self._device_pill.setItems(labels, cur)
        self._device_pill.blockSignals(False)

    def _on_device_text(self, text: str) -> None:
        for v, label in self._device_items:
            if label == text:
                self.deviceChanged.emit(v)
                return

    def set_target_languages(self, items: List[tuple], current=None) -> None:
        # items: [(TargetLanguage, 中文标签)]; current: TargetLanguage 成员
        self._lang_items = list(items)
        labels = [label for _v, label in items]
        cur = next((label for v, label in items if v == current),
                   labels[0] if labels else "")
        self._lang_pill.blockSignals(True)
        self._lang_pill.setItems(labels, cur)
        self._lang_pill.blockSignals(False)

    def _on_lang_text(self, text: str) -> None:
        for v, label in self._lang_items:
            if label == text:
                self.targetLanguageChanged.emit(v)
                return

    def set_source_languages(self, items: List[tuple], current=None) -> None:
        # items: [(code, 中文标签)]，如 ("auto","自动识别")
        self._src_lang_items = list(items)
        labels = [label for _v, label in items]
        cur = next((label for v, label in items if v == current), labels[0] if labels else "")
        self._src_lang_pill.blockSignals(True)
        self._src_lang_pill.setItems(labels, cur)
        self._src_lang_pill.blockSignals(False)

    def _on_src_lang_text(self, text: str) -> None:
        for v, label in self._src_lang_items:
            if label == text:
                self.sourceLanguageChanged.emit(v)
                return

    def set_translate(self, on: bool) -> None:
        self._translate_sw.blockSignals(True)
        self._translate_sw.setChecked(on)
        self._translate_sw.blockSignals(False)

    def set_overlay(self, on: bool) -> None:
        self._overlay_sw.blockSignals(True)
        self._overlay_sw.setChecked(on)
        self._overlay_sw.blockSignals(False)

    def set_level(self, level: float) -> None:
        """实时拾音电平（0~1）→ 波形。"""
        self._meter.push(level)

    def reset_level(self) -> None:
        self._meter.reset()

    def set_recent(self, records: List[LiveCaptionRecord]) -> None:
        self._recent.clear()
        for rec in records[:8]:
            card = _RecentCard(rec, self._recent)
            card.opened.connect(self.recordOpened.emit)
            self._recent.add(card)
        empty = self._recent.count() == 0
        self._recent_empty.setVisible(empty)
        self._recent.setVisible(not empty)

    def set_timer(self, value: str, label: str) -> None:
        self._timer.setText(value)
        self._timer_label.setText(label)

    def set_record_title(self, title: str, sub: str) -> None:
        self._title.setText(title)
        self._sub.setText(sub)

    def set_error(self, title: str, detail: str) -> None:
        # 标题走记录头（宿主 set_record_title），可操作的详情走顶部错误横幅。
        self._error_banner.setText(detail)

    def set_current_record(self, record: Optional[LiveCaptionRecord]) -> None:
        self._current_record = record

    def _open_current(self) -> None:
        if self._current_record is not None:
            self.recordOpened.emit(self._current_record)

    def set_saving(self) -> None:
        """「结束保存」后、记录就绪前的过渡态：禁用控制按钮 + 提示「正在保存…」，避免后台收尾
        （冲刷末句 + 写盘）期间用户以为没反应而反复点。"""
        self._b_stop.setEnabled(False)
        self._b_stop.setText(tr("liveview.btn.saving"))
        self._b_pause.setEnabled(False)
        self.set_timer(self._timer.text() or "00:00", tr("liveview.timer.saving"))

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        # 退出「保存中…」过渡态：任何态切换都复位结束/暂停按钮的可用与文案。
        self._b_stop.setEnabled(True)
        self._b_stop.setText(tr("liveview.btn.stop"))
        self._b_pause.setEnabled(True)
        live = mode in (MODE_LIVE, MODE_PAUSED)
        error = mode == MODE_ERROR
        # 内容区：录制/结束=转录流；就绪/错误=最近记录（错误态复用就绪布局 + 顶部错误横幅）。
        self._stack.setCurrentIndex(1 if mode in (MODE_LIVE, MODE_PAUSED, MODE_ENDED) else 0)
        self._error_banner.setVisible(error)
        # 侧栏始终保留：错误态也能就地换音频来源 + 重试。
        self._side.setVisible(True)
        # 记录头只在「有录制内容」时显示（录制中/暂停/已结束）。
        self._head.setVisible(mode in (MODE_LIVE, MODE_PAUSED, MODE_ENDED))
        self._btn_export.setVisible(mode == MODE_ENDED)
        # 控制按钮：就绪=开始，错误=重试（同一按钮，复用 startClicked）
        self._b_start.setVisible(mode in (MODE_READY, MODE_ERROR))
        if mode in (MODE_READY, MODE_ERROR):
            self._b_start.setText(tr("common.retry") if error else tr("liveview.btn.start"))
            self._b_start.setIcon(AppIcon.SYNC if error else AppIcon.PLAY)
        self._b_pause.setVisible(mode == MODE_LIVE)
        self._b_resume.setVisible(mode == MODE_PAUSED)
        self._b_stop.setVisible(live)
        self._b_view.setVisible(mode == MODE_ENDED)
        self._b_new.setVisible(mode == MODE_ENDED)  # 结束态：明确的「返回就绪/新建」路径
        # 结束态：当前段落落定成普通历史条（去掉「当前句」绿高亮）
        if mode == MODE_ENDED:
            self.transcript.finalize_all()
        # 设置可改性：录制中锁定来源/翻译/语言
        self._device_pill.setEnabled(not live)
        self._translate_sw.setEnabled(not live)
        self._lang_pill.setEnabled(not live)
        self._src_lang_pill.setEnabled(not live)  # 识别语言录制中锁定（改动需重开会话生效）
        if not live:
            self._meter.reset()  # 非录制态：波形归静音暗条
        # 头部文案默认（宿主可覆盖）
        defaults = {
            MODE_READY: (tr("liveview.ready.title"), tr("liveview.ready.detail")),
            MODE_ERROR: (tr("liveview.error.title"), tr("liveview.error.detail")),
        }
        if mode in defaults:
            self.set_record_title(*defaults[mode])
        labels = {
            MODE_READY: ("00:00", tr("liveview.timer.waiting")),
            MODE_ERROR: ("--:--", tr("liveview.error.title")),
        }
        if mode in labels:
            self.set_timer(*labels[mode])


class HistoryView(QWidget):
    """历史页：搜索 + 刷新 + 目录 + 卡片式记录列表。"""

    backClicked = pyqtSignal()
    refreshClicked = pyqtSignal()
    openDirClicked = pyqtSignal()
    recordOpened = pyqtSignal(object)
    renameRequested = pyqtSignal(object)
    exportRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)
    searchChanged = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        from videocaptioner.ui.components.workbench import AppLineEdit

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(_h2(tr("liveview.title.history"), self))
        head.addStretch(1)
        # 「返回」即回会话页（=实时字幕首页），不再放重复的「主页」
        self._back = CompactButton(tr("liveview.action.back"), AppIcon.ARROW_LEFT, self)
        self._back.clicked.connect(self.backClicked.emit)
        head.addWidget(self._back, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        root.addLayout(head)

        toolbar = _Panel(self)
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(16, 12, 16, 12)
        tl.setSpacing(12)
        self._search = AppLineEdit("", toolbar)
        self._search.setPlaceholderText(tr("liveview.history.search_placeholder"))
        self._search.textChanged.connect(self.searchChanged.emit)
        self._refresh = CompactButton(tr("liveview.action.refresh"), AppIcon.SYNC, toolbar)
        self._refresh.clicked.connect(self.refreshClicked.emit)
        self._dir = CompactButton(tr("liveview.action.folder"), AppIcon.FOLDER, toolbar)
        self._dir.clicked.connect(self.openDirClicked.emit)
        tl.addWidget(self._search, 1)
        tl.addWidget(self._refresh)
        tl.addWidget(self._dir)
        root.addWidget(toolbar)

        body = _Panel(self)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(0)
        self._list = _ScrollList(body)
        bl.addWidget(self._list, 1)
        self._empty = _EmptyState(AppIcon.HISTORY, tr("liveview.history.empty.title"),
                                  tr("liveview.history.empty.detail"), body)
        bl.addWidget(self._empty)
        self._empty.setVisible(False)
        root.addWidget(body, 1)

    def set_records(self, records: List[LiveCaptionRecord]) -> None:
        self._list.clear()
        for rec in records:
            row = _HistoryRow(rec, self._list)
            row.opened.connect(self.recordOpened.emit)
            row.renameRequested.connect(self.renameRequested.emit)
            row.exportRequested.connect(self.exportRequested.emit)
            row.deleteRequested.connect(self.deleteRequested.emit)
            self._list.add(row)
        empty = self._list.count() == 0
        self._empty.setVisible(empty)
        self._list.setVisible(not empty)


class DetailView(QWidget):
    """详情页：元信息 + 转录时间线 + 显示切换 + 导出 + 音频播放器。"""

    backClicked = pyqtSignal()
    homeClicked = pyqtSignal()
    exportRequested = pyqtSignal(str)  # "srt" / "txt"
    openFolderRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._record: Optional[LiveCaptionRecord] = None
        self._build()

    def _build(self) -> None:
        p = app_palette()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(_h2(tr("liveview.title.detail"), self))
        head.addStretch(1)
        self._home = CompactButton(tr("liveview.action.home"), AppIcon.HOME, self)
        self._home.clicked.connect(self.homeClicked.emit)
        self._back = CompactButton(tr("liveview.action.back"), AppIcon.ARROW_LEFT, self)
        self._back.clicked.connect(self.backClicked.emit)
        head.addWidget(self._home, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        head.addWidget(self._back, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        root.addLayout(head)

        top = _Panel(self)
        topl = QHBoxLayout(top)
        topl.setContentsMargins(20, 14, 20, 14)
        topl.setSpacing(12)
        self._mark = IconBox(AppIcon.MICROPHONE, top, size=40, tone="accent")
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self._title = QLabel(top)
        apply_font(self._title, 16, 850)
        self._title.setStyleSheet(f"color:{p.text};background:transparent;")
        self._sub = QLabel(top)
        apply_font(self._sub, 13, 600)
        self._sub.setStyleSheet(f"color:{p.subtle};background:transparent;")
        tcol.addWidget(self._title)
        tcol.addWidget(self._sub)
        topl.addWidget(self._mark, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        topl.addLayout(tcol, 1)
        root.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(16)
        self._tpanel = _Panel(self)
        tpl = QVBoxLayout(self._tpanel)
        tpl.setContentsMargins(8, 12, 8, 12)
        self.transcript = TranscriptList(self._tpanel, selectable=True)  # 文字可选中复制
        self.transcript.entryActivated.connect(self._on_entry)
        tpl.addWidget(self.transcript)
        body.addWidget(self._tpanel, 1)

        side = QWidget(self)
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        disp = _Panel(side)
        dl = QVBoxLayout(disp)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(12)
        dt = QLabel(tr("liveview.detail.display"), disp)
        apply_font(dt, 15, 850)
        dt.setStyleSheet(f"color:{p.text};background:transparent;")
        dl.addWidget(dt)
        self._display_tabs = FilterTabs(
            [
                (DISPLAY_BILINGUAL, tr("liveview.display.bilingual")),
                (DISPLAY_SOURCE, tr("liveview.display.source")),
                (DISPLAY_TARGET, tr("liveview.display.target")),
            ],
            disp,
        )
        self._display_tabs.changed.connect(self.transcript.set_display)
        dl.addWidget(self._display_tabs)
        sl.addWidget(disp)
        exp = _Panel(side)
        el = QVBoxLayout(exp)
        el.setContentsMargins(18, 16, 18, 16)
        el.setSpacing(10)
        et = QLabel(tr("liveview.detail.export"), exp)
        apply_font(et, 15, 850)
        et.setStyleSheet(f"color:{p.text};background:transparent;")
        el.addWidget(et)
        self._exp_srt = WorkbenchButton(tr("liveview.export.srt"), AppIcon.DOWNLOAD)
        self._exp_srt.clicked.connect(lambda: self.exportRequested.emit("srt"))
        self._exp_txt = WorkbenchButton(tr("liveview.export.txt"), AppIcon.DOCUMENT)
        self._exp_txt.clicked.connect(lambda: self.exportRequested.emit("txt"))
        self._open_dir = WorkbenchButton(tr("common.open_folder"), AppIcon.FOLDER)
        self._open_dir.clicked.connect(self.openFolderRequested.emit)
        el.addWidget(self._exp_srt)
        el.addWidget(self._exp_txt)
        el.addWidget(self._open_dir)
        sl.addWidget(exp)
        sl.addStretch(1)
        body.addWidget(side)
        root.addLayout(body, 1)

        self.player = AudioPlayerBar(self)
        self.player.sentenceChanged.connect(self.transcript.set_playing)
        root.addWidget(self.player)

        # 播放器快捷键（焦点在详情页内即生效）：空格 播放/暂停，←→ ±5s，↑↓ 上/下一句
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QShortcut

        self.setFocusPolicy(Qt.StrongFocus)  # type: ignore[arg-type]

        def _sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)  # type: ignore[arg-type]
            s.activated.connect(fn)

        _sc(Qt.Key_Space, self.player.toggle)  # type: ignore[arg-type]
        _sc(Qt.Key_Left, lambda: self.player.seek_relative(-5000))  # type: ignore[arg-type]
        _sc(Qt.Key_Right, lambda: self.player.seek_relative(5000))  # type: ignore[arg-type]
        _sc(Qt.Key_Up, lambda: self.player.step_sentence(-1))  # type: ignore[arg-type]
        _sc(Qt.Key_Down, lambda: self.player.step_sentence(1))  # type: ignore[arg-type]

    def load(self, record: LiveCaptionRecord) -> None:
        self._record = record
        self._title.setText(record.name)
        self._sub.setText(record.summary)
        self.transcript.set_segments(record.segments, _fmt_pos)
        starts = [s.start for s in record.segments]
        self.player.load(record.audio_path, starts, record.duration)
        self.player.setVisible(record.audio_path is not None)
        self.setFocus()  # 进入详情即可用播放快捷键

    def _on_entry(self, index: int) -> None:
        # 点击某句 → 跳到该句对应时间并从那里开始播放
        self.player.seek_sentence(index)
        self.player.play()
        self.transcript.set_playing(index)
        self.transcript.scroll_to_index(index)

    def stop_playback(self) -> None:
        self.player.stop()
