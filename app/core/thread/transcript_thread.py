import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from ..bk_asr import JianYingASR, KuaiShouASR, BcutASR, WhisperASR, WhisperAPI
from ..entities import Task, TranscribeModelEnum
from ..utils.video_utils import video2audio
from ..utils.logger import setup_logger

logger = setup_logger("transcript_thread")

class TranscriptThread(QThread):
    finished = pyqtSignal(Task)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    ASR_MODELS = {
        TranscribeModelEnum.JIANYING: JianYingASR,
        # TranscribeModelEnum.KUAISHOU: KuaiShouASR,
        TranscribeModelEnum.BIJIAN: BcutASR,
        TranscribeModelEnum.WHISPER: WhisperASR,
        TranscribeModelEnum.WHISPER_API: WhisperAPI,
    }

    def __init__(self, task: Task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            logger.info(f"\n===========转录任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")
            # 检查是否已经存在字幕文件
            if Path(self.task.original_subtitle_save_path).exists():
                logger.info("字幕文件已存在，跳过转录")
                self.progress.emit(100, self.tr("字幕已存在"))
                self.finished.emit(self.task)
                return

            video_path = Path(self.task.file_path)
            if not video_path:
                logger.error("视频路径不能为空")
                raise ValueError(self.tr("视频路径不能为空"))

            self.progress.emit(5, self.tr("转换音频中"))
            logger.info("开始转换音频")

            # 转换为音频(如果音频不存在则转换)
            audio_save_path = Path(self.task.audio_save_path)
            if not audio_save_path.exists():
                is_success = video2audio(str(video_path), output=str(audio_save_path))
                if not is_success:
                    logger.error("音频转换失败")
                    raise ValueError(self.tr("音频转换失败"))

            self.progress.emit(30, self.tr("语音转录中"))
            logger.info("开始语音转录")

            # 获取ASR模型
            asr_class = self.ASR_MODELS.get(self.task.transcribe_model)
            if not asr_class:
                logger.error("无效的转录模型: %s", str(self.task.transcribe_model))
                raise ValueError(self.tr("无效的转录模型: ") + str(self.task.transcribe_model))  # 检查转录模型是否有效

            # 执行转录
            args = {
                "use_cache": self.task.use_asr_cache,
                "need_word_time_stamp": self.task.need_word_time_stamp,
            }
            if self.task.transcribe_model == TranscribeModelEnum.WHISPER:
                args["language"] = self.task.transcribe_language
                args["whisper_model"] = self.task.whisper_model
                args["use_cache"] = False
                self.asr = WhisperASR(self.task.audio_save_path, **args)
            elif self.task.transcribe_model == TranscribeModelEnum.WHISPER_API:
                args["language"] = self.task.transcribe_language
                args["whisper_model"] = self.task.whisper_api_model
                args["api_key"] = self.task.whisper_api_key
                args["base_url"] = self.task.whisper_api_base
                args["prompt"] = self.task.whisper_api_prompt
                args["use_cache"] = False
                # args["need_word_time_stamp"] = True
                self.asr = WhisperAPI(self.task.audio_save_path, **args)
            elif self.task.transcribe_model == TranscribeModelEnum.BIJIAN:
                self.asr = BcutASR(self.task.audio_save_path, **args)
            elif self.task.transcribe_model == TranscribeModelEnum.JIANYING:
                self.asr = JianYingASR(self.task.audio_save_path, **args)
            else:
                raise ValueError(self.tr("无效的转录模型: ") + str(self.task.transcribe_model))
            
            asr_data = self.asr.run(callback=self.progress_callback)

            # 保存字幕文件
            original_subtitle_path = Path(self.task.original_subtitle_save_path)
            original_subtitle_path.parent.mkdir(parents=True, exist_ok=True)
            asr_data.to_srt(save_path=str(original_subtitle_path))
            logger.info("字幕文件已保存到: %s", str(original_subtitle_path))

            # 删除音频文件 和 封面
            audio_save_path.unlink()
            thumbnail_path = Path(self.task.video_info.thumbnail_path)
            if thumbnail_path.exists():
                thumbnail_path.unlink()

            self.progress.emit(100, self.tr("转录完成"))
            self.finished.emit(self.task)
        except Exception as e:
            logger.exception("转录过程中发生错误: %s", str(e))
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("转录失败"))

    def progress_callback(self, value, message):
        progress = min(30 + (value // 100) * 70, 100)
        self.progress.emit(progress, message)
    
    def stop(self):
        if hasattr(self, 'asr'):
            if hasattr(self.asr, 'stop'):
                self.asr.stop()
        self.terminate()
