# -*- coding: utf-8 -*-
"""语音转录页：单文件转录工作台。

左侧是预览与结果区，右侧是固定 330px 的参数 / 结果操作栏。

页面状态机（PageState）：

    EMPTY   未选择文件：左侧为拖放导入区，右侧参数可见但按钮禁用
    READY   文件就绪：当前文件卡片 + “尚未开始转录”占位，可开始
    RUNNING 转录中：进度卡片展示阶段与百分比，按钮禁用
    FAILED  失败恢复：失败原因面板，按钮变“重新转录”
    DONE    完成：左侧切换为 SRT 表格或纯文本预览，右侧切换为结果操作

线程统一由 TranscriptionController 持有，页面只消费它的信号；
widget 不直接创建线程，也不互相反向引用。

对外接口（HomeInterface 依赖，保持兼容）：
    finished(str, str)  转录产物路径、原媒体路径
    set_task(task) / process() / close()
"""

from __future__ import annotations

import os
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QRectF, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QDesktopServices,
    QPainter,
    QPainterPath,
    QPen,
)
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
from qfluentwidgets import InfoBar

from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.entities import (
    FasterWhisperModelEnum,
    SupportedAudioFormats,
    SupportedVideoFormats,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
    TranscribeTask,
    VideoInfo,
    WhisperModelEnum,
)
from videocaptioner.core.utils.platform_utils import (
    get_available_transcribe_models,
    open_folder,
    reveal_in_explorer,
)
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.enum_labels import enum_from_label, enum_label, enum_options
from videocaptioner.ui.common.model_options import (
    FUN_ASR_MODEL_OPTIONS,
    WHISPER_API_MODEL_OPTIONS,
)
from videocaptioner.ui.common.theme_tokens import app_palette, is_dark_theme, rgba
from videocaptioner.ui.components.workbench import (
    AdaptiveTitleLabel,
    ClickableFrame,
    CollapsibleSideHost,
    DropZone,
    ErrorCard,
    HeaderLinkButton,
    InfoChip,
    MediaThumb,
    OptionCard,
    PanelHeader,
    PillSelect,
    ProgressBarLine,
    RoundIconButton,
    StatusPill,
    ToggleSwitch,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    draw_rounded_surface,
    icon_pixmap,
)
from videocaptioner.ui.i18n import N_, tr
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.transcript_thread import TranscriptThread
from videocaptioner.ui.thread.video_info_thread import VideoInfoThread

# 转录服务在页面上的短名（状态胶囊里的写法）。
_PROVIDER_SHORT = {
    TranscribeModelEnum.BIJIAN: "B 接口",
    TranscribeModelEnum.JIANYING: "J 接口",
    TranscribeModelEnum.BAILIAN_FUN_ASR: "Fun-ASR",
    TranscribeModelEnum.WHISPER_API: "Whisper API",
    TranscribeModelEnum.FASTER_WHISPER: "FasterWhisper",
    TranscribeModelEnum.WHISPER_CPP: "WhisperCpp",
}

_MEDIA_FORMATS = {fmt.value for fmt in SupportedVideoFormats} | {
    fmt.value for fmt in SupportedAudioFormats
}

# 音轨语言代码 -> 选择器里的中文名（信息胶囊保留原始代码）。
_TRACK_LANGUAGE_NAMES = {
    "zh": "中文", "chi": "中文", "zho": "中文", "cmn": "中文", "yue": "粤语",
    "en": "英语", "eng": "英语",
    "ja": "日语", "jpn": "日语",
    "ko": "韩语", "kor": "韩语",
    "fr": "法语", "fra": "法语", "fre": "法语",
    "de": "德语", "deu": "德语", "ger": "德语",
    "es": "西班牙语", "spa": "西班牙语",
    "ru": "俄语", "rus": "俄语",
}


def _track_language(language: str) -> str:
    """规整音轨语言标签；und/空串视为未知，不展示。"""
    code = (language or "").strip().lower()
    if code in ("", "und"):
        return ""
    return _TRACK_LANGUAGE_NAMES.get(code, language)


def _track_label(index: int, language: str) -> str:
    name = _track_language(language)
    return f"音轨 {index + 1}" + (f" · {name}" if name else "")

_PREVIEW_ROW_LIMIT = 800


class PageState(Enum):
    EMPTY = auto()
    READY = auto()
    RUNNING = auto()
    FAILED = auto()
    DONE = auto()


# ---------------------------------------------------------------------------
# 线程编排
# ---------------------------------------------------------------------------


class TranscriptionController(QObject):
    """持有并编排本页的两类后台线程：媒体信息读取、转录执行。

    页面只调用 load_media / start_transcription / shutdown，
    其余交互全部通过信号；线程对象不暴露给任何 widget。
    """

    mediaLoaded = pyqtSignal(VideoInfo)
    mediaFailed = pyqtSignal(str)
    progressChanged = pyqtSignal(int, str)
    transcriptFailed = pyqtSignal(str)
    transcriptCompleted = pyqtSignal(TranscribeTask)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._info_thread: Optional[VideoInfoThread] = None
        self._transcript_thread: Optional[TranscriptThread] = None

    def load_media(self, file_path: str) -> None:
        # 重入保护：连拖两个文件（前一个 ffprobe 慢）时覆盖前先停旧线程，
        # 否则旧 running QThread 被 GC 触发 "Destroyed while still running" abort
        if self._info_thread is not None and self._info_thread.isRunning():
            self._info_thread.stop(wait_ms=200)
        thread = VideoInfoThread(file_path)
        thread.setParent(self)
        thread.finished.connect(self.mediaLoaded)
        thread.error.connect(self.mediaFailed)
        self._info_thread = thread
        thread.start()

    def start_transcription(self, task: TranscribeTask) -> bool:
        if self.is_transcribing():
            return False
        thread = TranscriptThread(task)
        thread.finished.connect(self.transcriptCompleted)
        thread.progress.connect(self.progressChanged)
        thread.error.connect(self.transcriptFailed)
        self._transcript_thread = thread
        thread.start()
        return True

    def is_transcribing(self) -> bool:
        return self._transcript_thread is not None and self._transcript_thread.isRunning()

    def cancel_transcription(self) -> None:
        """用户主动取消：先断开信号防止迟到事件污染 UI，再协作停止。"""
        thread = self._transcript_thread
        if thread is None:
            return
        self._transcript_thread = None
        if thread.isRunning():
            try:
                thread.finished.disconnect()
                thread.progress.disconnect()
                thread.error.disconnect()
            except TypeError:
                pass
            thread.stop()

    def shutdown(self) -> None:
        """页面关闭时调用：协作停止（基类内部超时才强杀）。"""
        for thread in (self._info_thread, self._transcript_thread):
            if thread is not None:
                thread.stop()


# ---------------------------------------------------------------------------
# 格式化工具
# ---------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_file_size(file_path: str) -> str:
    size = os.path.getsize(file_path)
    if size < 1024 * 1024:
        return f"{max(1, size // 1024)} KB"
    return f"{size / 1024 / 1024:.0f} MB"


def _format_clock(ms: int) -> str:
    secs, milli = divmod(max(0, int(ms)), 1000)
    hours, rest = divmod(secs, 3600)
    minutes, sec = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}.{milli:03d}"


def _provider_short(model: TranscribeModelEnum) -> str:
    return _PROVIDER_SHORT.get(model, model.value.replace(" ✨", ""))


