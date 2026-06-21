# -*- coding: utf-8 -*-
"""批量处理页：队列工作台。

布局与状态：
顶部是页头（标题 + 工具栏）与四张处理模式卡，中部左侧是任务队列
（空态拖放区 / 任务行列表 + 过滤 tab），右侧是「本批任务」统计与
流水线阶段卡，底部是提示条（含并发数选择）。

数据模型分三层，全部在 GUI 线程编排、无轮询：

    BatchJob        一行任务的纯数据（路径 / 状态 / 进度 / 输出）
    JobRunner       把一个任务按阶段链（转录 -> 字幕 -> 配音 -> 合成）
                    依次跑完，阶段进度映射为 0-100 总进度
    BatchController 持有队列与并发槽位，按并发数派发 JobRunner，
                    支持暂停（停止派发、在跑任务继续）/ 重试 / 移除

页面生命周期状态（PageState）由队列与控制器派生（_page_state），
不单独维护状态字段，避免与队列事实脱节。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBar, InfoBarPosition

from videocaptioner.core.application import output_paths
from videocaptioner.core.constant import (
    INFOBAR_DURATION_INFO,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.entities import (
    SupportedAudioFormats,
    SupportedSubtitleFormats,
    SupportedVideoFormats,
    TranscribeTask,
    TranslatorServiceEnum,
)
from videocaptioner.core.utils.platform_utils import open_folder, reveal_in_explorer
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import ConfirmDialog
from videocaptioner.ui.components.workbench import (
    DropZone,
    ElidedLabel,
    FilterTabs,
    IconBox,
    PanelHeader,
    PillSelect,
    ProgressBarLine,
    RoundIconButton,
    SelectableCard,
    StatusPill,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    draw_rounded_surface,
    file_type_icon,
    icon_pixmap,
)
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.dubbing_thread import DubbingThread
from videocaptioner.ui.thread.subtitle_thread import SubtitleThread
from videocaptioner.ui.thread.transcript_thread import TranscriptThread
from videocaptioner.ui.thread.video_synthesis_thread import VideoSynthesisThread

_MEDIA_EXTENSIONS = {f".{fmt.value}" for fmt in SupportedAudioFormats} | {
    f".{fmt.value}" for fmt in SupportedVideoFormats
}
_SUBTITLE_EXTENSIONS = {f".{fmt.value}" for fmt in SupportedSubtitleFormats}
_FOLDER_MAX_DEPTH = 3


@dataclass(frozen=True)
class BatchMode:
    key: str
    icon: AppIcon
    title: str
    desc: str
    accepts_media: bool  # True：音视频输入；False：字幕文件输入


BATCH_MODES = [
    BatchMode(
        "full",
        AppIcon.VIDEO,
        tr("batch.mode.full.title"),
        tr("batch.mode.full.desc"),
        True,
    ),
    BatchMode(
        "trans_sub",
        AppIcon.SUBTITLE,
        tr("batch.mode.trans_sub.title"),
        tr("batch.mode.trans_sub.desc"),
        True,
    ),
    BatchMode(
        "transcribe",
        AppIcon.MICROPHONE,
        tr("batch.mode.transcribe.title"),
        tr("batch.mode.transcribe.desc"),
        True,
    ),
    BatchMode(
        "subtitle",
        AppIcon.FILE,
        tr("batch.mode.subtitle.title"),
        tr("batch.mode.subtitle.desc"),
        False,
    ),
]

# 阶段元数据：key -> (图标, 标题, 说明)
STAGE_SPECS = {
    "transcribe": (
        AppIcon.MICROPHONE,
        tr("batch.stage.transcribe.title"),
        tr("batch.stage.transcribe.desc"),
    ),
    "subtitle": (
        AppIcon.SUBTITLE,
        tr("batch.stage.subtitle.title"),
        tr("batch.stage.subtitle.desc"),
    ),
    "dubbing": (
        AppIcon.VOLUME,
        tr("batch.stage.dubbing.title"),
        tr("batch.stage.dubbing.desc"),
    ),
    "synthesis": (
        AppIcon.VIDEO,
        tr("batch.stage.synthesis.title"),
        tr("batch.stage.synthesis.desc"),
    ),
}


def mode_by_key(key: str) -> BatchMode:
    for mode in BATCH_MODES:
        if mode.key == key:
            return mode
    return BATCH_MODES[0]


def stages_for_mode(mode_key: str, dubbing_enabled: bool) -> list[str]:
    if mode_key == "transcribe":
        return ["transcribe"]
    if mode_key == "subtitle":
        return ["subtitle"]
    if mode_key == "trans_sub":
        return ["transcribe", "subtitle"]
    stages = ["transcribe", "subtitle"]
    if dubbing_enabled:
        stages.append("dubbing")
    stages.append("synthesis")
    return stages


def collect_files(paths: list[str], extensions: set[str]) -> tuple[list[str], int]:
    """展开文件夹（最多 3 层）并按扩展名过滤，返回 (有效文件, 忽略数)。"""
    expanded: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                depth = root[len(path) :].count(os.sep)
                if depth >= _FOLDER_MAX_DEPTH:
                    dirs.clear()
                    continue
                dirs.sort()
                expanded.extend(os.path.join(root, name) for name in sorted(files))
        else:
            expanded.append(path)
    valid = [
        path
        for path in expanded
        if os.path.isfile(path) and Path(path).suffix.lower() in extensions
    ]
    return valid, len(expanded) - len(valid)


class JobStatus(Enum):
    WAITING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class BatchJob:
    path: str
    status: JobStatus = JobStatus.WAITING
    progress: int = 0
    note: str = field(default_factory=lambda: tr("batch.status.waiting"))
    error: str = ""
    stage: str = ""  # 运行中的当前阶段 key
    outputs: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def folder(self) -> str:
        folder = str(Path(self.path).parent)
        home = os.path.expanduser("~")
        return "~" + folder[len(home) :] if folder.startswith(home) else folder


class PageState(Enum):
    EMPTY = auto()
    READY = auto()
    RUNNING = auto()
    DONE = auto()


# ---------------------------------------------------------------------------
# 线程编排
# ---------------------------------------------------------------------------


class JobRunner(QObject):
    """把一个文件按阶段链依次跑完；阶段 i/n 的进度映射到总进度。"""

    progressChanged = pyqtSignal(int, str, str)  # 总进度 0-100 / 行内文案 / 阶段 key
    completed = pyqtSignal(list)  # 输出文件路径列表
    failed = pyqtSignal(str)

    def __init__(self, file_path: str, stages: list[str], parent: Optional[QObject] = None):
        super().__init__(parent)
        self._path = file_path
        self._stages = stages
        self._index = 0
        self._thread = None
        self._subtitle_path = ""  # 转录/字幕阶段产出，供后续阶段消费
        self._dub_video = ""  # 配音阶段产出的中间配音视频（在任务目录内）
        self._task_dir = ""  # 本文件流水线的任务目录（中间产物落盘处）

    def start(self):
        self._run_stage(0)

    def _ensure_task_dir(self) -> str:
        if not self._task_dir:
            self._task_dir = TaskFactory.new_task_dir(self._path, "batch")
        return self._task_dir

    def request_cancel(self):
        """广播取消请求（非阻塞）：批量取消时先让所有线程并发开始退出，再逐个 cancel() 收割。"""
        if self._thread is not None and self._thread.isRunning():
            self._thread.request_cancel()

    def cancel(self):
        thread, self._thread = self._thread, None
        if thread is not None and thread.isRunning():
            # 逐个断连：某个信号无连接抛 TypeError 不应放跑其余信号
            for signal in (thread.progress, thread.error, thread.finished):
                try:
                    signal.disconnect()
                except TypeError:
                    pass
            thread.stop()
        # 取消的运行是废弃物：thread.stop() 已等线程退出，任务目录可安全清掉
        output_paths.cleanup_task_dir(self._task_dir, keep=False)
        self._task_dir = ""
        self._dub_video = ""

    def release(self):
        """正常完成路径的收尾：等线程真正退出，供控制器在 deleteLater 前调用。

        自定义 finished 信号在 run() 返回前发出，此刻线程可能还在 finally
        （如 SubtitleThread clear_task_context）；不等退出就销毁 running
        QThread 会触发 "Destroyed while still running" qFatal。
        取消路径 cancel() 已把 _thread 置 None 并 wait 过，这里自然跳过。
        """
        thread, self._thread = self._thread, None
        if thread is not None and thread.isRunning():
            thread.wait(2000)

    # ----- 阶段链 -----

    def _run_stage(self, index: int):
        self._index = index
        stage = self._stages[index]
        try:
            thread = self._build_thread(stage)
        except Exception as exc:  # 任务构建失败（配置/路径问题）
            self.failed.emit(f"{STAGE_SPECS[stage][1]}：{exc}")
            return
        thread.setParent(self)
        thread.progress.connect(self._on_stage_progress)
        thread.error.connect(self._on_stage_error)
        self._thread = thread
        self._emit_progress(0, tr("batch.status.preparing"))
        thread.start()

    def _build_thread(self, stage: str):
        if stage == "transcribe":
            last = self._is_last(stage)
            task = TaskFactory.create_transcribe_task(
                self._path,
                need_next_task=not last,
                task_dir=None if last else self._ensure_task_dir(),
            )
            thread = TranscriptThread(task)
            thread.finished.connect(self._on_transcribed)
            return thread
        if stage == "subtitle":
            # 字幕模式下输入文件本身就是字幕；链式模式消费转录产物。
            # 成品锚定到媒体文件，落在源文件旁（builder 内统一处理）。
            source = self._subtitle_path or self._path
            video = self._path if self._subtitle_path else None
            need_synthesis = "synthesis" in self._stages[self._index + 1 :]
            task = TaskFactory.create_subtitle_task(
                source,
                video_path=video,
                need_next_task=need_synthesis,
                task_dir=self._ensure_task_dir() if need_synthesis else self._task_dir or None,
            )
            thread = SubtitleThread(task)
            thread.finished.connect(self._on_subtitled)
            return thread
        if stage == "dubbing":
            # 配音视频与音频都是中间产物，进任务目录，随任务目录清理
            video = Path(self._path)
            task_dir = Path(self._ensure_task_dir())
            dubbing_dir = task_dir / output_paths.DUBBING_DIR
            task = TaskFactory.create_dubbing_task(
                self._path,
                self._subtitle_path,
                output_video_path=str(dubbing_dir / f"dubbed{video.suffix}"),
                output_audio_path=str(dubbing_dir / output_paths.DUBBING_AUDIO_FILE),
                task_dir=str(task_dir),
            )
            thread = DubbingThread(task)
            thread.finished.connect(self._on_dubbed)
            return thread
        # synthesis：输出路径按原始视频命名，输入可换成配音视频
        task = TaskFactory.create_synthesis_task(
            self._path,
            self._subtitle_path,
            task_dir=self._task_dir or None,
            dubbed=bool(self._dub_video) or "dubbing" in self._stages,
        )
        if self._dub_video:
            task.video_path = self._dub_video
        thread = VideoSynthesisThread(task)
        thread.finished.connect(self._on_synthesized)
        return thread

    def _finish(self, outputs: list[str]):
        """流水线成功收尾：按设置清理任务目录后上报产物。"""
        output_paths.cleanup_task_dir(
            self._task_dir, keep=bool(cfg.keep_intermediates.value)
        )
        self._task_dir = ""
        self.completed.emit(outputs)

    def _is_last(self, stage: str) -> bool:
        return self._stages[-1] == stage

    def _advance(self, outputs: Optional[list[str]] = None):
        if outputs is not None:
            self._finish(outputs)
            return
        self._run_stage(self._index + 1)

    # ----- 阶段完成回调 -----

    def _on_transcribed(self, task: TranscribeTask):
        if not task.output_path:
            self.failed.emit(
                tr("batch.error.empty_output", stage=STAGE_SPECS["transcribe"][1])
            )
            return
        self._subtitle_path = task.output_path
        self._advance([task.output_path] if self._is_last("transcribe") else None)

    def _on_subtitled(self, _video_path: str, output_path: str):
        if not output_path:
            self.failed.emit(
                tr("batch.error.empty_output", stage=STAGE_SPECS["subtitle"][1])
            )
            return
        self._subtitle_path = output_path
        self._advance([output_path] if self._is_last("subtitle") else None)

    def _on_dubbed(self, task):
        if not task.output_video_path:
            self.failed.emit(
                tr("batch.error.empty_video_output", stage=STAGE_SPECS["dubbing"][1])
            )
            return
        self._dub_video = task.output_video_path
        self._advance()

    def _on_synthesized(self, task):
        if not task.output_path:
            self.failed.emit(
                tr("batch.error.empty_output", stage=STAGE_SPECS["synthesis"][1])
            )
            return
        self._advance([task.output_path])

    # ----- 进度 / 错误 -----

    def _on_stage_progress(self, value: int, message: str):
        self._emit_progress(value, message)

    def _emit_progress(self, value: int, message: str):
        stage = self._stages[self._index]
        title = STAGE_SPECS[stage][1]
        note = f"{title} · {message}" if message else title
        overall = int((self._index * 100 + max(0, min(100, value))) / len(self._stages))
        self.progressChanged.emit(overall, note, stage)

    def _on_stage_error(self, message: str):
        stage = self._stages[self._index]
        self.failed.emit(f"{STAGE_SPECS[stage][1]}：{message}")


class BatchController(QObject):
    """批量队列：按并发数派发 JobRunner，暂停只停派发、在跑任务继续。"""

    queueChanged = pyqtSignal()  # 队列成员变化（增删/清空），页面重建行
    jobChanged = pyqtSignal(int)  # 单行状态/进度变化
    activityChanged = pyqtSignal()  # 运行/暂停状态变化
    batchFinished = pyqtSignal()  # 一轮批量跑完（暂停清空不算）

    def __init__(
        self, concurrency: Callable[[], int], parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.jobs: list[BatchJob] = []
        self._concurrency = concurrency
        self._runners: dict[JobRunner, BatchJob] = {}
        self._stages: list[str] = []
        self._dispatch_enabled = False
        self._started = False  # 本批是否启动过（收尾判定用）
        self._finish_announced = False  # batchFinished 每批只发一次

    # ----- 队列维护 -----

    def add_paths(self, paths: list[str]) -> int:
        existing = {os.path.normpath(job.path) for job in self.jobs}
        added = 0
        for path in paths:
            normalized = os.path.normpath(path)
            if normalized in existing:
                continue
            existing.add(normalized)
            self.jobs.append(BatchJob(path=path))
            added += 1
        if added:
            self.queueChanged.emit()
            if self._dispatch_enabled:
                self._dispatch()
        return added

    def keep_only(self, extensions: set[str]) -> int:
        """切换模式后丢弃扩展名不匹配的任务，返回丢弃数。仅空闲时调用。"""
        kept = [job for job in self.jobs if Path(job.path).suffix.lower() in extensions]
        dropped = len(self.jobs) - len(kept)
        if dropped:
            self.jobs = kept
            self.queueChanged.emit()
        return dropped

    def remove(self, job: BatchJob):
        runner = self._runner_of(job)
        if runner is not None:
            runner.cancel()
            self._release_runner(runner)
        if job in self.jobs:
            self.jobs.remove(job)
            self.queueChanged.emit()
        self._dispatch()

    def retry(self, job: BatchJob, stages: Optional[list[str]] = None):
        """失败任务重试即跑：批次已结束时带 stages 重新开闸（只复跑这一个）。

        暂停排空中（还有任务在跑但派发已关）不偷开闸，尊重暂停语义。
        """
        if job.status != JobStatus.FAILED:
            return
        job.status = JobStatus.WAITING
        job.progress = 0
        job.note = tr("batch.status.waiting")
        job.error = ""
        self.jobChanged.emit(self.jobs.index(job))
        if stages is not None and not self._dispatch_enabled and not self._runners:
            self._stages = list(stages)
            self._dispatch_enabled = True
            self._started = True
            self._finish_announced = False
        if self._dispatch_enabled:
            self._dispatch()
        else:
            self.activityChanged.emit()

    def clear(self):
        self._dispatch_enabled = False
        self._started = False
        runners = list(self._runners)
        for runner in runners:  # 先并发广播取消，避免 N 个线程串行各等 3s 冻结 GUI
            runner.request_cancel()
        for runner in runners:
            runner.cancel()
            self._release_runner(runner)
        self.jobs.clear()
        self.queueChanged.emit()
        self.activityChanged.emit()

    # ----- 运行控制 -----

    def start(self, stages: list[str]):
        self._stages = list(stages)
        for job in self.jobs:
            if job.status == JobStatus.FAILED:
                job.status = JobStatus.WAITING
                job.progress = 0
                job.note = tr("batch.status.waiting")
                job.error = ""
        self._dispatch_enabled = True
        self._started = True
        self._finish_announced = False
        self.queueChanged.emit()
        self._dispatch()

    def pause(self):
        self._dispatch_enabled = False
        self.activityChanged.emit()

    def resume(self):
        self._dispatch_enabled = True
        self._dispatch()

    def shutdown(self):
        self._dispatch_enabled = False
        runners = list(self._runners)
        for runner in runners:  # 先并发广播取消，再逐个收割
            runner.request_cancel()
        for runner in runners:
            runner.cancel()
            self._release_runner(runner)

    # ----- 状态查询 -----

    def is_active(self) -> bool:
        return bool(self._runners) or (
            self._dispatch_enabled and self.count(JobStatus.WAITING) > 0
        )

    def is_paused(self) -> bool:
        return bool(self._runners) and not self._dispatch_enabled

    def count(self, status: JobStatus) -> int:
        return sum(1 for job in self.jobs if job.status == status)

    def current_progress(self) -> int:
        """当前进度：处理中任务的平均进度（与右栏「当前进度」对应）。"""
        running = [job.progress for job in self.jobs if job.status == JobStatus.RUNNING]
        return int(sum(running) / len(running)) if running else 0

    def active_stages(self) -> set[str]:
        return {job.stage for job in self._runners.values() if job.stage}

    # ----- 派发 -----

    def _runner_of(self, job: BatchJob) -> Optional[JobRunner]:
        for runner, owned in self._runners.items():
            if owned is job:
                return runner
        return None

    def _release_runner(self, runner: JobRunner):
        self._runners.pop(runner, None)
        runner.release()
        runner.deleteLater()

    def _dispatch(self):
        while self._dispatch_enabled and len(self._runners) < max(1, self._concurrency()):
            job = next((j for j in self.jobs if j.status == JobStatus.WAITING), None)
            if job is None:
                break
            self._start_job(job)
        self._maybe_finish()
        self.activityChanged.emit()

    def _maybe_finish(self):
        """统一收尾判定：没有在跑且没有可跑时宣布本批结束（每批一次）。

        覆盖正常跑完、暂停后排空到底、运行中移除最后一个等待任务等路径。
        暂停且还有等待任务时不算结束（用户主动停在半程）。
        """
        if self._runners or not self._started or self._finish_announced:
            return
        if not self.jobs or self.count(JobStatus.WAITING) > 0:
            return
        self._dispatch_enabled = False
        self._finish_announced = True
        self.batchFinished.emit()

    def _start_job(self, job: BatchJob):
        job.status = JobStatus.RUNNING
        job.progress = 0
        job.note = tr("batch.status.preparing")
        job.stage = self._stages[0] if self._stages else ""
        runner = JobRunner(job.path, self._stages, self)
        self._runners[runner] = job
        runner.progressChanged.connect(partial(self._on_job_progress, job))
        runner.completed.connect(partial(self._on_job_completed, job, runner))
        runner.failed.connect(partial(self._on_job_failed, job, runner))
        self.jobChanged.emit(self.jobs.index(job))
        runner.start()

    def _on_job_progress(self, job: BatchJob, value: int, note: str, stage: str):
        job.progress = value
        job.note = note
        job.stage = stage
        if job in self.jobs:
            self.jobChanged.emit(self.jobs.index(job))

    def _on_job_completed(self, job: BatchJob, runner: JobRunner, outputs: list):
        self._release_runner(runner)
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.stage = ""
        job.outputs = list(outputs)
        job.note = (
            tr("batch.note.output", name=Path(outputs[-1]).name)
            if outputs
            else tr("batch.note.completed")
        )
        if job in self.jobs:
            self.jobChanged.emit(self.jobs.index(job))
        self._dispatch()

    def _on_job_failed(self, job: BatchJob, runner: JobRunner, error: str):
        self._release_runner(runner)
        job.status = JobStatus.FAILED
        job.stage = ""
        job.error = error
        job.note = error.splitlines()[0] if error else tr("batch.note.failed")
        if job in self.jobs:
            self.jobChanged.emit(self.jobs.index(job))
        self._dispatch()


# ---------------------------------------------------------------------------
# 页面组件
# ---------------------------------------------------------------------------


class SquareIconButton(QFrame):
    """38px 方形图标按钮：打开目录 / 重试 / 移除。"""

    clicked = pyqtSignal()

    def __init__(self, icon: AppIcon, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._icon = icon
        self.setFixedSize(38, 38)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        if tooltip:
            self.setToolTip(tooltip)
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
        surface = palette.card_surface
        draw_rounded_surface(
            self,
            rgba(palette.accent, 0.10) if hovered else surface,
            rgba(palette.accent, 0.62) if hovered else palette.line_soft,
            10,
        )
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconLabel.setPixmap(icon_pixmap(self._icon, palette.muted, 17))
        self.setStyleSheet("background: transparent; border: none;")
        self.update()


class TaskRow(QFrame):
    """任务行：文件名/目录 + 进度 + 状态胶囊 + 操作。

    点击行空白区域弹出任务详情（完整错误 / 输出文件）。
    """

    openRequested = pyqtSignal(object)
    retryRequested = pyqtSignal(object)
    removeRequested = pyqtSignal(object)
    detailsRequested = pyqtSignal(object)

    def __init__(self, job: BatchJob, parent=None):
        super().__init__(parent)
        self.setObjectName("batchTaskRow")
        self.job = job
        self._running = False
        self.setMinimumHeight(78)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setToolTip(tr("batch.row.details_tip"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        # 文件类型图标（视频/音频/字幕/文本）
        self.typeIconBox = QFrame(self)
        self.typeIconBox.setObjectName("taskTypeIconBox")
        self.typeIconBox.setFixedSize(34, 34)
        type_icon_layout = QVBoxLayout(self.typeIconBox)
        type_icon_layout.setContentsMargins(0, 0, 0, 0)
        self.typeIconLabel = QLabel(self.typeIconBox)
        self.typeIconLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        type_icon_layout.addWidget(self.typeIconLabel)
        layout.addWidget(self.typeIconBox)

        file_box = QVBoxLayout()
        file_box.setSpacing(5)
        file_box.addStretch(1)
        self.nameLabel = ElidedLabel(job.name, self)
        self.nameLabel.setObjectName("taskName")
        apply_font(self.nameLabel, 15, 820)
        file_box.addWidget(self.nameLabel)
        self.pathLabel = ElidedLabel(job.folder, self)
        self.pathLabel.setObjectName("taskPath")
        apply_font(self.pathLabel, 12, 720)
        file_box.addWidget(self.pathLabel)
        file_box.addStretch(1)
        layout.addLayout(file_box, 2)

        progress_box = QVBoxLayout()
        progress_box.setSpacing(7)
        progress_box.addStretch(1)
        self.progressLine = ProgressBarLine(self)
        progress_box.addWidget(self.progressLine)
        self.noteLabel = ElidedLabel(job.note, self)
        self.noteLabel.setObjectName("taskNote")
        apply_font(self.noteLabel, 12, 720)
        progress_box.addWidget(self.noteLabel)
        progress_box.addStretch(1)
        # 进度列随窗口宽度自适应（窄窗口下让位给文件名列）
        progress_host = QWidget(self)
        progress_host.setLayout(progress_box)
        progress_host.setMinimumWidth(110)
        progress_host.setMaximumWidth(210)
        layout.addWidget(progress_host, 1)

        self.pill = StatusPill(tr("batch.status.waiting"), "neutral", self)
        self.pill.setMinimumWidth(86)
        layout.addWidget(self.pill)

        self.primaryButton = SquareIconButton(
            AppIcon.FOLDER, tr("batch.row.open_output"), self
        )
        self.primaryButton.clicked.connect(lambda: self.openRequested.emit(self.job))
        layout.addWidget(self.primaryButton)
        self.removeButton = SquareIconButton(AppIcon.CANCEL, tr("batch.row.remove"), self)
        self.removeButton.clicked.connect(lambda: self.removeRequested.emit(self.job))
        layout.addWidget(self.removeButton)
        self.syncStyle()
        self.refresh()

    def mousePressEvent(self, event):
        # 子按钮各自消费点击；落到行空白处的点击展示任务详情
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.detailsRequested.emit(self.job)
            event.accept()
            return
        super().mousePressEvent(event)

    def refresh(self):
        job = self.job
        self._running = job.status == JobStatus.RUNNING
        self.nameLabel.setText(job.name)
        self.pathLabel.setText(job.folder)
        self.noteLabel.setText(job.note)
        self.noteLabel.setToolTip(job.error or "")
        self.progressLine.setValue(job.progress)
        pill_specs = {
            JobStatus.WAITING: (tr("batch.status.waiting"), "neutral", "accent"),
            JobStatus.RUNNING: (tr("batch.status.running"), "warn", "warn"),
            JobStatus.COMPLETED: (tr("batch.status.completed"), "ok", "accent"),
            JobStatus.FAILED: (tr("batch.status.failed"), "fail", "fail"),
        }
        text, level, tone = pill_specs[job.status]
        self.pill.setState(text, level)
        self.progressLine.setTone(tone)
        failed = job.status == JobStatus.FAILED
        self.primaryButton.setIcon(AppIcon.SYNC if failed else AppIcon.FOLDER)
        self.primaryButton.setToolTip(
            tr("batch.row.retry") if failed else tr("batch.row.open_output")
        )
        try:
            self.primaryButton.clicked.disconnect()
        except TypeError:
            pass
        if failed:
            self.primaryButton.clicked.connect(
                lambda: self.retryRequested.emit(self.job)
            )
        else:
            self.primaryButton.clicked.connect(
                lambda: self.openRequested.emit(self.job)
            )
        self.update()

    def paintEvent(self, event):
        palette = app_palette()
        if self._running:
            bg, border = rgba(palette.accent, 0.07), rgba(palette.accent, 0.7)
        else:
            bg = palette.card_surface
            border = palette.line_soft
        draw_rounded_surface(self, bg, border, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.typeIconLabel.setPixmap(
            icon_pixmap(file_type_icon(self.job.path), palette.muted, 17)
        )
        self.setStyleSheet(
            f"""
            QFrame#batchTaskRow {{ background: transparent; border: none; }}
            QFrame#taskTypeIconBox {{
                background: {palette.control};
                border: none;
                border-radius: 10px;
            }}
            QLabel#taskName {{ color: {palette.text}; background: transparent; }}
            QLabel#taskPath, QLabel#taskNote {{
                color: {palette.muted}; background: transparent;
            }}
            """
        )
        self.pill.syncStyle()
        self.primaryButton.syncStyle()
        self.removeButton.syncStyle()


class MetricCard(QFrame):
    """统计卡：数值 + 标签。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("batchMetric")
        self.setMinimumHeight(68)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addStretch(1)
        self.valueLabel = QLabel("0", self)
        self.valueLabel.setObjectName("metricValue")
        apply_font(self.valueLabel, 22, 860)
        layout.addWidget(self.valueLabel)
        self.nameLabel = QLabel("", self)
        self.nameLabel.setObjectName("metricName")
        apply_font(self.nameLabel, 13, 760)
        layout.addWidget(self.nameLabel)
        layout.addStretch(1)
        self.syncStyle()

    def setData(self, value: str, name: str):
        self.valueLabel.setText(value)
        self.nameLabel.setText(name)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#batchMetric {{ background: transparent; border: none; }}
            QLabel#metricValue {{ color: {palette.text}; background: transparent; }}
            QLabel#metricName {{ color: {palette.muted}; background: transparent; }}
            """
        )
        self.update()


class StageRow(QFrame):
    """流水线阶段行：图标 + 标题/说明 + 设置入口。

    阶段状态（等待/当前/完成）用边框与底色表达；右侧是跳到对应
    设置页的齿轮按钮，不放文字状态 tag。
    """

    settingsRequested = pyqtSignal(str)  # stage key

    def __init__(self, stage_key: str, parent=None):
        super().__init__(parent)
        self.setObjectName("batchStageRow")
        icon, title, desc = STAGE_SPECS[stage_key]
        self.stage_key = stage_key
        self._icon = icon
        self._state = "wait"  # wait / active / done
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(11)
        self.iconBox = IconBox(icon, self, size=32, tone="accent")
        layout.addWidget(self.iconBox)
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("stageTitle")
        apply_font(self.titleLabel, 15, 820)
        text_box.addWidget(self.titleLabel)
        self.descLabel = ElidedLabel(desc, self)
        self.descLabel.setObjectName("stageDesc")
        apply_font(self.descLabel, 12, 720)
        text_box.addWidget(self.descLabel)
        layout.addLayout(text_box, 1)
        self.settingsButton = RoundIconButton(AppIcon.SETTING, diameter=28, parent=self)
        self.settingsButton.setToolTip(tr("batch.stage.settings_tip", title=title))
        self.settingsButton.clicked.connect(
            lambda: self.settingsRequested.emit(self.stage_key)
        )
        layout.addWidget(self.settingsButton)
        self.syncStyle()

    def setState(self, state: str):
        assert state in ("wait", "active", "done"), state
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event):
        palette = app_palette()
        if self._state in ("active", "done"):
            bg, border = rgba(palette.accent, 0.07), rgba(palette.accent, 0.66)
        else:
            bg = palette.card_surface
            border = palette.line_soft
        draw_rounded_surface(self, bg, border, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconBox.syncStyle()
        self.setStyleSheet(
            f"""
            QFrame#batchStageRow {{ background: transparent; border: none; }}
            QLabel#stageTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#stageDesc {{ color: {palette.muted}; background: transparent; }}
            """
        )
        self.settingsButton.syncStyle()
        self.update()


class BatchSidePanel(WorkbenchPanel):
    """右栏「本批任务」：状态胶囊 + 2x2 统计 + 流水线阶段。"""

    stageSettingsRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent, padded=True)
        self.bodyLayout.setContentsMargins(20, 20, 20, 20)
        self.bodyLayout.setSpacing(14)

        self.header = PanelHeader(
            tr("batch.panel.title"), inline=True, underline=True, parent=self
        )
        self.pill = StatusPill(tr("batch.panel.not_started"), "neutral", self)
        self.header.addRight(self.pill)
        self.bodyLayout.addWidget(self.header)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.metrics = [MetricCard(self) for _ in range(4)]
        for index, metric in enumerate(self.metrics):
            grid.addWidget(metric, index // 2, index % 2)
        self.bodyLayout.addLayout(grid)
        self.bodyLayout.addSpacing(14)

        self.stageBox = QVBoxLayout()
        self.stageBox.setSpacing(10)
        self.bodyLayout.addLayout(self.stageBox)
        self.stageRows: list[StageRow] = []
        self.bodyLayout.addStretch(1)
        self.syncStyle()

    def rebuildStages(self, stage_keys: list[str]):
        for row in self.stageRows:
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.stageRows = []
        for key in stage_keys:
            row = StageRow(key, self)
            row.settingsRequested.connect(self.stageSettingsRequested)
            self.stageBox.addWidget(row)
            self.stageRows.append(row)

    def setStageStates(self, states: dict[str, str]):
        for row in self.stageRows:
            row.setState(states.get(row.stage_key, "wait"))

    def setMetrics(self, data: list[tuple[str, str]]):
        for metric, (value, name) in zip(self.metrics, data):
            metric.setData(value, name)

    def syncStyle(self):
        WorkbenchPanel.syncStyle(self)
        self.header.syncStyle()


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


class BatchProcessInterface(QWidget):
    """批量处理页。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("BatchProcessInterface")
        self.setWindowTitle(tr("batch.title"))
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self.mode = mode_by_key(str(cfg.batch_mode.value))
        self._batch_ran = False
        self._filter = "all"
        self._rows: list[TaskRow] = []

        self.controller = BatchController(
            concurrency=lambda: int(cfg.batch_concurrency.value), parent=self
        )
        self._build_ui()
        self._connect_signals()
        self._rebuild_stage_rows()
        self._refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QWidget#BatchProcessInterface {{ background: {palette.bg}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(14)

        # 页头：标题 + 工具栏
        head = QHBoxLayout()
        head.setSpacing(14)
        self.headIcon = QLabel(self)
        self.headIcon.setFixedSize(24, 24)
        head.addWidget(self.headIcon)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.titleLabel = QLabel(tr("batch.title"), self)
        self.titleLabel.setObjectName("pageTitle")
        apply_font(self.titleLabel, 26, 860)
        title_box.addWidget(self.titleLabel)
        self.subtitleLabel = QLabel("", self)
        self.subtitleLabel.setObjectName("pageSubtitle")
        apply_font(self.subtitleLabel, 13, 720)
        title_box.addWidget(self.subtitleLabel)
        head.addLayout(title_box)
        head.addStretch(1)
        self.addFolderButton = WorkbenchButton(
            tr("batch.btn.add_folder"), AppIcon.FOLDER_ADD, parent=self
        )
        head.addWidget(self.addFolderButton)
        self.addFileButton = WorkbenchButton(
            tr("batch.btn.add_file"), AppIcon.ADD, parent=self
        )
        head.addWidget(self.addFileButton)
        self.clearButton = WorkbenchButton(
            tr("batch.btn.clear"), AppIcon.DELETE, parent=self
        )
        head.addWidget(self.clearButton)
        self.primaryButton = WorkbenchButton(
            tr("batch.btn.start"), AppIcon.PLAY, primary=True, parent=self
        )
        self.primaryButton.setMinimumWidth(150)
        head.addWidget(self.primaryButton)
        root.addLayout(head)

        # 模式卡
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        self.modeCards: list[SelectableCard] = []
        for mode in BATCH_MODES:
            card = SelectableCard(mode.key, mode.title, mode.desc, mode.icon, self)
            card.clicked.connect(self._on_mode_clicked)
            mode_row.addWidget(card, 1)
            self.modeCards.append(card)
        root.addLayout(mode_row)

        # 工作区：队列 + 右栏
        work = QHBoxLayout()
        work.setSpacing(14)
        self.queuePanel = WorkbenchPanel(self, padded=False)
        queue_layout = self.queuePanel.bodyLayout

        queue_head = QFrame(self.queuePanel)
        queue_head.setObjectName("queueHead")
        queue_head.setFixedHeight(60)
        head_layout = QHBoxLayout(queue_head)
        head_layout.setContentsMargins(16, 0, 16, 0)
        head_layout.setSpacing(12)
        self.filterTabs = FilterTabs(
            [
                ("all", tr("batch.filter.all")),
                ("waiting", tr("batch.status.waiting")),
                ("running", tr("batch.status.running")),
                ("failed", tr("batch.status.failed")),
            ],
            queue_head,
        )
        head_layout.addWidget(self.filterTabs)
        head_layout.addStretch(1)
        self.concurrencySelect = PillSelect(queue_head)
        self.concurrencySelect.setItems(
            [tr("batch.concurrency", n=value) for value in (1, 2, 3)],
            tr("batch.concurrency", n=int(cfg.batch_concurrency.value)),
        )
        head_layout.addWidget(self.concurrencySelect)
        self.countPill = StatusPill(tr("batch.count", n=0), "neutral", queue_head)
        self.countPill.setMinimumWidth(88)
        head_layout.addWidget(self.countPill)
        queue_layout.addWidget(queue_head)

        self.queueStack = QStackedWidget(self.queuePanel)
        # 空态拖放区
        drop_host = QWidget(self.queuePanel)
        drop_layout = QVBoxLayout(drop_host)
        # 与转录/字幕/合成页拖放区统一 16 边距
        drop_layout.setContentsMargins(16, 16, 16, 16)
        self.dropZone = DropZone(
            icon=AppIcon.FOLDER_ADD,
            title=tr("batch.drop.title"),
            pick_text=tr("batch.btn.add_file"),
            pick_icon=AppIcon.ADD,
            formats_line=" ",  # 占位保证间距，实际文案随模式在 _refresh 填充
            parent=drop_host,
        )
        drop_layout.addWidget(self.dropZone)
        self.queueStack.addWidget(drop_host)
        # 任务列表
        self.listScroll = QScrollArea(self.queuePanel)
        self.listScroll.setWidgetResizable(True)
        self.listScroll.setFrameShape(QFrame.NoFrame)
        self.rowsHost = QWidget(self.listScroll)
        self.rowsLayout = QVBoxLayout(self.rowsHost)
        self.rowsLayout.setContentsMargins(14, 14, 14, 14)
        self.rowsLayout.setSpacing(10)
        self.filterEmptyLabel = QLabel(tr("batch.filter.empty"), self.rowsHost)
        self.filterEmptyLabel.setObjectName("filterEmpty")
        self.filterEmptyLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.filterEmptyLabel, 14, 720)
        self.filterEmptyLabel.hide()
        self.rowsLayout.addWidget(self.filterEmptyLabel)
        self.rowsLayout.addStretch(1)
        self.listScroll.setWidget(self.rowsHost)
        self.queueStack.addWidget(self.listScroll)
        queue_layout.addWidget(self.queueStack, 1)
        work.addWidget(self.queuePanel, 1)

        self.sidePanel = BatchSidePanel(self)
        self.sidePanel.setFixedWidth(300)
        work.addWidget(self.sidePanel)
        root.addLayout(work, 1)

        self._sync_page_style()

    def _sync_page_style(self):
        palette = app_palette()
        self.headIcon.setPixmap(icon_pixmap(AppIcon.VIDEO, palette.muted, 24))
        # 滚动条规则并在 QScrollArea 样式表里：macOS 上只设到 QScrollBar
        # 子控件会走 transient 浮层模式，滚动条盖住任务行右缘。
        self.listScroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 4px 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {rgba(palette.muted, 0.32)};
                border-radius: 3px; min-height: 32px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            """
        )
        self.rowsHost.setStyleSheet(
            f"""
            QWidget {{ background: transparent; }}
            QLabel#filterEmpty {{ color: {palette.subtle}; }}
            """
        )
        extra = f"""
            QLabel#pageTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#pageSubtitle {{ color: {palette.muted}; background: transparent; }}
            QFrame#queueHead {{
                background: transparent; border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
        """
        self.setStyleSheet(
            f"QWidget#BatchProcessInterface {{ background: {palette.bg}; }}" + extra
        )

    # ------------------------------------------------------------- signals

    def _connect_signals(self):
        self.controller.queueChanged.connect(self._rebuild_rows)
        self.controller.jobChanged.connect(self._on_job_changed)
        self.controller.activityChanged.connect(self._refresh)
        self.controller.batchFinished.connect(self._on_batch_finished)

        self.dropZone.browseRequested.connect(self._browse_files)
        self.addFileButton.clicked.connect(self._browse_files)
        self.addFolderButton.clicked.connect(self._browse_folder)
        self.clearButton.clicked.connect(self._on_clear_clicked)
        self.primaryButton.clicked.connect(self._on_primary_clicked)
        self.filterTabs.changed.connect(self._on_filter_changed)
        self.concurrencySelect.currentTextChanged.connect(self._on_concurrency_selected)
        self.sidePanel.stageSettingsRequested.connect(self._open_stage_settings)

    # ------------------------------------------------------------ 文件加入

    def _allowed_extensions(self) -> set[str]:
        return _MEDIA_EXTENSIONS if self.mode.accepts_media else _SUBTITLE_EXTENSIONS

    def _browse_files(self):
        if self.mode.accepts_media:
            patterns = " ".join(f"*{ext}" for ext in sorted(_MEDIA_EXTENSIONS))
            file_filter = tr("batch.filter.media", patterns=patterns)
        else:
            patterns = " ".join(f"*{ext}" for ext in sorted(_SUBTITLE_EXTENSIONS))
            file_filter = tr("batch.filter.subtitle", patterns=patterns)
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("batch.dialog.pick_files"), "", file_filter
        )
        if files:
            self.add_paths(files)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("batch.dialog.pick_folder"), ""
        )
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: list[str]):
        """加入文件/文件夹：自动展开过滤、空队列时按文件类型自动切换模式。"""
        self._maybe_auto_switch_mode(paths)
        valid, ignored = collect_files(paths, self._allowed_extensions())
        added = self.controller.add_paths(valid) if valid else 0
        duplicated = len(valid) - added
        if added:
            parts = [tr("batch.added.count", n=added)]
            if duplicated:
                parts.append(tr("batch.added.duplicated", n=duplicated))
            if ignored:
                parts.append(tr("batch.added.ignored", n=ignored))
            InfoBar.success(
                tr("batch.added.title"), "，".join(parts),
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.TOP, parent=self,
            )
        else:
            reason = tr("batch.empty.duplicated") if duplicated else (
                tr("batch.empty.no_subtitle")
                if not self.mode.accepts_media
                else tr("batch.empty.no_media")
            )
            InfoBar.warning(
                tr("batch.empty.title"), reason,
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP, parent=self,
            )
        self._refresh()

    def _maybe_auto_switch_mode(self, paths: list[str]):
        """空队列时按拖入的文件类型自动切换输入类型不匹配的模式。"""
        if self.controller.jobs or self.controller.is_active():
            return
        media, _ = collect_files(paths, _MEDIA_EXTENSIONS)
        subtitles, _ = collect_files(paths, _SUBTITLE_EXTENSIONS)
        if self.mode.accepts_media and subtitles and not media:
            self._switch_mode("subtitle", announce=True)
        elif not self.mode.accepts_media and media and not subtitles:
            self._switch_mode("full", announce=True)

    # ----------------------------------------------------------- 模式切换

    def _on_mode_clicked(self, key: str):
        if key == self.mode.key:
            return
        if self.controller.is_active():
            InfoBar.warning(
                tr("batch.switch.busy_title"), tr("batch.switch.busy_body"),
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP, parent=self,
            )
            return
        self._switch_mode(key)

    def _switch_mode(self, key: str, announce: bool = False):
        self.mode = mode_by_key(key)
        if cfg.batch_mode.value != key:
            cfg.set(cfg.batch_mode, key)
        dropped = self.controller.keep_only(self._allowed_extensions())
        if dropped:
            InfoBar.info(
                tr("batch.filtered.title"),
                tr("batch.filtered.body", n=dropped, mode=self.mode.title),
                duration=INFOBAR_DURATION_INFO,
                position=InfoBarPosition.TOP, parent=self,
            )
        if announce:
            InfoBar.info(
                tr("batch.switched.title"),
                tr("batch.switched.body", mode=self.mode.title),
                duration=INFOBAR_DURATION_INFO,
                position=InfoBarPosition.TOP, parent=self,
            )
        self._batch_ran = False
        self._rebuild_stage_rows()
        self._refresh()

    def _rebuild_stage_rows(self):
        self.sidePanel.rebuildStages(
            stages_for_mode(self.mode.key, bool(cfg.dubbing_enabled.value))
        )

    # ----------------------------------------------------------- 运行控制

    def _preflight_error(self) -> Optional[str]:
        """开始前校验当前模式依赖的外部配置，返回错误文案。"""
        stages = stages_for_mode(self.mode.key, bool(cfg.dubbing_enabled.value))
        if "subtitle" in stages:
            needs_llm = (
                bool(cfg.need_optimize.value)
                or bool(cfg.need_split.value)
                or (
                    bool(cfg.need_translate.value)
                    and cfg.translator_service.value == TranslatorServiceEnum.OPENAI
                )
            )
            if needs_llm:
                task = TaskFactory.create_subtitle_task(file_path="")
                config = task.subtitle_config
                if config is None or not (
                    config.api_key and config.base_url and config.llm_model
                ):
                    return tr("batch.preflight.llm")
        if "synthesis" in stages and not shutil.which("ffmpeg"):
            return tr("batch.preflight.ffmpeg")
        if "dubbing" in stages:
            if not shutil.which("ffprobe"):
                return tr("batch.preflight.ffprobe")
            provider = cfg.dubbing_provider.value
            if provider != "edge" and not cfg.dubbing_api_key.value.strip():
                return tr("batch.preflight.dubbing_key")
        return None

    def _on_primary_clicked(self):
        state = self._page_state()
        if state == PageState.RUNNING:
            if self.controller.is_paused():
                self.controller.resume()
            else:
                self.controller.pause()
            return
        if state in (PageState.READY, PageState.DONE):
            error = self._preflight_error()
            if error is not None:
                InfoBar.error(
                    tr("batch.cannot_start"), error,
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP, parent=self,
                )
                return
            self._batch_ran = False
            self.controller.start(
                stages_for_mode(self.mode.key, bool(cfg.dubbing_enabled.value))
            )

    def _on_clear_clicked(self):
        self.controller.clear()
        self._batch_ran = False
        self._refresh()

    def _on_batch_finished(self):
        self._batch_ran = True
        failed = self.controller.count(JobStatus.FAILED)
        completed = self.controller.count(JobStatus.COMPLETED)
        if failed:
            InfoBar.warning(
                tr("batch.finished.title"),
                tr("batch.finished.body", completed=completed, failed=failed),
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP, parent=self,
            )
        else:
            InfoBar.success(
                tr("batch.done.title"),
                tr("batch.done.body", completed=completed),
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.TOP, parent=self,
            )
        self._refresh()

    def _on_concurrency_selected(self, text: str):
        digits = "".join(ch for ch in text if ch.isdigit())
        value = int(digits or 1)
        if cfg.batch_concurrency.value != value:
            cfg.set(cfg.batch_concurrency, value)

    # 阶段 key -> 设置页 key（SettingInterface.setCurrentPage）
    _STAGE_SETTING_PAGES = {
        "transcribe": "transcribe",
        "subtitle": "translate",  # 断句/优化/翻译在「翻译与优化」
        "dubbing": "dubbing",
        "synthesis": "subtitle",  # 「字幕合成配置」
    }

    def _open_stage_settings(self, stage_key: str):
        window = self.window()
        page_key = self._STAGE_SETTING_PAGES.get(stage_key)
        if page_key and hasattr(window, "openSettingsPage"):
            window.openSettingsPage(page_key)

    # ------------------------------------------------------------- 行操作

    def _on_open_job(self, job: BatchJob):
        # 在文件管理器中选中输出文件（无输出时选中源文件）
        target = job.outputs[-1] if job.outputs else job.path
        if Path(target).exists():
            reveal_in_explorer(str(target))
        else:
            open_folder(str(Path(target).parent))

    def _on_retry_job(self, job: BatchJob):
        error = self._preflight_error()
        if error is not None:
            InfoBar.error(
                tr("batch.cannot_retry"), error,
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP, parent=self,
            )
            return
        self.controller.retry(
            job, stages_for_mode(self.mode.key, bool(cfg.dubbing_enabled.value))
        )
        self._refresh()

    def _on_remove_job(self, job: BatchJob):
        self.controller.remove(job)
        self._refresh()

    def _show_job_details(self, job: BatchJob):
        """任务详情：完整错误 / 输出文件清单，附打开目录或重试入口。"""
        status_text = {
            JobStatus.WAITING: tr("batch.status.waiting"),
            JobStatus.RUNNING: tr("batch.status.running"),
            JobStatus.COMPLETED: tr("batch.status.completed"),
            JobStatus.FAILED: tr("batch.status.failed"),
        }[job.status]
        lines = [
            tr("batch.detail.file", path=job.path),
            tr("batch.detail.status", status=status_text, progress=job.progress),
        ]
        if job.status == JobStatus.FAILED and job.error:
            lines.append("")
            lines.append(tr("batch.detail.error", error=job.error))
        elif job.outputs:
            lines.append("")
            lines.append(tr("batch.detail.outputs"))
            lines.extend(f"· {path}" for path in job.outputs)
        elif job.note:
            lines.append(tr("batch.detail.progress", note=job.note))
        message = "\n".join(lines)
        if job.status == JobStatus.FAILED:
            dialog = ConfirmDialog(
                tr("batch.detail.title"),
                message,
                self,
                confirm_text=tr("batch.row.retry"),
                cancel_text=tr("common.close"),
                icon=AppIcon.FILE,
                width=560,
            )
            if dialog.exec():
                self._on_retry_job(job)
        elif job.status == JobStatus.COMPLETED:
            dialog = ConfirmDialog(
                tr("batch.detail.title"),
                message,
                self,
                confirm_text=tr("batch.row.open_output"),
                cancel_text=tr("common.close"),
                icon=AppIcon.FILE,
                width=560,
            )
            if dialog.exec():
                self._on_open_job(job)
        else:
            ConfirmDialog(
                tr("batch.detail.title"),
                message,
                self,
                confirm_text=tr("batch.detail.got_it"),
                cancel_text=None,
                icon=AppIcon.FILE,
                width=560,
            ).exec()

    # ------------------------------------------------------------- 列表

    def _rebuild_rows(self):
        for row in self._rows:
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        insert_at = self.rowsLayout.count() - 1  # stretch 之前
        for job in self.controller.jobs:
            row = TaskRow(job, self.rowsHost)
            row.openRequested.connect(self._on_open_job)
            row.retryRequested.connect(self._on_retry_job)
            row.removeRequested.connect(self._on_remove_job)
            row.detailsRequested.connect(self._show_job_details)
            self.rowsLayout.insertWidget(insert_at, row)
            insert_at += 1
            self._rows.append(row)
        self._apply_filter()
        self._refresh()

    def _on_job_changed(self, index: int):
        if 0 <= index < len(self._rows):
            self._rows[index].refresh()
        self._apply_filter()
        self._refresh()

    def _on_filter_changed(self, key: str):
        self._filter = key
        self._apply_filter()

    def _matches_filter(self, job: BatchJob) -> bool:
        return {
            "all": lambda j: True,
            "waiting": lambda j: j.status == JobStatus.WAITING,
            "running": lambda j: j.status == JobStatus.RUNNING,
            "failed": lambda j: j.status == JobStatus.FAILED,
        }[self._filter](job)

    def _apply_filter(self):
        visible = 0
        for row in self._rows:
            show = self._matches_filter(row.job)
            row.setVisible(show)
            visible += int(show)
        self.filterEmptyLabel.setVisible(bool(self._rows) and visible == 0)

    # --------------------------------------------------------- 状态派生

    def _page_state(self) -> PageState:
        if not self.controller.jobs:
            return PageState.EMPTY
        if self.controller.is_active():
            return PageState.RUNNING
        if self._batch_ran and self.controller.count(JobStatus.WAITING) == 0:
            return PageState.DONE
        return PageState.READY

    def _refresh(self):
        state = self._page_state()
        controller = self.controller
        jobs = controller.jobs
        total = len(jobs)
        waiting = controller.count(JobStatus.WAITING)
        running = controller.count(JobStatus.RUNNING)
        failed = controller.count(JobStatus.FAILED)
        completed = controller.count(JobStatus.COMPLETED)
        concurrency = int(cfg.batch_concurrency.value)
        paused = controller.is_paused()

        # 页头副标题 + 主按钮
        if state == PageState.EMPTY:
            self.subtitleLabel.setText(tr("batch.subtitle.empty"))
            self.primaryButton.setText(tr("batch.btn.start"))
            self.primaryButton.setIcon(AppIcon.PLAY)
            self.primaryButton.setEnabled(False)
        elif state == PageState.READY:
            self.subtitleLabel.setText(tr("batch.subtitle.ready", n=total))
            self.primaryButton.setText(tr("batch.btn.start"))
            self.primaryButton.setIcon(AppIcon.PLAY)
            self.primaryButton.setEnabled(waiting > 0 or failed > 0)
        elif state == PageState.RUNNING:
            if paused:
                self.subtitleLabel.setText(tr("batch.subtitle.paused"))
                self.primaryButton.setText(tr("batch.btn.resume"))
                self.primaryButton.setIcon(AppIcon.PLAY)
            else:
                self.subtitleLabel.setText(tr("batch.subtitle.running"))
                self.primaryButton.setText(tr("batch.btn.pause"))
                self.primaryButton.setIcon(AppIcon.CANCEL)
            self.primaryButton.setEnabled(True)
        else:  # DONE
            if failed:
                self.subtitleLabel.setText(tr("batch.subtitle.done_failed", n=failed))
            else:
                self.subtitleLabel.setText(tr("batch.subtitle.done"))
            self.primaryButton.setText(tr("batch.btn.start"))
            self.primaryButton.setIcon(AppIcon.PLAY)
            self.primaryButton.setEnabled(failed > 0)
        self.clearButton.setEnabled(total > 0)

        # 模式卡：运行中锁定
        for card in self.modeCards:
            card.setActive(card.key == self.mode.key)
            card.setEnabled(state != PageState.RUNNING)

        # 队列区
        self.queueStack.setCurrentIndex(0 if state == PageState.EMPTY else 1)
        accepts = (
            tr("batch.drop.media_kinds")
            if self.mode.accepts_media
            else tr("batch.drop.subtitle_kinds")
        )
        self.dropZone.formatLabel.setText(
            tr("batch.drop.format", mode=self.mode.title, kinds=accepts)
        )
        self.dropZone.formatLabel.setVisible(True)
        count_level = {PageState.RUNNING: "warn", PageState.DONE: "ok"}.get(
            state, "neutral"
        )
        self.countPill.setState(tr("batch.count", n=total), count_level)

        # 右栏统计 + 阶段
        if state == PageState.EMPTY:
            pill = (tr("batch.panel.not_started"), "neutral")
            metrics = [
                ("0", tr("batch.metric.queue")),
                (str(concurrency), tr("batch.metric.concurrency")),
                ("0", tr("batch.status.running")),
                ("0", tr("batch.status.failed")),
            ]
        elif state == PageState.READY:
            pill = (tr("batch.panel.ready"), "neutral")
            metrics = [
                (str(total), tr("batch.metric.queue")),
                (str(concurrency), tr("batch.metric.concurrency")),
                (str(waiting), tr("batch.status.waiting")),
                (str(failed), tr("batch.status.failed")),
            ]
        elif state == PageState.RUNNING:
            pill = (
                (tr("batch.panel.paused"), "neutral")
                if paused
                else (tr("batch.panel.running"), "warn")
            )
            metrics = [
                (str(total), tr("batch.metric.queue")),
                (str(running), tr("batch.status.running")),
                (str(waiting), tr("batch.status.waiting")),
                (f"{controller.current_progress()}%", tr("batch.metric.progress")),
            ]
        else:
            pill = (tr("batch.panel.ended"), "ok")
            rate = round(completed * 100 / total) if total else 0
            metrics = [
                (str(total), tr("batch.metric.queue")),
                (str(completed), tr("batch.status.completed")),
                (str(failed), tr("batch.status.failed")),
                (f"{rate}%", tr("batch.metric.success_rate")),
            ]
        self.sidePanel.pill.setState(*pill)
        self.sidePanel.setMetrics(metrics)
        self.sidePanel.setStageStates(self._stage_states(state))

    def _stage_states(self, state: PageState) -> dict[str, str]:
        keys = [row.stage_key for row in self.sidePanel.stageRows]
        if state == PageState.DONE:
            # 有失败任务时不把流水线全标“完成”，避免误导
            if self.controller.count(JobStatus.FAILED):
                return {}
            return {key: "done" for key in keys}
        if state != PageState.RUNNING:
            return {}
        active = self.controller.active_stages()
        if not active:
            return {}
        indexes = [keys.index(key) for key in active if key in keys]
        if not indexes:
            return {}
        first_active = min(indexes)
        states: dict[str, str] = {}
        for index, key in enumerate(keys):
            if key in active:
                states[key] = "active"
            elif index < first_active:
                states[key] = "done"
        return states

    # ------------------------------------------------------------ 拖放

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.dropZone.setDragActive(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.dropZone.setDragActive(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.dropZone.setDragActive(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
        if paths:
            self.add_paths(paths)

    # ------------------------------------------------------------ 生命周期

    def showEvent(self, event):
        # 配音开关可能在设置/配音页变化，回到本页时刷新阶段卡
        self._rebuild_stage_rows()
        self._refresh()
        super().showEvent(event)

    def closeEvent(self, event):
        self.controller.shutdown()
        super().closeEvent(event)
