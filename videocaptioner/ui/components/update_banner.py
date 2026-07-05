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
        info: UpdateInfo | None,
        dest_dir: Path,
        on_install: Callable[[str], None],
        *,
        blocked: str | None = None,
    ):
        self._window = window
        self._info = info
        self._dest_dir = Path(dest_dir)
        self._on_install = on_install
        self._blocked = blocked  # 非空=当前版本被后端封禁，文案直接展示
        self._self_update = can_self_update()
        self._state = "available"
        self._zip_path: str | None = None
        self._dl = None
        self._bar: InfoBar | None = None
        self._button: PrimaryPushButton | None = None

    def show(self) -> None:
        # 普通更新标题带版本号；版本被封禁时用「需更新才能继续使用」标题，原因放正文
        title = (
            tr("app.update.title", version=self._info.version)
            if (self._info and not self._blocked)
            else tr("app.update.mandatory")
        )
        self._bar = InfoBar(
            InfoBarIcon.INFORMATION,
            title,
            "",
            # 封禁且能自更新时才不可关（逼用户在应用内更新）；不能自更新时仍可关，
            # 否则用户被卡在一个只能「前往下载」的常驻条上、无应用内出路。
            isClosable=not (self._blocked and self._self_update),
            duration=-1,
            # 右下角：TOP 会压住自绘标题栏和页头文字；常驻条放通知惯例位、不遮内容
            position=InfoBarPosition.BOTTOM_RIGHT,
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
        self._teardown_dl()

    def _teardown_dl(self) -> None:
        """取消 + 等待 + 断信号 + 清空当前下载线程，维持「至多一个在跑」的单例不变量。

        否则 取消→再下载 会让旧线程成为仍在跑、信号仍连着 banner 的孤儿：迟到的 progress
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

    # ---- 状态机 ----
    def _set_state(self, state: str, *, percent: int = 0, error: str = "") -> None:
        self._state = state
        if self._bar is None or self._button is None:
            return
        if state == "available":
            content = self._blocked or tr("app.update.available")
            # 能自更新且有资产才给「下载更新」，否则退化「前往下载」（pip / 无本平台资产）
            button = (
                tr("app.update.download")
                if (self._self_update and self._info)
                else tr("app.update.go_download")
            )
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
        elif self._self_update and self._info is not None:  # available / failed
            self._start_download()
        else:
            QDesktopServices.openUrl(QUrl(RELEASE_URL))

    def _start_download(self) -> None:
        if self._info is None:  # 无资产不可下载（理论上按钮已退化为前往下载）
            return
        self._teardown_dl()  # 重试/再下载前先清掉上一个线程，保证单例
        self._dl = UpdateDownloadThread(self._info, self._dest_dir, self._window)
        self._dl.progress.connect(self._on_progress)
        self._dl.downloaded.connect(self._on_downloaded)
        self._dl.downloadFailed.connect(self._on_failed)
        self._set_state("downloading", percent=0)
        self._dl.start()

    def _cancel(self) -> None:
        self._teardown_dl()
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
