"""transcribe command — convert audio/video to subtitles via ASR."""

import os
from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.validators import validate_transcribe
from videocaptioner.core.application.config_store import get


def run(args: Namespace, config: dict) -> int:
    from videocaptioner.cli.validators import validate_media_input

    input_path = Path(args.input)
    if not input_path.exists():
        output.error(f"Input file not found: {input_path}")
        return EXIT.FILE_NOT_FOUND

    err = validate_media_input(input_path)
    if err is not None:
        return err

    if not validate_transcribe(config):
        return EXIT.USAGE_ERROR

    # Determine output path
    out_fmt = get(config, "output.format", "srt")
    if args.output:
        out = Path(args.output)
        # If output is a directory, auto-generate filename inside it
        if out.is_dir() or str(args.output).endswith("/"):
            out.mkdir(parents=True, exist_ok=True)
            output_path = str(out / f"{input_path.stem}.{out_fmt}")
        else:
            # Auto-append format extension if no extension given
            if not out.suffix:
                output_path = f"{args.output}.{out_fmt}"
            else:
                output_path = args.output
    else:
        output_path = str(input_path.with_suffix(f".{out_fmt}"))

    # Validate output format
    from videocaptioner.cli.validators import validate_output_format
    err = validate_output_format(Path(output_path))
    if err is not None:
        return err

    asr_engine = get(config, "transcribe.asr", "faster-whisper")
    language = get(config, "transcribe.language", "auto")

    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)

    if verbose:
        output.info(f"ASR engine: {asr_engine}")
        output.info(f"Language: {language}")

    # Setup environment for Whisper API
    if asr_engine == "whisper-api":
        whisper_key = get(config, "whisper_api.api_key", "")
        whisper_base = get(config, "whisper_api.api_base", "")
        if whisper_key:
            os.environ["OPENAI_API_KEY"] = whisper_key
        if whisper_base:
            os.environ["OPENAI_BASE_URL"] = whisper_base

    from videocaptioner.cli.config_adapter import app_config_from_cli
    from videocaptioner.core.application import TaskBuilder
    transcribe_config = TaskBuilder(app_config_from_cli(config)).create_transcribe_config(
        need_word_timestamp=getattr(args, "word_timestamps", False)
    )

    # Progress callback
    progress = None if quiet else output.ProgressLine(f"Transcribing [{asr_engine}]").start()

    def callback(pct: int, msg: str) -> None:
        if progress:
            progress.update(pct, f"Transcribing [{asr_engine}] {msg}")

    try:
        # Auto-convert video to audio if needed
        from videocaptioner.cli.validators import AUDIO_EXTENSIONS
        audio_path = str(input_path)
        temp_audio = None

        ext_lower = input_path.suffix.lstrip(".").lower()
        needs_conversion = ext_lower not in AUDIO_EXTENSIONS
        # whisper-cpp requires WAV format specifically
        if not needs_conversion and asr_engine == "whisper-cpp" and ext_lower != "wav":
            needs_conversion = True

        if needs_conversion:
            if verbose:
                output.info("Converting input to WAV audio...")
            import tempfile

            from videocaptioner.core.utils.video_utils import video2audio
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio.close()
            if not video2audio(str(input_path), output=temp_audio.name):
                # Check if the temp file is empty (no audio track)
                if os.path.getsize(temp_audio.name) == 0:
                    output.error("Input video has no audio track")
                else:
                    output.error("Failed to extract audio from video. Is FFmpeg installed?")
                return EXIT.RUNTIME_ERROR
            audio_path = temp_audio.name

        from videocaptioner.core.asr import transcribe
        asr_data = transcribe(audio_path, transcribe_config, callback=callback)

        # Save output
        asr_data.save(save_path=output_path)

        if progress:
            n = len(asr_data.segments)
            progress.finish(f"Transcription complete -> {output_path} ({n} segment{'' if n == 1 else 's'})")
        if quiet:
            print(output_path)
        return EXIT.SUCCESS

    except Exception as e:
        msg = output.clean_error(str(e))
        if progress:
            progress.fail(msg)
        else:
            output.error(msg)
        if verbose:
            import traceback
            traceback.print_exc()
        return EXIT.RUNTIME_ERROR
    finally:
        if temp_audio is not None:
            try:
                os.unlink(temp_audio.name)
            except OSError:
                pass
