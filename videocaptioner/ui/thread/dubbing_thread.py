# -*- coding: utf-8 -*-
"""配音线程：按字幕生成配音音轨（可选合入视频）。

基于 WorkerThread：管线进度回调里有取消检查点，stop() 协作中止。
中间产物（拟合分段、report.json）写进任务目录的 dubbing/ 子目录，
由流程所有者（控制器/JobRunner）在收尾时统一清理。
"""

from __future__ import annotations

import datetime
from pathlib import Path

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.application import output_paths
from videocaptioner.core.dubbing import DubbingPipeline, SpeakerProfile, build_dubbing_config
from videocaptioner.core.entities import DubbingTask
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.worker import WorkerThread

logger = setup_logger("dubbing_thread")


class DubbingThread(WorkerThread):
    finished = pyqtSignal(DubbingTask)

    def __init__(self, task: DubbingTask):
        super().__init__()
        self.task = task

    def _work(self):
        self.task.started_at = datetime.datetime.now()
        config = self.task.dubbing_config
        if config is None:
            raise ValueError(tr("t_dubbing.error.config_empty"))
        if not self.task.subtitle_path:
            raise ValueError(tr("t_dubbing.error.subtitle_path_empty"))
        if not self.task.output_audio_path:
            raise ValueError(tr("t_dubbing.error.output_audio_path_empty"))
        if not self.task.task_dir:
            raise ValueError(tr("t_dubbing.error.task_dir_empty"))

        logger.info("\n%s", config.print_config())
        self.progress.emit(2, tr("t_dubbing.status.preparing"))

        speaker_profiles = {
            name: SpeakerProfile(name=name, voice=voice)
            for name, voice in config.speaker_voices.items()
            if voice
        }
        if config.clone_audio_path:
            speaker_profiles["default"] = SpeakerProfile(
                name="default",
                clone_audio_path=config.clone_audio_path,
                clone_audio_text=config.clone_audio_text,
            )

        core_config = build_dubbing_config(
            provider=config.provider,
            preset=config.preset,
            api_key=config.api_key,
            api_base=config.api_base,
            model=config.model,
            voice=config.voice,
            timing=config.timing,
            audio_mode=config.audio_mode,
            tts_workers=config.tts_workers,
            use_cache=config.use_cache,
            speaker_profiles=speaker_profiles,
        )

        self.checkpoint()

        result = DubbingPipeline(core_config).run(
            self.task.subtitle_path,
            self.task.output_audio_path,
            work_dir=str(Path(self.task.task_dir) / output_paths.DUBBING_DIR),
            video_path=self.task.video_path or None,
            output_video_path=self.task.output_video_path or None,
            text_track=config.text_track,
            callback=self._progress_callback,
        )

        self.task.output_audio_path = str(result.audio_path)
        self.task.output_video_path = (
            str(result.video_path) if result.video_path else None
        )
        self.task.completed_at = datetime.datetime.now()
        self.progress.emit(100, tr("t_dubbing.status.done"))
        self.finished.emit(self.task)

    def _progress_callback(self, value: int, message: str):
        self.checkpoint()
        self.progress.emit(value, message)
