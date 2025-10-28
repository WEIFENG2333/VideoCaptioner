import datetime

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.entities import (
    FullProcessTask,
    SubtitleTask,
    SynthesisTask,
    TranscribeTask,
)
from app.core.utils.logger import setup_logger

from .subtitle_thread import SubtitleThread
from .transcript_thread import TranscriptThread
from .video_synthesis_thread import VideoSynthesisThread

logger = setup_logger("subtitle_pipeline_thread")


class SubtitlePipelineThread(QThread):
    """字幕处理全流程线程，包含:
    1. 转录生成字幕
    2. 字幕优化/翻译
    3. 视频合成
    """

    progress = pyqtSignal(int, str)  # 进度值, 进度描述
    finished = pyqtSignal(FullProcessTask)
    error = pyqtSignal(str)

    def __init__(self, task: FullProcessTask):
        super().__init__()
        self.task = task
        self.has_error = False

    def run(self):
        try:

            def handle_error(error_msg):
                logger.error("pipeline 发生错误: %s", error_msg)
                self.has_error = True
                self.error.emit(error_msg)

            # 1. 转录生成字幕
            self.task.started_at = datetime.datetime.now()
            logger.info(f"\n{self.task.transcribe_config.print_config()}")
            logger.info(f"\n{self.task.subtitle_config.print_config()}")
            if self.task.synthesis_config:
                logger.info(f"\n{self.task.synthesis_config.print_config()}")
            self.progress.emit(0, self.tr("开始转录"))

            # 创建转录任务
            transcribe_task = TranscribeTask(
                file_path=self.task.file_path,
                transcribe_config=self.task.transcribe_config,
                need_next_task=True,
                queued_at=self.task.queued_at,
                started_at=self.task.started_at,
                completed_at=self.task.completed_at,
            )
            transcript_thread = TranscriptThread(transcribe_task)
            transcript_thread.progress.connect(
                lambda value, msg: self.progress.emit(int(value * 0.4), msg)
            )
            transcript_thread.error.connect(handle_error)
            transcript_thread.run()

            if self.has_error:
                logger.info("转录过程中发生错误，终止流程")
                return

            # 2. 字幕优化/翻译
            # self.task.status = Task.Status.OPTIMIZING
            self.progress.emit(40, self.tr("开始优化字幕"))

            # 创建字幕任务
            subtitle_task = SubtitleTask(
                subtitle_path=transcribe_task.output_path or "",
                video_path=self.task.file_path,
                output_path=self.task.output_path,
                subtitle_config=self.task.subtitle_config,
                need_next_task=True,
                queued_at=self.task.queued_at,
                started_at=self.task.started_at,
                completed_at=self.task.completed_at,
            )
            optimization_thread = SubtitleThread(subtitle_task)
            optimization_thread.progress.connect(
                lambda value, msg: self.progress.emit(int(40 + value * 0.2), msg)
            )
            optimization_thread.error.connect(handle_error)
            optimization_thread.run()

            if self.has_error:
                logger.info("字幕优化过程中发生错误，终止流程")
                return

            # 3. 视频合成
            # self.task.status = Task.Status.GENERATING
            self.progress.emit(80, self.tr("开始合成视频"))

            # 创建合成任务
            synthesis_task = SynthesisTask(
                video_path=self.task.file_path,
                subtitle_path=subtitle_task.output_path,
                output_path=self.task.output_path,
                synthesis_config=self.task.synthesis_config,
                queued_at=self.task.queued_at,
                started_at=self.task.started_at,
                completed_at=self.task.completed_at,
            )
            synthesis_thread = VideoSynthesisThread(synthesis_task)
            synthesis_thread.progress.connect(
                lambda value, msg: self.progress.emit(int(70 + value * 0.3), msg)
            )
            synthesis_thread.error.connect(handle_error)
            synthesis_thread.run()

            if self.has_error:
                logger.info("视频合成过程中发生错误，终止流程")
                return

            # self.task.status = FullProcessTask.Status.COMPLETED  # type: ignore
            logger.info("处理完成")
            self.progress.emit(100, self.tr("处理完成"))
            self.finished.emit(self.task)

        except Exception as e:
            # self.task.status = FullProcessTask.Status.FAILED  # type: ignore
            logger.exception("处理失败: %s", str(e))
            self.error.emit(str(e))
