# -*- coding: utf-8 -*-
"""在线视频下载线程：core/download/media.py 引擎的 Qt 信号薄壳。

下载逻辑（站点回退、浏览器登录态兜底、字幕 sidecar）全部在引擎里，
与 CLI download 共用；这里只做信号映射与协作取消（checkpoint 在
yt-dlp 数据块边界被引擎回调，取消请求让下载干净退出）。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.application import output_paths
from videocaptioner.core.download.media import MediaDownloader
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.worker import WorkerThread


class MediaDownloadThread(WorkerThread):
    """下载在线视频（含可用字幕）到 work_dir/downloads/。

    finished(video_path, subtitle_path_or_None)
    stats(speed_text, eta_text)  下载中实时速度与剩余时间
    """

    finished = pyqtSignal(str, object)
    stats = pyqtSignal(str, str)
    media = pyqtSignal(dict)  # 解析出的元数据：title/uploader/duration/site
    probed = pyqtSignal(dict)  # probe 模式的完整解析结果（含清晰度档位）

    def __init__(
        self,
        url: str,
        work_dir: str,
        *,
        probe_only: bool = False,
        max_height: Optional[int] = None,
    ):
        super().__init__()
        self.url = url
        self.work_dir = work_dir
        self.probe_only = probe_only
        self.max_height = max_height

    def _work(self):
        downloader = MediaDownloader(
            self.url,
            None if self.probe_only else str(output_paths.downloads_dir(self.work_dir)),
            probe_only=self.probe_only,
            max_height=self.max_height,
            on_progress=self.progress.emit,
            on_stats=self.stats.emit,
            on_media=self.media.emit,
            on_probed=self.probed.emit,
            cancel_check=self.checkpoint,
        )
        video_path, subtitle_path = downloader.run()
        if self.probe_only:
            return
        if not video_path:
            raise RuntimeError(tr("t_media.error.no_video_file"))
        self.progress.emit(100, tr("t_media.status.completed"))
        self.finished.emit(video_path, subtitle_path)
