# -*- coding: utf-8 -*-
"""任务创建页（首页入口）。

布局与状态：
hero 标识 + 输入卡（链接/文件 + 主按钮 + 轻状态行）+ 详情区
（文件就绪面板 / 下载进度盒 / 错误卡）+ 流程线 + 底部品牌行。

输入形态由内容实时派生（_input_kind）：

    EMPTY    什么都没填          ->  选择文件
    FILE     本地受支持音视频     ->  开始处理（直接进转录）
    URL      http(s) 链接        ->  开始处理（先下载，完成自动流转）
    INVALID  无法识别            ->  错误卡 + 选择文件

下载是页面唯一的长任务，由 DownloadController 持有
MediaDownloadThread（协作取消）；对外契约保持 finished(str, object)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBar, InfoBarPosition

from videocaptioner.config import ASSETS_PATH, VERSION
from videocaptioner.core.constant import INFOBAR_DURATION_SUCCESS
from videocaptioner.core.entities import (
    SupportedAudioFormats,
    SupportedVideoFormats,
    VideoInfo,
)
from videocaptioner.ui.common.app_icons import AppIcon, render_svg_icon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import app_palette, is_dark_theme, rgba
from videocaptioner.ui.components.donate_dialog import DonateDialog
from videocaptioner.ui.components.feedback_dialog import FeedbackDialog
from videocaptioner.ui.components.workbench import (
    CompactButton,
    ElidedLabel,
    ErrorCard,
    InfoChip,
    PillSelect,
    PrimaryIconButton,
    ProgressBarLine,
    StatusPill,
    WorkbenchButton,
    apply_font,
    draw_rounded_surface,
    file_type_icon,
    icon_pixmap,
)
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.media_download_thread import MediaDownloadThread
from videocaptioner.ui.thread.video_info_thread import VideoInfoThread
from videocaptioner.ui.view.log_window import LogWindow

HERO_MARK_PATH = ASSETS_PATH / "hero-logo-mark.svg"

_MEDIA_EXTENSIONS = {f".{fmt.value}" for fmt in SupportedVideoFormats} | {
    f".{fmt.value}" for fmt in SupportedAudioFormats
}

class InputKind:
    EMPTY = "empty"
    FILE = "file"
    URL = "url"
    INVALID = "invalid"


def classify_input(text: str) -> str:
    """输入内容 -> 形态。本地文件要求扩展名受支持。"""
    text = text.strip()
    if not text:
        return InputKind.EMPTY
    if os.path.isfile(text):
        return (
            InputKind.FILE
            if Path(text).suffix.lower() in _MEDIA_EXTENSIONS
            else InputKind.INVALID
        )
    try:
        result = urlparse(text)
    except ValueError:
        return InputKind.INVALID
    if result.scheme in ("http", "https") and result.netloc:
        return InputKind.URL
    return InputKind.INVALID


class PageState:
    INPUT = "input"
    PROBING = "probing"  # 解析链接信息中（未下载）
    CONFIRM = "confirm"  # 解析完成，等用户确认清晰度后开始下载
    DOWNLOADING = "downloading"


# ---------------------------------------------------------------------------
# 线程编排
# ---------------------------------------------------------------------------


class DownloadController(QObject):
    """持有下载线程；进度/速度透传，支持协作取消。"""

    progressChanged = pyqtSignal(int, str)
    statsChanged = pyqtSignal(str, str)
    mediaChanged = pyqtSignal(dict)  # 解析出的视频元数据
    probed = pyqtSignal(dict)  # 解析完成（含清晰度档位），等待确认
    completed = pyqtSignal(str, object)  # (视频路径, 字幕路径或 None)
    failed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._thread: Optional[MediaDownloadThread] = None

    def probe(self, url: str) -> bool:
        """只解析视频信息（标题/清晰度/字幕），秒级返回，不下载。"""
        return self._launch(url, probe_only=True)

    def start(self, url: str, max_height: Optional[int] = None) -> bool:
        return self._launch(url, max_height=max_height)

    def _launch(
        self, url: str, probe_only: bool = False, max_height: Optional[int] = None
    ) -> bool:
        if self.is_running():
            return False
        thread = MediaDownloadThread(
            url, str(cfg.work_dir.value), probe_only=probe_only, max_height=max_height
        )
        thread.progress.connect(self.progressChanged)
        thread.stats.connect(self.statsChanged)
        thread.media.connect(self.mediaChanged)
        thread.probed.connect(self.probed)
        thread.finished.connect(self.completed)
        thread.error.connect(self.failed)
        self._thread = thread
        thread.start()
        return True

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def cancel(self):
        thread, self._thread = self._thread, None
        if thread is not None and thread.isRunning():
            signals = (
                thread.progress, thread.stats, thread.media,
                thread.probed, thread.finished, thread.error,
            )
            for signal in signals:
                try:
                    signal.disconnect()
                except TypeError:
                    pass
            thread.stop()

    def shutdown(self):
        self.cancel()


# ---------------------------------------------------------------------------
# 页面组件
# ---------------------------------------------------------------------------


class InputField(QFrame):
    """输入框：58 高 12 圆角，左侧形态图标 + 内嵌输入框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskInputField")
        self._icon = AppIcon.LINK
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(12)
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(20, 20)
        layout.addWidget(self.iconLabel)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("taskInputEdit")
        self.edit.setPlaceholderText(tr("home.input.placeholder"))
        # 聚焦反馈由外框点亮主题色承担，关掉 macOS 原生蓝色焦点环
        self.edit.setAttribute(Qt.WA_MacShowFocusRect, False)  # type: ignore[attr-defined]
        # 自绘清除按钮：Qt 内置清除图标是低分辨率位图，Retina 下发糊
        self.clearAction = QAction(self.edit)
        self.clearAction.triggered.connect(self.edit.clear)
        self.clearAction.setVisible(False)
        self.edit.addAction(self.clearAction, QLineEdit.TrailingPosition)
        self.edit.textChanged.connect(
            lambda text: self.clearAction.setVisible(bool(text))
        )
        apply_font(self.edit, 16, 760)
        # 焦点进出时重绘外框（聚焦点亮主题色描边）
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit, 1)
        self.syncStyle()

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.update()
        return super().eventFilter(obj, event)

    def setKindIcon(self, icon: AppIcon):
        if icon != self._icon:
            self._icon = icon
            self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        focused = self.edit.hasFocus()
        draw_rounded_surface(
            self,
            palette.field,
            rgba(palette.accent, 0.62) if focused else palette.line,
            12,
        )
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.iconLabel.setPixmap(icon_pixmap(self._icon, palette.muted, 20))
        self.clearAction.setIcon(render_svg_icon(AppIcon.CLOSE, palette.muted, 16))
        self.setStyleSheet(
            f"""
            QFrame#taskInputField {{ background: transparent; border: none; }}
            QLineEdit#taskInputEdit {{
                color: {palette.text};
                background: transparent;
                border: none;
                selection-background-color: {rgba(palette.accent, 0.35)};
            }}
            """
        )
        self.update()


