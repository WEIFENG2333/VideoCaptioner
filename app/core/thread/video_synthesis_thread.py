import datetime
import logging
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

from ..entities import Task
from ..utils.video_utils import add_subtitles
from ..utils.logger import setup_logger
from ...common.config import cfg

logger = setup_logger("video_synthesis_thread")

class VideoSynthesisThread(QThread):
    finished = pyqtSignal(Task)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, task: Task):
        super().__init__()
        self.task = task
        logger.debug(f"初始化 VideoSynthesisThread，任务: {self.task}")

    def run(self):
        try:
            logger.info(f"\n===========视频合成任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")
            self.task.status = Task.Status.GENERATING
            video_file = self.task.file_path
            if Path(self.task.result_subtitle_save_path).is_file():
                # result sub exist (after optimizing)
                subtitle_file = self.task.result_subtitle_save_path
            elif Path(self.task.original_subtitle_save_path).is_file():
                # No optimzing, original sub only
                subtitle_file = self.task.original_subtitle_save_path
            else:
                raise RuntimeError("No subtitle file available.")
            
            video_save_path = self.task.video_save_path
            soft_subtitle = self.task.soft_subtitle
            need_video = cfg.need_video.value

            if not need_video:
                logger.info(f"不需要合成视频，跳过")
                self.progress.emit(100, self.tr("合成完成"))
                self.finished.emit(self.task)
                return
            
            logger.info(f"开始合成视频: {video_file}")
            self.progress.emit(5, self.tr("正在合成"))
            add_subtitles(video_file, subtitle_file, video_save_path, soft_subtitle=soft_subtitle,
                          progress_callback=self.progress_callback)
            self.progress.emit(100, self.tr("合成完成"))
            logger.info(f"视频合成完成，保存路径: {video_save_path}")
            self.finished.emit(self.task)
        except Exception as e:
            logger.exception(f"视频合成失败: {e}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("视频合成失败"))

    def progress_callback(self, value, message):
        progress = int(5 + int(value) / 100 * 95)
        logger.debug(f"合成进度: {progress}% - {message}")
        self.progress.emit(progress, str(progress) + "% " + message)
