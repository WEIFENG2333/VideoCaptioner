# -*- coding: utf-8 -*-
"""媒体信息线程：ffmpeg 探测媒体信息并生成缩略图。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.entities import AudioStreamInfo, VideoInfo
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.media_info import extract_thumbnail, probe_media
from videocaptioner.ui.thread.worker import WorkerThread

logger = setup_logger("video_info_thread")


class VideoInfoThread(WorkerThread):
    finished = pyqtSignal(VideoInfo)

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def _work(self):
        info = probe_media(self.file_path)
        self.checkpoint()
        if info is None:
            import shutil

            if shutil.which("ffmpeg") is None:
                raise ValueError("FFmpeg 不可用，无法读取媒体信息，请先安装 FFmpeg")
            raise ValueError("无法获取媒体文件信息，请确保文件格式正确")

        thumbnail_path = ""
        if info.has_video and info.duration_seconds > 0:
            candidate = (
                Path(tempfile.gettempdir()) / f"{Path(self.file_path).stem}_thumbnail.jpg"
            )
            if extract_thumbnail(self.file_path, str(candidate), info.duration_seconds * 0.3):
                thumbnail_path = str(candidate)
        self.checkpoint()

        self.finished.emit(
            VideoInfo(
                file_name=Path(self.file_path).stem,
                file_path=self.file_path,
                width=info.width,
                height=info.height,
                fps=info.fps,
                duration_seconds=info.duration_seconds,
                bitrate_kbps=info.bitrate_kbps,
                video_codec=info.video_codec,
                audio_codec=info.audio_codec,
                audio_sampling_rate=info.audio_sampling_rate,
                thumbnail_path=thumbnail_path,
                audio_streams=[
                    AudioStreamInfo(index=s.index, codec=s.codec, language=s.language)
                    for s in info.audio_streams
                ],
            )
        )