def _installed_local_models(kind: str) -> list[str]:
    """已下载到本地的模型名（与设置页同一口径）。"""
    from videocaptioner.config import MODEL_PATH
    from videocaptioner.core.download import iter_models, model_install_state

    models_dir = (
        Path(cfg.faster_whisper_model_dir.value or MODEL_PATH)
        if kind == "faster-whisper"
        else Path(MODEL_PATH)
    )
    return [
        spec.name for spec in iter_models(kind) if model_install_state(spec, models_dir)
    ]


def _local_model_spec(kind: str, configured: str) -> Optional[tuple[list[str], str]]:
    """本地引擎只列已下载的模型；一个都没有时隐藏模型行（去设置页下载）。"""
    installed = _installed_local_models(kind)
    if not installed:
        return None
    current = configured if configured in installed else installed[0]
    return installed, current


def _service_model_spec(
    service: TranscribeModelEnum,
) -> Optional[tuple[list[str], str]]:
    """返回服务的（模型候选列表, 当前模型）；没有模型概念的服务返回 None。"""
    if service == TranscribeModelEnum.BAILIAN_FUN_ASR:
        return list(FUN_ASR_MODEL_OPTIONS), str(cfg.fun_asr_model.value)
    if service == TranscribeModelEnum.WHISPER_API:
        return list(WHISPER_API_MODEL_OPTIONS), str(cfg.whisper_api_model.value)
    if service == TranscribeModelEnum.WHISPER_CPP:
        return _local_model_spec(
            "whisper-cpp",
            getattr(cfg.whisper_model.value, "value", str(cfg.whisper_model.value)),
        )
    if service == TranscribeModelEnum.FASTER_WHISPER:
        return _local_model_spec(
            "faster-whisper",
            getattr(
                cfg.faster_whisper_model.value,
                "value",
                str(cfg.faster_whisper_model.value),
            ),
        )
    return None  # B 接口 / J 接口：仅默认模型


def _is_audio_file(file_path: str) -> bool:
    suffix = Path(file_path).suffix.lstrip(".").lower()
    return suffix in {fmt.value for fmt in SupportedAudioFormats}


def _clear_chip_row(layout: QHBoxLayout) -> None:
    """清空胶囊行（保留末尾 stretch）。

    必须先 setParent(None) 再 deleteLater：offscreen/截图场景下 DeferredDelete
    事件可能还没处理，残留的旧胶囊会以父控件 (0,0) 为原点悬浮显示。
    """
    while layout.count() > 1:
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def _result_artifact(task: TranscribeTask) -> tuple[Path, bool]:
    """根据输出格式推导实际产物路径。返回 (路径, 是否纯文本预览)。"""
    base = Path(str(task.output_path)).with_suffix("")
    fmt = task.transcribe_config.output_format if task.transcribe_config else None
    if fmt == TranscribeOutputFormatEnum.TXT:
        return base.with_suffix(".txt"), True
    if fmt is None or fmt == TranscribeOutputFormatEnum.ALL:
        return base.with_suffix(".srt"), False
    return base.with_suffix(f".{fmt.value.lower()}"), False


# ---------------------------------------------------------------------------
# 左侧：媒体卡片与各状态部件
# ---------------------------------------------------------------------------


class MediaCard(QFrame):
    """当前文件卡片：缩略图 + 标题 + 信息胶囊。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaCard")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        self.thumb = MediaThumb(self)
        self.thumb.setFixedSize(210, 118)
        layout.addWidget(self.thumb, 0, Qt.AlignVCenter)  # type: ignore[arg-type]

        column = QVBoxLayout()
        column.setSpacing(12)
        self.titleLabel = AdaptiveTitleLabel(24, 860, 19, self)
        self.titleLabel.setObjectName("mediaTitle")
        column.addWidget(self.titleLabel)
        self.chipsRow = QHBoxLayout()
        self.chipsRow.setSpacing(9)
        self.chipsRow.addStretch(1)
        column.addLayout(self.chipsRow)
        layout.addLayout(column, 1)
        self.syncStyle()

    def setThumbSize(self, width: int, height: int):
        self.thumb.setFixedSize(width, height)

    def setTitle(self, title: str):
        self.titleLabel.setFullText(title)

    def setChips(self, texts: list[str]):
        _clear_chip_row(self.chipsRow)
        for index, text in enumerate(texts):
            self.chipsRow.insertWidget(index, InfoChip(text, self))

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.panel, palette.line, 16)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#mediaCard {{ background: transparent; border: none; }}
            QLabel#mediaTitle {{
                color: {palette.text};
                background: transparent;
                border: none;
            }}
            """
        )


