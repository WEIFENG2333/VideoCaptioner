"""硬字幕提取页：OCR 提取烧录字幕为可编辑字幕。

拖入视频 → 自动识别区域(可拖框微调) → 提取(实时入表) → 改字/删行 → 导出或送入字幕优化。
页面只做 UI 与状态机；耗时走 ui.thread.hardsub_thread，core 回调经 Qt 信号回 GUI 线程。
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Action, RoundMenu

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.hardsub.config import LANGUAGES, HardsubConfig, RecognizeMode
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import ConfirmDialog
from videocaptioner.ui.components.roi_selector import RoiSelector
from videocaptioner.ui.components.workbench import (
    CompactButton,
    DropZone,
    ElidedLabel,
    ErrorCard,
    IconBox,
    PillSelect,
    ProgressBarLine,
    StatusPill,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    icon_pixmap,
    to_qcolor,
)
from videocaptioner.ui.i18n import N_, tr

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v", ".ts"}


class _State(Enum):
    EMPTY = auto()        # 等待视频
    REGION = auto()       # 已载入，确认/调整字幕区域
    PROCESSING = auto()   # 提取中
    DONE = auto()         # 完成
    NO_SUBTITLE = auto()  # 未识别到字幕
    ENGINE_MISSING = auto()  # OCR 依赖未就绪


def _fmt_ts(ms: int) -> str:
    """毫秒 → MM:SS.cc（厘秒，表格显示用，简洁可读，对字幕足够）。"""
    s, msec = divmod(max(0, int(ms)), 1000)
    return f"{s // 60:02d}:{s % 60:02d}.{msec // 10:02d}"


def _parse_ts(text: str) -> Optional[int]:
    """宽松解析 MM:SS.cc / SS.cc / 秒 → 毫秒；失败返回 None。"""
    text = text.strip()
    if not text:
        return None
    try:
        if ":" in text:
            mm, rest = text.split(":", 1)
            return int(round((int(mm) * 60 + float(rest)) * 1000))
        return int(round(float(text) * 1000))
    except ValueError:
        return None


class HardsubInterface(QWidget):
    """硬字幕提取页（单文件工作台）。"""

    # 送入字幕优化页（main_window 路由）：传提取出的字幕文件路径 + 源视频路径
    sendToOptimize = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HardsubInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self._state = _State.EMPTY
        self._video_path: Optional[str] = None
        self._duration = 0.0
        self._lang = "ch"
        self._engine = None
        self._prepare_thread = None
        self._region_thread = None
        self._extract_thread = None
        # 框是否由用户手动框选/调整（而非自动检测回填）→ 提取所见即所得，见 HardsubConfig.roi_is_manual。
        self._roi_manual = False
        # 自动检测顺带学到的主导字号，供提取复用。
        self._region_font_height: Optional[float] = None
        # 载入代次：每次载入新视频 +1，线程创建时打上代次，迟到的回调按 _stale 作废（防旧视频检测覆盖新的）。
        self._load_gen = 0

        self._build_ui()
        self._apply_state(_State.EMPTY)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        palette = app_palette()
        self.setStyleSheet(f"QWidget#HardsubInterface {{ background: {palette.bg}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(18)

        root.addLayout(self._build_page_head())

        work = QHBoxLayout()
        work.setSpacing(18)
        work.addWidget(self._build_stage_panel(), 5)
        work.addWidget(self._build_result_panel(), 3)
        root.addLayout(work, 1)

    def _build_page_head(self) -> QHBoxLayout:
        palette = app_palette()
        head = QHBoxLayout()
        head.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.titleLabel = QLabel(tr("hardsub.title"), self)
        apply_font(self.titleLabel, 26, 950)
        self.titleLabel.setStyleSheet(f"color: {palette.text}; background: transparent;")
        self.subtitleLabel = QLabel(
            tr("hardsub.subtitle"), self
        )
        apply_font(self.subtitleLabel, 13, 760)
        self.subtitleLabel.setStyleSheet(f"color: {palette.muted}; background: transparent;")
        titles.addWidget(self.titleLabel)
        titles.addWidget(self.subtitleLabel)
        head.addLayout(titles)
        head.addStretch(1)

        self.replaceBtn = WorkbenchButton(tr("hardsub.btn.replace_video"), AppIcon.VIDEO, parent=self)
        self.replaceBtn.clicked.connect(self._on_pick_file)
        self.autoRegionBtn = WorkbenchButton(tr("hardsub.btn.auto_region"), AppIcon.SYNC, parent=self)
        self.autoRegionBtn.clicked.connect(self._on_auto_region)
        head.addWidget(self.replaceBtn)
        head.addWidget(self.autoRegionBtn)
        return head

    def _build_stage_panel(self) -> QWidget:
        palette = app_palette()
        panel = WorkbenchPanel(self, padded=False)
        self._stagePanel = panel
        layout = panel.bodyLayout

        # 头：视频文件行 + 状态胶囊（页面大标题已是「硬字幕提取」，这里不再重复，
        # 改为显示当前视频名——空态显示「视频预览」）。
        header = QFrame(panel)
        header.setObjectName("stageHead")
        header.setFixedHeight(56)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 0, 22, 0)
        hl.setSpacing(9)
        self.stageFileIcon = QLabel(header)
        self.stageFileIcon.setObjectName("stageFileIcon")
        self.stageFileIcon.hide()
        hl.addWidget(self.stageFileIcon)
        self.stageFile = ElidedLabel(tr("hardsub.stage.video_preview"), header)
        self.stageFile.setObjectName("stageFileName")
        apply_font(self.stageFile, 16, 860)
        hl.addWidget(self.stageFile, 1)
        hl.addSpacing(8)
        self.stagePill = StatusPill(tr("hardsub.status.waiting_video"), "neutral", header)
        hl.addWidget(self.stagePill)
        # object-name 作用域：避免 border-bottom 级联到子标签（否则每个标签后面都出现矩形线框）。
        header.setStyleSheet(
            f"""
            QFrame#stageHead {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QLabel#stageFileName, QLabel#stageFileIcon {{
                color: {palette.text}; background: transparent; border: none;
            }}
            """
        )
        layout.addWidget(header)

        # 主体：空态拖放 / 预览框选
        self.stageStack = QStackedWidget(panel)
        layout.addWidget(self.stageStack, 1)

        drop_host = QWidget(panel)
        dh = QVBoxLayout(drop_host)
        dh.setContentsMargins(22, 22, 22, 22)
        self.dropZone = DropZone(
            icon=AppIcon.VIDEO,
            title=tr("hardsub.drop.title"),
            pick_text=tr("hardsub.drop.pick"),
            pick_icon=AppIcon.FOLDER_ADD,
            formats_line="mp4 / mov / mkv",
            parent=drop_host,
        )
        self.dropZone.browseRequested.connect(self._on_pick_file)
        dh.addWidget(self.dropZone)
        self.stageStack.addWidget(drop_host)  # index 0

        preview_host = QWidget(panel)
        ph = QVBoxLayout(preview_host)
        ph.setContentsMargins(20, 18, 20, 18)
        ph.setSpacing(12)
        self.roiSelector = RoiSelector(preview_host)
        self.roiSelector.roi_changed.connect(self._on_roi_changed)
        ph.addWidget(self.roiSelector, 1)
        # 进度行：固定高度、始终占位（只在提取时显示内容）——否则它显隐会把上方视频挤大挤小、形成跳变。
        self.progressRow = QWidget(preview_host)
        self.progressRow.setFixedHeight(24)
        pr = QHBoxLayout(self.progressRow)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(14)
        self.progressTitle = QLabel(tr("hardsub.progress.title"), self.progressRow)
        apply_font(self.progressTitle, 14, 900)
        self.progressTitle.setStyleSheet(f"color: {palette.text}; background: transparent;")
        self.progressBar = ProgressBarLine(self.progressRow)
        self.progressPercent = QLabel("0%", self.progressRow)
        apply_font(self.progressPercent, 15, 900)
        self.progressPercent.setStyleSheet(f"color: {palette.accent_text}; background: transparent;")
        self.progressPercent.setFixedWidth(56)
        self.progressPercent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        pr.addWidget(self.progressTitle)
        pr.addWidget(self.progressBar, 1)
        pr.addWidget(self.progressPercent)
        ph.addWidget(self.progressRow)
        self.stageStack.addWidget(preview_host)  # index 1
        return panel

    def _build_result_panel(self) -> QWidget:
        palette = app_palette()
        panel = WorkbenchPanel(self, padded=False)
        panel.setMinimumWidth(300)
        layout = panel.bodyLayout

        # 头：字幕结果 + 语言下拉 / 计数
        header = QFrame(panel)
        header.setObjectName("resultHead")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 0, 18, 0)
        header.setFixedHeight(56)
        title = QLabel(tr("hardsub.result.title"), header)
        title.setObjectName("resultHeadTitle")
        apply_font(title, 16, 900)
        hl.addWidget(title)
        hl.addStretch(1)
        self.langSelect = PillSelect(header)
        self.langSelect.setItems([name for _, name in LANGUAGES], LANGUAGES[0][1])
        self.langSelect.currentTextChanged.connect(self._on_lang_changed)
        self.countPill = StatusPill("", "neutral", header)
        self.countPill.hide()
        hl.addWidget(self.langSelect)
        hl.addWidget(self.countPill)
        header.setStyleSheet(
            f"""
            QFrame#resultHead {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QLabel#resultHeadTitle {{ color: {palette.text}; background: transparent; border: none; }}
            """
        )
        layout.addWidget(header)

        # 主体：占位（空/区域/错误）或 结果表
        self.resultStack = QStackedWidget(panel)
        layout.addWidget(self.resultStack, 1)

        self.placeholder = _Placeholder(panel)
        self.resultStack.addWidget(self.placeholder)   # index 0

        self.table = _ResultTable(panel)
        self.table.locateRequested.connect(self._on_locate)
        self.resultStack.addWidget(self.table)          # index 1

        # 底部：提示 + 动作
        footer = QFrame(panel)
        footer.setObjectName("resultFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 12, 18, 14)
        fl.setSpacing(10)
        self.footerNote = QLabel("", footer)
        self.footerNote.setObjectName("resultFooterNote")
        apply_font(self.footerNote, 12, 760)
        self.footerNote.setWordWrap(True)
        fl.addWidget(self.footerNote, 1)

        # 完成后可回流：重新提取（回到框选态，可调区域/语言后再来一遍）。
        self.redoBtn = CompactButton(tr("hardsub.btn.redo"), AppIcon.SYNC, parent=footer)
        self.redoBtn.clicked.connect(self._on_redo)
        self.exportBtn = CompactButton(tr("hardsub.btn.export"), AppIcon.DOWNLOAD, parent=footer)
        self.exportBtn.clicked.connect(self._on_export)
        self.cancelBtn = CompactButton(tr("common.cancel"), AppIcon.CANCEL, parent=footer)
        self.cancelBtn.clicked.connect(self._on_cancel)
        self.startBtn = WorkbenchButton(tr("hardsub.btn.start"), AppIcon.PLAY, primary=True, parent=footer)
        self.startBtn.clicked.connect(self._on_start)
        self.sendBtn = WorkbenchButton(
            tr("hardsub.btn.send_optimize"), AppIcon.RIGHT_ARROW, primary=True, parent=footer
        )
        self.sendBtn.clicked.connect(self._on_send_optimize)
        for btn in (self.redoBtn, self.exportBtn, self.cancelBtn, self.startBtn, self.sendBtn):
            fl.addWidget(btn)
        footer.setStyleSheet(
            f"""
            QFrame#resultFooter {{
                background: transparent;
                border: none;
                border-top: 1px solid {palette.line_soft};
            }}
            QLabel#resultFooterNote {{ color: {palette.subtle}; background: transparent; border: none; }}
            """
        )
        layout.addWidget(footer)
        return panel

    # ------------------------------------------------------------- 状态机

    def _apply_state(self, state: _State) -> None:
        self._state = state
        is_empty = state == _State.EMPTY
        has_video = state not in (_State.EMPTY, _State.ENGINE_MISSING)

        self.replaceBtn.setVisible(not is_empty)
        self.autoRegionBtn.setVisible(state in (_State.REGION, _State.DONE, _State.NO_SUBTITLE))
        # 头部文件行：有视频显示文件名 + 图标，否则回到「视频预览」占位。
        self.stageFileIcon.setVisible(has_video)
        if not has_video:
            self.stageFile.setText(tr("hardsub.stage.video_preview"))

        # 左栏：空态/引擎缺失 → 拖放区；其余 → 预览
        if state in (_State.EMPTY, _State.ENGINE_MISSING):
            self.stageStack.setCurrentIndex(0)
        else:
            self.stageStack.setCurrentIndex(1)
        # 进度行始终占位（固定高度），只切换内容显隐——避免视频区被挤大挤小的跳变。
        processing = state == _State.PROCESSING
        for w in (self.progressTitle, self.progressBar, self.progressPercent):
            w.setVisible(processing)

        # 状态胶囊
        pill_spec = {
            _State.EMPTY: (tr("hardsub.status.waiting_video"), "neutral"),
            _State.ENGINE_MISSING: (tr("hardsub.status.engine_missing"), "fail"),
            _State.REGION: (tr("hardsub.status.region_detected"), "ok"),
            _State.PROCESSING: (tr("hardsub.status.processing"), "warn"),
            _State.DONE: (tr("hardsub.status.done"), "ok"),
            _State.NO_SUBTITLE: (tr("hardsub.status.need_action"), "fail"),
        }[state]
        self.stagePill.setState(*pill_spec)

        # 右栏主体
        if state in (_State.PROCESSING, _State.DONE):
            self.resultStack.setCurrentIndex(1)
        else:
            self.resultStack.setCurrentIndex(0)
            self.placeholder.set_for_state(state)

        # 语言下拉只在「待提取」阶段可改
        self.langSelect.setVisible(state in (_State.REGION, _State.NO_SUBTITLE))
        self.langSelect.setEnabled(state in (_State.REGION, _State.NO_SUBTITLE))

        # 计数胶囊
        if state == _State.PROCESSING:
            self.countPill.show()
            self.countPill.setState(tr("hardsub.count.recognized", n=0), "warn")
        elif state == _State.DONE:
            self.countPill.show()
            self.countPill.setState(tr("hardsub.count.total", n=self.table.rowCount()), "ok")
        else:
            self.countPill.hide()

        # 底部按钮
        self.redoBtn.setVisible(state == _State.DONE)
        self.exportBtn.setVisible(state == _State.DONE)
        self.cancelBtn.setVisible(state == _State.PROCESSING)
        self.sendBtn.setVisible(state == _State.DONE)
        self.startBtn.setVisible(state in (_State.REGION, _State.NO_SUBTITLE))
        notes = {
            _State.EMPTY: tr("hardsub.note.empty"),
            _State.ENGINE_MISSING: tr("hardsub.note.engine_missing"),
            _State.REGION: tr("hardsub.note.region"),
            _State.PROCESSING: tr("hardsub.note.processing"),
            _State.DONE: tr("hardsub.note.done"),
            _State.NO_SUBTITLE: tr("hardsub.note.no_subtitle"),
        }
        self.footerNote.setText(notes[state])
        # 完成态底部三个按钮占满，提示文案会被挤成窄列；此时让按钮独占，提示交给表头/右键。
        self.footerNote.setVisible(state != _State.DONE)

    # --------------------------------------------------------------- 交互

    def _on_pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("hardsub.dialog.pick_video"), "",
            "Video (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v *.ts);;All files (*)",
        )
        if path:
            self._load_video(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.dropZone.setDragActive(True)

    def dragLeaveEvent(self, event):
        self.dropZone.setDragActive(False)

    def dropEvent(self, event):
        self.dropZone.setDragActive(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in _VIDEO_EXTS:
                self._load_video(path)
                break

    def _load_video(self, path: str) -> None:
        from videocaptioner.ui.thread.hardsub_thread import PrepareThread, ocr_ready

        missing = ocr_ready()
        if missing is not None:
            self._show_engine_missing(missing)
            return

        # 探测/抽首帧是 ffmpeg 子进程、会卡 GUI——放后台线程，期间显示「载入中」遮罩。
        self._video_path = path
        self._engine = None
        self._roi_manual = False  # 新视频：等自动检测回填或用户重新框
        self._region_font_height = None
        self._load_gen += 1       # 作废上个视频仍在跑的探测/区域检测的迟到回调
        self.table.clear_rows()
        self.stageFile.setText(Path(path).name)
        self.stageFileIcon.setPixmap(icon_pixmap(AppIcon.VIDEO, app_palette().muted, 18))
        self._apply_state(_State.REGION)
        self.roiSelector.set_busy(tr("hardsub.busy.loading_video"))
        thread = PrepareThread(path)
        thread._gen = self._load_gen
        thread.ready.connect(self._on_prepared)
        thread.error.connect(self._on_prepare_error)
        self._prepare_thread = thread
        thread.start()

    def _on_prepared(self, width: int, height: int, duration: float, first_frame) -> None:
        from videocaptioner.core.hardsub.frames import grab_frame
        if self._stale() or not self._video_path:
            return
        self._duration = duration
        path = self._video_path
        self.roiSelector.set_video(
            lambda t: grab_frame(path, t, max_width=1280),
            QSize(width, height), duration, Path(path).name, first_frame=first_frame,
        )
        self._start_region_detect()

    def _on_prepare_error(self, msg: str) -> None:
        self.roiSelector.set_busy(None)
        self._toast(tr("hardsub.error.read_video", msg=msg))
        self._apply_state(_State.EMPTY)

    def _ensure_engine(self):
        from videocaptioner.ui.thread.hardsub_thread import make_engine
        cfg = HardsubConfig.from_mode(self._video_path or "", lang=self._lang)
        if self._engine is None:
            self._engine = make_engine(cfg)
        return self._engine

    def _start_region_detect(self) -> None:
        from videocaptioner.ui.thread.hardsub_thread import RegionDetectThread
        if not self._video_path:
            return
        self.autoRegionBtn.setEnabled(False)
        self.roiSelector.set_busy(tr("hardsub.busy.detecting_region"))
        thread = RegionDetectThread(self._video_path, self._ensure_engine())
        thread._gen = self._load_gen
        thread.detected.connect(self._on_region_detected)
        thread.progress.connect(self._on_region_progress)
        thread.error.connect(self._on_region_error)
        thread.finished.connect(self._on_region_finished)
        self._region_thread = thread
        thread.start()

    def _on_region_progress(self, percent: int, _text: str) -> None:
        if self._stale():
            return
        self.roiSelector.set_busy(tr("hardsub.busy.detecting_region_pct", percent=percent))

    def _on_region_detected(self, result) -> None:
        if self._stale():
            return
        self.roiSelector.set_busy(None)
        if result is not None:
            self.roiSelector.set_roi_src(result.roi)
            self._roi_manual = False  # 自动检测回填的框：提取按自动模式过滤杂质
            self._region_font_height = result.font_height  # 复用主导字号，提取不再重复学
        else:
            # 没检测到稳定字幕带：提示手动框选（不强行用默认带产出杂质）。
            self._toast(tr("hardsub.toast.no_auto_region"))

    def _on_region_error(self, _msg: str) -> None:
        self.roiSelector.set_busy(None)
        self.autoRegionBtn.setEnabled(True)

    def _on_region_finished(self) -> None:
        self.roiSelector.set_busy(None)
        self.autoRegionBtn.setEnabled(True)

    def _on_auto_region(self) -> None:
        self._start_region_detect()

    def _stale(self) -> bool:
        """迟到回调判废：发信线程创建时的载入代次已被新载入超越（切到别的视频了）。"""
        return getattr(self.sender(), "_gen", self._load_gen) != self._load_gen

    def _on_roi_changed(self, _roi) -> None:
        # 仅用户鼠标编辑才发此信号（自动回填走 set_roi_src 不发）→ 标记手动指定。
        self._roi_manual = True

    def _on_lang_changed(self, name: str) -> None:
        for code, label in LANGUAGES:
            if label == name:
                if code != self._lang:
                    self._lang = code
                    self._engine = None  # 换语言要换识别模型
                break

    def _on_start(self) -> None:
        from videocaptioner.core.hardsub.pipeline import EXTRACT_DET_LIMIT
        from videocaptioner.ui.thread.hardsub_thread import HardsubExtractThread, make_engine
        if not self._video_path:
            return
        roi = self.roiSelector.roi_src()
        cfg = HardsubConfig.from_mode(
            self._video_path, mode=RecognizeMode.STANDARD, lang=self._lang,
            roi=roi, roi_is_manual=self._roi_manual,
            font_height=None if self._roi_manual else self._region_font_height,
        )
        self.table.clear_rows()
        self._apply_state(_State.PROCESSING)
        # 提取用 768 引擎；区域检测仍用 _ensure_engine 的 960。
        thread = HardsubExtractThread(cfg, make_engine(cfg, det_limit_side_len=EXTRACT_DET_LIMIT))
        thread.cue_ready.connect(self._on_cue)
        thread.progress.connect(self._on_progress)
        thread.error.connect(self._on_error)
        thread.finished.connect(self._on_finished)
        self._extract_thread = thread
        thread.start()

    def _on_cancel(self) -> None:
        if self._extract_thread is not None:
            self._extract_thread.request_cancel()

    def _on_redo(self) -> None:
        """完成后重新提取：回到框选态（保留视频与已识别区域，可调区域/语言后再来一遍）。"""
        if not self._video_path:
            return
        self.table.clear_rows()
        self._apply_state(_State.REGION)

    def _on_locate(self, seconds: float) -> None:
        """结果表点行「定位到此画面」：左栏预览跳到该时刻，让用户核对该条字幕真实画面（剔杂质用）。"""
        if not self._video_path:
            return
        self.stageStack.setCurrentIndex(1)  # 确保显示视频预览
        self.roiSelector.seek_to(seconds)

    def _on_cue(self, cue) -> None:
        self.table.append_cue(cue.start, cue.end, cue.text)
        self.countPill.setState(tr("hardsub.count.recognized", n=self.table.rowCount()), "warn")

    def _on_progress(self, percent: int, _text: str) -> None:
        self.progressBar.setValue(percent)
        self.progressPercent.setText(f"{percent}%")

    def _on_error(self, msg: str) -> None:
        self._toast(msg)
        self._apply_state(_State.REGION)

    def _on_finished(self, data) -> None:
        if self.table.rowCount() == 0:
            self._apply_state(_State.NO_SUBTITLE)
            return
        self._apply_state(_State.DONE)

    def _on_export(self) -> None:
        data = self.table.to_asrdata()
        if not data.has_data():
            return
        default = ""
        if self._video_path:
            from videocaptioner.core.application import output_paths
            default = str(output_paths.product_path(
                Path(self._video_path), output_paths.TAG_HARDSUB, ext=".srt"))
        path, _ = QFileDialog.getSaveFileName(
            self, tr("hardsub.dialog.export"), default,
            "SRT (*.srt);;ASS (*.ass);;Plain text (*.txt)",
        )
        if path:
            data.save(path)
            self._toast(tr("hardsub.toast.exported", name=Path(path).name))

    def _on_send_optimize(self) -> None:
        data = self.table.to_asrdata()
        if not data.has_data() or not self._video_path:
            return
        from videocaptioner.core.application import output_paths
        out = output_paths.product_path(
            Path(self._video_path), output_paths.TAG_HARDSUB, ext=".srt")
        data.save(str(out))
        self.sendToOptimize.emit(str(out), self._video_path)

    # --------------------------------------------------------------- 杂项

    def _show_engine_missing(self, reason: str) -> None:
        self._apply_state(_State.ENGINE_MISSING)
        self.placeholder.set_error(
            tr("hardsub.engine.title"),
            tr("hardsub.engine.desc"),
        )
        self.dropZone.setVisible(False)
        card = ErrorCard(reason, title=tr("hardsub.engine.card_title"), parent=self._stagePanel)
        card.setMaximumWidth(520)  # 紧凑居中的错误卡；直接 addWidget 会撑满舞台、内部文字被拉散
        host = self.stageStack.widget(0)
        lay = host.layout()
        if lay is not None and lay.count() and not getattr(self, "_engine_card_shown", False):
            self.dropZone.hide()
            lay.addWidget(card, 0, Qt.AlignCenter)  # type: ignore[call-arg]
            self._engine_card_shown = True

    def _toast(self, text: str) -> None:
        ConfirmDialog(tr("common.tip"), text, parent=self, cancel_text=None).exec()

    def closeEvent(self, event):
        for thread in (self._prepare_thread, self._region_thread, self._extract_thread):
            if thread is not None and thread.isRunning():
                thread.stop()
        super().closeEvent(event)


class _Placeholder(QWidget):
    """右栏空/区域/错误占位：图标 + 标题 + 说明。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addStretch(1)
        self.iconBox = IconBox(AppIcon.SUBTITLE, self, size=58)
        layout.addWidget(self.iconBox, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        layout.addSpacing(12)
        self.titleLabel = QLabel("", self)
        apply_font(self.titleLabel, 20, 900)
        self.titleLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        layout.addWidget(self.titleLabel)
        layout.addSpacing(6)
        self.subLabel = QLabel("", self)
        apply_font(self.subLabel, 13, 760)
        self.subLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self.subLabel.setWordWrap(True)
        layout.addWidget(self.subLabel)
        layout.addStretch(1)
        self._sync()

    def _sync(self) -> None:
        palette = app_palette()
        self.titleLabel.setStyleSheet(f"color: {palette.text}; background: transparent;")
        self.subLabel.setStyleSheet(f"color: {palette.muted}; background: transparent;")

    def set_for_state(self, state) -> None:
        from videocaptioner.ui.view.hardsub_interface import _State
        specs = {
            _State.EMPTY: (AppIcon.SUBTITLE, tr("hardsub.ph.empty.title"), tr("hardsub.ph.empty.sub")),
            _State.REGION: (AppIcon.LAYOUT, tr("hardsub.ph.region.title"), tr("hardsub.ph.region.sub")),
            _State.NO_SUBTITLE: (AppIcon.SUBTITLE, tr("hardsub.ph.no_subtitle.title"), tr("hardsub.ph.no_subtitle.sub")),
            _State.ENGINE_MISSING: (AppIcon.SUBTITLE, tr("hardsub.ph.engine_missing.title"), tr("hardsub.ph.engine_missing.sub")),
        }
        icon, title, sub = specs.get(state, specs[_State.EMPTY])
        self.iconBox.setIcon(icon)
        self.titleLabel.setText(title)
        self.subLabel.setText(sub)
        self._sync()

    def set_error(self, title: str, sub: str) -> None:
        self.iconBox.setIcon(AppIcon.SUBTITLE)
        self.titleLabel.setText(title)
        self.subLabel.setText(sub)
        self._sync()


class _ResultModel(QAbstractTableModel):
    """字幕结果表模型：开始 / 结束 / 文本，三列均可双击编辑。

    内部存原始毫秒 + 文本；时间列显示为 MM:SS.cc，编辑时宽松解析回毫秒
    （解析失败则拒绝该次编辑，保留原值）。
    """

    HEADERS = (N_("hardsub.col.start"), N_("hardsub.col.end"), N_("hardsub.col.text"))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[list] = []  # [start_ms, end_ms, text]

    def append(self, start_s: float, end_s: float, text: str) -> None:
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append([int(start_s * 1000), int(end_s * 1000), text])
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def remove_row(self, row: int) -> None:
        if not 0 <= row < len(self._rows):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        self._rows.pop(row)
        self.endRemoveRows()

    def start_seconds(self, row: int) -> Optional[float]:
        if 0 <= row < len(self._rows):
            return self._rows[row][0] / 1000.0
        return None

    def to_asrdata(self) -> ASRData:
        segs = [
            ASRDataSeg(text.strip(), start, end)
            for start, end, text in self._rows
            if text.strip()
        ]
        return ASRData(segs)

    # ----- Qt 模型接口 -----

    def rowCount(self, parent: Optional[QModelIndex] = None) -> int:
        return len(self._rows)

    def columnCount(self, parent: Optional[QModelIndex] = None) -> int:
        return 3

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[assignment]
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):  # type: ignore[attr-defined]
            if col == 2:
                return self._rows[row][2]
            return _fmt_ts(self._rows[row][col])
        if role == Qt.TextAlignmentRole and col < 2:  # type: ignore[attr-defined]
            return int(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore[arg-type]
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # type: ignore[assignment]
        if not index.isValid() or role != Qt.EditRole:  # type: ignore[attr-defined]
            return False
        row, col = index.row(), index.column()
        if col == 2:
            self._rows[row][2] = str(value)
        else:
            ms = _parse_ts(str(value))
            if ms is None:
                return False
            self._rows[row][col] = ms
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):  # type: ignore[assignment]
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:  # type: ignore[attr-defined]
            return tr(self.HEADERS[section])
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags  # type: ignore[attr-defined]
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable  # type: ignore[attr-defined]


