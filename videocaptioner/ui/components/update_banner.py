"""更新提示条：可用 → 下载中 NN% → 重启并安装；失败可重试，开发态/不可写则退化为「前往下载」。

持有一个常驻 InfoBar + 一个按钮（按钮动作随状态切换），挂在主窗口上。下载走
UpdateDownloadThread（含 sha256 校验、可取消）。安装由调用方注入的回调完成
（apply_update + 退出应用）——本组件不直接退出进程，也不碰业务配置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import InfoBar, InfoBarIcon, InfoBarPosition, PrimaryPushButton

from videocaptioner.config import RELEASE_URL
from videocaptioner.core.update import UpdateInfo, can_self_update
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.update_thread import UpdateDownloadThread


class UpdateBanner:
    """更新提示条的状态机。``on_install(zip_path)`` 在用户点「重启并安装」时被调用。"""

    def __init__(
        self,
        window,
        info: UpdateInfo,
        dest_dir: Path,
        on_install: Callable[[str], None],
    ):
        self._window = window
        self._info = info
        self._dest_dir = Path(dest_dir)
        self._on_install = on_install
        self._self_update = can_self_update()
        self._state = "available"
        self._zip_path: str | None = None
        self._dl = None
        self._bar: InfoBar | None = None
        self._button: PrimaryPushButton | None = None

    def show(self) -> None:
        self._bar = InfoBar(
            InfoBarIcon.INFORMATION,
            tr("app.update.title", version=self._info.version),
            "",
            isClosable=not self._info.mandatory,
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self._window,
        )
        self._button = PrimaryPushButton(self._bar)
        self._button.clicked.connect(self._on_button)
        self._bar.addWidget(self._button)
        self._bar.closedSignal.connect(self.stop)
        self._set_state("available")
        self._bar.show()

    def stop(self) -> None:
        """取消在途下载并等待线程退出（供窗口关闭/提示条关闭时调用）。"""
        if self._dl is not None and self._dl.isRunning():
            self._dl.cancel()
            self._dl.wait(3000)

    # ---- 状态机 ----
    def _set_state(self, state: str, *, percent: int = 0, error: str = "") -> None:
        self._state = state
        if self._bar is None or self._button is None:
            return
        if state == "available":
            content = tr("app.update.mandatory") if self._info.mandatory else tr("app.update.available")
            button = tr("app.update.download") if self._self_update else tr("app.update.go_download")
        elif state == "downloading":
            content = tr("app.update.downloading", percent=percent)
            button = tr("app.update.cancel")
        elif state == "ready":
            content = tr("app.update.ready")
            button = tr("app.update.install")
        else:  # failed
            content = tr("app.update.failed", error=error)
            button = tr("app.update.retry") if self._self_update else tr("app.update.go_download")
        self._bar.contentLabel.setText(content)
        self._button.setText(button)

    def _on_button(self) -> None:
        if self._state == "downloading":
            self._cancel()
        elif self._state == "ready":
            self._install()
        elif self._self_update:  # available / failed
            self._start_download()
        else:
            QDesktopServices.openUrl(QUrl(RELEASE_URL))

    def _start_download(self) -> None:
        self._dl = UpdateDownloadThread(self._info, self._dest_dir, self._window)
        self._dl.progress.connect(self._on_progress)
        self._dl.downloaded.connect(self._on_downloaded)
        self._dl.downloadFailed.connect(self._on_failed)
        self._set_state("downloading", percent=0)
        self._dl.start()

    def _cancel(self) -> None:
        if self._dl is not None:
            self._dl.cancel()
        self._set_state("available")

    def _install(self) -> None:
        if self._zip_path:
            self._on_install(self._zip_path)

    def _on_progress(self, received: int, total: int) -> None:
        if self._bar is None:
            return
        percent = int(received * 100 / total) if total else 0
        self._bar.contentLabel.setText(tr("app.update.downloading", percent=percent))

    def _on_downloaded(self, path: str) -> None:
        self._zip_path = path
        self._set_state("ready")

    def _on_failed(self, message: str) -> None:
        self._set_state("failed", error=message)
