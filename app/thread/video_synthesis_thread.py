import datetime
import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.asr.asr_data import ASRData
from app.core.entities import SynthesisTask
from app.core.utils.logger import setup_logger
from app.core.utils.video_utils import add_subtitles, add_subtitles_with_style

logger = setup_logger("video_synthesis_thread")


class VideoSynthesisThread(QThread):
    finished = pyqtSignal(SynthesisTask)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, task: SynthesisTask):
        super().__init__()
        self.task = task
        logger.debug(f"初始化 VideoSynthesisThread，任务: {self.task}")

    def run(self):
        try:
            self.task.started_at = datetime.datetime.now()
            config = self.task.synthesis_config
            logger.info(f"\n{config.print_config()}")

            video_file = self.task.video_path
            subtitle_file = self.task.subtitle_path
            output_path = self.task.output_path

            if not config.need_video:
                logger.info("不需要合成视频，跳过")
                self.progress.emit(100, self.tr("合成完成"))
                self.finished.emit(self.task)
                return

            logger.info(f"开始合成视频: {video_file}")
            self.progress.emit(5, self.tr("正在合成"))

            if not video_file:
                raise ValueError(self.tr("视频路径为空"))
            if not subtitle_file:
                raise ValueError(self.tr("字幕路径为空"))
            if not output_path:
                raise ValueError(self.tr("输出路径为空"))

            video_quality = config.video_quality
            crf = video_quality.get_crf()
            preset = video_quality.get_preset()

            # 读取字幕数据
            asr_data = ASRData.from_subtitle_file(subtitle_file)

            if config.soft_subtitle:
                # 软字幕：转为 SRT 后内嵌
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".srt",
                    delete=False,
                    encoding="utf-8",
                    prefix="VideoCaptioner_soft_",
                ) as f:
                    srt_content = asr_data.to_srt(layout=config.subtitle_layout)
                    f.write(srt_content)
                    temp_srt_path = f.name

                try:
                    add_subtitles(
                        video_file,
                        temp_srt_path,
                        output_path,
                        crf=crf,
                        preset=preset,
                        soft_subtitle=True,
                        progress_callback=self.progress_callback,
                    )
                finally:
                    Path(temp_srt_path).unlink(missing_ok=True)

            else:
                # 硬字幕：使用样式配置渲染
                add_subtitles_with_style(
                    video_path=video_file,
                    asr_data=asr_data,
                    output_path=output_path,
                    render_mode=config.render_mode,
                    subtitle_layout=config.subtitle_layout,
                    ass_style=config.ass_style,
                    rounded_style=config.rounded_style,
                    crf=crf,
                    preset=preset,
                    progress_callback=self.progress_callback,
                )

            self.progress.emit(100, self.tr("合成完成"))
            logger.info(f"视频合成完成，保存路径: {output_path}")
            self.finished.emit(self.task)

        except Exception as e:
            logger.exception(f"视频合成失败: {e}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("视频合成失败"))

    def progress_callback(self, value, message):
        progress = int(5 + int(value) / 100 * 95)
        logger.debug(f"合成进度: {progress}% - {message}")
        self.progress.emit(progress, str(progress) + "% " + message)
