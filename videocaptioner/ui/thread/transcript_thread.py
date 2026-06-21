# -*- coding: utf-8 -*-
"""转录线程：提取音频 -> ASR 转录 -> 按输出格式落盘。

基于 WorkerThread：进度回调里有取消检查点，stop() 可在阶段间
协作中止；被取消的运行不发任何结果信号。
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.asr import transcribe
from videocaptioner.core.entities import (
    TranscribeOutputFormatEnum,
    TranscribeTask,
)
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.video_utils import video2audio
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.worker import WorkerThread

logger = setup_logger("transcript_thread")


class TranscriptThread(WorkerThread):
    """finished(task) 转录成功；progress/error 来自基类约定。"""

    finished = pyqtSignal(TranscribeTask)

    def __init__(self, task: TranscribeTask):
        super().__init__()
        self.task = task

    def _work(self):
        self.task.started_at = datetime.datetime.now()
        self._validate_task()
        logger.info("\n%s", self.task.transcribe_config.print_config())

        audio_path = self._extract_audio()
        try:
            self.checkpoint()
            self.progress.emit(20, tr("t_transcript.status.transcribing"))
            logger.info("开始语音转录")
            asr_data = transcribe(
                audio_path,
                self.task.transcribe_config,
                callback=self._progress_callback,
            )
            self.checkpoint()
            self._save_outputs(asr_data)
            self.progress.emit(100, tr("t_transcript.status.done"))
            self.finished.emit(self.task)
        finally:
            Path(audio_path).unlink(missing_ok=True)

    # ----- 阶段 -----

    def _validate_task(self):
        if not self.task.file_path:
            raise ValueError(tr("t_transcript.error.no_file_path"))
        if not Path(self.task.file_path).exists():
            raise ValueError(tr("t_transcript.error.file_not_found"))
        if not self.task.transcribe_config:
            raise ValueError(tr("t_transcript.error.no_config"))
        if not self.task.output_path:
            raise ValueError(tr("t_transcript.error.no_output_path"))

    def _extract_audio(self) -> str:
        self.progress.emit(5, tr("t_transcript.status.extracting_audio"))
        logger.info("开始转换音频")
        # delete=False 避免 Windows 句柄占用，结束后统一清理
        temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_audio.close()
        ok = video2audio(
            str(self.task.file_path),
            output=temp_audio.name,
            audio_track_index=self.task.selected_audio_track_index,
        )
        if not ok:
            Path(temp_audio.name).unlink(missing_ok=True)
            raise RuntimeError(tr("t_transcript.error.audio_extract_failed"))
        return temp_audio.name

    def _save_outputs(self, asr_data):
        """按配置导出目标格式；流水线模式额外保证 SRT 存在。"""
        output_format = self.task.transcribe_config.output_format
        base_path = Path(self.task.output_path).with_suffix("")

        if output_format == TranscribeOutputFormatEnum.ALL:
            formats = {
                fmt.value.lower()
                for fmt in TranscribeOutputFormatEnum
                if fmt != TranscribeOutputFormatEnum.ALL
            }
        else:
            formats = {output_format.value.lower()}
        if self.task.need_next_task:
            formats.add(TranscribeOutputFormatEnum.SRT.value.lower())

        for fmt in sorted(formats):
            save_path = f"{base_path}.{fmt}"
            asr_data.save(save_path)
            logger.info("%s 字幕已保存到: %s", fmt.upper(), save_path)

    def _progress_callback(self, value, message):
        self.checkpoint()
        # ASR 阶段映射到整体进度的 20-100 区间
        self.progress.emit(int(min(20 + value * 0.8, 100)), message)