class MediaReadyPanel(QFrame):
    """文件就绪面板：文件名 + 路径 + 元信息胶囊 + 已就绪。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaReadyPanel")
        self.setMinimumHeight(112)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(18)
        column = QVBoxLayout()
        column.setSpacing(7)
        self.nameLabel = ElidedLabel("", self)
        self.nameLabel.setObjectName("mediaName")
        apply_font(self.nameLabel, 19, 860)
        column.addWidget(self.nameLabel)
        self.pathLabel = ElidedLabel("", self)
        self.pathLabel.setObjectName("mediaPath")
        apply_font(self.pathLabel, 13, 720)
        column.addWidget(self.pathLabel)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chipRow = chips
        chips.addStretch(1)
        column.addLayout(chips)
        layout.addLayout(column, 1)
        self.pill = StatusPill(tr("home.media.ready"), "ok", self)
        layout.addWidget(self.pill, 0, Qt.AlignTop)  # type: ignore[arg-type]
        self.syncStyle()

    def setFile(self, path: str, info: Optional[VideoInfo] = None):
        file = Path(path)
        self.nameLabel.setText(file.stem)
        self.pathLabel.setText(path)
        chips = [
            tr("home.media.kind.audio")
            if file_type_icon(path) == AppIcon.MUSIC
            else tr("home.media.kind.video")
        ]
        chips.append(file.suffix.lstrip(".").lower())
        if info is not None and info.duration_seconds:
            minutes, seconds = divmod(int(info.duration_seconds), 60)
            chips.append(f"{minutes:02d}:{seconds:02d}")
            if info.width and info.height:
                chips.append(f"{info.width}x{info.height}")
        if file.exists():
            size = file.stat().st_size
            chips.append(
                f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024
                else f"{max(1, size // 1024)} KB"
            )
        self._set_chips(chips)

    def _set_chips(self, texts: list[str]):
        while self.chipRow.count() > 1:  # 末尾 stretch 保留
            item = self.chipRow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for text in texts:
            self.chipRow.insertWidget(self.chipRow.count() - 1, InfoChip(text, self))

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 15)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#mediaReadyPanel {{ background: transparent; border: none; }}
            QLabel#mediaName {{ color: {palette.text}; background: transparent; }}
            QLabel#mediaPath {{ color: {palette.muted}; background: transparent; }}
            """
        )


