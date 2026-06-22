"""更新检查 / 下载的 Qt 线程薄壳；业务在 core/update，UI 只消费信号。

- UpdateCheckThread：启动时后台拉 manifest，比较版本 → updateAvailable/upToDate/checkFailed。
- UpdateDownloadThread：用户点「下载更新」后后台下载（进度/取消）→ downloaded/downloadFailed。
切语言/安装走 main_window；本模块不碰 UI 控件。
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.config import UPDATE_MANIFEST_URL, VERSION
from videocaptioner.core.download.downloader import DownloadCancelled, DownloadProgress
from videocaptioner.core.update import UpdateInfo, download_update, fetch_manifest
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("update_thread")


class UpdateCheckThread(QThread):
    """后台检查更新 + 公告（一次拉取 manifest）。dev 版（0.0.0-dev）跳过，避免源码运行每次误报。"""

    updateAvailable = pyqtSignal(object)  # UpdateInfo
    announcementAvailable = pyqtSignal(object)  # Announcement（与是否有新版无关）
    upToDate = pyqtSignal()
    checkFailed = pyqtSignal(str)

    def run(self) -> None:
        if VERSION.startswith("0.0.0"):
            self.upToDate.emit()
            return
        try:
            manifest = fetch_manifest(VERSION, (UPDATE_MANIFEST_URL,))
        except Exception as exc:  # noqa: BLE001 — 检查失败不该影响启动
            logger.warning("update check failed: %s", exc)
            self.checkFailed.emit(str(exc))
            return
        if manifest is None:
            self.checkFailed.emit("manifest 不可达")
            return
        if manifest.announcement is not None:
            self.announcementAvailable.emit(manifest.announcement)
        if manifest.update is None:
            self.upToDate.emit()
        else:
            self.updateAvailable.emit(manifest.update)


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
