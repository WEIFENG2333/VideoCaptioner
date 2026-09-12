"""更新检查 / 下载的 Qt 线程薄壳；业务在 core/update，UI 只消费信号。

- UpdateCheckThread：启动后台调后端 check → resultReady(CheckResult) / checkFailed。
  开发版（channel=dev）也检查，方便调试公告与更新；pip 版后端不下发更新。
- UpdateDownloadThread：用户点「下载更新」后后台下载（进度/取消）→ downloaded/downloadFailed。
切语言/安装走 main_window；本模块不碰 UI 控件。
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.config import UPDATE_CHECK_URL
from videocaptioner.core.download.downloader import DownloadCancelled, DownloadProgress
from videocaptioner.core.update import UpdateInfo, check_update, download_update
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("update_thread")


class UpdateCheckThread(QThread):
    """后台调后端检查更新 + 公告（一次请求拿 block/update/announcement）。"""

    resultReady = pyqtSignal(object)  # CheckResult
    checkFailed = pyqtSignal(str)

    def run(self) -> None:
        result = check_update(UPDATE_CHECK_URL)
        if result is None:
            self.checkFailed.emit("update check unreachable")
            return
        self.resultReady.emit(result)


class UpdateDownloadThread(QThread):
    """后台下载更新包（含 sha256 校验）；可取消。"""

    progress = pyqtSignal(int, int)  # received, total（total 未知为 0）
    downloaded = pyqtSignal(str)  # zip 路径
    downloadFailed = pyqtSignal(str)

    def __init__(self, info: UpdateInfo, dest_dir: Path, parent=None):
        super().__init__(parent)
        self._info = info
        self._dest_dir = dest_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def on_progress(p: DownloadProgress) -> None:
            self.progress.emit(p.received, p.total or 0)

        try:
            path = download_update(
                self._info,
                self._dest_dir,
                on_progress=on_progress,
                should_cancel=lambda: self._cancelled,
            )
        except DownloadCancelled:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("update download failed: %s", exc)
            self.downloadFailed.emit(str(exc))
            return
        self.downloaded.emit(str(path))
