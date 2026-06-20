"""运行依赖下载弹窗（ffmpeg / voxgate）。

把本机缺失的外部二进制一站式补齐：按系统自动选版本、国内走加速镜像、逐行进度/取消/
重试、可一键安装所有缺失项。所有下载件来自 :mod:`core.download.dependencies` 注册表，
新增依赖无需改本弹窗。

约定（对齐 model_manager_dialog）：同一时刻只跑一个下载任务；关闭弹窗即取消进行中的
下载（.part 保留续传）。复用 workbench 设计原子（圆角卡片、进度条、状态胶囊、按钮）。
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from videocaptioner.config import BIN_PATH
from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.download.dependencies import (
    DependencySpec,
    asset_for,
    is_installed,
    iter_dependencies,
)
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import (
    AccentButton,
    CompactButton,
    IconBox,
    ProgressBarLine,
    StatusPill,
    apply_font,
    draw_rounded_surface,
)
from videocaptioner.ui.thread.artifact_download_thread import (
    ArtifactDownloadThread,
    dependency_download_thread,
)

_ICON_FOR = {"voxgate": AppIcon.MICROPHONE, "ffmpeg": AppIcon.TERMINAL}


class _DependencyRow(QFrame):
    """一个依赖行：图标盒 + 名称/说明 +（右侧单槽）状态胶囊 / 下载按钮 / 下载进度。

    右侧任一时刻只呈现一件事，且都靠右贴边：已装→绿胶囊；缺失→下载按钮；下载中→
    进度条+取消；失败→红胶囊+重试。隐藏的控件在布局里自动塌缩，可见件始终顶到右边。
    """

    actionRequested = pyqtSignal(object)  # spec
    cancelRequested = pyqtSignal()

    def __init__(self, spec: DependencySpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("dependencyRow")
        self.setFixedHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)
        layout.addWidget(IconBox(_ICON_FOR.get(spec.key, AppIcon.FILE), self))

        # 名称 / 说明：上下两行，整体垂直居中（首尾 stretch 夹住）
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addStretch(1)
        self.nameLabel = QLabel(spec.display_name, self)
        self.nameLabel.setObjectName("depName")
        apply_font(self.nameLabel, 14, 820)
        column.addWidget(self.nameLabel)
        self.descLabel = QLabel(spec.description, self)
        self.descLabel.setObjectName("depDesc")
        self.descLabel.setWordWrap(False)
        apply_font(self.descLabel, 12, 650)
        column.addWidget(self.descLabel)
        column.addStretch(1)
        layout.addLayout(column, 1)

        # —— 右侧单槽：进度 / 胶囊 / 按钮互斥，隐藏即塌缩，可见件自动贴右边 ——
        self.progressLine = ProgressBarLine(self)
        self.progressLine.setFixedWidth(132)
        self.progressLine.hide()
        layout.addWidget(self.progressLine)
        self.percentLabel = QLabel("", self)
        self.percentLabel.setObjectName("depPercent")
        self.percentLabel.setFixedWidth(40)
        self.percentLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        apply_font(self.percentLabel, 12, 750)
        self.percentLabel.hide()
        layout.addWidget(self.percentLabel)

        self.status = StatusPill("", "neutral", self)
        self.status.hide()
        layout.addWidget(self.status)

        self.actionButton = AccentButton(self.tr("下载"), AppIcon.DOWNLOAD, self)
        self.actionButton.clicked.connect(lambda: self.actionRequested.emit(self.spec))
        self.actionButton.hide()
        layout.addWidget(self.actionButton)
        self.cancelButton = CompactButton(self.tr("取消"), None, self)
        self.cancelButton.clicked.connect(self.cancelRequested)
        self.cancelButton.hide()
        layout.addWidget(self.cancelButton)
        self.syncStyle()

    # ---- 状态切换 ----

    def _hide_right(self):
        for w in (self.progressLine, self.percentLabel, self.status,
                  self.actionButton, self.cancelButton):
            w.setVisible(False)

    def showState(self, *, installed: bool, supported: bool, busy: bool, failed: bool):
        self._hide_right()
        self.descLabel.setText(self.spec.description)
        if installed:
            self.status.setState(self.tr("已安装"), "ok")  # 绿胶囊已表态，无需再放按钮
            self.status.setVisible(True)
        elif not supported:
            self.status.setState(self.tr("暂不支持"), "neutral")
            self.status.setVisible(True)
        elif failed:
            self.status.setState(self.tr("失败"), "fail")
            self.status.setVisible(True)
            self.actionButton.setText(self.tr("重试"))
            self.actionButton.setIcon(AppIcon.DOWNLOAD)
            self.actionButton.setEnabled(not busy)
            self.actionButton.setVisible(True)
        else:  # 缺失、可装
            self.actionButton.setText(self.tr("下载"))
            self.actionButton.setIcon(AppIcon.DOWNLOAD)
            self.actionButton.setEnabled(not busy)
            self.actionButton.setVisible(True)

    def showDownloading(self):
        self._hide_right()
        self.progressLine.setValue(0)
        self.progressLine.setVisible(True)
        self.percentLabel.setText("0%")
        self.percentLabel.setVisible(True)
        self.descLabel.setText(self.tr("正在连接镜像…"))
        self.cancelButton.setEnabled(True)
        self.cancelButton.setVisible(True)

    def setProgress(self, percent: int, message: str):
        if percent >= 0:
            self.progressLine.setValue(percent)
            self.percentLabel.setText(f"{percent}%")
        self.descLabel.setText(message)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QLabel#depName {{ color: {palette.text}; background: transparent; }}"
            f"QLabel#depDesc {{ color: {palette.subtle}; background: transparent; }}"
            f"QLabel#depPercent {{ color: {palette.muted}; background: transparent; }}"
        )

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.card_surface, palette.line_soft, 12)
        super().paintEvent(event)


class DependencyDownloadDialog(AppDialog):
    """运行依赖下载弹窗：单任务串行，逐行进度/取消/重试，可一键装缺失。"""

    depsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("下载运行依赖", icon=AppIcon.DOWNLOAD, parent=parent, width=560)
        self._thread: ArtifactDownloadThread | None = None
        self._active: _DependencyRow | None = None
        self._queue: list[DependencySpec] = []  # 一键安装缺失的待装队列
        self._failed: set[str] = set()
        self._rows: list[_DependencyRow] = []

        self.addBodyText(
            self.tr("按你的系统自动选择合适的版本下载到本机；国内网络会优先走加速镜像。")
        )
        for spec in iter_dependencies():
            row = _DependencyRow(spec, self.widget)
            row.actionRequested.connect(self._on_row_action)
            row.cancelRequested.connect(self._cancel_active)
            self.bodyLayout.addWidget(row)
            self._rows.append(row)

        self.openDirButton = self.addFooterButton(self.tr("打开安装目录"), icon=AppIcon.FOLDER)
        self.openDirButton.clicked.connect(self._open_bin_dir)
        self.addFooterStretch()
        self.installAllButton = self.addFooterButton(
            self.tr("一键安装缺失"), kind="accent", icon=AppIcon.DOWNLOAD
        )
        self.installAllButton.clicked.connect(self._install_all_missing)
        self.doneButton = self.addFooterButton(self.tr("完成"))
        self.doneButton.clicked.connect(lambda: self.done(0))

        self._refresh()

    # ------------------------------------------------------------- 状态刷新

    @property
    def _busy(self) -> bool:
        return self._thread is not None

    def _refresh(self):
        any_missing = False
        for row in self._rows:
            supported = asset_for(row.spec) is not None
            installed = is_installed(row.spec)
            if row is self._active:
                continue  # 下载中由进度回调驱动，别覆盖
            row.showState(
                installed=installed,
                supported=supported,
                busy=self._busy,
                failed=row.spec.key in self._failed,
            )
            if supported and not installed:
                any_missing = True
        self.installAllButton.setEnabled(any_missing and not self._busy)

    # ------------------------------------------------------------- 下载

    def _on_row_action(self, spec: DependencySpec):
        if self._busy:
            return
        self._start(spec)

    def _start(self, spec: DependencySpec):
        row = next((r for r in self._rows if r.spec.key == spec.key), None)
        if row is None:
            return
        self._failed.discard(spec.key)
        thread = dependency_download_thread(spec, self)
        self._thread = thread
        self._active = row
        row.showDownloading()
        thread.progress.connect(row.setProgress)
        thread.completed.connect(lambda _path, s=spec: self._on_done(s))
        thread.error.connect(lambda message, s=spec: self._on_error(s, message))
        thread.finished.connect(self._on_finished)
        self._refresh()
        thread.start()

    def _install_all_missing(self):
        if self._busy:
            return
        missing = [
            spec
            for spec in (row.spec for row in self._rows)
            if asset_for(spec) is not None and not is_installed(spec)
        ]
        if not missing:
            self._info(self.tr("无需安装"), self.tr("所有依赖都已就绪。"))
            return
        self._queue = missing[1:]
        self._start(missing[0])

    def _on_done(self, spec: DependencySpec):
        self._failed.discard(spec.key)
        self._info(self.tr("已安装"), self.tr("{} 下载完成。").format(spec.display_name))
        self.depsChanged.emit()

    def _on_error(self, spec: DependencySpec, message: str):
        self._failed.add(spec.key)
        self._error(self.tr("下载失败"), message)

    def _on_finished(self):
        thread = self._thread
        self._thread = None
        self._active = None
        if thread is not None:
            thread.deleteLater()
        # 一键安装队列：装下一个（已失败的也跳过，避免卡住）
        nxt = None
        while self._queue:
            candidate = self._queue.pop(0)
            if candidate.key not in self._failed and not is_installed(candidate):
                nxt = candidate
                break
        self._refresh()
        if nxt is not None:
            self._start(nxt)

    def _cancel_active(self):
        self._queue.clear()  # 取消即放弃整条一键安装队列
        if self._thread is not None:
            self._thread.stop()

    def done(self, code: int):  # noqa: A003
        self._cancel_active()
        super().done(code)

    # ------------------------------------------------------------- 工具

    def _open_bin_dir(self):
        bin_path = Path(BIN_PATH)
        bin_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(bin_path)))

    def _info(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.success(title, message, duration=INFOBAR_DURATION_SUCCESS, parent=self.window())

    def _warn(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.warning(title, message, duration=INFOBAR_DURATION_WARNING, parent=self.window())

    def _error(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.error(title, message, duration=INFOBAR_DURATION_ERROR, parent=self.window())
