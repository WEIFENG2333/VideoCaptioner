"""process command — full pipeline: transcribe → optimize → translate → synthesize/dub."""

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import get


def run(args: Namespace, config: dict) -> int:
    input_path = args.input
    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)

    no_optimize = not get(config, "subtitle.optimize", True)
    no_translate = not get(config, "subtitle.translate", False)
    no_split = not get(config, "subtitle.split", True)
    no_synthesize = getattr(args, "no_synthesize", False)
    do_dub = getattr(args, "dub", False) or getattr(args, "dub_only", False)
    if getattr(args, "dub_only", False):
        no_synthesize = True

    # If user specified --translator or --target-language, enable translation
    if getattr(args, "translator", None) or getattr(args, "target_language", None):
        no_translate = False

    # URL input not yet supported
    is_url = input_path.startswith("http://") or input_path.startswith("https://")
    if is_url:
        output.error("URL input is not yet supported in the process pipeline")
        output.hint("Download first: videocaptioner download <url>")
        output.hint("Then: videocaptioner process <downloaded_file>")
        return EXIT.GENERAL_ERROR

    # Validate input file first (before expensive pre-flight checks)
    path = Path(input_path)
    if not path.exists():
        output.error(f"Input file not found: {path}")
        return EXIT.FILE_NOT_FOUND

    # Auto-detect audio files and skip synthesis
    audio_extensions = {"mp3", "wav", "flac", "m4a", "ogg", "opus", "aac", "wma"}
    is_audio_input = path.suffix.lstrip(".").lower() in audio_extensions
    if is_audio_input and not no_synthesize:
        no_synthesize = True
        if not quiet:
            output.info("Audio file detected, skipping video synthesis")

    # Pre-flight validation
    from videocaptioner.cli.validators import validate_dubbing, validate_process
    if not validate_process(config, no_synthesize=no_synthesize):
        return EXIT.USAGE_ERROR
    if do_dub and not validate_dubbing(
        config,
        needs_video=path.suffix.lstrip(".").lower() not in audio_extensions,
        rewrite=bool(get(config, "dubbing.rewrite_too_long", False)),
    ):
        return EXIT.USAGE_ERROR

    out_arg = getattr(args, "output", None)
    if out_arg:
        out_path = Path(out_arg)
        # If it looks like a file path (has extension), use its parent as dir
        out_dir = out_path.parent if out_path.suffix else out_path
    else:
        out_dir = path.parent

    total_steps = 2 + (0 if no_synthesize else 1) + (1 if do_dub else 0)
    current_step = 1
    final_output_path = _resolve_final_output_path(out_arg, out_dir, path, do_dub, no_synthesize, is_audio_input)
    dubbed_video_path: str | None = None

    # Step 1: Transcribe
    if not quiet:
        output.info(f"Step {current_step}/{total_steps}: Transcribing...")
    subtitle_path = str(out_dir / f"{path.stem}.srt")

    # Word timestamps are useful for semantic splitting/optimization, but bad for
    # direct dubbing because they create word-level TTS fragments.
    need_word_ts = not (no_optimize and no_split)
    tr_args = Namespace(
        input=str(path), output=subtitle_path, format="srt", word_timestamps=need_word_ts,
        verbose=verbose, quiet=quiet, config=getattr(args, "config", None),
        asr=getattr(args, "asr", None), language=getattr(args, "language", None),
        fw_model=None, fw_device=None, fw_vad_method=None, fw_vad_threshold=None,
        fw_voice_extraction=False, fw_prompt=None,
        whisper_api_key=getattr(args, "whisper_api_key", None),
        whisper_api_base=getattr(args, "whisper_api_base", None),
        whisper_model=None, whisper_prompt=None,
    )
    from videocaptioner.cli.commands.transcribe import run as transcribe_run
    ret = transcribe_run(tr_args, config)
    if ret != 0:
        return ret
    current_step += 1

    # Step 2: Subtitle (optimize + translate)
    if not no_optimize or not no_translate:
        if not quiet:
            output.info(f"Step {current_step}/{total_steps}: Processing subtitles...")

        processed_path = str(out_dir / f"{path.stem}_processed.srt")
        sub_args = Namespace(
            input=subtitle_path, output=processed_path,
            format=get(config, "output.format", "srt"),
            no_optimize=no_optimize, no_translate=no_translate, no_split=no_split,
            verbose=verbose, quiet=quiet, config=getattr(args, "config", None),
            api_key=getattr(args, "api_key", None),
            api_base=getattr(args, "api_base", None),
            model=getattr(args, "model", None),
            translator=getattr(args, "translator", None),
            target_language=getattr(args, "target_language", None),
            reflect=getattr(args, "reflect", False),
            max_cjk=None, max_english=None,
            prompt=getattr(args, "prompt", None),
            prompt_file=getattr(args, "prompt_file", None),
            thread_num=getattr(args, "thread_num", None),
            batch_size=getattr(args, "batch_size", None),
            layout=getattr(args, "layout", None),
        )
        from videocaptioner.cli.commands.subtitle import run as subtitle_run
        ret = subtitle_run(sub_args, config)
        if ret != 0:
            return ret
        subtitle_path = processed_path
    else:
        if not quiet:
            output.info(f"Step {current_step}/{total_steps}: Skipped (optimization and translation disabled)")
    current_step += 1

    # Step 3: Dub
    if do_dub:
        if not quiet:
            output.info(f"Step {current_step}/{total_steps}: Dubbing...")

        is_audio = path.suffix.lstrip(".").lower() in audio_extensions
        if not no_translate:
            layout_for_dub = getattr(args, "layout", None) or get(config, "synthesize.layout", "target-above")
            text_track = "second" if layout_for_dub == "source-above" else "first"
        else:
            text_track = "first"
        dub_audio_path = str(out_dir / f"{path.stem}_dubbed.wav")
        if is_audio:
            dub_video_path = None
        elif no_synthesize:
            dub_video_path = final_output_path
        else:
            dub_video_path = str(out_dir / f"{path.stem}_dubbed{path.suffix}")
        dub_args = Namespace(
            subtitle=subtitle_path,
            video=None if is_audio else str(path),
            output=dub_video_path or dub_audio_path,
            audio_output=dub_audio_path,
            dub_preset=getattr(args, "dub_preset", None),
            provider=getattr(args, "dub_provider", None),
            tts_api_key=getattr(args, "tts_api_key", None),
            tts_api_base=getattr(args, "tts_api_base", None),
            tts_model=getattr(args, "tts_model", None),
            voice=getattr(args, "voice", None),
            style_prompt=getattr(args, "style_prompt", None),
            tts_workers=getattr(args, "tts_workers", None),
            timing=getattr(args, "timing", None),
            audio_mode=getattr(args, "audio_mode", None),
            sample_rate=None,
            speed=None,
            gain=None,
            speaker_voice=getattr(args, "speaker_voice", []),
            speaker_style=getattr(args, "speaker_style", []),
            speaker_clone=getattr(args, "speaker_clone", []),
            clone_audio=getattr(args, "clone_audio", None),
            clone_text=getattr(args, "clone_text", None),
            text_track=text_track,
            fit_mode=getattr(args, "fit_mode", None),
            max_speed=getattr(args, "max_speed", None),
            target_padding_ms=None,
            rewrite_too_long=getattr(args, "rewrite_too_long", False),
            rewrite_threshold=None,
            mix_original_audio=getattr(args, "mix_original_audio", False),
            original_audio_volume=None,
            dubbed_audio_volume=None,
            api_key=getattr(args, "api_key", None),
            api_base=getattr(args, "api_base", None),
            model=getattr(args, "model", None),
            verbose=verbose,
            quiet=quiet,
            config=getattr(args, "config", None),
        )
        from videocaptioner.cli.commands.dub import run as dub_run
        ret = dub_run(dub_args, config)
        if ret != 0:
            return ret
        dubbed_video_path = dub_video_path
        current_step += 1

    # Step 4: Synthesize
    if not no_synthesize:
        if not quiet:
            output.info(f"Step {current_step}/{total_steps}: Synthesizing video...")

        synth_video = dubbed_video_path or str(path)
        syn_args = Namespace(
            video=synth_video, subtitle=subtitle_path,
            output=final_output_path,
            subtitle_mode=getattr(args, "subtitle_mode", None),
            quality=getattr(args, "quality", None),
            style=None, layout=getattr(args, "layout", None),
            format=None, verbose=verbose, quiet=quiet,
            config=getattr(args, "config", None),
        )
        from videocaptioner.cli.commands.synthesize import run as synthesize_run
        ret = synthesize_run(syn_args, config)
        if ret != 0:
            return ret
    else:
        if not quiet and not getattr(args, "dub_only", False):
            output.info(f"Step {current_step}/{total_steps}: Skipped (synthesis disabled)")

    if not quiet:
        output.success("Pipeline complete!")
    return EXIT.SUCCESS


def _resolve_final_output_path(
    output_arg: str | None,
    out_dir: Path,
    input_path: Path,
    do_dub: bool,
    no_synthesize: bool,
    is_audio: bool,
) -> str:
    if output_arg:
        out_path = Path(output_arg)
        if out_path.suffix:
            return str(out_path)
    suffix = ".wav" if is_audio and do_dub else input_path.suffix
    if do_dub and no_synthesize:
        return str(out_dir / f"{input_path.stem}_dubbed{suffix}")
    if do_dub:
        return str(out_dir / f"{input_path.stem}_dubbed_captioned{suffix}")
    return str(out_dir / f"{input_path.stem}_captioned{suffix}")
