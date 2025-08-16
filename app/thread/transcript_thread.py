import datetime
import os
import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.config import CACHE_PATH
from app.core.bk_asr import transcribe
from app.core.entities import TranscribeModelEnum, TranscribeTask
from app.core.storage.cache_manager import ServiceUsageManager
from app.core.storage.database import DatabaseManager
from app.core.utils.logger import setup_logger
from app.core.utils.video_utils import video2audio

logger = setup_logger("transcript_thread")


class TranscriptThread(QThread):
    finished = pyqtSignal(TranscribeTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    MAX_DAILY_ASR_CALLS = 40

    def __init__(self, task: TranscribeTask):
        super().__init__()
        self.task = task
        # 初始化服务管理器
        db_manager = DatabaseManager(str(CACHE_PATH))
        self.service_manager = ServiceUsageManager(db_manager)

    def run(self):
        temp_file = None
        try:
            logger.info("\n===========转录任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")

            # 检查是否已经存在字幕文件
            # if Path(self.task.output_path).exists():
            #     logger.info("字幕文件已存在，跳过转录")
            #     self.progress.emit(100, self.tr("字幕已存在"))
            #     self.finished.emit(self.task)
            #     return

            # 检查视频文件是否存在
            if not self.task.file_path:
                raise ValueError(self.tr("文件路径为空"))
            video_path = Path(self.task.file_path)
            if not video_path.exists():
                logger.error(f"视频文件不存在：{video_path}")
                raise ValueError(self.tr("视频文件不存在"))

            # 对于BIJIAN和JIANYING模型，检查服务使用限制
            if self.task.transcribe_config.transcribe_model in [
                TranscribeModelEnum.BIJIAN,
                TranscribeModelEnum.JIANYING,
            ]:
                if not self.service_manager.check_service_available(
                    "asr", self.MAX_DAILY_ASR_CALLS
                ):
                    raise Exception(
                        self.tr("公益ASR服务已达到每日使用限制，建议使用本地转录")
                    )

            # 检查是否存在下载的字幕文件（对于视频url的任务，前面可能已下载字幕文件）
            if self.task.need_next_task and self.task.file_path:
                subtitle_dir = Path(self.task.file_path).parent / "subtitle"
                downloaded_subtitles = (
                    list(subtitle_dir.glob("【下载字幕】*"))
                    if subtitle_dir.exists()
                    else []
                )
                if downloaded_subtitles:
                    subtitle_file = downloaded_subtitles[0]
                    self.task.output_path = str(
                        subtitle_file
                    )  # 设置task输出路径为下载的字幕文件
                    logger.info(
                        f"字幕文件已下载，跳过转录。找到下载的字幕文件：{subtitle_file}"
                    )
                    self.progress.emit(100, self.tr("字幕已下载"))
                    self.finished.emit(self.task)
                    return

            self.progress.emit(5, self.tr("转换音频中"))
            logger.info("开始转换音频")

            # 转换音频文件
            temp_dir = tempfile.gettempdir()
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".wav", dir=temp_dir, delete=False
            )
            temp_file.close()
            is_success = video2audio(str(video_path), output=temp_file.name)
            if not is_success:
                logger.error("音频转换失败")
                raise RuntimeError(self.tr("音频转换失败"))

            self.progress.emit(20, self.tr("语音转录中"))
            logger.info("开始语音转录")

            # 进行转录，并回调进度。 （传入 transcribe_config）
            if not self.task.transcribe_config:
                raise ValueError(self.tr("转录配置为空"))
            asr_data = transcribe(
                temp_file.name,
                self.task.transcribe_config,
                callback=self.progress_callback,
            )

            # 如果是BIJIAN或JIANYING模型，增加使用次数
            if self.task.transcribe_config.transcribe_model in [
                TranscribeModelEnum.BIJIAN,
                TranscribeModelEnum.JIANYING,
            ]:
                self.service_manager.increment_usage("asr", self.MAX_DAILY_ASR_CALLS)

            # 保存字幕文件
            if not self.task.output_path:
                raise ValueError(self.tr("输出路径为空"))
            output_path = Path(self.task.output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            asr_data.to_srt(save_path=str(output_path))
            logger.info("字幕文件已保存到: %s", str(output_path))

            self.progress.emit(100, self.tr("转录完成"))
            self.finished.emit(self.task)
        except Exception as e:
            logger.exception("转录过程中发生错误: %s", str(e))
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("转录失败"))
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

    def progress_callback(self, value, message):
        progress = min(20 + (value * 0.8), 100)
        self.progress.emit(int(progress), message)