class PendingResultArea(QFrame):
    """“尚未开始转录”占位。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pendingResult")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addStretch(1)
        self.iconBox = QFrame(self)
        self.iconBox.setObjectName("pendingIcon")
        self.iconBox.setFixedSize(54, 54)
        icon_layout = QVBoxLayout(self.iconBox)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.iconLabel = QLabel(self.iconBox)
        self.iconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        icon_layout.addWidget(self.iconLabel)
        layout.addWidget(self.iconBox, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        layout.addSpacing(12)
        self.textLabel = QLabel(tr("transcribe.pending.not_started"), self)
        self.textLabel.setObjectName("pendingText")
        self.textLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.textLabel, 18, 820)
        layout.addWidget(self.textLabel)
        layout.addStretch(1)
        self.syncStyle()

    def paintEvent(self, event):
        from videocaptioner.ui.components.workbench import to_qcolor

        dark = is_dark_theme()
        surface = app_palette().card_surface
        dashed = rgba("#cbd4d0", 0.22) if dark else rgba("#000000", 0.18)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, to_qcolor(surface))
        pen = QPen(to_qcolor(dashed), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.update()
        self.iconLabel.setPixmap(icon_pixmap(AppIcon.DOCUMENT, palette.muted, 28))
        self.setStyleSheet(
            f"""
            QFrame#pendingResult {{
                background: transparent;
                border: none;
            }}
            QFrame#pendingIcon {{
                background: {palette.control};
                border: 1px solid {rgba("#ffffff", 0.04)};
                border-radius: 14px;
            }}
            QLabel#pendingText {{ color: {palette.muted}; background: transparent; }}
            """
        )

class ProgressCard(QFrame):
    """转录进度卡：百分比 + 进度条 + 三个阶段行。"""

    _STAGES = (
        N_("transcribe.stage.read_audio"),
        N_("transcribe.stage.recognize"),
        N_("transcribe.stage.write_subtitle"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("progressCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(18)

        head = QHBoxLayout()
        self.phaseLabel = QLabel(tr("transcribe.progress.phase"), self)
        self.phaseLabel.setObjectName("progressPhase")
        apply_font(self.phaseLabel, 17, 820)
        head.addWidget(self.phaseLabel)
        head.addStretch(1)
        self.percentLabel = QLabel("0%", self)
        self.percentLabel.setObjectName("progressPercent")
        self.percentLabel.setMinimumWidth(56)
        self.percentLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        apply_font(self.percentLabel, 17, 820)
        head.addWidget(self.percentLabel)
        layout.addLayout(head)

        self.bar = ProgressBarLine(self)
        layout.addWidget(self.bar)

        self.stagePills: list[StatusPill] = []
        for index, name in enumerate(self._STAGES):
            row_frame = QFrame(self)
            row_frame.setMinimumHeight(42)
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            dot = QLabel(str(index + 1), row_frame)
            dot.setObjectName("stageDot")
            dot.setFixedSize(24, 24)
            dot.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
            apply_font(dot, 13, 850)
            row.addWidget(dot)
            label = QLabel(tr(name), row_frame)
            label.setObjectName("stageName")
            apply_font(label, 14, 740)
            row.addWidget(label, 1)
            pill = StatusPill(tr("transcribe.stage.waiting"), "neutral", row_frame)
            self.stagePills.append(pill)
            row.addWidget(pill)
            layout.addWidget(row_frame)
        self.syncStyle()

    def setPhase(self, message: str):
        """标题展示线程上报的真实阶段消息，空串时回落到默认文案。"""
        self.phaseLabel.setText(message or tr("transcribe.progress.phase"))

    def setProgress(self, value: int):
        value = max(0, min(100, value))
        self.percentLabel.setText(f"{value}%")
        self.bar.setValue(value)
        # 阶段映射：<20 在读音频；20-97 在识别；>=98 在写字幕文件。
        running = N_("transcribe.stage.running")
        waiting = N_("transcribe.stage.waiting")
        done = N_("transcribe.stage.done")
        if value < 20:
            states = [(running, "warn"), (waiting, "neutral"), (waiting, "neutral")]
        elif value < 98:
            states = [(done, "ok"), (running, "warn"), (waiting, "neutral")]
        else:
            states = [(done, "ok"), (done, "ok"), (running, "warn")]
        for pill, (key, level) in zip(self.stagePills, states):
            pill.setState(tr(key), level)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line, 14)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.update()
        self.setStyleSheet(
            f"""
            QFrame#progressCard {{
                background: transparent;
                border: none;
            }}
            QLabel#progressPhase, QLabel#progressPercent {{
                color: {palette.text}; background: transparent;
            }}
            QLabel#stageDot {{
                color: {palette.accent};
                background: {palette.accent_soft};
                border-radius: 12px;
            }}
            QLabel#stageName {{ color: {palette.muted}; background: transparent; }}
            """
        )


# ---------------------------------------------------------------------------
# 左侧：结果预览
# ---------------------------------------------------------------------------


class SubtitlePreviewPanel(WorkbenchPanel):
    """SRT 结果表格：开始时间 / 结束时间 / 字幕内容。"""

    replaceRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, padded=False)
        self.header = PanelHeader(tr("transcribe.preview.title"), inline=False, parent=self)
        self.pill = StatusPill("", "ok", self)
        self.header.addRight(self.pill)
        # 完成态也要能直接导入下一个文件。
        self.replaceLink = HeaderLinkButton(tr("transcribe.action.replace_file"), AppIcon.FOLDER_ADD, self)
        self.replaceLink.clicked.connect(self.replaceRequested)
        self.header.addRight(self.replaceLink)
        self.bodyLayout.addWidget(self.header)

        self.theadFrame = QFrame(self)
        self.theadFrame.setObjectName("subtitleThead")
        self.theadFrame.setFixedHeight(46)
        thead_layout = QHBoxLayout(self.theadFrame)
        thead_layout.setContentsMargins(0, 0, 0, 0)
        thead_layout.setSpacing(0)
        self.theadLabels = []
        for text, width in ((tr("transcribe.col.start"), 150), (tr("transcribe.col.end"), 150), (tr("transcribe.col.content"), 0)):
            label = QLabel(text, self.theadFrame)
            label.setObjectName("subtitleTheadCell")
            label.setContentsMargins(16, 0, 16, 0)
            apply_font(label, 14, 800)
            if width:
                label.setFixedWidth(width)
                thead_layout.addWidget(label)
            else:
                thead_layout.addWidget(label, 1)
            self.theadLabels.append(label)
        self.bodyLayout.addWidget(self.theadFrame)

        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFrameShape(QFrame.NoFrame)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self.rowsHost = QWidget(self)
        self.rowsLayout = QVBoxLayout(self.rowsHost)
        self.rowsLayout.setContentsMargins(0, 0, 0, 0)
        self.rowsLayout.setSpacing(0)
        self.rowsLayout.addStretch(1)
        self.scrollArea.setWidget(self.rowsHost)
        self.bodyLayout.addWidget(self.scrollArea, 1)
        self.rows: list[QFrame] = []
        self._active_index = -1
        self.syncStyle()

    def setSegments(self, segments: list[tuple[int, int, str]]):
        for row in self.rows:
            row.deleteLater()
        self.rows.clear()
        self._active_index = -1
        self.pill.setText(tr("transcribe.preview.count", n=len(segments)))
        for index, (start_ms, end_ms, text) in enumerate(segments[:_PREVIEW_ROW_LIMIT]):
            row = self._make_row(index, _format_clock(start_ms), _format_clock(end_ms), text)
            self.rows.append(row)
            self.rowsLayout.insertWidget(index, row)
        self._sync_rows_style()

    def _make_row(self, index: int, start: str, end: str, text: str) -> QFrame:
        row = QFrame(self.rowsHost)
        row.setObjectName("subtitleRow")
        row.setMinimumHeight(56)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for value, width in ((start, 150), (end, 150), (text, 0)):
            cell = QLabel(value, row)
            cell.setObjectName("subtitleCell")
            cell.setContentsMargins(16, 0, 16, 0)
            apply_font(cell, 14, 650)
            if width:
                cell.setFixedWidth(width)
                layout.addWidget(cell)
            else:
                layout.addWidget(cell, 1)

        def _select(event, target=index):
            self.setActiveRow(target)

        row.mousePressEvent = _select  # type: ignore[assignment]
        return row

    def setActiveRow(self, index: int):
        self._active_index = index
        self._sync_rows_style()

    def _sync_rows_style(self):
        palette = app_palette()
        for index, row in enumerate(self.rows):
            if index == self._active_index:
                row.setStyleSheet(
                    f"""
                    QFrame#subtitleRow {{
                        background: {rgba(palette.accent, 0.075)};
                        border: none;
                        border-top: 1px solid {palette.line_soft};
                        border-left: 3px solid {palette.accent};
                    }}
                    QLabel#subtitleCell {{ color: {palette.text}; background: transparent; }}
                    """
                )
            else:
                row.setStyleSheet(
                    f"""
                    QFrame#subtitleRow {{
                        background: transparent;
                        border: none;
                        border-top: 1px solid {palette.line_soft};
                    }}
                    QLabel#subtitleCell {{ color: {palette.muted}; background: transparent; }}
                    """
                )

    def syncStyle(self):
        super().syncStyle()
        palette = app_palette()
        self.theadFrame.setStyleSheet(
            f"""
            QFrame#subtitleThead {{
                background: {palette.panel_deep};
                border: none;
            }}
            QLabel#subtitleTheadCell {{
                color: {palette.muted};
                background: transparent;
                border-right: 1px solid {palette.line_soft};
            }}
            """
        )
        self.scrollArea.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {palette.line};
                border-radius: 2px;
                min-height: 32px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; background: transparent;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            """
        )