class DownloadPanel(QFrame):
    """下载进度盒：标题行 + 元信息行 + 进度行，信息分层不堆标签。

        视频标题                                    ⊗ 取消
        YouTube · Anthropic · 01:53
        ▮▮▮▮▮▮▯▯▯▯  38%   10.9 MB/s · 剩余 01:18

    元数据来自 yt-dlp 解析结果，站点缺什么字段就少一段。
    """

    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadPanel")
        self.setMinimumHeight(106)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.titleLabel = ElidedLabel(tr("home.download.parsing"), self)
        self.titleLabel.setObjectName("downloadTitle")
        apply_font(self.titleLabel, 15, 850)
        head.addWidget(self.titleLabel, 1)
        # 下载必须可取消
        self.cancelButton = CompactButton(tr("common.cancel"), AppIcon.CANCEL, self)
        self.cancelButton.clicked.connect(self.cancelRequested)
        head.addWidget(self.cancelButton)
        layout.addLayout(head)

        self.metaLabel = ElidedLabel("", self)
        self.metaLabel.setObjectName("downloadMeta")
        apply_font(self.metaLabel, 12, 720)
        layout.addWidget(self.metaLabel)
        layout.addSpacing(4)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.progressLine = ProgressBarLine(self)
        progress_row.addWidget(self.progressLine, 1)
        self.percentLabel = QLabel("0%", self)
        self.percentLabel.setObjectName("downloadPercent")
        self.percentLabel.setMinimumWidth(46)
        self.percentLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        apply_font(self.percentLabel, 14, 880)
        progress_row.addWidget(self.percentLabel)
        self.speedLabel = QLabel("", self)
        self.speedLabel.setObjectName("downloadSpeed")
        apply_font(self.speedLabel, 12, 740)
        self.speedLabel.setMinimumWidth(152)
        progress_row.addWidget(self.speedLabel)
        layout.addLayout(progress_row)
        self.syncStyle()

    def setPreparing(self, url: str):
        """解析阶段：标题占位 + 元信息行先放链接域名。"""
        self.titleLabel.setText(tr("home.download.parsing"))
        try:
            from urllib.parse import urlparse

            self.metaLabel.setText(urlparse(url).netloc or "")
        except ValueError:
            self.metaLabel.setText("")
        self.setProgress(0, "")
        self.setStats("--", "")

    def setMedia(self, summary: dict):
        if summary.get("title"):
            self.titleLabel.setText(summary["title"])
        parts = [
            summary[key] for key in ("site", "uploader", "duration") if summary.get(key)
        ]
        if parts:
            self.metaLabel.setText(" · ".join(parts))

    def setProgress(self, value: int, message: str):
        self.progressLine.setValue(value)
        self.percentLabel.setText(f"{value}%")

    def setStats(self, speed: str, eta: str):
        if not speed or speed == "--":
            self.speedLabel.setText("")
            return
        self.speedLabel.setText(f"{speed} · {eta}" if eta else speed)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 13)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#downloadPanel {{ background: transparent; border: none; }}
            QLabel#downloadTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#downloadMeta {{ color: {palette.muted}; background: transparent; }}
            QLabel#downloadPercent {{ color: {palette.warn_fg}; background: transparent; }}
            QLabel#downloadSpeed {{ color: {palette.muted}; background: transparent; }}
            """
        )


class ConfirmPanel(QFrame):
    """下载前确认面板：解析结果 + 清晰度选择，确认后才真正下载。

        视频标题                                  ⊗ 取消
        YouTube · Anthropic · 01:53 · 含字幕
        清晰度 [1080p ▾]              [▶ 开始下载]
    """

    startRequested = pyqtSignal(object)  # 选中的清晰度上限（int 或 None=最佳）
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("confirmPanel")
        self.setMinimumHeight(112)
        self._heights: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.titleLabel = ElidedLabel("", self)
        self.titleLabel.setObjectName("confirmTitle")
        apply_font(self.titleLabel, 15, 850)
        head.addWidget(self.titleLabel, 1)
        self.cancelButton = CompactButton(tr("common.cancel"), AppIcon.CANCEL, self)
        self.cancelButton.clicked.connect(self.cancelRequested)
        head.addWidget(self.cancelButton)
        layout.addLayout(head)

        self.metaLabel = ElidedLabel("", self)
        self.metaLabel.setObjectName("confirmMeta")
        apply_font(self.metaLabel, 12, 720)
        layout.addWidget(self.metaLabel)
        layout.addSpacing(2)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.qualityLabel = QLabel(tr("home.confirm.quality"), self)
        self.qualityLabel.setObjectName("confirmQualityLabel")
        apply_font(self.qualityLabel, 13, 780)
        action_row.addWidget(self.qualityLabel)
        self.qualitySelect = PillSelect(self)
        action_row.addWidget(self.qualitySelect)
        action_row.addStretch(1)
        self.startButton = WorkbenchButton(
            tr("home.download.start"), AppIcon.PLAY, primary=True, height=34, parent=self
        )
        self.startButton.setMinimumWidth(118)
        self.startButton.clicked.connect(self._emit_start)
        action_row.addWidget(self.startButton)
        layout.addLayout(action_row)
        self.syncStyle()

    def setData(self, summary: dict):
        self.titleLabel.setText(summary.get("title") or tr("home.confirm.untitled"))
        parts = [
            summary[key] for key in ("site", "uploader", "duration") if summary.get(key)
        ]
        if summary.get("has_subtitle"):
            parts.append(tr("home.confirm.has_subtitle"))
        self.metaLabel.setText(" · ".join(parts))
        self._heights = list(summary.get("qualities") or [])
        labels = [tr("home.confirm.quality.best")] + [f"{h}p" for h in self._heights]
        self.qualitySelect.setItems(labels, labels[0])
        # 始终显示清晰度选择（至少「最佳」）：没探测到分档时也让用户知道是自动选最佳，
        # 而不是只剩一个下载按钮、以为没有清晰度可选。
        self.qualityLabel.setVisible(True)
        self.qualitySelect.setVisible(True)

    def selectedHeight(self) -> Optional[int]:
        text = self.qualitySelect.currentText()
        return int(text[:-1]) if text.endswith("p") else None

    def _emit_start(self):
        self.startRequested.emit(self.selectedHeight())

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, rgba(palette.accent, 0.45), 13)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#confirmPanel {{ background: transparent; border: none; }}
            QLabel#confirmTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#confirmMeta {{ color: {palette.muted}; background: transparent; }}
            QLabel#confirmQualityLabel {{ color: {palette.muted}; background: transparent; }}
            """
        )