class _ResultEditDelegate(QStyledItemDelegate):
    """单元格编辑委托：悬浮行淡色高亮 + 深色行内编辑器（accent 边框、光标落末尾不全选）。"""

    def __init__(self, view: "_ResultTable") -> None:
        super().__init__(view)
        self._view = view

    def paint(self, painter, option, index):
        if (
            index.row() == self._view.hover_row()
            and not option.state & QStyle.State_Selected  # type: ignore[attr-defined]
        ):
            painter.fillRect(option.rect, to_qcolor(app_palette().card_surface_hover))
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        palette = app_palette()
        editor = QLineEdit(parent)
        apply_font(editor, 14, 650)
        editor.setStyleSheet(
            f"""
            QLineEdit {{
                background: {palette.panel_deep};
                color: {palette.text};
                border: 1px solid {rgba(palette.accent, 0.85)};
                border-radius: 6px;
                padding: 0 8px;
                selection-background-color: {rgba(palette.accent, 0.35)};
                selection-color: {palette.text};
            }}
            """
        )
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.EditRole) or "")  # type: ignore[attr-defined]
        editor.deselect()
        editor.end(False)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(4, 6, -4, -6))


class _ResultTable(QTableView):
    """字幕结果表（QTableView + 模型）：开始 / 结束 / 文本。

    双击编辑、右键「定位到此画面 / 删除」（项目 RoundMenu，非原生菜单）、Delete 删除选中行。
    样式与字幕优化页表格一致：透明底、主题色选中、行/列分隔线。
    """

    locateRequested = pyqtSignal(float)  # 请求在视频里定位到该条字幕的起始秒

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = _ResultModel(self)
        self.setModel(self._model)
        self.setObjectName("hardsubResultTable")
        self._hover_row = -1
        self.setMouseTracking(True)
        self.setItemDelegate(_ResultEditDelegate(self))

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(0, 112)
        self.setColumnWidth(1, 112)
        header.setFixedHeight(42)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore[arg-type]
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(46)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)  # type: ignore[arg-type]
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._apply_style()

    # ----- 页面用的薄 API（保持调用点不变）-----

    def append_cue(self, start: float, end: float, text: str) -> None:
        at_bottom = self.verticalScrollBar().value() >= self.verticalScrollBar().maximum() - 4
        self._model.append(start, end, text)
        if at_bottom:
            self.scrollToBottom()

    def clear_rows(self) -> None:
        self._model.clear()

    def rowCount(self) -> int:
        return self._model.rowCount()

    def to_asrdata(self) -> ASRData:
        return self._model.to_asrdata()

    def hover_row(self) -> int:
        return self._hover_row

    # ----- 交互 -----

    def _on_context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        menu = RoundMenu(parent=self)
        locate = Action(tr("hardsub.menu.locate"))
        locate.triggered.connect(lambda: self._emit_locate(row))
        menu.addAction(locate)
        remove = Action(tr("hardsub.menu.delete_row"))
        remove.triggered.connect(lambda: self._model.remove_row(row))
        menu.addAction(remove)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _emit_locate(self, row: int) -> None:
        start = self._model.start_seconds(row)
        if start is not None:
            self.locateRequested.emit(start)

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key_Delete, Qt.Key_Backspace)  # type: ignore[attr-defined]
            and self.state() != QAbstractItemView.EditingState
            and self.currentIndex().isValid()
        ):
            self._model.remove_row(self.currentIndex().row())
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        row = self.rowAt(event.pos().y())
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()
        super().leaveEvent(event)

    def _apply_style(self) -> None:
        palette = app_palette()
        selection_bg = rgba(palette.accent, 0.10)
        self.setStyleSheet(
            f"""
            QTableView#hardsubResultTable {{
                background: transparent;
                border: none;
                color: {palette.muted};
                font-size: 14px;
                selection-background-color: {selection_bg};
                selection-color: {palette.text};
                outline: none;
            }}
            QTableView#hardsubResultTable::item {{
                padding: 0 14px;
                border-bottom: 1px solid {palette.line_soft};
                border-right: 1px solid {palette.line_soft};
            }}
            QTableView#hardsubResultTable::item:selected {{
                background: {selection_bg};
                color: {palette.text};
            }}
            """
        )
        self.horizontalHeader().setStyleSheet(
            f"""
            QHeaderView {{ background: {palette.panel_deep}; border: none; }}
            QHeaderView::section {{
                background: {palette.panel_deep};
                color: {palette.muted};
                border: none;
                border-bottom: 1px solid {palette.line_soft};
                border-right: 1px solid {palette.line_soft};
                padding-left: 14px;
                font-size: 14px;
                font-weight: bold;
            }}
            """
        )
        self.verticalScrollBar().setStyleSheet(
            f"""
            QScrollBar:vertical {{
                background: transparent; width: 5px; margin: 0; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {palette.line}; border-radius: 2px; min-height: 32px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; width: 0; background: transparent; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            """
        )
