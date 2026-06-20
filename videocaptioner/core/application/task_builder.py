"""Build executable task dataclasses from canonical application config.

输出命名与任务目录规则统一在 output_paths 模块，这里只负责把规则
应用到各任务：成品落源文件旁（unique 防覆盖），中间产物进任务目录。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from videocaptioner.config import WORK_PATH
from videocaptioner.core.application import output_paths
from videocaptioner.core.application.app_config import AppConfig
from videocaptioner.core.entities import (
    DubbingTask,
    DubbingUIConfig,
    SubtitleConfig,
    SubtitleRenderModeEnum,
    SubtitleTask,
    SynthesisConfig,
    SynthesisTask,
    TranscribeConfig,
    TranscribeTask,
)
from videocaptioner.core.subtitle.style_manager import (
    SubtitleRenderer,
    load_style,
    normalize_style_id,
)


class TaskBuilder:
    """Create core tasks without depending on UI widgets or CLI argument shapes."""

    def __init__(self, app_config: AppConfig):
        self.config = app_config

    def new_task_dir(self, source: str, task_type: str) -> str:
        """为一次流水线运行创建任务目录（流程所有者负责跨阶段传递与清理）。"""
        return str(output_paths.new_task_dir(self.config.work_dir or WORK_PATH, source, task_type))

    def get_ass_style(self, style_name: Optional[str] = None) -> str:
        style = load_style(style_name or self.config.subtitle.style_name, renderer=SubtitleRenderer.ASS)
        return style.to_ass_string() if style is not None else ""

    def get_rounded_style(self) -> dict:
        style_id = normalize_style_id(
            self.config.synthesis.style_id,
            self.config.synthesis.render_mode.value,
        )
        style = load_style(style_id, renderer=SubtitleRenderer.ROUNDED)
        return style.to_rounded_dict() if style is not None else {}

    def create_transcribe_config(self, *, need_word_timestamp: bool) -> TranscribeConfig:
        settings = self.config.transcribe
        return TranscribeConfig(
            transcribe_model=settings.model,
            transcribe_language=settings.language,
            need_word_time_stamp=need_word_timestamp,
            output_format=settings.output_format,
            whisper_model=settings.whisper_model,
            whisper_api_key=settings.whisper_api_key,
            whisper_api_base=settings.whisper_api_base,
            whisper_api_model=settings.whisper_api_model,
            whisper_api_prompt=settings.whisper_api_prompt,
            fun_asr_api_key=settings.fun_asr_api_key,
            fun_asr_api_base=settings.fun_asr_api_base,
            fun_asr_model=settings.fun_asr_model,
            faster_whisper_program=settings.faster_whisper_program,
            faster_whisper_model=settings.faster_whisper_model,
            faster_whisper_model_dir=settings.faster_whisper_model_dir,
            faster_whisper_device=settings.faster_whisper_device,
            faster_whisper_vad_filter=settings.faster_whisper_vad_filter,
            faster_whisper_vad_threshold=settings.faster_whisper_vad_threshold,
            faster_whisper_vad_method=settings.faster_whisper_vad_method,
            faster_whisper_ff_mdx_kim2=settings.faster_whisper_ff_mdx_kim2,
            faster_whisper_one_word=settings.faster_whisper_one_word,
            faster_whisper_prompt=settings.faster_whisper_prompt,
        )

    def create_transcribe_task(
        self,
        file_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ) -> TranscribeTask:
        need_word_timestamp = self.config.subtitle.need_split if need_next_task else False
        if need_next_task:
            # 流水线中间产物：原始转录进任务目录，路径即语义。
            task_dir = task_dir or self.new_task_dir(file_path, output_paths.TASK_TRANSCRIBE)
            output_path = str(Path(task_dir) / output_paths.TRANSCRIPT_FILE)
        else:
            output_path = str(
                output_paths.unique_path(output_paths.product_path(file_path, ext=".srt"))
            )

        task = TranscribeTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
            task_dir=task_dir,
            transcribe_config=self.create_transcribe_config(
                need_word_timestamp=need_word_timestamp
            ),
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    def create_subtitle_config(self) -> SubtitleConfig:
        llm = self.config.llm
        settings = self.config.subtitle
        return SubtitleConfig(
            base_url=llm.api_base,
            api_key=llm.api_key,
            llm_model=llm.model,
            deeplx_endpoint=settings.deeplx_endpoint,
            translator_service=settings.translator_service,
            need_reflect=settings.need_reflect,
            need_translate=settings.need_translate,
            need_optimize=settings.need_optimize,
            thread_num=settings.thread_num,
            batch_size=settings.batch_size,
            subtitle_layout=settings.layout,
            subtitle_style=self.get_ass_style(settings.style_name),
            max_word_count_cjk=settings.max_word_count_cjk,
            max_word_count_english=settings.max_word_count_english,
            need_split=settings.need_split,
            target_language=settings.target_language,
            custom_prompt_text=settings.custom_prompt_text,
        )

    def subtitle_product_tag(self) -> str:
        """字幕成品 tag：翻译输出目标语言码，否则 optimized。"""
        if self.config.subtitle.need_translate:
            return output_paths.language_tag(self.config.subtitle.target_language)
        return output_paths.TAG_OPTIMIZED

    def create_subtitle_task(
        self,
        file_path: str,
        video_path: Optional[str] = None,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ) -> SubtitleTask:
        if need_next_task:
            # 流水线中间产物：样式字幕进任务目录，供后续合成消费。
            task_dir = task_dir or self.new_task_dir(
                video_path or file_path, output_paths.TASK_TRANSCRIBE)
            output_path = str(Path(task_dir) / output_paths.STYLED_SUBTITLE_FILE)
        else:
            # 成品锚定到媒体文件（有视频时），否则锚定到输入字幕。
            anchor = video_path or file_path
            output_path = str(
                output_paths.unique_path(
                    output_paths.product_path(anchor, self.subtitle_product_tag(), ext=".srt")
                )
            )

        task = SubtitleTask(
            queued_at=datetime.datetime.now(),
            subtitle_path=file_path,
            video_path=video_path,
            output_path=output_path,
            task_dir=task_dir,
            subtitle_config=self.create_subtitle_config(),
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    def create_synthesis_config(self) -> SynthesisConfig:
        settings = self.config.synthesis
        subtitle = self.config.subtitle
        hard_subtitle = not settings.soft_subtitle
        style_id = normalize_style_id(settings.style_id, settings.render_mode.value)
        ass_style = ""
        ass_line_gap = 0
        rounded_style = None
        if hard_subtitle:
            if settings.render_mode == SubtitleRenderModeEnum.ASS_STYLE:
                style = load_style(style_id, renderer=SubtitleRenderer.ASS)
                ass_style = style.to_ass_string() if style is not None else ""
                ass_line_gap = getattr(style.style, "line_gap", 0) if style is not None else 0
            else:
                style = load_style(style_id, renderer=SubtitleRenderer.ROUNDED)
                rounded_style = style.to_rounded_dict() if style is not None else {}
        return SynthesisConfig(
            need_video=settings.need_video,
            soft_subtitle=settings.soft_subtitle,
            render_mode=settings.render_mode,
            video_quality=settings.video_quality,
            subtitle_layout=subtitle.layout,
            ass_style=ass_style,
            ass_line_gap=ass_line_gap,
            rounded_style=rounded_style,
        )

    def create_synthesis_task(
        self,
        video_path: str,
        subtitle_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
        dubbed: bool = False,
    ) -> SynthesisTask:
        tags = (
            (output_paths.TAG_DUBBED, output_paths.TAG_SUBTITLED)
            if dubbed
            else (output_paths.TAG_SUBTITLED,)
        )
        output_path = str(
            output_paths.unique_path(output_paths.product_path(video_path, *tags, ext=".mp4"))
        )
        task = SynthesisTask(
            queued_at=datetime.datetime.now(),
            video_path=video_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            task_dir=task_dir,
            synthesis_config=self.create_synthesis_config(),
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    def create_dubbing_ui_config(self) -> DubbingUIConfig:
        settings = self.config.dubbing
        return DubbingUIConfig(
            enabled=settings.enabled,
            preset=settings.preset,
            provider=settings.provider,
            api_key=settings.api_key,
            api_base=settings.api_base,
            model=settings.model,
            voice=settings.voice,
            text_track=settings.text_track,
            timing=settings.timing,
            audio_mode=settings.audio_mode,
            tts_workers=settings.tts_workers,
            use_cache=self.config.cache_enabled,
            clone_audio_path=settings.clone_audio_path if settings.supports_clone else "",
            clone_audio_text=settings.clone_audio_text if settings.supports_clone else "",
        )

    def create_dubbing_task(
        self,
        video_path: str,
        subtitle_path: str,
        output_video_path: Optional[str] = None,
        output_audio_path: Optional[str] = None,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ) -> DubbingTask:
        anchor = video_path or subtitle_path
        task_dir = task_dir or self.new_task_dir(anchor, output_paths.TASK_DUBBING)
        if output_video_path is None and video_path:
            output_video_path = str(
                output_paths.unique_path(
                    output_paths.product_path(video_path, output_paths.TAG_DUBBED)
                )
            )
        if output_audio_path is None:
            # 配音音频与配音视频共用 dubbed tag，扩展名区分容器。
            output_audio_path = str(
                output_paths.unique_path(
                    output_paths.product_path(anchor, output_paths.TAG_DUBBED, ext=".wav")
                )
            )

        task = DubbingTask(
            queued_at=datetime.datetime.now(),
            video_path=video_path or None,
            subtitle_path=subtitle_path,
            output_audio_path=output_audio_path,
            output_video_path=output_video_path,
            task_dir=task_dir,
            dubbing_config=self.create_dubbing_ui_config(),
        )
        if task_id:
            task.task_id = task_id
        return task
