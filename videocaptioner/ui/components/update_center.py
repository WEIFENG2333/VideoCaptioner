"""更新中心：发现新版本 → 静默后台下载 → 侧栏入口就绪可装（对齐 Chrome/VS Code 惯例）。

UpdateCenter 是状态机（available → downloading NN% → ready / failed），能自更新时
start() 立即开始后台下载，全程不打扰用户；侧栏底部的更新入口与详情弹窗都只监听
stateChanged 渲染。UpdateDialog 展示版本、更新说明、实时进度与状态化按钮。

安装由调用方注入的回调完成（apply_update + 退出应用）——本模块不直接退出进程，
也不碰业务配置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from videocaptioner.config import RELEASE_URL
from videocaptioner.core.update import UpdateInfo, can_self_update
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import ProgressBarLine, apply_font
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.update_thread import UpdateDownloadThread

_NOTES_MAX_HEIGHT = 220  # 更新说明超高时内部滚动，弹窗本体不无限拉长


class UpdateCenter(QObject):
    """更新流程状态机。``on_install(zip_path)`` 在用户点「重启并安装」时被调用。"""

    stateChanged = pyqtSignal()

    def __init__(
        self,
        info: UpdateInfo | None,
        dest_dir: Path,
        on_install: Callable[[str], None],
        *,
        blocked: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.info = info
        self.blocked = blocked  # 非空=当前版本被后端封禁，文案直接展示
        # 能自更新且有本平台资产才走应用内下载，否则一律「前往下载页」
        self.self_update = can_self_update() and info is not None
        self._dest_dir = Path(dest_dir)
        self._on_install = on_install
        self.state = "available"
        self.percent = 0
        self.error = ""
        self._zip_path: str | None = None
        self._dl: Optional[UpdateDownloadThread] = None

    # ---- 流程 ----

    def start(self) -> None:
        """发现新版本后的入口：能自更新就立即静默后台下载，下载完侧栏一键可装。"""
        if self.self_update:
            self.start_download()

    def start_download(self) -> None:
        if not self.self_update or self.info is None:
            return
        self._teardown_dl()  # 重试/再下载前先清掉上一个线程，保证单例
        self._dl = UpdateDownloadThread(self.info, self._dest_dir, self)
        self._dl.progress.connect(self._on_progress)
        self._dl.downloaded.connect(self._on_downloaded)
        self._dl.downloadFailed.connect(self._on_failed)
        self._set("downloading", percent=0)
        self._dl.start()

    def cancel_download(self) -> None:
        self._teardown_dl()
        self._set("available")

    def install(self) -> None:
        if self._zip_path:
            self._on_install(self._zip_path)

    def open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(RELEASE_URL))

    def stop(self) -> None:
        """取消在途下载并等待线程退出（供窗口关闭时调用）。"""
        self._teardown_dl()

    # ---- 内部 ----

    def _teardown_dl(self) -> None:
        """取消 + 等待 + 断信号 + 清空当前下载线程，维持「至多一个在跑」的单例不变量。

        否则 取消→再下载 会让旧线程成为仍在跑、信号仍连着的孤儿：迟到的 progress
        会盖掉新线程进度，退出时 stop() 也够不到它 → 销毁运行中 QThread 触发 abort。
        """
        if self._dl is None:
            return
        dl, self._dl = self._dl, None
        dl.cancel()
        dl.wait(3000)
        try:
            dl.progress.disconnect(self._on_progress)
            dl.downloaded.disconnect(self._on_downloaded)
            dl.downloadFailed.disconnect(self._on_failed)
        except (TypeError, RuntimeError):
            pass

    def _set(self, state: str, *, percent: int = 0, error: str = "") -> None:
        self.state = state
        self.percent = percent
        self.error = error
        self.stateChanged.emit()

    def _on_progress(self, received: int, total: int) -> None:
        percent = int(received * 100 / total) if total else 0
        if percent != self.percent:  # 只在整数百分比变化时重绘，避免刷屏
            self._set("downloading", percent=percent)

    def _on_downloaded(self, path: str) -> None:
        self._zip_path = path
        self._set("ready", percent=100)

    def _on_failed(self, message: str) -> None:
        self._set("failed", error=message)


class UpdateDialog(AppDialog):
    """更新详情弹窗：版本 + 更新说明 + 实时进度 + 状态化按钮。

    弹窗只是 UpdateCenter 的视图：关掉它下载照常进行（「后台下载」），
    重新打开无缝接上当前进度。
    """

    def __init__(self, center: UpdateCenter, parent: QWidget | None = None):
        info = center.info
        title = (
            tr("app.update.title", version=info.version)
            if (info and not center.blocked)
            else tr("app.update.mandatory")
        )
        super().__init__(title, icon=AppIcon.DOWNLOAD, parent=parent, width=480)
        self._center = center

        if center.blocked:  # 封禁原因优先、用警示色展示
            blocked = QLabel(center.blocked, self.widget)
            blocked.setObjectName("updateBlockedLabel")
            blocked.setWordWrap(True)
            apply_font(blocked, 13, 700)
            self.bodyLayout.addWidget(blocked)

        notes = (info.notes or "").strip() if info else ""
        if notes:
            self._add_notes(notes)
        elif not center.blocked:
            self.addBodyText(tr("app.update.available"))

        self.progressBar = ProgressBarLine(self.widget)
        self.bodyLayout.addWidget(self.progressBar)
        self.statusLabel = QLabel("", self.widget)
        self.statusLabel.setObjectName("updateStatusLabel")
        self.statusLabel.setWordWrap(True)
        apply_font(self.statusLabel, 12, 600)
        self.bodyLayout.addWidget(self.statusLabel)

        self.addFooterStretch()
        self.laterButton = self.addFooterButton(tr("app.update.later"))
        self.laterButton.clicked.connect(lambda: self.done(0))
        # 次按钮动作随状态切换：下载中=取消下载；失败=前往下载页
        self.secondaryButton = self.addFooterButton("")
        self.secondaryButton.clicked.connect(self._on_secondary)
        self.primaryButton = self.addFooterButton("", kind="accent")
        self.primaryButton.clicked.connect(self._on_primary)

        center.stateChanged.connect(self._refresh)
        self._refresh()
        self.syncStyle()

    def _add_notes(self, notes: str) -> None:
        scroll = QScrollArea(self.widget)
        scroll.setObjectName("updateNotesScroll")
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(_NOTES_MAX_HEIGHT)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        host = QWidget(scroll)
        host.setObjectName("updateNotesHost")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        label = QLabel(notes, host)
        label.setObjectName("updateNotesLabel")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore[arg-type]
        apply_font(label, 13, 600)
        layout.addWidget(label)
        layout.addStretch(1)
        scroll.setWidget(host)
        self.bodyLayout.addWidget(scroll)

    # ---- 状态渲染 ----

    def _refresh(self) -> None:
        center = self._center
        state = center.state

        self.progressBar.setVisible(state in ("downloading", "ready", "failed"))
        if state == "downloading":
            self.progressBar.setTone("accent")
            self.progressBar.setValue(center.percent)
            self.statusLabel.setText(tr("app.update.downloading", percent=center.percent))
        elif state == "ready":
            self.progressBar.setTone("accent")
            self.progressBar.setValue(100)
            self.statusLabel.setText(tr("app.update.ready"))
        elif state == "failed":
            self.progressBar.setTone("fail")
            self.progressBar.setValue(100)
            self.statusLabel.setText(tr("app.update.failed", error=center.error))
        else:  # available
            self.statusLabel.setText("")
        self.statusLabel.setVisible(bool(self.statusLabel.text()))

        # 封禁时不给「稍后」：应用已锁定，唯一出路就是更新（弹窗仍可关，侧栏入口还在）
        self.laterButton.setVisible(state in ("available", "ready") and not center.blocked)
        self.secondaryButton.setVisible(state in ("downloading", "failed"))
        if state == "downloading":
            self.secondaryButton.setText(tr("app.update.cancel"))
            self.primaryButton.setText(tr("app.update.background"))
        elif state == "failed":
            self.secondaryButton.setText(tr("app.update.go_download"))
            self.primaryButton.setText(tr("app.update.retry"))
        elif state == "ready":
            self.primaryButton.setText(tr("app.update.install"))
        else:  # available
            self.primaryButton.setText(
                tr("app.update.download") if center.self_update else tr("app.update.go_download")
            )

    def _on_primary(self) -> None:
        center, state = self._center, self._center.state
        if state == "downloading":  # 后台下载 = 关弹窗，下载继续
            self.done(0)
        elif state == "ready":
            center.install()
        elif center.self_update:  # available / failed → （重新）下载
            center.start_download()
        else:
            center.open_release_page()

    def _on_secondary(self) -> None:
        if self._center.state == "downloading":
            self._center.cancel_download()
        else:  # failed
            self._center.open_release_page()

    def done(self, result: int) -> int:
        # 弹窗关闭即与状态机断开；下载线程归 UpdateCenter 所有，不受弹窗生命周期影响
        try:
            self._center.stateChanged.disconnect(self._refresh)
        except (TypeError, RuntimeError):
            pass
        return super().done(result)

    def extraStyleRules(self, palette) -> str:
        return f"""
            QScrollArea#updateNotesScroll {{ background: transparent; border: none; }}
            QWidget#updateNotesHost {{ background: transparent; }}
            QLabel#updateNotesLabel {{ color: {palette.muted}; background: transparent; }}
            QLabel#updateStatusLabel {{ color: {palette.subtle}; background: transparent; }}
            QLabel#updateBlockedLabel {{ color: {palette.danger_fg}; background: transparent; }}
            QScrollArea#updateNotesScroll QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px; border: none;
            }}
            QScrollArea#updateNotesScroll QScrollBar::handle:vertical {{
                background: {palette.line}; border-radius: 4px; min-height: 36px;
            }}
            QScrollArea#updateNotesScroll QScrollBar::add-line:vertical,
            QScrollArea#updateNotesScroll QScrollBar::sub-line:vertical {{
                height: 0; background: transparent;
            }}
        """
