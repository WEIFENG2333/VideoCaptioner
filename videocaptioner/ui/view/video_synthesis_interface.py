# -*- coding: utf-8 -*-
"""字幕视频合成页：组合开关工作台。

左侧是输入文件面板（拖放 / 文件清单 / 生成计划 / 结果文件），
右侧是可折叠的「本次生成」栏（输出内容开关 + 参数 + 主按钮）。

输出由两个开关组合驱动：

    字幕视频（cfg.need_video）   需要 字幕 + 视频
    配音音轨（cfg.dubbing_enabled） 仅需字幕，视频可选（选了则额外产出配音视频）

生命周期状态（PageState）只有 IDLE / RUNNING / DONE；
IDLE 下的具体呈现（空态 / 缺文件 / 配置缺失 / 可生成）由 _evaluate()
根据开关与输入实时计算，避免组合爆炸。

线程统一由 SynthesisController 持有（配音 -> 合成 链式编排在控制器内，
进度按 0-55 / 55-100 映射）；对外接口与其它工作台页一致：
    finished()  /  set_task(task) / process() / close()
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.core.application import output_paths
from videocaptioner.core.dubbing import get_dubbing_preset
from videocaptioner.core.entities import (
    DubbingTask,
    SubtitleRenderModeEnum,
    SupportedSubtitleFormats,
    SupportedVideoFormats,
    SynthesisTask,
    VideoInfo,
    VideoQualityEnum,
)
from videocaptioner.core.subtitle.ass_renderer import ffmpeg_supports_ass_filter
from videocaptioner.core.utils.platform_utils import open_folder, reveal_in_explorer
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.dubbing_options import get_provider_voices
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.workbench import (
    CollapsibleSideHost,
    CompactButton,
    DropZone,
    ElidedLabel,
    ErrorCard,
    HeaderLinkButton,
    IconBox,
    MediaThumb,
    OptionCard,
    PanelHeader,
    PillSelect,
    ProgressBarLine,
    RoundIconButton,
    SectionLabel,
    StatusPill,
    ToggleCard,
    ToggleSwitch,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    draw_rounded_surface,
    file_type_icon,
    icon_pixmap,
)
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.dubbing_thread import DubbingThread
from videocaptioner.ui.thread.video_info_thread import VideoInfoThread
from videocaptioner.ui.thread.video_synthesis_thread import VideoSynthesisThread

_SUBTITLE_FORMATS = {fmt.value for fmt in SupportedSubtitleFormats}
_VIDEO_FORMATS = {fmt.value for fmt in SupportedVideoFormats}

TEXT_TRACK_LABELS = {"auto": "自动选择", "first": "第一行", "second": "第二行"}


def _voice_labels() -> dict[str, str]:
    """当前配音提供商的可选音色（preset -> 标题），与配音页提供商选择联动。"""
    return {
        voice.preset: voice.title
        for voice in get_provider_voices(cfg.dubbing_provider.value)
    }
TIMING_LABELS = {"natural": "自然", "balanced": "平衡", "strict": "严格贴合"}
AUDIO_MODE_LABELS = {"replace": "替换原声", "mix": "混合原声", "duck": "压低原声"}
SUBTITLE_MODE_LABELS = {False: "硬字幕", True: "软字幕"}


class PageState(Enum):
    IDLE = auto()
    RUNNING = auto()
    DONE = auto()


@dataclass
class Readiness:
    """IDLE 状态的呈现计算结果。"""

    view: str  # "empty" / "files"
    title: str
    bottom: str
    pill: tuple[str, str]
    primary: tuple[str, AppIcon, bool]  # 文案 / 图标 / 是否可点
    blocker: str = ""  # 右栏错误卡文案（缺 Key / 缺 FFmpeg 等）
    plan: list[str] = field(default_factory=list)  # 生成计划步骤标题


# ---------------------------------------------------------------------------
# 线程编排
# ---------------------------------------------------------------------------


class SynthesisController(QObject):
    """编排配音 / 合成线程；全流程时在控制器内链式执行。

    进度映射：全流程 配音 0-55、合成 55-100；单流程 0-100。
    """

    progressChanged = pyqtSignal(int, str)
    completed = pyqtSignal(list)  # [(标签, 路径)]
    failed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._dubbing_thread: Optional[DubbingThread] = None
        self._synthesis_thread: Optional[VideoSynthesisThread] = None
        self._chained_synthesis: Optional[SynthesisTask] = None
        self._results: list[tuple[str, str]] = []
        self._cancelled = False

    # ----- 启动 -----

    def start_synthesis_only(self, task: SynthesisTask) -> bool:
        if self.is_running():
            return False
        self._results = []
        self._chained_synthesis = None
        self._cancelled = False
        self._start_synthesis(task, offset=0)
        return True

    def start_dubbing(
        self, task: DubbingTask, chained_synthesis: Optional[SynthesisTask] = None
    ) -> bool:
        """配音；chained_synthesis 不为空时配音完成后接续视频合成。"""
        if self.is_running():
            return False
        self._results = []
        self._chained_synthesis = chained_synthesis
        self._cancelled = False
        thread = DubbingThread(task)
        thread.finished.connect(self._on_dubbing_finished)
        thread.progress.connect(self._on_dubbing_progress)
        thread.error.connect(self.failed)
        self._dubbing_thread = thread
        thread.start()
        return True

    # ----- 内部链路 -----

    def _start_synthesis(self, task: SynthesisTask, offset: int):
        thread = VideoSynthesisThread(task)
        thread.finished.connect(self._on_synthesis_finished)
        scale = (100 - offset) / 100
        thread.progress.connect(
            lambda value, message: self.progressChanged.emit(
                int(offset + value * scale), message
            )
        )
        thread.error.connect(self.failed)
        self._synthesis_thread = thread
        thread.start()

    def _on_dubbing_progress(self, value: int, message: str):
        if self._chained_synthesis is not None:
            value = int(value * 0.55)
        self.progressChanged.emit(value, message)

    def _on_dubbing_finished(self, task: DubbingTask):
        # 取消后已投递的 queued finished 信号仍会到达，丢弃以免启动已取消的链式合成。
        if self._cancelled:
            return
        if task.output_audio_path:
            self._results.append(("配音音频", task.output_audio_path))
        if self._chained_synthesis is not None:
            if not task.output_video_path:
                self.failed.emit("配音视频输出路径为空")
                return
            synthesis = self._chained_synthesis
            self._chained_synthesis = None
            synthesis.video_path = task.output_video_path
            self._start_synthesis(synthesis, offset=55)
            return
        if task.output_video_path:
            self._results.append(("配音视频", task.output_video_path))
        self.completed.emit(list(self._results))

    def _on_synthesis_finished(self, task: SynthesisTask):
        if self._cancelled:
            return
        # 链式模式的中间配音视频在任务目录里，随任务目录由页面统一清理。
        if task.output_path:
            self._results.insert(0, ("字幕视频", task.output_path))
        self.completed.emit(list(self._results))

    # ----- 控制 -----

    def is_running(self) -> bool:
        return any(
            thread is not None and thread.isRunning()
            for thread in (self._dubbing_thread, self._synthesis_thread)
        )

    def cancel(self):
        self._cancelled = True
        self._chained_synthesis = None
        for attr in ("_dubbing_thread", "_synthesis_thread"):
            thread = getattr(self, attr)
            setattr(self, attr, None)
            if thread is not None and thread.isRunning():
                try:
                    thread.finished.disconnect()
                    thread.progress.disconnect()
                    thread.error.disconnect()
                except TypeError:
                    pass
                thread.stop()

    def shutdown(self):
        for thread in (self._dubbing_thread, self._synthesis_thread):
            if thread is not None:
                thread.stop()


# ---------------------------------------------------------------------------
# 左侧：文件行 / 计划行 / 结果行 / 底部状态条
# ---------------------------------------------------------------------------


class FileStateRow(QFrame):
    """输入文件行：名称 + 说明 + 状态胶囊；缺失时虚线边。"""

    clicked = pyqtSignal()

    def __init__(self, label: str, icon: AppIcon = AppIcon.FILE, parent=None):
        super().__init__(parent)
        self.setObjectName("fileStateRow")
        self._missing = True
        self._icon = icon
        self.setMinimumHeight(56)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(18, 18)
        layout.addWidget(self.iconLabel)
        self.nameLabel = QLabel(label, self)
        self.nameLabel.setObjectName("fileRowName")
        self.nameLabel.setFixedWidth(76)
        apply_font(self.nameLabel, 14, 850)
        layout.addWidget(self.nameLabel)
        self.detailLabel = ElidedLabel("", self)
        self.detailLabel.setObjectName("fileRowDetail")
        apply_font(self.detailLabel, 14, 720)
        layout.addWidget(self.detailLabel, 1)
        self.pill = StatusPill("", "warn", self)
        layout.addWidget(self.pill)
        self.syncStyle()

    def setName(self, name: str):
        self.nameLabel.setText(name)

    def setState(self, detail: str, pill_text: str, level: str, missing: bool):
        self.detailLabel.setText(detail)
        self.pill.setState(pill_text, level)
        if missing != self._missing:
            self._missing = missing
            self.update()
        self.syncStyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QPainter, QPainterPath, QPen

        from videocaptioner.ui.components.workbench import to_qcolor

        palette = app_palette()
        surface = palette.card_surface
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.fillPath(path, to_qcolor(surface))
        pen = QPen(to_qcolor(palette.line_soft), 1)
        if self._missing:
            pen.setStyle(Qt.DashLine)  # type: ignore[attr-defined]
        painter.setPen(pen)
        painter.drawPath(path)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        detail_color = palette.subtle if self._missing else palette.muted
        self.iconLabel.setPixmap(
            icon_pixmap(self._icon, palette.subtle if self._missing else palette.muted, 18)
        )
        self.setStyleSheet(
            f"""
            QFrame#fileStateRow {{ background: transparent; border: none; }}
            QLabel#fileRowName {{ color: {palette.text}; background: transparent; }}
            QLabel#fileRowDetail {{ color: {detail_color}; background: transparent; }}
            """
        )


class PlanStepRow(QFrame):
    """生成计划行：图标 + 步骤名 + 状态胶囊。"""

    def __init__(self, icon: AppIcon, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("planStepRow")
        self._icon = icon
        self.setMinimumHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        self.iconBox = IconBox(self._icon, self, size=32, tone="accent")
        layout.addWidget(self.iconBox)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("planTitle")
        apply_font(self.titleLabel, 15, 820)
        layout.addWidget(self.titleLabel, 1)
        self.pill = StatusPill(self.tr("待生成"), "neutral", self)
        layout.addWidget(self.pill)
        self.syncStyle()

    def setTitle(self, title: str):
        self.titleLabel.setText(title)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconBox.syncStyle()
        self.setStyleSheet(
            f"""
            QFrame#planStepRow {{ background: transparent; border: none; }}
            QLabel#planTitle {{ color: {palette.text}; background: transparent; }}
            """
        )


class SynthesisBottomBar(QFrame):
    """底部状态条：提示文案 +（运行中）进度条 + 状态胶囊。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("synthesisBottomBar")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 14, 0)
        layout.setSpacing(14)
        # 消息文本用弹性省略吸收长度变化，进度条与胶囊右锚定；
        # 百分比胶囊固定最小宽（"100%"），位数变化不再让整行抖动
        self.messageLabel = ElidedLabel("", self)
        self.messageLabel.setObjectName("bottomMessage")
        apply_font(self.messageLabel, 14, 730)
        layout.addWidget(self.messageLabel, 1)
        self.progressLine = ProgressBarLine(self)
        self.progressLine.setFixedWidth(320)
        self.progressLine.hide()
        layout.addWidget(self.progressLine)
        self.pill = StatusPill("", "warn", self)
        self.pill.setMinimumWidth(66)
        layout.addWidget(self.pill)
        self.syncStyle()

    def setState(self, message: str, pill_text: str, level: str, progress: int = -1):
        self.messageLabel.setText(message)
        self.pill.setState(pill_text, level)
        self.progressLine.setVisible(progress >= 0)
        if progress >= 0:
            self.progressLine.setValue(progress)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#synthesisBottomBar {{
                background: transparent;
                border: none;
                border-top: 1px solid {palette.line_soft};
            }}
            QLabel#bottomMessage {{ color: {palette.muted}; background: transparent; }}
            """
        )


class ResultFileRow(QFrame):
    """结果文件行：名称 + 元信息 + 完成胶囊，点击打开。"""

    clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultFileRow")
        self._path = ""
        self.setMinimumHeight(58)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)
        self._icon = AppIcon.FILE
        self.iconBox = QFrame(self)
        self.iconBox.setObjectName("resultIconBox")
        self.iconBox.setFixedSize(34, 34)
        icon_layout = QVBoxLayout(self.iconBox)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self.iconBox)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        icon_layout.addWidget(self.iconLabel)
        layout.addWidget(self.iconBox)
        column = QVBoxLayout()
        column.setSpacing(4)
        self.nameLabel = ElidedLabel("", self)
        self.nameLabel.setObjectName("resultRowName")
        apply_font(self.nameLabel, 15, 840)
        column.addWidget(self.nameLabel)
        self.metaLabel = QLabel(self)
        self.metaLabel.setObjectName("resultRowMeta")
        apply_font(self.metaLabel, 13, 760)
        column.addWidget(self.metaLabel)
        layout.addLayout(column, 1)
        self.pill = StatusPill(self.tr("完成"), "ok", self)
        layout.addWidget(self.pill)
        self.syncStyle()

    def setResult(self, label: str, path: str):
        self._path = path
        file = Path(path)
        self._icon = file_type_icon(path)
        self.syncStyle()
        self.nameLabel.setText(file.name)
        suffix = file.suffix.lstrip(".").upper()
        size = ""
        if file.exists():
            size = f" · {max(1, file.stat().st_size // 1024)} KB"
            if file.stat().st_size >= 1024 * 1024:
                size = f" · {file.stat().st_size / 1024 / 1024:.1f} MB"
        self.metaLabel.setText(f"{label} · {suffix}{size}")
        self.setToolTip(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._path:  # type: ignore[attr-defined]
            self.clicked.emit(self._path)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconLabel.setPixmap(icon_pixmap(self._icon, palette.muted, 17))
        self.setStyleSheet(
            f"""
            QFrame#resultFileRow {{ background: transparent; border: none; }}
            QFrame#resultIconBox {{
                background: {palette.control};
                border: none;
                border-radius: 10px;
            }}
            QLabel#resultRowName {{ color: {palette.text}; background: transparent; }}
            QLabel#resultRowMeta {{ color: {palette.subtle}; background: transparent; }}
            """
        )


def _section_label(text: str, parent=None) -> QLabel:
    return SectionLabel(text, parent)


# ---------------------------------------------------------------------------
# 右侧：本次生成面板
# ---------------------------------------------------------------------------


class GeneratePanel(WorkbenchPanel):
    """右侧「本次生成」：输出内容开关 + 字幕/配音参数 + 主按钮。"""

    settingsRequested = pyqtSignal()
    collapseRequested = pyqtSignal()
    voiceLibraryRequested = pyqtSignal()
    styleLibraryRequested = pyqtSignal()
    primaryRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    openFolderRequested = pyqtSignal()

    def __init__(self, parent=None):
        # 自管内边距：滚动区横向通到面板边，滚动条落在右侧留白带里，
        # 不再贴着参数卡；头部 / 参数卡 / 底部按钮仍按 22 对齐。
        super().__init__(parent, padded=False)
        self.bodyLayout.setContentsMargins(0, 22, 0, 22)
        self.bodyLayout.setSpacing(0)

        self.header = PanelHeader(
            self.tr("本次生成"), inline=True, underline=True, parent=self
        )
        # 直径与转录/字幕页右栏头部按钮一致（默认 34）
        self.collapseButton = RoundIconButton(AppIcon.RIGHT_ARROW, parent=self)
        self.collapseButton.setToolTip(self.tr("收起本栏"))
        self.collapseButton.clicked.connect(self.collapseRequested)
        self.header.addRight(self.collapseButton)
        self.configButton = RoundIconButton(AppIcon.SETTING, parent=self)
        self.configButton.setToolTip(self.tr("打开合成配置"))
        self.configButton.clicked.connect(self.settingsRequested)
        self.header.addRight(self.configButton)
        head_wrap = QVBoxLayout()
        head_wrap.setContentsMargins(22, 0, 22, 0)
        head_wrap.addWidget(self.header)
        self.bodyLayout.addLayout(head_wrap)

        body = QVBoxLayout()
        # 顶部 18 / 卡片间距 14：与转录、字幕处理页右栏参数区一致；
        # 右 12 + 滚动条列 10 = 22，参数卡与头部 / 底部按钮对齐；
        # 底部留白：滚动到底时最后一张参数卡不贴视口边（否则像被截断）
        body.setContentsMargins(22, 18, 12, 12)
        body.setSpacing(14)

        body.addWidget(_section_label(self.tr("输出内容"), self))
        self.subtitleCard = ToggleCard(
            self.tr("字幕视频"), self.tr("把字幕合成到视频里"), parent=self
        )
        body.addWidget(self.subtitleCard)
        self.dubbingCard = ToggleCard(
            self.tr("配音音轨"), self.tr("按字幕生成配音"), parent=self
        )
        body.addWidget(self.dubbingCard)

        self.errorCard = ErrorCard(parent=self)
        self.errorCard.hide()
        body.addWidget(self.errorCard)

        # 字幕视频参数
        self.subtitleSection = QWidget(self)
        subtitle_layout = QVBoxLayout(self.subtitleSection)
        subtitle_layout.setContentsMargins(0, 6, 0, 0)
        subtitle_layout.setSpacing(14)
        subtitle_layout.addWidget(_section_label(self.tr("字幕视频参数"), self))
        self.subtitleModeSelect = PillSelect(self)
        subtitle_layout.addWidget(OptionCard(self.tr("字幕方式"), self.subtitleModeSelect, self))
        self.styleSwitch = ToggleSwitch(parent=self)
        self.styleCard = OptionCard(self.tr("字幕样式"), self.styleSwitch, self)
        subtitle_layout.addWidget(self.styleCard)
        self.styleCard.hide()
        self.renderModeSelect = PillSelect(self)
        self.renderModeCard = OptionCard(self.tr("渲染模式"), self.renderModeSelect, self)
        subtitle_layout.addWidget(self.renderModeCard)
        style_control = QWidget(self)
        style_row = QHBoxLayout(style_control)
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.setSpacing(8)
        self.stylePageLink = HeaderLinkButton(self.tr("样式页"), AppIcon.SUBTITLE, self)
        self.stylePageLink.clicked.connect(self.styleLibraryRequested)
        style_row.addWidget(self.stylePageLink)
        style_row.addStretch(1)
        self.stylePageCard = OptionCard(self.tr("样式"), style_control, self)
        subtitle_layout.addWidget(self.stylePageCard)
        self.qualitySelect = PillSelect(self)
        self.qualityCard = OptionCard(self.tr("视频质量"), self.qualitySelect, self)
        subtitle_layout.addWidget(self.qualityCard)
        body.addWidget(self.subtitleSection)

        # 配音参数
        self.dubbingSection = QWidget(self)
        dubbing_layout = QVBoxLayout(self.dubbingSection)
        dubbing_layout.setContentsMargins(0, 6, 0, 0)
        dubbing_layout.setSpacing(14)
        dubbing_layout.addWidget(_section_label(self.tr("配音参数"), self))
        voice_control = QWidget(self)
        voice_row = QHBoxLayout(voice_control)
        voice_row.setContentsMargins(0, 0, 0, 0)
        voice_row.setSpacing(8)
        self.voiceSelect = PillSelect(self)
        voice_row.addWidget(self.voiceSelect)
        self.voiceLibraryLink = HeaderLinkButton(self.tr("音色库"), AppIcon.MUSIC, self)
        self.voiceLibraryLink.clicked.connect(self.voiceLibraryRequested)
        voice_row.addWidget(self.voiceLibraryLink)
        dubbing_layout.addWidget(OptionCard(self.tr("音色"), voice_control, self))
        self.textTrackSelect = PillSelect(self)
        dubbing_layout.addWidget(OptionCard(self.tr("文本轨道"), self.textTrackSelect, self))
        self.timingSelect = PillSelect(self)
        self.timingCard = OptionCard(self.tr("时间贴合"), self.timingSelect, self)
        dubbing_layout.addWidget(self.timingCard)
        self.audioModeSelect = PillSelect(self)
        self.audioModeCard = OptionCard(self.tr("音频处理"), self.audioModeSelect, self)
        dubbing_layout.addWidget(self.audioModeCard)
        body.addWidget(self.dubbingSection)
        body.addStretch(1)

        # 参数区可滚动：两组输出全开时参数较多，矮窗口下不挤掉主按钮
        body_host = QWidget(self)
        body_host.setLayout(body)
        self.bodyScroll = QScrollArea(self)
        self.bodyScroll.setWidgetResizable(True)
        self.bodyScroll.setFrameShape(QFrame.NoFrame)
        self.bodyScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self.bodyScroll.setWidget(body_host)
        self.bodyLayout.addWidget(self.bodyScroll, 1)

        # 底部：分隔线 + 操作按钮，左右 22 与头部对齐
        bottom = QVBoxLayout()
        bottom.setContentsMargins(22, 0, 22, 0)
        bottom.setSpacing(0)
        # 滚动区与按钮区之间留间隔 + 分隔线（仅参数溢出可滚时出现），
        # 否则滚动中被视口裁切的参数卡看起来像被按钮盖住
        bottom.addSpacing(10)
        self.scrollDivider = QFrame(self)
        self.scrollDivider.setObjectName("scrollDivider")
        self.scrollDivider.setFixedHeight(1)
        self.scrollDivider.hide()
        self.bodyScroll.verticalScrollBar().rangeChanged.connect(
            lambda _min, max_value: self.scrollDivider.setVisible(max_value > 0)
        )
        bottom.addWidget(self.scrollDivider)
        bottom.addSpacing(10)

        self.cancelButton = WorkbenchButton(self.tr("取消"), AppIcon.CANCEL, parent=self)
        self.cancelButton.clicked.connect(self.cancelRequested)
        self.cancelButton.hide()
        bottom.addWidget(self.cancelButton)
        bottom.addSpacing(10)
        self.openFolderButton = WorkbenchButton(
            self.tr("打开文件夹"), AppIcon.FOLDER, parent=self
        )
        self.openFolderButton.clicked.connect(self.openFolderRequested)
        self.openFolderButton.hide()
        bottom.addWidget(self.openFolderButton)
        bottom.addSpacing(10)
        self.primaryButton = WorkbenchButton(
            self.tr("等待文件"), AppIcon.FILE, primary=False, height=48, parent=self
        )
        self.primaryButton.setEnabled(False)
        self.primaryButton.clicked.connect(self.primaryRequested)
        bottom.addWidget(self.primaryButton)
        self.bodyLayout.addLayout(bottom)
        self.syncStyle()

    def setError(self, message: str):
        self.errorCard.setText(message)
        self.errorCard.setVisible(bool(message))

    def setButton(self, text: str, *, icon: AppIcon, primary: bool, enabled: bool):
        self.primaryButton.setText(text)
        self.primaryButton.setIcon(icon)
        self.primaryButton.setPrimary(primary)
        self.primaryButton.setEnabled(enabled)

    def syncStyle(self):
        super().syncStyle()
        palette = app_palette()
        if hasattr(self, "errorCard"):
            self.errorCard.syncStyle()
        if hasattr(self, "scrollDivider"):
            self.scrollDivider.setStyleSheet(
                f"background: {palette.line_soft}; border: none;"
            )
        if hasattr(self, "bodyScroll"):
            # 滚动条规则必须并在 QScrollArea 自己的样式表里：macOS 上只给
            # QScrollBar 子控件设样式时仍走 transient 浮层模式（不占布局空间），
            # 滚动条会盖在参数卡右缘上；并入后强制占位模式，对齐才成立。
            self.bodyScroll.setStyleSheet(
                f"""
                QScrollArea {{ background: transparent; border: none; }}
                QScrollBar:vertical {{
                    background: transparent; width: 10px; margin: 2px 3px;
                }}
                QScrollBar::handle:vertical {{
                    background: {rgba(palette.muted, 0.32)};
                    border-radius: 2px; min-height: 28px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: transparent;
                }}
                """
            )
            self.bodyScroll.widget().setStyleSheet("background: transparent;")


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


class VideoSynthesisInterface(QWidget):
    """字幕视频合成页（组合开关工作台）。"""

    finished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("VideoSynthesisInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self.state = PageState.IDLE
        self.subtitle_path: Optional[str] = None
        self.video_path: Optional[str] = None
        self.task: Optional[SynthesisTask] = None
        self._results: list[tuple[str, str]] = []
        self._active_task_dir: Optional[str] = None
        self._pipeline_task_dir: Optional[str] = None
        self._config_signal_connections: list[tuple] = []

        self.controller = SynthesisController(self)
        self._info_thread: Optional[VideoInfoThread] = None
        self._build_ui()
        self._connect_signals()
        self._load_options_from_config()
        self._refresh()
        if cfg.synthesis_panel_collapsed.value:
            self.sideHost.setCollapsed(True, animate=False)
            self._sync_collapsed_controls()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QWidget#VideoSynthesisInterface {{ background: {palette.bg}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 2)
        root.setSpacing(18)

        # 左：输入 / 计划 / 结果面板
        self.workspace = WorkbenchPanel(self, padded=False)
        self.header = PanelHeader(self.tr("输入文件"), inline=False, parent=self.workspace)
        self.subtitleButton = CompactButton(self.tr("选择字幕"), AppIcon.FOLDER_ADD, self)
        self.header.addRight(self.subtitleButton)
        self.videoButton = CompactButton(self.tr("选择视频"), AppIcon.FOLDER_ADD, self)
        self.header.addRight(self.videoButton)
        self.headStartButton = WorkbenchButton(
            self.tr("生成成片"), AppIcon.PLAY, primary=True, height=32, parent=self
        )
        self.headStartButton.setMinimumWidth(104)
        self.headStartButton.hide()
        self.header.addRight(self.headStartButton)
        self.expandButton = RoundIconButton(AppIcon.LAYOUT, diameter=32, parent=self)
        self.expandButton.setToolTip(self.tr("展开生成栏"))
        self.expandButton.hide()
        self.header.addRight(self.expandButton)
        self.workspace.bodyLayout.addWidget(self.header)

        self.stack = QStackedWidget(self)

        # 空态拖放
        self.dropZone = DropZone(
            icon=AppIcon.VIDEO,
            title=self.tr("拖入字幕和视频文件"),
            pick_text=self.tr("点击选择文件"),
            pick_icon=AppIcon.FOLDER_ADD,
            formats_line=self.tr("字幕：srt / ass / vtt    视频：mp4 / mov / mkv"),
            parent=self,
        )
        drop_host = QWidget(self)
        drop_layout = QVBoxLayout(drop_host)
        drop_layout.setContentsMargins(16, 16, 16, 16)
        drop_layout.addWidget(self.dropZone)
        self.stack.addWidget(drop_host)

        # 文件清单 + 生成计划
        inputs_host = QWidget(self)
        inputs_layout = QVBoxLayout(inputs_host)
        inputs_layout.setContentsMargins(16, 16, 16, 16)
        inputs_layout.setSpacing(10)
        self.subtitleRow = FileStateRow(self.tr("字幕文件"), AppIcon.SUBTITLE, self)
        inputs_layout.addWidget(self.subtitleRow)
        self.videoRow = FileStateRow(self.tr("视频文件"), AppIcon.VIDEO, self)
        inputs_layout.addWidget(self.videoRow)
        inputs_layout.addSpacing(8)
        self.planSteps: list[PlanStepRow] = [
            PlanStepRow(AppIcon.VOLUME, self.tr("生成配音音轨"), self),
            PlanStepRow(AppIcon.SUBTITLE, self.tr("合成字幕视频"), self),
            PlanStepRow(AppIcon.FOLDER, self.tr("保存结果文件"), self),
        ]
        for step in self.planSteps:
            inputs_layout.addWidget(step)
        inputs_layout.addStretch(1)
        self.stack.addWidget(inputs_host)

        # 结果视图
        done_host = QWidget(self)
        done_layout = QVBoxLayout(done_host)
        done_layout.setContentsMargins(16, 16, 16, 16)
        done_layout.setSpacing(12)
        self.resultThumb = MediaThumb(self)
        self.resultThumb.setMinimumHeight(240)
        done_layout.addWidget(self.resultThumb, 1)
        self.resultRows = [ResultFileRow(self), ResultFileRow(self)]
        for row in self.resultRows:
            row.hide()
            done_layout.addWidget(row)
        self.stack.addWidget(done_host)

        self.workspace.bodyLayout.addWidget(self.stack, 1)
        self.bottomBar = SynthesisBottomBar(self)
        self.workspace.bodyLayout.addWidget(self.bottomBar)
        root.addWidget(self.workspace, 1)

        # 右：本次生成（可折叠）
        self.generatePanel = GeneratePanel(self)
        self.sideHost = CollapsibleSideHost(self.generatePanel, parent=self)
        root.addWidget(self.sideHost, 1)

    # ------------------------------------------------------------- signals

    def _connect_signals(self):
        self.controller.progressChanged.connect(self._on_progress)
        self.controller.completed.connect(self._on_completed)
        self.controller.failed.connect(self._on_failed)

        self.dropZone.browseRequested.connect(self._browse_any)
        self.subtitleButton.clicked.connect(self._browse_subtitle)
        self.videoButton.clicked.connect(self._browse_video)
        self.subtitleRow.clicked.connect(self._browse_subtitle)
        self.videoRow.clicked.connect(self._browse_video)
        self.headStartButton.clicked.connect(self._on_primary)
        self.expandButton.clicked.connect(lambda: self.sideHost.setCollapsed(False))

        panel = self.generatePanel
        panel.primaryRequested.connect(self._on_primary)
        panel.cancelRequested.connect(self._cancel)
        panel.openFolderRequested.connect(self._open_result_folder)
        panel.settingsRequested.connect(self._open_synthesis_settings)
        panel.voiceLibraryRequested.connect(self._open_voice_library)
        panel.styleLibraryRequested.connect(self._open_subtitle_style_library)
        panel.collapseRequested.connect(lambda: self.sideHost.setCollapsed(True))
        self.sideHost.collapsedChanged.connect(self._on_panel_collapsed)
        for row in self.resultRows:
            row.clicked.connect(self._open_file)

        panel.subtitleCard.toggled.connect(
            lambda checked: self._set_config_bool(cfg.need_video, checked)
        )
        panel.dubbingCard.toggled.connect(
            lambda checked: self._set_config_bool(cfg.dubbing_enabled, checked)
        )
        panel.subtitleModeSelect.currentTextChanged.connect(self._on_subtitle_mode)
        panel.renderModeSelect.currentTextChanged.connect(self._on_render_mode)
        panel.qualitySelect.currentTextChanged.connect(self._on_quality)
        panel.voiceSelect.currentTextChanged.connect(self._on_voice)
        panel.textTrackSelect.currentTextChanged.connect(
            lambda text: self._set_label_config(cfg.dubbing_text_track, TEXT_TRACK_LABELS, text)
        )
        panel.timingSelect.currentTextChanged.connect(
            lambda text: self._set_label_config(cfg.dubbing_timing, TIMING_LABELS, text)
        )
        panel.audioModeSelect.currentTextChanged.connect(
            lambda text: self._set_label_config(cfg.dubbing_audio_mode, AUDIO_MODE_LABELS, text)
        )

        self._connect_config_signal(cfg.need_video, self._on_outputs_changed)
        self._connect_config_signal(cfg.dubbing_enabled, self._on_outputs_changed)

    def _connect_config_signal(self, option, handler: Callable):
        option.valueChanged.connect(handler)
        self._config_signal_connections.append((option.valueChanged, handler))

    def _disconnect_config_signals(self):
        for signal, handler in self._config_signal_connections:
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass
        self._config_signal_connections.clear()

    # ------------------------------------------------------- config <-> UI

    def _load_options_from_config(self):
        panel = self.generatePanel
        panel.subtitleCard.setChecked(bool(cfg.need_video.value))
        panel.dubbingCard.setChecked(bool(cfg.dubbing_enabled.value))
        panel.subtitleModeSelect.setItems(
            list(SUBTITLE_MODE_LABELS.values()),
            SUBTITLE_MODE_LABELS[bool(cfg.soft_subtitle.value)],
        )
        panel.renderModeSelect.setItems(
            [mode.value for mode in SubtitleRenderModeEnum],
            cfg.subtitle_render_mode.value.value,
        )
        panel.qualitySelect.setItems(
            [quality.value for quality in VideoQualityEnum],
            cfg.video_quality.value.value,
        )
        self._sync_voice_options()
        panel.textTrackSelect.setItems(
            list(TEXT_TRACK_LABELS.values()),
            TEXT_TRACK_LABELS.get(cfg.dubbing_text_track.value, "自动选择"),
        )
        panel.timingSelect.setItems(
            list(TIMING_LABELS.values()),
            TIMING_LABELS.get(cfg.dubbing_timing.value, "平衡"),
        )
        panel.audioModeSelect.setItems(
            list(AUDIO_MODE_LABELS.values()),
            AUDIO_MODE_LABELS.get(cfg.dubbing_audio_mode.value, "替换原声"),
        )

    def showEvent(self, event):
        super().showEvent(event)
        # 从配音页回来时提供商 / 音色可能已变，重新同步音色选项
        self._sync_voice_options()

    def _set_config_bool(self, option, checked: bool):
        if option.value != checked:
            cfg.set(option, checked)

    @staticmethod
    def _set_label_config(option, labels: dict, label: str):
        for key, value in labels.items():
            if value == label:
                if option.value != key:
                    cfg.set(option, key)
                return

    def _on_outputs_changed(self, _value=None):
        self.generatePanel.subtitleCard.setChecked(bool(cfg.need_video.value))
        self.generatePanel.dubbingCard.setChecked(bool(cfg.dubbing_enabled.value))
        if self.state == PageState.DONE:
            # 完成后调整输出选择即视为准备下一次生成
            self.state = PageState.IDLE
        self._refresh()

    def _on_subtitle_mode(self, label: str):
        soft = label == SUBTITLE_MODE_LABELS[True]
        self._set_config_bool(cfg.soft_subtitle, soft)
        self._refresh_param_locks()

    def _on_render_mode(self, label: str):
        for mode in SubtitleRenderModeEnum:
            if mode.value == label:
                if cfg.subtitle_render_mode.value != mode:
                    cfg.set(cfg.subtitle_render_mode, mode)
                break

    def _on_quality(self, label: str):
        for quality in VideoQualityEnum:
            if quality.value == label:
                if cfg.video_quality.value != quality:
                    cfg.set(cfg.video_quality, quality)
                break

    def _sync_voice_options(self):
        labels = _voice_labels()
        current = labels.get(cfg.dubbing_preset.value) or next(
            iter(labels.values()), ""
        )
        self.generatePanel.voiceSelect.setItems(list(labels.values()), current)

    def _on_voice(self, label: str):
        for preset, title in _voice_labels().items():
            if title == label:
                if cfg.dubbing_preset.value != preset:
                    cfg.set(cfg.dubbing_preset, preset)
                    option = get_dubbing_preset(preset)
                    if option is not None:
                        cfg.set(cfg.dubbing_voice, option.voice)
                self._refresh()
                return

    def _refresh_param_locks(self):
        """渲染模式仅硬字幕可调；软字幕由播放器决定样式，整行连同样式入口一起隐藏。"""
        hard_subtitle = not cfg.soft_subtitle.value
        self.generatePanel.renderModeSelect.setEnabled(hard_subtitle)
        self.generatePanel.renderModeCard.setVisible(hard_subtitle)
        self.generatePanel.stylePageCard.setVisible(hard_subtitle)

    # --------------------------------------------------------- state engine

    def _evaluate(self) -> Readiness:
        """根据开关与输入计算 IDLE 的呈现。"""
        add_subtitle = bool(cfg.need_video.value)
        add_dubbing = bool(cfg.dubbing_enabled.value)
        has_subtitle = bool(self.subtitle_path)
        has_video = bool(self.video_path)

        plan = []
        if add_dubbing:
            plan.append(self.tr("生成配音音轨"))
        if add_subtitle:
            plan.append(self.tr("合成字幕视频"))
        plan.append(self.tr("保存结果文件"))

        if not add_subtitle and not add_dubbing:
            return Readiness(
                view="files" if has_subtitle else "empty",
                title=self.tr("输入文件"),
                bottom=self.tr("请在右侧至少打开一种输出内容"),
                pill=(self.tr("未选择输出"), "warn"),
                primary=(self.tr("选择输出内容"), AppIcon.SETTING, False),
            )
        if not has_subtitle:
            need_both = add_subtitle
            return Readiness(
                view="empty",
                title=self.tr("输入文件"),
                bottom=self.tr("需要字幕文件和视频文件")
                if need_both
                else self.tr("需要字幕文件"),
                pill=(self.tr("等待文件"), "warn"),
                primary=(self.tr("等待文件"), AppIcon.FILE, False),
            )
        if add_subtitle and not has_video:
            return Readiness(
                view="files",
                title=self.tr("输入文件"),
                bottom=self.tr("还需要视频文件"),
                pill=(self.tr("缺少视频"), "warn"),
                primary=(self.tr("等待视频"), AppIcon.VIDEO, False),
                plan=plan,
            )

        blocker = self._preflight_blocker(add_dubbing)
        if blocker:
            return Readiness(
                view="files",
                title=self.tr("配置检查"),
                bottom=blocker[0],
                pill=blocker[1],
                primary=(self._primary_text(add_subtitle, add_dubbing), AppIcon.PLAY, False),
                blocker=blocker[2],
                plan=plan,
            )

        bottoms = {
            (True, True): self.tr("将先生成配音，再合成字幕视频"),
            (True, False): self.tr("将把字幕合成进视频"),
            (False, True): self.tr("仅生成配音音频，视频文件可不选"),
        }
        return Readiness(
            view="files",
            title=self.tr("生成前确认"),
            bottom=bottoms[(add_subtitle, add_dubbing)],
            pill=(self.tr("可以生成"), "ok"),
            primary=(self._primary_text(add_subtitle, add_dubbing), AppIcon.PLAY, True),
            plan=plan,
        )

    def _primary_text(self, add_subtitle: bool, add_dubbing: bool) -> str:
        if add_subtitle and add_dubbing:
            return self.tr("生成成片")
        if add_dubbing:
            return self.tr("生成配音音频")
        return self.tr("生成字幕视频")

    def _preflight_blocker(self, add_dubbing: bool) -> Optional[tuple]:
        """返回 (底部文案, (胶囊文案, 等级), 错误卡文案)；通过返回 None。"""
        if not shutil.which("ffmpeg"):
            return (
                self.tr("未找到 FFmpeg"),
                (self.tr("缺少 FFmpeg"), "fail"),
                self.tr("请先安装 FFmpeg 并确保 ffmpeg 在 PATH 中。"),
            )
        if add_dubbing and not shutil.which("ffprobe"):
            return (
                self.tr("未找到 FFprobe"),
                (self.tr("缺少 FFprobe"), "fail"),
                self.tr("配音需要 ffprobe 读取音频时长，请确认 FFmpeg 套件完整。"),
            )
        if add_dubbing:
            provider = cfg.dubbing_provider.value
            if provider != "edge" and not cfg.dubbing_api_key.value.strip():
                return (
                    self.tr("当前音色需要 API Key"),
                    (self.tr("缺少 Key"), "fail"),
                    self.tr("当前音色缺少 API Key，请检查配音配置，或切换到 Edge 免费音色。"),
                )
        return None

    def _refresh(self):
        """IDLE 状态的统一刷新入口。"""
        if self.state != PageState.IDLE:
            return
        readiness = self._evaluate()
        self.header.setTitle(readiness.title)
        self.stack.setCurrentIndex(0 if readiness.view == "empty" else 1)
        if readiness.view == "files":
            self._refresh_file_rows()
            self._refresh_plan(readiness.plan)
        # 空态与转录/字幕页一致：不显示底部状态条（拖放区已说明一切）
        self.bottomBar.setVisible(readiness.view != "empty")
        self.bottomBar.setState(readiness.bottom, *readiness.pill)
        text, icon, enabled = readiness.primary
        self.generatePanel.setButton(text, icon=icon, primary=enabled, enabled=enabled)
        self.generatePanel.setError(readiness.blocker)
        self.generatePanel.cancelButton.hide()
        self.generatePanel.openFolderButton.hide()
        self.subtitleButton.show()
        self.videoButton.show()
        self.videoButton.textLabel.setText(
            self.tr("可选视频")
            if cfg.dubbing_enabled.value and not cfg.need_video.value
            else self.tr("选择视频")
        )
        # 参数组只跟输出开关走：开了哪个输出就显示哪组全部参数，
        # 不再按文件就绪度/双开收敛隐藏（参数区可滚动，不怕长）。
        # 例外：配音配置缺失（缺 Key）时配音组只留音色行，先解决配置。
        add_subtitle = bool(cfg.need_video.value)
        add_dubbing = bool(cfg.dubbing_enabled.value)
        blocked = bool(readiness.blocker)
        panel = self.generatePanel
        panel.subtitleSection.setVisible(add_subtitle)
        panel.dubbingSection.setVisible(add_dubbing)
        panel.styleCard.hide()
        panel.qualityCard.setVisible(add_subtitle)
        show_full_dubbing = add_dubbing and not blocked
        panel.textTrackSelect.parentWidget().setVisible(show_full_dubbing)
        panel.timingCard.setVisible(show_full_dubbing)
        panel.audioModeCard.setVisible(show_full_dubbing)
        self._refresh_param_locks()
        self._sync_collapsed_controls()

    def _refresh_file_rows(self):
        add_subtitle = bool(cfg.need_video.value)
        if self.subtitle_path:
            self.subtitleRow.setState(
                Path(self.subtitle_path).name, self.tr("已就绪"), "ok", missing=False
            )
        else:
            self.subtitleRow.setState(
                self.tr("必填：选择 SRT / ASS / VTT 字幕"),
                self.tr("缺少"),
                "warn",
                missing=True,
            )
        self.videoRow.setName(
            self.tr("视频文件") if add_subtitle else self.tr("参考视频")
        )
        if self.video_path:
            self.videoRow.setState(
                Path(self.video_path).name, self.tr("已就绪"), "ok", missing=False
            )
        elif add_subtitle:
            self.videoRow.setState(
                self.tr("必填：选择 MP4 / MOV / MKV 视频"),
                self.tr("缺少"),
                "warn",
                missing=True,
            )
        else:
            self.videoRow.setState(
                self.tr("可选：选择后额外生成配音视频"),
                self.tr("可选"),
                "neutral",
                missing=True,
            )

    def _refresh_plan(self, plan: list[str], statuses: Optional[list[tuple]] = None):
        """生成计划行：默认全部待生成；运行中由 statuses 指定。"""
        for index, step in enumerate(self.planSteps):
            if index < len(plan):
                step.setTitle(plan[index])
                step.show()
                if statuses and index < len(statuses):
                    step.pill.setState(*statuses[index])
                else:
                    step.pill.setState(self.tr("待生成"), "neutral")
            else:
                step.hide()

    def _sync_collapsed_controls(self):
        collapsed = self.sideHost.isCollapsed()
        self.expandButton.setVisible(collapsed)
        enabled = (
            self.state == PageState.IDLE and self.generatePanel.primaryButton.isEnabled()
        )
        button = self.headStartButton
        button.setText(self.generatePanel.primaryButton.text())
        button.setPrimary(enabled)
        button.setEnabled(enabled)
        button.setVisible(collapsed and self.state == PageState.IDLE and enabled)

    def _on_panel_collapsed(self, collapsed: bool):
        if cfg.synthesis_panel_collapsed.value != collapsed:
            cfg.set(cfg.synthesis_panel_collapsed, collapsed)
        self._sync_collapsed_controls()

    # ------------------------------------------------------------ file flow

    def _browse_subtitle(self):
        if self.controller.is_running():
            return
        formats = " ".join(f"*.{fmt}" for fmt in sorted(_SUBTITLE_FORMATS))
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", f"{self.tr('字幕文件')} ({formats})"
        )
        if path:
            self.set_subtitle_file(path)

    def _browse_video(self):
        if self.controller.is_running():
            return
        formats = " ".join(f"*.{fmt}" for fmt in sorted(_VIDEO_FORMATS))
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择视频文件"), "", f"{self.tr('视频文件')} ({formats})"
        )
        if path:
            self.set_video_file(path)

    def _browse_any(self):
        formats = " ".join(
            f"*.{fmt}" for fmt in sorted(_SUBTITLE_FORMATS | _VIDEO_FORMATS)
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("选择字幕和视频文件"), "", f"{self.tr('媒体文件')} ({formats})"
        )
        for path in paths:
            self._dispatch_file(path)

    def _dispatch_file(self, path: str) -> bool:
        suffix = Path(path).suffix.lstrip(".").lower()
        if suffix in _SUBTITLE_FORMATS:
            self.set_subtitle_file(path)
            return True
        if suffix in _VIDEO_FORMATS:
            self.set_video_file(path)
            return True
        return False

    def set_subtitle_file(self, path: str):
        self.subtitle_path = path
        if self.state == PageState.DONE:
            self.state = PageState.IDLE
        self._refresh()

    def set_video_file(self, path: str):
        self.video_path = path
        if self.state == PageState.DONE:
            self.state = PageState.IDLE
        self._refresh()

    # ------------------------------------------------------------- run flow

    def _on_primary(self):
        if self.state == PageState.DONE:
            self.state = PageState.IDLE  # 重新生成
        if self.state != PageState.IDLE:
            return
        readiness = self._evaluate()
        if not readiness.primary[2]:
            self._refresh()
            return
        add_subtitle = bool(cfg.need_video.value)
        add_dubbing = bool(cfg.dubbing_enabled.value)

        # ASS 滤镜检查放在点击时做（探测有进程开销，不适合放实时 evaluate）。
        if (
            add_subtitle
            and not cfg.soft_subtitle.value
            and cfg.subtitle_render_mode.value == SubtitleRenderModeEnum.ASS_STYLE
            and not ffmpeg_supports_ass_filter()
        ):
            self.generatePanel.setError(
                self.tr("FFmpeg 不支持 ASS 硬字幕，请安装带 libass 的完整 FFmpeg，或切换为圆角背景渲染。")
            )
            return

        # 首页流水线注入的任务目录只消费一次（含转录/字幕中间产物，收尾一并清理）
        pipeline_task_dir, self._pipeline_task_dir = self._pipeline_task_dir, None

        if add_dubbing and add_subtitle:
            # 配音+字幕链式：共享一个任务目录，配音视频是其中的中间产物。
            task_dir = pipeline_task_dir or TaskFactory.new_task_dir(self.video_path)
            temp_video = str(
                Path(task_dir) / output_paths.DUBBING_DIR / f"dubbed{Path(self.video_path).suffix}"
            )
            synthesis = TaskFactory.create_synthesis_task(
                self.video_path, self.subtitle_path, task_dir=task_dir, dubbed=True
            )
            dubbing = TaskFactory.create_dubbing_task(
                self.video_path,
                self.subtitle_path,
                output_video_path=temp_video,
                task_dir=task_dir,
            )
            self._active_task_dir = task_dir
            started = self.controller.start_dubbing(dubbing, chained_synthesis=synthesis)
        elif add_dubbing:
            dubbing = TaskFactory.create_dubbing_task(
                self.video_path or "",
                self.subtitle_path,
                task_dir=pipeline_task_dir,
            )
            self._active_task_dir = dubbing.task_dir
            started = self.controller.start_dubbing(dubbing)
        else:
            self.task = TaskFactory.create_synthesis_task(
                self.video_path, self.subtitle_path, task_dir=pipeline_task_dir
            )
            self._active_task_dir = pipeline_task_dir
            started = self.controller.start_synthesis_only(self.task)
        if started:
            self._enter_running()

    def _enter_running(self):
        self.state = PageState.RUNNING
        self.header.setTitle(self.tr("生成中"))
        self.stack.setCurrentIndex(1)
        self.bottomBar.show()
        self._refresh_file_rows()
        plan = []
        if cfg.dubbing_enabled.value:
            plan.append(self.tr("生成配音音轨"))
        if cfg.need_video.value:
            plan.append(self.tr("合成字幕视频"))
        plan.append(self.tr("整理结果文件"))
        self._refresh_plan(plan, [(self.tr("等待"), "neutral")] * len(plan))
        self.bottomBar.setState(
            self.tr("正在生成结果文件"), self.tr("生成中"), "warn", progress=0
        )
        self.generatePanel.setButton(
            self.tr("生成中"), icon=AppIcon.SYNC, primary=False, enabled=False
        )
        self.generatePanel.setError("")
        self.generatePanel.cancelButton.show()
        self.generatePanel.openFolderButton.hide()
        self.subtitleButton.hide()
        self.videoButton.hide()
        self._sync_collapsed_controls()

    def _on_progress(self, value: int, message: str):
        if self.state != PageState.RUNNING:
            return
        self.bottomBar.setState(
            message or self.tr("正在生成结果文件"),
            f"{value}%",
            "warn",
            progress=value,
        )
        # 计划行状态跟随整体进度（全流程 0-55 配音 / 55-100 合成）。
        dubbing_on = bool(cfg.dubbing_enabled.value)
        subtitle_on = bool(cfg.need_video.value)
        if dubbing_on and subtitle_on:
            if value < 55:
                statuses = [(f"{int(value / 55 * 100)}%", "warn"), (self.tr("等待"), "neutral")]
            else:
                statuses = [
                    (self.tr("完成"), "ok"),
                    (f"{int((value - 55) / 45 * 100)}%", "warn"),
                ]
            statuses.append((self.tr("等待"), "neutral"))
        else:
            statuses = [(f"{value}%", "warn"), (self.tr("等待"), "neutral")]
        for step, status in zip([s for s in self.planSteps if s.isVisible()], statuses):
            step.pill.setState(*status)

    def _cancel(self):
        self.controller.cancel()
        # 取消的运行是废弃物，任务目录直接清掉（controller.cancel 已等线程退出）。
        output_paths.cleanup_task_dir(self._active_task_dir, keep=False)
        self._active_task_dir = None
        self.state = PageState.IDLE
        self._refresh()

    def _on_failed(self, error: str):
        # 失败保留任务目录供排查，只复位引用。
        self._active_task_dir = None
        self.state = PageState.IDLE
        self._refresh()
        self.generatePanel.setError(error)
        self.bottomBar.setState(self.tr("生成失败"), self.tr("失败"), "fail")

    def _on_completed(self, results: list):
        output_paths.cleanup_task_dir(
            self._active_task_dir, keep=bool(cfg.keep_intermediates.value)
        )
        self._active_task_dir = None
        self.state = PageState.DONE
        self._results = results
        self.header.setTitle(self.tr("结果文件"))
        self.stack.setCurrentIndex(2)
        for row, result in zip(self.resultRows, results[: len(self.resultRows)]):
            row.setResult(*result)
            row.show()
        for row in self.resultRows[len(results):]:
            row.hide()

        # 有视频产物时异步读取封面帧做预览
        video_result = next(
            (path for _, path in results if Path(path).suffix.lower() == ".mp4"), None
        )
        self.resultThumb.setVisible(video_result is not None)
        if video_result:
            self._info_thread = VideoInfoThread(video_result)
            self._info_thread.finished.connect(self._on_result_info)
            self._info_thread.start()

        self.bottomBar.setState(self.tr("生成完成"), self.tr("已完成"), "ok")
        self.generatePanel.setButton(
            self.tr("重新生成"), icon=AppIcon.SYNC, primary=True, enabled=True
        )
        self.generatePanel.cancelButton.hide()
        self.generatePanel.openFolderButton.show()
        self.subtitleButton.show()
        self.videoButton.show()
        self._sync_collapsed_controls()
        self._open_result_folder()

    def _on_result_info(self, info: VideoInfo):
        self.resultThumb.setMedia(info.thumbnail_path, is_audio=False)

    # ------------------------------------------------------------- actions

    def _open_result_folder(self):
        # 已知具体文件时在文件管理器中直接选中它
        target = None
        if self._results:
            target = Path(self._results[0][1])
        elif self.video_path:
            target = Path(self.video_path)
        elif self.subtitle_path:
            target = Path(self.subtitle_path)
        if target is None:
            return
        if target.exists():
            reveal_in_explorer(str(target))
        else:
            open_folder(str(target.parent))

    def _open_file(self, path: str):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        if Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_synthesis_settings(self):
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            window.openSettingsPage("subtitle")  # type: ignore[attr-defined]

    def _open_voice_library(self):
        window = self.window()
        dubbing = getattr(window, "dubbingInterface", None)
        if dubbing is not None and hasattr(window, "switchTo"):
            window.switchTo(dubbing)  # type: ignore[attr-defined]

    def _open_subtitle_style_library(self):
        window = self.window()
        style_page = getattr(window, "subtitleStyleInterface", None)
        if style_page is not None and hasattr(window, "switchTo"):
            window.switchTo(style_page)  # type: ignore[attr-defined]

    # --------------------------------------------------------- external API

    def set_task(self, task: SynthesisTask):
        """外部（流水线）注入任务：填充输入文件与待清理的任务目录。"""
        self.task = task
        self.subtitle_path = str(task.subtitle_path) if task.subtitle_path else None
        self.video_path = str(task.video_path) if task.video_path else None
        self._pipeline_task_dir = task.task_dir
        self.state = PageState.IDLE
        self._refresh()

    def process(self):
        """外部注入任务后直接开始（流水线模式）。"""
        self._on_primary()

    # ----------------------------------------------------------- drag&drop

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.dropZone.setDragActive(True)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.dropZone.setDragActive(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.dropZone.setDragActive(False)
        if self.controller.is_running():
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._dispatch_file(path)

    def closeEvent(self, event):
        self._disconnect_config_signals()
        self.controller.shutdown()
        if self._info_thread is not None:
            self._info_thread.stop()
        super().closeEvent(event)
