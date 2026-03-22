"""synthesize command — burn subtitles into video."""

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import get
from videocaptioner.cli.validators import validate_synthesize

# Quality presets: name → (crf, preset)
_QUALITY_MAP = {
    "ultra": (18, "slow"),
    "high": (23, "medium"),
    "medium": (28, "medium"),
    "low": (32, "fast"),
}


def run(args: Namespace, config: dict) -> int:
    video_path = Path(args.video)
    subtitle_path = Path(args.subtitle)

    if not video_path.exists():
        output.error(f"Video file not found: {video_path}")
        return EXIT.FILE_NOT_FOUND
    if not subtitle_path.exists():
        output.error(f"Subtitle file not found: {subtitle_path}")
        return EXIT.FILE_NOT_FOUND
    if not validate_synthesize(config):
        return EXIT.DEPENDENCY_MISSING

    subtitle_mode = get(config, "synthesize.subtitle_mode", "soft")
    quality = get(config, "synthesize.quality", "medium")
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)

    crf, preset = _QUALITY_MAP.get(quality, (28, "medium"))
    soft = subtitle_mode == "soft"

    # Output path
    if args.output:
        output_path = args.output
    else:
        stem = video_path.stem
        suffix = "_captioned" if not soft else "_subtitled"
        output_path = str(video_path.with_stem(stem + suffix))

    if verbose:
        output.info(f"Mode: {'soft (embedded track)' if soft else 'hard (burned in)'}")
        output.info(f"Quality: {quality} (CRF={crf}, preset={preset})")

    progress = None if quiet else output.ProgressLine(f"Synthesizing video [{subtitle_mode}]").start()

    def progress_callback(*args) -> None:
        """Accept both (pct,) and (pct, msg) signatures from video_utils."""
        if progress and args:
            pct = args[0]
            try:
                progress.update(int(float(pct)), f"Encoding [{subtitle_mode}]")
            except (ValueError, TypeError):
                pass

    try:
        from videocaptioner.core.utils.video_utils import add_subtitles

        add_subtitles(
            input_file=str(video_path),
            subtitle_file=str(subtitle_path),
            output=output_path,
            crf=crf,
            preset=preset,
            soft_subtitle=soft,
            progress_callback=progress_callback,
        )

        if progress:
            progress.finish(f"Done -> {output_path}")
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
