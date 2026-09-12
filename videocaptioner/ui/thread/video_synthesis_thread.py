# -*- coding: utf-8 -*-
"""视频合成线程：把字幕以软/硬方式合成进视频。

基于 WorkerThread：ffmpeg 进度回调里有取消检查点，stop() 协作中止。
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.entities import SynthesisTask
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.video_utils import add_subtitles, add_subtitles_with_style
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.worker import WorkerThread

logger = setup_logger("video_synthesis_thread")


class VideoSynthesisThread(WorkerThread):
    finished = pyqtSignal(SynthesisTask)

    def __init__(self, task: SynthesisTask):
        super().__init__()
        self.task = task

    def _work(self):
        self.task.started_at = datetime.datetime.now()
        config = self.task.synthesis_config
        logger.info("\n%s", config.print_config())

        if not config.need_video:
            self.progress.emit(100, tr("t_synth.status.done"))
            self.finished.emit(self.task)
            return

        if not self.task.video_path:
            raise ValueError(tr("t_synth.error.no_video_path"))
        if not self.task.subtitle_path:
            raise ValueError(tr("t_synth.error.no_subtitle_path"))
        if not self.task.output_path:
            raise ValueError(tr("t_synth.error.no_output_path"))

        self.progress.emit(5, tr("t_synth.status.synthesizing"))
        logger.info("开始合成视频: %s", self.task.video_path)
        asr_data = ASRData.from_subtitle_file(self.task.subtitle_path)
        self.checkpoint()

        crf = config.video_quality.get_crf()
        preset = config.video_quality.get_preset()

        # 字幕文件的行序即布局；按文件行序原样烧录，不二次翻转已排版的双语文件。
        render_layout = asr_data.resolve_layout_from_file(config.subtitle_layout)

        if config.soft_subtitle:
            self._synthesize_soft(asr_data, render_layout, crf, preset)
        else:
            add_subtitles_with_style(
                video_path=self.task.video_path,
                asr_data=asr_data,
                output_path=self.task.output_path,
                render_mode=config.render_mode,
                subtitle_layout=render_layout,
                ass_style=config.ass_style,
                rounded_style=config.rounded_style,
                ass_line_gap=config.ass_line_gap,
                crf=crf,
                preset=preset,
                progress_callback=self._progress_callback,
            )

        self.progress.emit(100, tr("t_synth.status.done"))
        logger.info("视频合成完成，保存路径: %s", self.task.output_path)
        self.finished.emit(self.task)

    def _synthesize_soft(self, asr_data, layout, crf: int, preset: str):
        """软字幕：转为 SRT 临时文件后内嵌字幕轨。"""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".srt",
            delete=False,
            encoding="utf-8",
            prefix="VideoCaptioner_soft_",
        ) as handle:
            handle.write(asr_data.to_srt(layout=layout))
            temp_srt = handle.name
        try:
            add_subtitles(
                self.task.video_path,
                temp_srt,
                self.task.output_path,
                crf=crf,
                preset=preset,
                soft_subtitle=True,
                progress_callback=self._progress_callback,
            )
        finally:
            Path(temp_srt).unlink(missing_ok=True)

    def _progress_callback(self, value, message):
        self.checkpoint()
        progress = int(5 + int(value) / 100 * 95)
        self.progress.emit(progress, f"{progress}% {message}")