class TextPreviewPanel(WorkbenchPanel):
    """纯文本结果预览。"""

    replaceRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, padded=False)
        self.header = PanelHeader(tr("transcribe.text_preview.title"), inline=False, parent=self)
        self.pill = StatusPill(tr("transcribe.text_preview.done"), "ok", self)
        self.header.addRight(self.pill)
        self.replaceLink = HeaderLinkButton(tr("transcribe.action.replace_file"), AppIcon.FOLDER_ADD, self)
        self.replaceLink.clicked.connect(self.replaceRequested)
        self.header.addRight(self.replaceLink)
        self.bodyLayout.addWidget(self.header)
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 24, 24, 24)
        self.textLabel = QLabel(body)
        self.textLabel.setObjectName("textPreview")
        self.textLabel.setWordWrap(True)
        self.textLabel.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # type: ignore[arg-type]
        body_layout.addWidget(self.textLabel, 1)
        self.bodyLayout.addWidget(body, 1)
        self.syncStyle()

    def setContent(self, text: str):
        palette = app_palette()
        lines = [line for line in text.splitlines() if line.strip()]
        html = "<br>".join(lines)
        self.textLabel.setText(
            f'<div style="color:{palette.muted}; font-size:18px; line-height:175%;">{html}</div>'
        )


# ---------------------------------------------------------------------------
# 右侧：参数面板与结果操作面板
# ---------------------------------------------------------------------------


class ParamsPanel(WorkbenchPanel):
    """右侧参数面板：服务 / 模型 / 语言 / 音轨 / 输出 / 词时间戳 + 开始按钮。

    「服务」选转录提供商；「模型」选该服务下的具体模型，
    没有模型概念的服务（B 接口 / J 接口）会隐藏模型行。
    选项卡片与字幕处理页保持同一套 OptionCard / PillSelect 组件。
    """

    startRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    collapseRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, padded=True)
        self.header = PanelHeader(
            tr("transcribe.params.title"), inline=True, underline=True, parent=self
        )
        self.collapseButton = RoundIconButton(AppIcon.RIGHT_ARROW, parent=self)
        self.collapseButton.setToolTip(tr("transcribe.params.collapse_tip"))
        self.collapseButton.clicked.connect(self.collapseRequested)
        self.header.addRight(self.collapseButton)
        # 仅失败态展示状态胶囊（“未连通”）；提供商已由服务卡片表达。
        self.statusPill = StatusPill("", "fail", self)
        self.statusPill.hide()
        self.header.addRight(self.statusPill)
        self.configButton = RoundIconButton(AppIcon.SETTING, parent=self)
        self.configButton.setToolTip(tr("transcribe.config.open_tip"))
        self.configButton.clicked.connect(self.settingsRequested)
        self.header.addRight(self.configButton)
        self.bodyLayout.addWidget(self.header)

        self.serviceSelect = PillSelect(self)
        self.modelSelect = PillSelect(self)
        self.languageSelect = PillSelect(self)
        self.trackSelect = PillSelect(self)
        self.outputSelect = PillSelect(self)
        self.wordSwitch = ToggleSwitch(True, self)

        self.serviceRow = OptionCard(tr("transcribe.opt.service"), self.serviceSelect, self)
        self.modelRow = OptionCard(tr("transcribe.opt.model"), self.modelSelect, self)
        self.languageRow = OptionCard(tr("transcribe.opt.language"), self.languageSelect, self)
        self.trackRow = OptionCard(tr("transcribe.opt.track"), self.trackSelect, self)
        self.outputRow = OptionCard(tr("transcribe.opt.output"), self.outputSelect, self)
        self.wordRow = OptionCard(tr("transcribe.opt.word_timestamp"), self.wordSwitch, self)
        # 子布局统一间距：模型/音轨行按需隐藏时不会残留多余间距。
        options = QVBoxLayout()
        options.setContentsMargins(0, 18, 0, 0)
        options.setSpacing(14)
        for row in (
            self.serviceRow,
            self.modelRow,
            self.languageRow,
            self.trackRow,
            self.outputRow,
            self.wordRow,
        ):
            options.addWidget(row)
        self.bodyLayout.addLayout(options)
        self.trackRow.hide()

        self.bodyLayout.addStretch(1)
        # 底部主按钮 48 高，与字幕处理 / 视频合成页右栏主按钮一致
        self.startButton = WorkbenchButton(
            tr("transcribe.btn.waiting_file"), AppIcon.PLAY, primary=False, height=48, parent=self
        )
        self.startButton.setEnabled(False)
        self.startButton.clicked.connect(self.startRequested)
        self.bodyLayout.addSpacing(10)
        self.bodyLayout.addWidget(self.startButton)

    def setButtonState(self, text: str, *, icon: AppIcon, primary: bool, enabled: bool):
        self.startButton.setText(text)
        self.startButton.setIcon(icon)
        self.startButton.setPrimary(primary)
        self.startButton.setEnabled(enabled)


class _ResultFileCard(ClickableFrame):
    """结果文件卡片：自绘圆角（QSS 圆角无抗锯齿）。"""

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.panel_deep, palette.line_soft, 14)
        super().paintEvent(event)