class FooterAction(QLabel):
    """底部链接动作：hover 点亮主题色。"""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        apply_font(self, 12, 780)
        self.syncStyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.syncStyle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.syncStyle()
        super().leaveEvent(event)

    def syncStyle(self):
        palette = app_palette()
        color = palette.accent if self.underMouse() else palette.subtle
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none; padding: 0 9px;"
        )


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


class TaskCreationInterface(QWidget):
    """任务创建页（首页）。"""

    finished = pyqtSignal(str, object)  # (媒体文件路径, 字幕路径或 None)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("TaskCreationInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self.state = PageState.INPUT
        self.task = None
        self._error: str = ""  # 下载失败后的错误卡内容
        self._media_info: Optional[VideoInfo] = None
        self._info_thread: Optional[VideoInfoThread] = None
        self._log_window: Optional[LogWindow] = None

        self.controller = DownloadController(self)
        self._build_ui()
        self._connect_signals()
        self._refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(42, 24, 42, 0)
        root.setSpacing(0)
        root.addStretch(5)

        # hero：标识 + 标题
        hero = QHBoxLayout()
        hero.setSpacing(22)
        hero.addStretch(1)
        self.heroMark = QLabel(self)
        self.heroMark.setFixedSize(96, 96)
        self.heroMark.setScaledContents(True)
        self.heroMark.setPixmap(QPixmap(str(HERO_MARK_PATH)))
        hero.addWidget(self.heroMark)
        self.heroTitle = QLabel(tr("home.hero.title"), self)
        self.heroTitle.setObjectName("heroTitle")
        # 跨平台中文字体栈：mac / Windows / Linux 各取系统最佳黑体
        apply_font(
            self.heroTitle,
            36,
            900,
            families=[
                "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei",
                "Noto Sans CJK SC", "Source Han Sans SC", "sans-serif",
            ],
        )
        hero.addWidget(self.heroTitle)
        hero.addStretch(1)
        root.addLayout(hero)
        root.addSpacing(26)

        # 内容列（输入卡 / 详情 / 流程线，宽度收敛到 860）
        column_host = QWidget(self)
        column = QVBoxLayout(column_host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        column_host.setMaximumWidth(1020)

        self.inputCard = QFrame(self)
        self.inputCard.setObjectName("taskInputCard")
        card_layout = QVBoxLayout(self.inputCard)
        card_layout.setContentsMargins(14, 14, 14, 10)
        card_layout.setSpacing(10)
        input_row = QHBoxLayout()
        input_row.setSpacing(12)
        self.inputField = InputField(self.inputCard)
        input_row.addWidget(self.inputField, 1)
        self.primaryButton = PrimaryIconButton(
            AppIcon.FOLDER_ADD, diameter=52, parent=self.inputCard
        )
        self.primaryButton.setToolTip(tr("home.btn.browse"))
        input_row.addWidget(self.primaryButton)
        card_layout.addLayout(input_row)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(12)
        self.quickLabel = QLabel("", self.inputCard)
        self.quickLabel.setObjectName("taskQuickLabel")
        apply_font(self.quickLabel, 13, 740)
        quick_row.addWidget(self.quickLabel)
        quick_row.addStretch(1)
        self.statusPill = StatusPill(tr("home.status.waiting"), "neutral", self.inputCard)
        self.statusPill.setMinimumWidth(66)
        quick_row.addWidget(self.statusPill)
        card_layout.addLayout(quick_row)
        column.addWidget(self.inputCard)

        # 详情区：占位 / 文件就绪 / 下载进度 / 错误条。
        # 每个子页顶对齐（内容多高就显示多高），整个区域固定占位，
        # 详情切换时 hero/输入卡位置纹丝不动。
        def top_aligned(widget: QWidget) -> QWidget:
            host = QWidget(self)
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.addWidget(widget)
            host_layout.addStretch(1)
            return host

        self.detailStack = QStackedWidget(self)
        self.detailPlaceholder = QWidget(self)
        self.detailStack.addWidget(self.detailPlaceholder)
        self.mediaPanel = MediaReadyPanel(self)
        self.mediaHost = top_aligned(self.mediaPanel)
        self.detailStack.addWidget(self.mediaHost)
        self.downloadPanel = DownloadPanel(self)
        self.downloadHost = top_aligned(self.downloadPanel)
        self.detailStack.addWidget(self.downloadHost)
        self.confirmPanel = ConfirmPanel(self)
        self.confirmHost = top_aligned(self.confirmPanel)
        self.detailStack.addWidget(self.confirmHost)
        self.errorCard = ErrorCard(parent=self)
        self.errorHost = top_aligned(self.errorCard)
        self.detailStack.addWidget(self.errorHost)
        self.detailStack.setFixedHeight(118)
        column.addWidget(self.detailStack)

        center_row = QHBoxLayout()
        center_row.addStretch(1)
        center_row.addWidget(column_host, 8)
        center_row.addStretch(1)
        root.addLayout(center_row)
        root.addStretch(7)

        # 底部品牌行：贴底、整体居中——程序名 + 版本胶囊 ｜ 查看日志 ｜ 捐助
        self.footerBar = QFrame(self)
        self.footerBar.setObjectName("taskFooter")
        self.footerBar.setFixedHeight(34)
        footer = QHBoxLayout(self.footerBar)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)
        self.brandLabel = QLabel("VideoCaptioner", self.footerBar)
        self.brandLabel.setObjectName("taskBrand")
        apply_font(self.brandLabel, 12, 850)
        footer.addWidget(self.brandLabel)
        self.versionChip = QLabel(f"v{VERSION}", self.footerBar)
        self.versionChip.setObjectName("taskVersionChip")
        self.versionChip.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        self.versionChip.setFixedHeight(18)
        apply_font(self.versionChip, 10, 800)
        footer.addWidget(self.versionChip)
        footer.addSpacing(14)
        self.feedbackAction = FooterAction(tr("feedback.title"), self.footerBar)
        self.logAction = FooterAction(tr("home.footer.logs"), self.footerBar)
        self.donateAction = FooterAction(tr("home.footer.donate"), self.footerBar)
        self._footerDividers = []
        for index, action in enumerate((self.feedbackAction, self.logAction, self.donateAction)):
            if index:
                divider = QFrame(self.footerBar)
                divider.setObjectName("taskFooterDivider")
                divider.setFixedSize(1, 11)
                footer.addWidget(divider)
                self._footerDividers.append(divider)
            footer.addWidget(action)
        footer.addStretch(1)
        root.addWidget(self.footerBar)
        self._sync_page_style()

    def _sync_page_style(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QWidget#TaskCreationInterface {{ background: {palette.bg}; }}
            QLabel#heroTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#taskQuickLabel {{ color: {palette.muted}; background: transparent; }}
            QLabel#taskBrand {{ color: {rgba(palette.text, 0.64)}; background: transparent; }}
            QLabel#taskAuthor {{ color: {rgba(palette.muted, 0.5)}; background: transparent; }}
            QFrame#taskFooter {{ background: transparent; border: none; }}
            QLabel#taskVersionChip {{
                color: {palette.muted};
                background: {palette.control};
                border: none;
                border-radius: 9px;
                padding: 0 8px;
            }}
            QFrame#taskFooterDivider {{
                background: {rgba(palette.muted, 0.22)};
                border: none;
            }}
            """
        )
        if hasattr(self, "errorCard"):
            self.errorCard.syncStyle()
        self.inputCard.setStyleSheet(
            f"""
            QFrame#taskInputCard {{
                background: {rgba("#ffffff", 0.03) if is_dark_theme() else rgba("#000000", 0.02)};
                border: 1px solid {palette.line_soft};
                border-radius: 16px;
            }}
            """
        )

    # ------------------------------------------------------------- signals

    def _connect_signals(self):
        self.inputField.edit.textChanged.connect(self._on_text_changed)
        self.primaryButton.clicked.connect(self._on_primary_clicked)
        self.downloadPanel.cancelRequested.connect(self._cancel_download)
        self.confirmPanel.startRequested.connect(self._start_download)
        self.confirmPanel.cancelRequested.connect(self._cancel_download)
        self.controller.probed.connect(self._on_probed)
        self.controller.progressChanged.connect(self._on_download_progress)
        self.controller.statsChanged.connect(self.downloadPanel.setStats)
        self.controller.mediaChanged.connect(self.downloadPanel.setMedia)
        self.controller.completed.connect(self._on_download_completed)
        self.controller.failed.connect(self._on_download_failed)
        self.feedbackAction.clicked.connect(lambda: FeedbackDialog(self).exec())
        self.logAction.clicked.connect(self._show_log_window)
        self.donateAction.clicked.connect(lambda: DonateDialog(self).exec_())

    # --------------------------------------------------------- 输入与动作

    def _input_text(self) -> str:
        return self.inputField.edit.text().strip()

    def _input_kind(self) -> str:
        return classify_input(self._input_text())

    def _on_text_changed(self):
        self._error = ""
        self._media_info = None
        if self.state == PageState.INPUT:
            kind = self._input_kind()
            if kind == InputKind.FILE:
                self._load_media_info(self._input_text())
            self._refresh()

    def _on_primary_clicked(self):
        if self.state == PageState.CONFIRM:
            self._start_download(self.confirmPanel.selectedHeight())
            return
        kind = self._input_kind()
        if kind == InputKind.FILE:
            self.finished.emit(self._input_text(), None)
            return
        if kind == InputKind.URL:
            self._start_probe()
            return
        self._browse_file()

    def _browse_file(self):
        if self.state == PageState.DOWNLOADING:
            return
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        audio_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedAudioFormats)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("home.dialog.select_media"),
            "",
            f"{tr('home.dialog.filter.media')} ({video_formats} {audio_formats});;"
            f"{tr('home.dialog.filter.video')} ({video_formats});;"
            f"{tr('home.dialog.filter.audio')} ({audio_formats})",
        )
        if file_path:
            self.inputField.edit.setText(file_path)

    # ------------------------------------------------------------- 下载

    def _start_probe(self):
        """第一步：只解析视频信息，完成后进入确认面板（不下载）。"""
        if not self.controller.probe(self._input_text()):
            return
        self._error = ""
        self.state = PageState.PROBING
        self.downloadPanel.setPreparing(self._input_text())
        self._refresh()

    def _on_probed(self, summary: dict):
        if self.state != PageState.PROBING:
            return
        self.state = PageState.CONFIRM
        self.confirmPanel.setData(summary)
        self._refresh()

    def _start_download(self, max_height):
        """第二步：用户确认清晰度后真正开始下载。"""
        if not self.controller.start(self._input_text(), max_height):
            return
        self._error = ""
        self.state = PageState.DOWNLOADING
        self.downloadPanel.setPreparing(self._input_text())
        self._refresh()

    def _cancel_download(self):
        self.controller.cancel()
        self.state = PageState.INPUT
        self._refresh()

    def _on_download_progress(self, value: int, message: str):
        if self.state == PageState.DOWNLOADING:
            self.downloadPanel.setProgress(value, message)
            self.statusPill.setState(f"{value}%", "warn")

    def _on_download_completed(self, video_path: str, subtitle_path):
        self.state = PageState.INPUT
        self.inputField.edit.setText(video_path)
        InfoBar.success(
            tr("home.download.done.title"), tr("home.download.done.body"),
            duration=INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.TOP, parent=self,
        )
        self.finished.emit(video_path, subtitle_path)

    def _on_download_failed(self, message: str):
        self.state = PageState.INPUT
        self._error = message
        self._refresh()

    # --------------------------------------------------------- 媒体元信息

    def _load_media_info(self, path: str):
        if self._info_thread is not None and self._info_thread.isRunning():
            self._info_thread.stop(wait_ms=200)
        thread = VideoInfoThread(path)
        thread.setParent(self)
        thread.finished.connect(self._on_media_info)
        thread.error.connect(lambda _msg: None)  # 元信息失败不阻断流程
        self._info_thread = thread
        thread.start()

    def _on_media_info(self, info: VideoInfo):
        self._media_info = info
        if self.state == PageState.INPUT and self._input_kind() == InputKind.FILE:
            self.mediaPanel.setFile(self._input_text(), info)

    # --------------------------------------------------------- 状态呈现

    def _refresh(self):
        kind = self._input_kind()

        if self.state in (PageState.PROBING, PageState.DOWNLOADING):
            probing = self.state == PageState.PROBING
            self.inputField.setKindIcon(AppIcon.LINK)
            self.inputField.edit.setReadOnly(True)
            self.primaryButton.setIcon(AppIcon.SYNC)
            self.primaryButton.setToolTip(
                tr("home.tip.parsing") if probing else tr("home.tip.downloading")
            )
            self.primaryButton.setEnabled(False)
            self.quickLabel.setText(
                tr("home.quick.parsing")
                if probing
                else tr("home.quick.downloading")
            )
            self.statusPill.setState(
                tr("home.status.parsing") if probing else "0%", "warn"
            )
            self.detailStack.setCurrentWidget(self.downloadHost)
            return

        if self.state == PageState.CONFIRM:
            self.inputField.setKindIcon(AppIcon.LINK)
            self.inputField.edit.setReadOnly(True)
            self.primaryButton.setIcon(AppIcon.PLAY)
            self.primaryButton.setToolTip(tr("home.download.start"))
            self.primaryButton.setEnabled(True)
            self.quickLabel.setText(tr("home.quick.confirm"))
            self.statusPill.setState(tr("home.status.pending"), "ok")
            self.detailStack.setCurrentWidget(self.confirmHost)
            return

        self.inputField.edit.setReadOnly(False)
        specs = {
            InputKind.EMPTY: (AppIcon.LINK, tr("home.btn.browse"), AppIcon.FOLDER_ADD, tr("home.status.waiting"), "neutral"),
            InputKind.FILE: (file_type_icon(self._input_text()), tr("home.btn.start"), AppIcon.PLAY, tr("home.status.ready"), "ok"),
            InputKind.URL: (AppIcon.LINK, tr("home.btn.start"), AppIcon.PLAY, tr("home.status.ready"), "ok"),
            InputKind.INVALID: (AppIcon.FILE, tr("home.btn.browse"), AppIcon.FOLDER_ADD, tr("home.status.invalid"), "fail"),
        }
        icon, tooltip, button_icon, pill_text, pill_level = specs[kind]
        self.inputField.setKindIcon(icon)
        self.primaryButton.setIcon(button_icon)
        self.primaryButton.setToolTip(tooltip)
        self.primaryButton.setEnabled(True)
        self.statusPill.setState(pill_text, pill_level)

        quick_texts = {
            InputKind.EMPTY: tr("home.quick.empty"),
            InputKind.FILE: tr("home.quick.file"),
            InputKind.URL: tr("home.quick.url"),
            InputKind.INVALID: tr("home.quick.invalid"),
        }
        self.quickLabel.setText(quick_texts[kind])

        if self._error:
            self.errorCard.setText(self._error)
            self.detailStack.setCurrentWidget(self.errorHost)
        elif kind == InputKind.FILE:
            self.mediaPanel.setFile(self._input_text(), self._media_info)
            self.detailStack.setCurrentWidget(self.mediaHost)
        elif kind == InputKind.INVALID:
            self.errorCard.setText(tr("home.error.invalid_input"))
            self.detailStack.setCurrentWidget(self.errorHost)
        else:
            self.detailStack.setCurrentWidget(self.detailPlaceholder)

    # ------------------------------------------------------------ 外部契约

    def set_task(self, task):
        self.task = task
        if task is not None and getattr(task, "file_path", None):
            self.inputField.edit.setText(task.file_path)

    def process(self):
        self._on_primary_clicked()

    # ------------------------------------------------------------ 拖放

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.state == PageState.INPUT:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.isfile(path):
                if Path(path).suffix.lower() in _MEDIA_EXTENSIONS:
                    self.inputField.edit.setText(path)
                    return
        self._error = tr("home.error.unsupported_drop")
        self._refresh()

    # ------------------------------------------------------------ 其他

    def _show_log_window(self):
        if self._log_window is None:
            self._log_window = LogWindow()
        if self._log_window.isHidden():
            self._log_window.show()
        else:
            self._log_window.activateWindow()

    def closeEvent(self, event):
        self.controller.shutdown()
        if self._info_thread is not None and self._info_thread.isRunning():
            self._info_thread.stop(wait_ms=500)
        super().closeEvent(event)
