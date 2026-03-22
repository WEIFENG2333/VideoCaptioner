"""process command — full pipeline: transcribe → optimize → translate → synthesize."""

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
    no_synthesize = getattr(args, "no_synthesize", False)

    # If user specified --translator or --target-language, enable translation
    if getattr(args, "translator", None) or getattr(args, "target_language", None):
        no_translate = False

    # Pre-flight validation — fail fast before expensive transcription
    from videocaptioner.cli.validators import validate_process
    if not validate_process(config, no_synthesize=no_synthesize):
        return EXIT.USAGE_ERROR

    # URL input not yet supported in pipeline
    is_url = input_path.startswith("http://") or input_path.startswith("https://")
    if is_url:
        output.error("URL input is not yet supported in the process pipeline")
        output.hint("Download first: videocaptioner download <url>")
        output.hint("Then: videocaptioner process <downloaded_file>")
        return EXIT.GENERAL_ERROR

    # Validate input file
    path = Path(input_path)
    if not path.exists():
        output.error(f"Input file not found: {path}")
        return EXIT.FILE_NOT_FOUND

    out_dir = Path(getattr(args, "output", None) or path.parent)

    # Step 1: Transcribe
    if not quiet:
        output.info("Step 1/3: Transcribing...")
    subtitle_path = str(out_dir / f"{path.stem}.srt")

    tr_args = Namespace(
        input=str(path), output=subtitle_path, format="srt", word_timestamps=True,
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

    # Step 2: Subtitle (optimize + translate)
    if not no_optimize or not no_translate:
        if not quiet:
            output.info("Step 2/3: Processing subtitles...")

        processed_path = str(out_dir / f"{path.stem}_processed.srt")
        sub_args = Namespace(
            input=subtitle_path, output=processed_path,
            format=get(config, "output.format", "srt"),
            no_optimize=no_optimize, no_translate=no_translate, no_split=False,
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
            output.info("Step 2/3: Skipped (optimization and translation disabled)")

    # Step 3: Synthesize
    if not no_synthesize:
        if not quiet:
            output.info("Step 3/3: Synthesizing video...")

        syn_args = Namespace(
            video=str(path), subtitle=subtitle_path,
            output=str(out_dir / f"{path.stem}_captioned{path.suffix}"),
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
        if not quiet:
            output.info("Step 3/3: Skipped (synthesis disabled)")

    if not quiet:
        output.success("Pipeline complete!")
    return EXIT.SUCCESS