class ResultTextLink(QFrame):
    """结果区的文字链接：重新转录。"""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 5)
        layout.setSpacing(7)
        self.iconLabel = QLabel(self)
        layout.addWidget(self.iconLabel)
        self.textLabel = QLabel(text, self)
        apply_font(self.textLabel, 16, 820)
        layout.addWidget(self.textLabel)
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        self.iconLabel.setPixmap(icon_pixmap(AppIcon.SYNC, palette.accent_text, 17))
        self.textLabel.setStyleSheet(
            f"color: {palette.accent_text}; background: transparent; border: none;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        palette = app_palette()
        painter = QPainter(self)
        accent = QColor(palette.accent)
        accent.setAlphaF(0.75)
        painter.fillRect(QRectF(0, self.height() - 1, self.width(), 1), accent)


class ResultActionsPanel(WorkbenchPanel):
    """右侧结果操作面板：缩略图、结果文件、操作按钮。"""

    openSubtitleRequested = pyqtSignal()
    openFolderRequested = pyqtSignal()
    openFileRequested = pyqtSignal()
    retryRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    collapseRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, padded=True)
        self.header = PanelHeader(
            tr("transcribe.result.title"), inline=True, underline=True, parent=self
        )
        self.collapseButton = RoundIconButton(AppIcon.RIGHT_ARROW, parent=self)
        self.collapseButton.setToolTip(tr("transcribe.result.collapse_tip"))
        self.collapseButton.clicked.connect(self.collapseRequested)
        self.header.addRight(self.collapseButton)
        self.statusPill = StatusPill(tr("transcribe.status.done"), "ok", self)
        self.header.addRight(self.statusPill)
        self.configButton = RoundIconButton(AppIcon.SETTING, parent=self)
        self.configButton.setToolTip(tr("transcribe.config.open_tip"))
        self.configButton.clicked.connect(self.settingsRequested)
        self.header.addRight(self.configButton)
        self.bodyLayout.addWidget(self.header)

        self.thumb = MediaThumb(self)
        self.thumb.setFixedHeight(132)
        self.bodyLayout.addWidget(self.thumb)
        self.bodyLayout.addSpacing(16)

        self.titleLabel = AdaptiveTitleLabel(18, 860, 15, self)
        self.titleLabel.setObjectName("resultTitle")
        self.bodyLayout.addWidget(self.titleLabel)
        self.bodyLayout.addSpacing(12)

        self.chipsRow = QHBoxLayout()
        self.chipsRow.setSpacing(9)
        self.chipsRow.addStretch(1)
        self.bodyLayout.addLayout(self.chipsRow)
        self.bodyLayout.addSpacing(16)

        self.fileCard = _ResultFileCard(self)
        self.fileCard.setObjectName("resultFileCard")
        self.fileCard.setToolTip(tr("transcribe.result.open_file_tip"))
        self.fileCard.clicked.connect(self.openFileRequested)
        file_layout = QVBoxLayout(self.fileCard)
        file_layout.setContentsMargins(22, 22, 22, 22)
        file_layout.setSpacing(8)
        self.fileCardTitle = QLabel(tr("transcribe.result.file"), self.fileCard)
        self.fileCardTitle.setObjectName("resultFileTitle")
        apply_font(self.fileCardTitle, 19, 840)
        file_layout.addWidget(self.fileCardTitle)
        self.pathLabel = QLabel(self.fileCard)
        self.pathLabel.setObjectName("resultFilePath")
        apply_font(self.pathLabel, 14, 720)
        file_layout.addWidget(self.pathLabel)
        self.bodyLayout.addWidget(self.fileCard)
        self.bodyLayout.addSpacing(16)

        self.openSubtitleButton = WorkbenchButton(
            tr("transcribe.btn.open_subtitle"), AppIcon.RIGHT_ARROW, primary=True, height=48, parent=self
        )
        self.openSubtitleButton.clicked.connect(self.openSubtitleRequested)
        self.bodyLayout.addWidget(self.openSubtitleButton)
        self.bodyLayout.addSpacing(12)
        self.openFolderButton = WorkbenchButton(
            tr("common.open_folder"), AppIcon.FOLDER, primary=False, parent=self
        )
        self.openFolderButton.clicked.connect(self.openFolderRequested)
        self.bodyLayout.addWidget(self.openFolderButton)
        self.bodyLayout.addSpacing(16)
        self.retryLink = ResultTextLink(tr("transcribe.btn.retranscribe"), self)
        self.retryLink.clicked.connect(self.retryRequested)
        retry_row = QHBoxLayout()
        retry_row.addStretch(1)
        retry_row.addWidget(self.retryLink)
        retry_row.addStretch(1)
        self.bodyLayout.addLayout(retry_row)
        self.bodyLayout.addStretch(1)
        self.syncStyle()

    def setResult(self, *, title: str, chips: list[str], file_name: str):
        self.titleLabel.setFullText(title)
        _clear_chip_row(self.chipsRow)
        for index, text in enumerate(chips):
            self.chipsRow.insertWidget(index, InfoChip(text, self))
        path_metrics = self.pathLabel.fontMetrics()
        self.pathLabel.setText(
            path_metrics.elidedText(file_name, Qt.ElideMiddle, 238)  # type: ignore[arg-type]
        )
        self.pathLabel.setToolTip(file_name)

    def syncStyle(self):
        super().syncStyle()
        palette = app_palette()
        self.fileCard.setStyleSheet(
            f"""
            QFrame#resultFileCard {{
                background: {palette.panel_deep};
                border: 1px solid {palette.line_soft};
                border-radius: 14px;
            }}
            QLabel#resultFileTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#resultFilePath {{ color: {palette.subtle}; background: transparent; }}
            """
        )
        self.titleLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


