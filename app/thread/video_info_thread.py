import os
import re
import subprocess
import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.entities import VideoInfo
from app.core.utils.logger import setup_logger

logger = setup_logger("video_info_thread")


class VideoInfoThread(QThread):
    finished = pyqtSignal(VideoInfo)
    error = pyqtSignal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            # 生成缩略图到临时文件
            temp_dir = tempfile.gettempdir()
            file_name = Path(self.file_path).stem
            thumbnail_path = os.path.join(temp_dir, f"{file_name}_thumbnail.jpg")

            # 获取视频信息
            video_info = self._get_video_info(thumbnail_path)
            self.finished.emit(video_info)

        except Exception as e:
            self.error.emit(str(e))

    def _get_video_info(self, thumbnail_path: str) -> VideoInfo:
        """获取视频信息"""
        try:
            cmd = ["ffmpeg", "-i", self.file_path]
            # logger.info(f"获取视频信息执行命令: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            info = result.stderr

            video_info_dict = {
                "file_name": Path(self.file_path).stem,
                "file_path": self.file_path,
                "duration_seconds": 0,
                "bitrate_kbps": 0,
                "video_codec": "",
                "width": 0,
                "height": 0,
                "fps": 0,
                "audio_codec": "",
                "audio_sampling_rate": 0,
                "thumbnail_path": "",
            }

            # 提取时长
            if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
                hours, minutes, seconds = map(float, duration_match.groups())
                video_info_dict["duration_seconds"] = (
                    hours * 3600 + minutes * 60 + seconds
                )
                logger.info(f"视频时长: {video_info_dict['duration_seconds']}秒")

            # 提取比特率
            if bitrate_match := re.search(r"bitrate: (\d+) kb/s", info):
                video_info_dict["bitrate_kbps"] = int(bitrate_match.group(1))

            # 提取视频流信息
            if video_stream_match := re.search(
                r"Stream #\d+:\d+.*Video: (\w+).*?, (\d+)x(\d+).*?, ([\d.]+) (?:fps|tb)",
                info,
                re.DOTALL,
            ):
                video_info_dict.update(
                    {
                        "video_codec": video_stream_match.group(1),
                        "width": int(video_stream_match.group(2)),
                        "height": int(video_stream_match.group(3)),
                        "fps": float(video_stream_match.group(4)),
                    }
                )

                if thumbnail_path:
                    if self._extract_thumbnail(
                        video_info_dict["duration_seconds"] * 0.3, thumbnail_path
                    ):
                        video_info_dict["thumbnail_path"] = thumbnail_path
            else:
                video_info_dict["thumbnail_path"] = thumbnail_path
                logger.warning("未找到视频流信息")

            # 提取音频流信息
            if audio_stream_match := re.search(
                r"Stream #\d+:\d+.*Audio: (\w+).* (\d+) Hz", info
            ):
                video_info_dict.update(
                    {
                        "audio_codec": audio_stream_match.group(1),
                        "audio_sampling_rate": int(audio_stream_match.group(2)),
                    }
                )

            return VideoInfo(**video_info_dict)
        except Exception as e:
            logger.exception(f"获取视频信息时出错: {str(e)}")
            raise

    def _extract_thumbnail(self, seek_time: float, thumbnail_path: str) -> bool:
        """提取视频缩略图"""
        if not Path(self.file_path).is_file():
            logger.error(f"视频文件不存在: {self.file_path}")
            return False

        try:
            timestamp = f"{int(seek_time // 3600):02}:{int((seek_time % 3600) // 60):02}:{seek_time % 60:06.3f}"
            # 确保输出目录存在
            Path(thumbnail_path).parent.mkdir(parents=True, exist_ok=True)

            # 转换路径为合适的格式
            video_path = Path(self.file_path).as_posix()
            thumbnail_path = Path(thumbnail_path).as_posix()

            cmd = [
                "ffmpeg",
                "-ss",
                timestamp,
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                thumbnail_path,
            ]
            # logger.info(f"提取缩略图执行命令: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0

        except Exception as e:
            logger.exception(f"提取缩略图时出错: {str(e)}")
            return False
