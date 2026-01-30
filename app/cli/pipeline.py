"""Synchronous Processing Pipeline for CLI

This module provides synchronous wrappers around the core processing modules,
suitable for CLI usage without PyQt5 dependencies.
"""

import sys
from pathlib import Path
from typing import Callable, Optional

from app.core.asr import transcribe
from app.core.asr.asr_data import ASRData
from app.core.entities import (
    SubtitleConfig,
    TranscribeConfig,
    TranscribeModelEnum,
    TranslatorServiceEnum,
)
from app.core.split.split import SubtitleSplitter
from app.core.translate.factory import TranslatorFactory
from app.core.translate.types import TargetLanguage, TranslatorType
from app.core.utils.logger import setup_logger

logger = setup_logger("cli_pipeline")


class ProgressReporter:
    """Progress reporter for CLI output with rich library support."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.current_stage = ""
        self._rich_available = False
        self._progress = None
        self._task_id = None

        # Try to import rich
        if not quiet:
            try:
                from rich.console import Console
                from rich.progress import (
                    BarColumn,
                    Progress,
                    SpinnerColumn,
                    TaskProgressColumn,
                    TextColumn,
                    TimeElapsedColumn,
                )

                self._rich_available = True
                self.console = Console()
                self._Progress = Progress
                self._SpinnerColumn = SpinnerColumn
                self._TextColumn = TextColumn
                self._BarColumn = BarColumn
                self._TaskProgressColumn = TaskProgressColumn
                self._TimeElapsedColumn = TimeElapsedColumn
            except ImportError:
                self._rich_available = False

    def print(self, message: str, style: str = ""):
        """Print message to console."""
        if self.quiet:
            return
        if self._rich_available and style:
            self.console.print(message, style=style)
        else:
            print(message)

    def start_stage(self, stage: str, total: int = 100):
        """Start a new processing stage with progress bar."""
        self.current_stage = stage
        if self.quiet:
            return

        if self._rich_available:
            self._progress = self._Progress(
                self._SpinnerColumn(),
                self._TextColumn("[bold blue]{task.description}"),
                self._BarColumn(),
                self._TaskProgressColumn(),
                self._TimeElapsedColumn(),
                console=self.console,
                transient=True,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(stage, total=total)
        else:
            print(f"\n[{stage}]")

    def update(self, progress: int = 0, message: str = "", advance: int = 0):
        """Update progress."""
        if self.quiet:
            return

        if self._rich_available and self._progress and self._task_id is not None:
            if advance > 0:
                self._progress.update(self._task_id, advance=advance)
            elif progress > 0:
                self._progress.update(self._task_id, completed=progress)
            if message:
                self._progress.update(self._task_id, description=f"{self.current_stage}: {message}")
        else:
            if message:
                print(f"  {message}")
            elif progress > 0:
                print(f"  {progress}%", end="\r")
                sys.stdout.flush()

    def finish_stage(self, message: str = "Done"):
        """Finish current stage."""
        if self.quiet:
            return

        if self._rich_available and self._progress:
            self._progress.stop()
            self._progress = None
            self._task_id = None
            self.console.print(f"  [green]✓[/green] {self.current_stage}: {message}")
        else:
            print(f"  ✓ {message}")

    def error(self, message: str):
        """Report error."""
        if self._rich_available:
            self.console.print(f"  [red]✗ Error:[/red] {message}")
        else:
            print(f"  ✗ Error: {message}", file=sys.stderr)


class CLIPipeline:
    """Synchronous processing pipeline for CLI.

    Provides methods for:
    - Speech recognition (transcribe)
    - Subtitle splitting
    - Subtitle optimization
    - Translation
    """

    def __init__(self, quiet: bool = False):
        """Initialize pipeline.

        Args:
            quiet: Suppress progress output
        """
        self.progress = ProgressReporter(quiet=quiet)

    def transcribe(
        self,
        audio_path: str,
        config: TranscribeConfig,
    ) -> ASRData:
        """Run speech recognition.

        Args:
            audio_path: Path to audio/video file
            config: Transcription configuration

        Returns:
            ASRData with transcription results
        """
        self.progress.start_stage("Transcribing", total=100)

        def callback(progress: int, message: str):
            self.progress.update(progress=progress, message=message)

        try:
            result = transcribe(audio_path, config, callback=callback)
            self.progress.finish_stage(f"{len(result.segments)} segments")
            return result
        except Exception as e:
            self.progress.error(str(e))
            raise

    def split_subtitle(
        self,
        asr_data: ASRData,
        config: SubtitleConfig,
    ) -> ASRData:
        """Split subtitle segments.

        Args:
            asr_data: Input ASR data
            config: Subtitle configuration

        Returns:
            ASRData with split segments
        """
        if not config.need_split:
            return asr_data

        self.progress.start_stage("Splitting", total=100)

        try:
            splitter = SubtitleSplitter(
                thread_num=config.thread_num,
                model=config.llm_model or "gpt-4o-mini",
                max_word_count_cjk=config.max_word_count_cjk,
                max_word_count_english=config.max_word_count_english,
            )

            # The actual method is split_subtitle
            result = splitter.split_subtitle(asr_data)
            self.progress.finish_stage(f"{len(result.segments)} segments")
            return result
        except Exception as e:
            self.progress.error(str(e))
            raise

    def translate_subtitle(
        self,
        asr_data: ASRData,
        config: SubtitleConfig,
    ) -> ASRData:
        """Translate subtitle text.

        Args:
            asr_data: Input ASR data
            config: Subtitle configuration

        Returns:
            ASRData with translated text
        """
        if not config.need_translate or config.target_language is None:
            return asr_data

        # Map service enum to translator type
        service_map = {
            TranslatorServiceEnum.OPENAI: TranslatorType.OPENAI,
            TranslatorServiceEnum.GOOGLE: TranslatorType.GOOGLE,
            TranslatorServiceEnum.BING: TranslatorType.BING,
            TranslatorServiceEnum.DEEPLX: TranslatorType.DEEPLX,
        }

        translator_type = service_map.get(
            config.translator_service or TranslatorServiceEnum.OPENAI,
            TranslatorType.OPENAI
        )

        total = len(asr_data.segments)
        self.progress.start_stage("Translating", total=total)

        completed = 0

        def callback(count: int):
            nonlocal completed
            completed += count
            self.progress.update(advance=count)

        try:
            translator = TranslatorFactory.create_translator(
                translator_type=translator_type,
                thread_num=config.thread_num,
                batch_num=config.batch_size,
                target_language=config.target_language,
                model=config.llm_model or "gpt-4o-mini",
                custom_prompt=config.custom_prompt_text or "",
                is_reflect=config.need_reflect,
                update_callback=callback,
            )

            result = translator.translate(asr_data)
            self.progress.finish_stage(f"{len(result.segments)} segments")
            return result
        except Exception as e:
            self.progress.error(str(e))
            raise

    def save_subtitle(
        self,
        asr_data: ASRData,
        output_path: str,
        format: str = "srt",
    ) -> str:
        """Save subtitle to file.

        Args:
            asr_data: ASR data to save
            output_path: Output file path (with or without extension)
            format: Output format (srt, ass, txt, json)

        Returns:
            Path to saved file
        """
        output_path = Path(output_path)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        format_lower = format.lower()

        # Handle extension
        if output_path.suffix.lower() in [".srt", ".ass", ".txt", ".json"]:
            file_path = output_path
            format_lower = output_path.suffix[1:].lower()
        else:
            file_path = output_path.with_suffix(f".{format_lower}")

        # Use ASRData's save method
        if format_lower in ["srt", "ass", "txt", "json"]:
            asr_data.save(str(file_path))
            return str(file_path)
        else:
            # Fallback to SRT for unsupported formats
            file_path = output_path.with_suffix(".srt")
            asr_data.save(str(file_path))
            return str(file_path)

    def process_full(
        self,
        input_path: str,
        output_dir: Optional[str],
        transcribe_config: TranscribeConfig,
        subtitle_config: SubtitleConfig,
        output_format: str = "srt",
    ) -> dict:
        """Run full processing pipeline.

        Args:
            input_path: Input audio/video file
            output_dir: Output directory (None = same as input)
            transcribe_config: Transcription settings
            subtitle_config: Subtitle processing settings
            output_format: Output subtitle format

        Returns:
            Dict with output file paths
        """
        input_path = Path(input_path)

        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = input_path.parent

        out_dir.mkdir(parents=True, exist_ok=True)
        base_name = input_path.stem

        # Step 1: Transcribe
        asr_data = self.transcribe(str(input_path), transcribe_config)

        # Step 2: Split (if enabled)
        if subtitle_config.need_split:
            asr_data = self.split_subtitle(asr_data, subtitle_config)

        # Step 3: Translate (if enabled)
        if subtitle_config.need_translate:
            asr_data = self.translate_subtitle(asr_data, subtitle_config)

        # Step 4: Save
        output_file = out_dir / f"{base_name}.{output_format}"
        subtitle_path = self.save_subtitle(asr_data, str(output_file), output_format)

        return {
            "subtitle": subtitle_path,
            "segments": len(asr_data.segments),
        }


def create_transcribe_config(
    model: TranscribeModelEnum = TranscribeModelEnum.WHISPER_API,
    language: str = "",
    word_timestamps: bool = True,
    whisper_api_key: str = "",
    whisper_api_base: str = "",
    whisper_api_model: str = "whisper-1",
    whisper_prompt: str = "",
) -> TranscribeConfig:
    """Create transcription configuration.

    Args:
        model: Transcription model to use
        language: Source language (empty for auto-detect)
        word_timestamps: Enable word-level timestamps
        whisper_api_key: Whisper API key
        whisper_api_base: Whisper API base URL
        whisper_api_model: Whisper API model name
        whisper_prompt: Prompt for Whisper

    Returns:
        TranscribeConfig instance
    """
    return TranscribeConfig(
        transcribe_model=model,
        transcribe_language=language,
        need_word_time_stamp=word_timestamps,
        whisper_api_key=whisper_api_key,
        whisper_api_base=whisper_api_base,
        whisper_api_model=whisper_api_model,
        whisper_api_prompt=whisper_prompt,
    )


def create_subtitle_config(
    need_split: bool = True,
    need_translate: bool = False,
    target_language: Optional[TargetLanguage] = None,
    translator_service: TranslatorServiceEnum = TranslatorServiceEnum.OPENAI,
    need_reflect: bool = False,
    llm_model: str = "gpt-4o-mini",
    api_key: str = "",
    base_url: str = "",
    thread_num: int = 10,
    batch_size: int = 10,
    max_word_count_cjk: int = 12,
    max_word_count_english: int = 18,
    custom_prompt: str = "",
) -> SubtitleConfig:
    """Create subtitle processing configuration.

    Args:
        need_split: Enable subtitle splitting
        need_translate: Enable translation
        target_language: Translation target language
        translator_service: Translation service to use
        need_reflect: Enable reflection for translation
        llm_model: LLM model name
        api_key: API key for LLM
        base_url: API base URL
        thread_num: Number of concurrent threads
        batch_size: Batch size for processing
        max_word_count_cjk: Max words per line for CJK
        max_word_count_english: Max words per line for English
        custom_prompt: Custom prompt for optimization

    Returns:
        SubtitleConfig instance
    """
    return SubtitleConfig(
        need_split=need_split,
        need_optimize=False,  # Optimization requires LLM
        need_translate=need_translate,
        target_language=target_language,
        translator_service=translator_service,
        need_reflect=need_reflect,
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        thread_num=thread_num,
        batch_size=batch_size,
        max_word_count_cjk=max_word_count_cjk,
        max_word_count_english=max_word_count_english,
        custom_prompt_text=custom_prompt,
    )
