import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.entities import VideoInfo
from app.core.utils.logger import setup_logger
from app.core.utils.video_utils import get_video_info

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
            thumbnail_path = f"{temp_dir}/{file_name}_thumbnail.jpg"

            # 使用统一的 get_video_info 函数
            video_info = get_video_info(self.file_path, thumbnail_path=thumbnail_path)

            if video_info:
                self.finished.emit(video_info)
            else:
                self.error.emit("无法获取媒体文件信息，请确保文件格式正确")

        except Exception as e:
            logger.exception("获取视频信息时出错")
            self.error.emit(str(e))