class TranscriptionInterface(QWidget):
    """语音转录页（单文件工作台）。"""

    finished = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("TranscriptionInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self.state = PageState.EMPTY
        self.task: Optional[TranscribeTask] = None
        self.media_info: Optional[VideoInfo] = None
        self._media_path: Optional[str] = None
        self._result_path: Optional[Path] = None
        self._config_signal_connections: list[tuple] = []

        self.controller = TranscriptionController(self)
        self._build_ui()
        self._connect_signals()
        self._load_params_from_config()
        self.sideHost.setCollapsed(
            bool(cfg.transcribe_panel_collapsed.value), animate=False
        )
        self._apply_state(PageState.EMPTY)

    def _make_compact_start(self, parent) -> WorkbenchButton:
        """折叠态下左侧头部的主操作按钮（与右栏主按钮状态同步）。"""
        button = WorkbenchButton(
            tr("transcribe.btn.start"), AppIcon.PLAY, primary=True, height=32, parent=parent
        )
        button.setMinimumWidth(104)
        button.hide()
        button.clicked.connect(self._on_compact_primary)
        return button

    def _make_expand_button(self, parent) -> RoundIconButton:
        """折叠态下左侧头部的“展开右栏”入口（位置固定，不随动画漂移）。"""
        button = RoundIconButton(AppIcon.LAYOUT, diameter=32, parent=parent)
        button.setToolTip(tr("transcribe.params.expand_tip"))
        button.hide()
        button.clicked.connect(lambda: self.sideHost.setCollapsed(False))
        return button

    def _compact_start_buttons(self) -> list[WorkbenchButton]:
        return [
            self.emptyCompactStart,
            self.fileCompactStart,
            self.previewCompactStart,
            self.textCompactStart,
        ]

    def _expand_buttons(self) -> list[RoundIconButton]:
        return [
            self.emptyExpand,
            self.fileExpand,
            self.previewExpand,
            self.textExpand,
        ]

    def _on_compact_primary(self):
        if self.state == PageState.DONE:
            self._on_open_subtitle()
        else:
            self._on_start_clicked()

    def _on_panel_collapsed(self, collapsed: bool):
        if cfg.transcribe_panel_collapsed.value != collapsed:
            cfg.set(cfg.transcribe_panel_collapsed, collapsed)
        self._sync_compact_start()

    def _sync_compact_start(self):
        """折叠态主按钮与当前状态同步（DONE 态为进入字幕优化）。"""
        if self.state == PageState.DONE:
            text, icon, primary, enabled = (
                tr("transcribe.btn.open_subtitle"), AppIcon.RIGHT_ARROW, True, True,
            )
        else:
            specs = {
                PageState.EMPTY: (tr("transcribe.btn.waiting_file"), AppIcon.PLAY, False, False),
                PageState.READY: (tr("transcribe.btn.start"), AppIcon.PLAY, True, True),
                PageState.RUNNING: (tr("transcribe.btn.running"), AppIcon.SYNC, False, False),
                PageState.FAILED: (tr("transcribe.btn.retranscribe"), AppIcon.PLAY, True, True),
            }
            text, icon, primary, enabled = specs[self.state]
        collapsed = self.sideHost.isCollapsed()
        show_start = collapsed and self.state != PageState.EMPTY
        for button in self._compact_start_buttons():
            button.setText(text)
            button.setIcon(icon)
            button.setPrimary(primary)
            button.setEnabled(enabled)
            button.setVisible(show_start)
        for button in self._expand_buttons():
            button.setVisible(collapsed)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QWidget#TranscriptionInterface {{ background: {palette.bg}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 2)
        root.setSpacing(18)

        # 左列：空态 / 当前文件 / SRT 结果 / 纯文本结果
        self.leftStack = QStackedWidget(self)
        root.addWidget(self.leftStack, 1)

        # 空态外壳与字幕/合成页同构：56 高标题栏（带分隔线）+ 16 边距拖放区。
        self.emptyPanel = WorkbenchPanel(self, padded=False)
        empty_header = PanelHeader(
            tr("transcribe.empty.title"), inline=False, parent=self.emptyPanel
        )
        self.emptyCompactStart = self._make_compact_start(self.emptyPanel)
        empty_header.addRight(self.emptyCompactStart)
        self.emptyExpand = self._make_expand_button(self.emptyPanel)
        empty_header.addRight(self.emptyExpand)
        self.emptyPanel.bodyLayout.addWidget(empty_header)
        self.dropZone = DropZone(
            icon=AppIcon.VIDEO,
            title=tr("transcribe.drop.title"),
            pick_text=tr("transcribe.drop.pick"),
            pick_icon=AppIcon.FOLDER_ADD,
            formats_line="mp4 / mov / mkv / mp3 / wav / m4a",
            parent=self.emptyPanel,
        )
        drop_host = QWidget(self.emptyPanel)
        drop_layout = QVBoxLayout(drop_host)
        drop_layout.setContentsMargins(16, 16, 16, 16)
        drop_layout.addWidget(self.dropZone)
        self.emptyPanel.bodyLayout.addWidget(drop_host, 1)
        self.leftStack.addWidget(self.emptyPanel)

        self.filePanel = WorkbenchPanel(self, padded=False)
        self.fileHeader = PanelHeader(tr("transcribe.file.title"), inline=False, parent=self.filePanel)
        self.filePill = StatusPill(tr("transcribe.status.pending"), "neutral", self.filePanel)
        self.fileHeader.addRight(self.filePill)
        self.replaceLink = HeaderLinkButton(tr("transcribe.action.replace_file"), AppIcon.FOLDER_ADD, self.filePanel)
        self.fileHeader.addRight(self.replaceLink)
        # 转录中必须可以取消。
        self.cancelLink = HeaderLinkButton(tr("transcribe.action.cancel"), AppIcon.CANCEL, self.filePanel)
        self.fileHeader.addRight(self.cancelLink)
        self.cancelLink.hide()
        self.fileCompactStart = self._make_compact_start(self.filePanel)
        self.fileHeader.addRight(self.fileCompactStart)
        self.fileExpand = self._make_expand_button(self.filePanel)
        self.fileHeader.addRight(self.fileExpand)
        self.filePanel.bodyLayout.addWidget(self.fileHeader)
        file_body = QWidget(self.filePanel)
        file_body_layout = QVBoxLayout(file_body)
        file_body_layout.setContentsMargins(22, 22, 22, 22)
        file_body_layout.setSpacing(18)
        self.mediaCard = MediaCard(file_body)
        file_body_layout.addWidget(self.mediaCard)
        self.pendingArea = PendingResultArea(file_body)
        file_body_layout.addWidget(self.pendingArea, 1)
        self.progressCard = ProgressCard(file_body)
        file_body_layout.addWidget(self.progressCard)
        self.errorBanner = ErrorCard(title=tr("transcribe.error.title"), parent=file_body)
        file_body_layout.addWidget(self.errorBanner)
        file_body_layout.addStretch(0)
        # 初始即隐藏：QStackedWidget 的最小尺寸取所有页面之和，
        # 三个互斥区块同时可见会把整页最小高度撑得过高。
        self.progressCard.hide()
        self.errorBanner.hide()
        self.filePanel.bodyLayout.addWidget(file_body, 1)
        self.leftStack.addWidget(self.filePanel)

        self.subtitlePreview = SubtitlePreviewPanel(self)
        self.previewCompactStart = self._make_compact_start(self.subtitlePreview)
        self.subtitlePreview.header.addRight(self.previewCompactStart)
        self.previewExpand = self._make_expand_button(self.subtitlePreview)
        self.subtitlePreview.header.addRight(self.previewExpand)
        self.leftStack.addWidget(self.subtitlePreview)
        self.textPreview = TextPreviewPanel(self)
        self.textCompactStart = self._make_compact_start(self.textPreview)
        self.textPreview.header.addRight(self.textCompactStart)
        self.textExpand = self._make_expand_button(self.textPreview)
        self.textPreview.header.addRight(self.textExpand)
        self.leftStack.addWidget(self.textPreview)

        # 右列：参数 / 结果操作
        self.rightStack = QStackedWidget(self)
        # 弹性右栏（280-330 自适应）+ 可折叠宿主，折叠状态持久化。
        self.sideHost = CollapsibleSideHost(self.rightStack, 280, 330, self)
        root.addWidget(self.sideHost, 1)
        self.paramsPanel = ParamsPanel(self)
        self.rightStack.addWidget(self.paramsPanel)
        self.resultPanel = ResultActionsPanel(self)
        self.rightStack.addWidget(self.resultPanel)

    # ------------------------------------------------------------- signals

    def _connect_signals(self):
        self.controller.mediaLoaded.connect(self._on_media_loaded)
        self.controller.mediaFailed.connect(self._on_media_failed)
        self.controller.progressChanged.connect(self._on_progress)
        self.controller.transcriptFailed.connect(self._on_transcript_failed)
        self.controller.transcriptCompleted.connect(self._on_transcript_completed)

        self.dropZone.browseRequested.connect(self._browse_file)
        self.replaceLink.clicked.connect(self._browse_file)
        self.cancelLink.clicked.connect(self._cancel_transcription)
        self.subtitlePreview.replaceRequested.connect(self._browse_file)
        self.textPreview.replaceRequested.connect(self._browse_file)
        self.resultPanel.openFileRequested.connect(self._on_open_result_file)
        self.paramsPanel.startRequested.connect(self._on_start_clicked)
        self.paramsPanel.settingsRequested.connect(self._open_transcribe_settings)
        self.paramsPanel.collapseRequested.connect(
            lambda: self.sideHost.setCollapsed(True)
        )
        self.resultPanel.collapseRequested.connect(
            lambda: self.sideHost.setCollapsed(True)
        )
        self.sideHost.collapsedChanged.connect(self._on_panel_collapsed)
        self.resultPanel.settingsRequested.connect(self._open_transcribe_settings)
        self.resultPanel.openSubtitleRequested.connect(self._on_open_subtitle)
        self.resultPanel.openFolderRequested.connect(self._on_open_folder)
        self.resultPanel.retryRequested.connect(self._restart_transcription)

        self.paramsPanel.serviceSelect.currentTextChanged.connect(self._on_service_selected)
        self.paramsPanel.modelSelect.currentTextChanged.connect(self._on_model_selected)
        self.paramsPanel.languageSelect.currentTextChanged.connect(self._on_language_selected)
        self.paramsPanel.outputSelect.currentTextChanged.connect(self._on_output_selected)
        self.paramsPanel.wordSwitch.toggled.connect(self._on_word_timestamp_toggled)

        self._connect_config_signal(cfg.transcribe_model, self._on_service_config_changed)

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

    def _load_params_from_config(self):
        services = [_provider_short(model) for model in get_available_transcribe_models()]
        self.paramsPanel.serviceSelect.setItems(
            services, _provider_short(cfg.transcribe_model.value)
        )
        self.paramsPanel.languageSelect.setItems(
            enum_options(TranscribeLanguageEnum),
            enum_label(cfg.transcribe_language.value),
        )
        self.paramsPanel.outputSelect.setItems(
            enum_options(TranscribeOutputFormatEnum),
            enum_label(cfg.transcribe_output_format.value),
        )
        self.paramsPanel.wordSwitch.setChecked(bool(cfg.transcribe_word_timestamp.value))
        self._refresh_service_row()

    def _refresh_service_row(self):
        """服务变化后刷新模型行（无模型概念的服务隐藏模型行）。"""
        service = cfg.transcribe_model.value
        spec = _service_model_spec(service)
        if spec is None:
            self.paramsPanel.modelRow.hide()
            return
        options, current = spec
        if current and current not in options:
            options = [current, *options]
        self.paramsPanel.modelRow.show()
        self.paramsPanel.modelSelect.setItems(options, current or options[0])

    def _on_service_selected(self, short_name: str):
        for model in TranscribeModelEnum:
            if _provider_short(model) == short_name:
                if cfg.transcribe_model.value != model:
                    cfg.set(cfg.transcribe_model, model)
                break
        self._refresh_service_row()

    def _on_service_config_changed(self, model: TranscribeModelEnum):
        self.paramsPanel.serviceSelect.setCurrentText(_provider_short(model))
        self._refresh_service_row()

    def _on_model_selected(self, model_name: str):
        """把模型行的选择写回当前服务对应的配置字段。"""
        service = cfg.transcribe_model.value
        if service == TranscribeModelEnum.BAILIAN_FUN_ASR:
            if cfg.fun_asr_model.value != model_name:
                cfg.set(cfg.fun_asr_model, model_name)
        elif service == TranscribeModelEnum.WHISPER_API:
            if cfg.whisper_api_model.value != model_name:
                cfg.set(cfg.whisper_api_model, model_name)
        elif service == TranscribeModelEnum.WHISPER_CPP:
            for option in WhisperModelEnum:
                if option.value == model_name:
                    if cfg.whisper_model.value != option:
                        cfg.set(cfg.whisper_model, option)
                    break
        elif service == TranscribeModelEnum.FASTER_WHISPER:
            for option in FasterWhisperModelEnum:
                if option.value == model_name:
                    if cfg.faster_whisper_model.value != option:
                        cfg.set(cfg.faster_whisper_model, option)
                    break

    def _on_language_selected(self, language_name: str):
        language = enum_from_label(TranscribeLanguageEnum, language_name)
        if language is not None and cfg.transcribe_language.value != language:
            cfg.set(cfg.transcribe_language, language)

    def _on_output_selected(self, format_name: str):
        fmt = enum_from_label(TranscribeOutputFormatEnum, format_name)
        if fmt is not None and cfg.transcribe_output_format.value != fmt:
            cfg.set(cfg.transcribe_output_format, fmt)

    def _on_word_timestamp_toggled(self, checked: bool):
        if cfg.transcribe_word_timestamp.value != checked:
            cfg.set(cfg.transcribe_word_timestamp, checked)

    # --------------------------------------------------------- state machine

    def _apply_state(self, state: PageState, *, preview_text: bool = False):
        self.state = state
        if state == PageState.EMPTY:
            self.leftStack.setCurrentWidget(self.emptyPanel)
        elif state == PageState.DONE:
            self.leftStack.setCurrentWidget(
                self.textPreview if preview_text else self.subtitlePreview
            )
        else:
            self.leftStack.setCurrentWidget(self.filePanel)

        self.rightStack.setCurrentWidget(
            self.resultPanel if state == PageState.DONE else self.paramsPanel
        )

        if state in (PageState.READY, PageState.RUNNING, PageState.FAILED):
            pills = {
                PageState.READY: (tr("transcribe.status.pending"), "neutral"),
                PageState.RUNNING: (tr("transcribe.status.running"), "warn"),
                PageState.FAILED: (tr("transcribe.status.failed"), "fail"),
            }
            self.filePill.setState(*pills[state])
            self.replaceLink.setVisible(state != PageState.RUNNING)
            self.cancelLink.setVisible(state == PageState.RUNNING)
            self.pendingArea.setVisible(state == PageState.READY)
            self.progressCard.setVisible(state == PageState.RUNNING)
            self.errorBanner.setVisible(state == PageState.FAILED)
            # 就绪态用带分隔线的标题栏 + 190px 缩略图；
            # 运行/失败态用无分隔线标题 + 210px 缩略图和运行上下文胶囊。
            self.fileHeader.setInline(state != PageState.READY)
            if state == PageState.READY:
                self.mediaCard.setThumbSize(190, 106)
                if self.media_info is not None:
                    self.mediaCard.setChips(
                        self._media_chips(
                            self.media_info, _is_audio_file(self.media_info.file_path)
                        )
                    )
            else:
                self.mediaCard.setThumbSize(210, 118)
                self.mediaCard.setChips(self._run_chips())

        buttons = {
            PageState.EMPTY: (tr("transcribe.btn.waiting_file"), AppIcon.PLAY, False, False),
            PageState.READY: (tr("transcribe.btn.start"), AppIcon.PLAY, True, True),
            PageState.RUNNING: (tr("transcribe.btn.running"), AppIcon.SYNC, False, False),
            PageState.FAILED: (tr("transcribe.btn.retranscribe"), AppIcon.PLAY, True, True),
            PageState.DONE: (tr("transcribe.btn.start"), AppIcon.PLAY, True, True),
        }
        text, icon, primary, enabled = buttons[state]
        self.paramsPanel.setButtonState(text, icon=icon, primary=primary, enabled=enabled)

        if state == PageState.FAILED:
            self.paramsPanel.statusPill.setState(tr("transcribe.status.unreachable"), "fail")
            self.paramsPanel.statusPill.show()
        else:
            self.paramsPanel.statusPill.hide()
            self._refresh_service_row()

        # 音轨行只在文件就绪可调（运行/失败状态不显示）。
        self.paramsPanel.trackRow.setVisible(
            state == PageState.READY and self.media_info is not None
        )
        self._sync_compact_start()

    # ----------------------------------------------------------- media flow

    def _browse_file(self):
        if self.controller.is_transcribing():
            self._warn_processing()
            return
        desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        audio_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedAudioFormats)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("transcribe.dialog.pick_media"),
            desktop,
            f"{tr('transcribe.dialog.media_filter')} ({video_formats} {audio_formats})",
        )
        if file_path:
            self.load_media(file_path)

    def load_media(self, file_path: str):
        """加载媒体文件：先占位显示文件名，信息线程完成后填充详情。"""
        self._media_path = file_path
        self.media_info = None
        self.task = None
        self.mediaCard.setTitle(Path(file_path).name)
        self.mediaCard.setChips([])
        self.mediaCard.thumb.setMedia(None, _is_audio_file(file_path))
        self._apply_state(PageState.READY)
        self.controller.load_media(file_path)

    def _on_media_loaded(self, info: VideoInfo):
        if self._media_path and info.file_path != self._media_path:
            return  # 过期线程的结果，忽略
        self.media_info = info
        is_audio = _is_audio_file(info.file_path)
        self.mediaCard.setTitle(info.file_name)
        self.mediaCard.setChips(self._media_chips(info, is_audio))
        self.mediaCard.thumb.setMedia(info.thumbnail_path, is_audio)
        tracks = [
            _track_label(index, stream.language)
            for index, stream in enumerate(info.audio_streams)
        ] or [tr("transcribe.track.first")]
        self.paramsPanel.trackSelect.setItems(tracks, tracks[0])
        if self.state == PageState.READY:
            self._apply_state(PageState.READY)
        elif self.state == PageState.DONE:
            # 带下载字幕的任务会“直通完成”，结果先于封面解析出来——
            # 封面到了再回填右栏缩略图
            self.resultPanel.thumb.setMedia(info.thumbnail_path, is_audio)

    def _media_chips(self, info: VideoInfo, is_audio: bool) -> list[str]:
        """就绪态胶囊：媒体本身的事实（分辨率 / 时长 / 大小 / 音轨）。"""
        chips = []
        if not is_audio and info.width and info.height:
            chips.append(f"{info.width} × {info.height}")
        if info.duration_seconds:
            chips.append(_format_duration(info.duration_seconds))
        if is_audio:
            chips.append(_format_file_size(info.file_path))
        if info.audio_streams and not is_audio:
            stream = info.audio_streams[0]
            chip = tr("transcribe.track.first")
            if _track_language(stream.language):
                chip += f" ({stream.language})"
            chips.append(chip)
        return chips

    def _run_chips(self) -> list[str]:
        """运行 / 失败态胶囊：本次转录的上下文（时长 / 大小 / 服务 / 格式）。"""
        chips = []
        info = self.media_info
        is_audio = _is_audio_file(self._media_path) if self._media_path else False
        if info and info.duration_seconds:
            chips.append(_format_duration(info.duration_seconds))
        if is_audio and info:
            chips.append(_format_file_size(info.file_path))
        chips.append(_provider_short(cfg.transcribe_model.value))
        if not is_audio:
            chips.append(enum_label(cfg.transcribe_output_format.value))
        return chips

    def _on_media_failed(self, message: str):
        InfoBar.error(
            tr("common.error"), message, duration=INFOBAR_DURATION_ERROR, parent=self
        )
        if self.state == PageState.READY and self.media_info is None:
            self._apply_state(PageState.EMPTY)

    # ------------------------------------------------------ transcribe flow

    def _on_start_clicked(self):
        if self.state in (PageState.READY, PageState.FAILED, PageState.DONE):
            self._restart_transcription()

    def _restart_transcription(self):
        """从就绪 / 失败 / 完成状态发起（重新）转录，任务按当前参数重建。"""
        if not self._media_path:
            return
        if self.controller.is_transcribing():
            self._warn_processing()
            return
        self.task = TaskFactory.create_transcribe_task(self._media_path)
        if self.task.transcribe_config is not None:
            self.task.transcribe_config.need_word_time_stamp = bool(
                cfg.transcribe_word_timestamp.value
            )
        self._launch_task()

    def _launch_task(self):
        assert self.task is not None
        track_items = self.paramsPanel.trackSelect.items()
        if track_items:
            current = self.paramsPanel.trackSelect.currentText()
            self.task.selected_audio_track_index = max(0, track_items.index(current))
        self.progressCard.setProgress(0)
        # start_transcription 在控制器忙时返回 False；只有真正启动才进 RUNNING，否则
        # 页面显示 RUNNING 但线程在跑上一个任务（A 转录中从任务页投 B 的竞态）。
        if self.controller.start_transcription(self.task):
            self._apply_state(PageState.RUNNING)

    def _on_progress(self, value: int, message: str):
        self.progressCard.setProgress(value)
        self.progressCard.setPhase(message)

    def _cancel_transcription(self):
        """取消进行中的转录，回到文件就绪状态（文件保留）。"""
        self.controller.cancel_transcription()
        self.progressCard.setProgress(0)
        self.progressCard.setPhase("")
        self._apply_state(PageState.READY)

    def _on_open_result_file(self):
        if self._result_path and self._result_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result_path)))

    def _on_transcript_failed(self, message: str):
        self.errorBanner.setText(message)
        self._apply_state(PageState.FAILED)

    def _on_transcript_completed(self, task: TranscribeTask):
        self.task = task
        artifact, is_text = _result_artifact(task)
        self._result_path = artifact
        self._show_result(task, artifact, is_text)
        if task.need_next_task and task.output_path:
            self.finished.emit(task.output_path, task.file_path)

    def _show_result(self, task: TranscribeTask, artifact: Path, is_text: bool):
        if is_text:
            content = artifact.read_text(encoding="utf-8") if artifact.exists() else ""
            self.textPreview.setContent(content)
        else:
            self.subtitlePreview.setSegments(self._load_segments(artifact))

        info = self.media_info
        is_audio = _is_audio_file(str(task.file_path))
        chips = [_provider_short(cfg.transcribe_model.value)]
        if info and info.duration_seconds:
            chips.append(_format_duration(info.duration_seconds))
        chips.append(tr("transcribe.format.txt") if is_text else artifact.suffix.lstrip(".").upper())
        self.resultPanel.thumb.setMedia(
            info.thumbnail_path if info else None, is_audio
        )
        self.resultPanel.setResult(
            title=Path(str(task.file_path)).stem,
            chips=chips,
            file_name=artifact.name,
        )
        self._apply_state(PageState.DONE, preview_text=is_text)

    def _load_segments(self, artifact: Path) -> list[tuple[int, int, str]]:
        from videocaptioner.core.asr.asr_data import ASRData

        if not artifact.exists():
            return []
        try:
            asr_data = ASRData.from_subtitle_file(str(artifact))
        except Exception:
            return []
        return [(seg.start_time, seg.end_time, seg.text) for seg in asr_data.segments]

    # ------------------------------------------------------- result actions

    def _on_open_subtitle(self):
        srt_path = Path(str(self.task.output_path)).with_suffix(".srt") if self.task else None
        if self.task and srt_path and srt_path.exists():
            self.finished.emit(str(srt_path), str(self.task.file_path))
            return
        if self._result_path and self._result_path.suffix != ".txt" and self._result_path.exists():
            self.finished.emit(str(self._result_path), str(self.task.file_path))
            return
        InfoBar.warning(
            tr("common.tip"),
            tr("transcribe.toast.no_subtitle"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self,
        )

    def _on_open_folder(self):
        # 已知具体文件时在文件管理器中直接选中它
        target = self._result_path if self._result_path and self._result_path.exists() else None
        if target is None and self._media_path:
            target = Path(self._media_path)
        if target is None:
            return
        if target.exists():
            reveal_in_explorer(str(target))
        else:
            open_folder(str(target.parent))

    def _open_transcribe_settings(self):
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            window.openSettingsPage("transcribe")  # type: ignore[attr-defined]

    def _warn_processing(self):
        InfoBar.warning(
            tr("common.warning"),
            tr("transcribe.toast.processing"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self,
        )

    # ------------------------------------------------------- external API

    def set_task(self, task: TranscribeTask):
        """外部（任务创建流程）注入任务：加载媒体信息并保留任务配置。"""
        self.task = task
        self._media_path = str(task.file_path)
        self.media_info = None
        self.mediaCard.setTitle(Path(self._media_path).name)
        self.mediaCard.setChips([])
        self.mediaCard.thumb.setMedia(None, _is_audio_file(self._media_path))
        self._apply_state(PageState.READY)
        self.controller.load_media(self._media_path)

    def process(self):
        """外部注入任务后直接开始转录（流水线模式）。"""
        if self.task is None:
            return
        self._launch_task()

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
        if self.controller.is_transcribing():
            self._warn_processing()
            return
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if not os.path.isfile(file_path):
                continue
            suffix = Path(file_path).suffix.lstrip(".").lower()
            if suffix in _MEDIA_FORMATS:
                self.load_media(file_path)
                return
            InfoBar.error(
                tr("transcribe.toast.bad_format", suffix=suffix),
                tr("transcribe.toast.drop_media"),
                duration=INFOBAR_DURATION_ERROR,
                parent=self,
            )

    def closeEvent(self, event):
        self._disconnect_config_signals()
        self.controller.shutdown()
        super().closeEvent(event)
