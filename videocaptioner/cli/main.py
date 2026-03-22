"""VideoCaptioner CLI — AI-powered video captioning from the command line.

Usage:
    videocaptioner <command> [options]

Commands:
    transcribe   Transcribe audio/video to subtitles
    subtitle     Optimize and/or translate subtitle files
    synthesize   Burn subtitles into video
    process      Full pipeline (transcribe → optimize → translate → synthesize)
    download     Download online video (YouTube, Bilibili, etc.)
    config       Manage configuration
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from videocaptioner.cli import exit_codes as EXIT


def _add_llm_options(parser: argparse.ArgumentParser) -> None:
    """Add LLM-related options shared across commands."""
    group = parser.add_argument_group("LLM options")
    group.add_argument("--api-key", metavar="KEY", help="LLM API key")
    group.add_argument("--api-base", metavar="URL", help="LLM API base URL")
    group.add_argument("--model", metavar="NAME", help="LLM model name (e.g. gpt-4o-mini)")


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """Add output-related options."""
    group = parser.add_argument_group("Output options")
    group.add_argument("-o", "--output", metavar="PATH", help="Output file or directory path")
    group.add_argument(
        "--format",
        choices=["srt", "ass", "txt", "json"],
        help="Output subtitle format (default: srt)",
    )


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    """Add options common to all commands."""
    parser.add_argument("--config", metavar="FILE", help="Path to config file")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (only output result path)")


def _build_transcribe_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "transcribe",
        help="Transcribe audio/video to subtitles",
        description="Convert audio or video files to subtitle files using ASR (Automatic Speech Recognition).",
    )
    p.add_argument("input", help="Audio or video file path")
    _add_common_options(p)
    _add_output_options(p)

    asr = p.add_argument_group("ASR options")
    asr.add_argument(
        "--asr",
        choices=["faster-whisper", "whisper-api", "bijian", "jianying", "whisper-cpp"],
        help="ASR engine (default: faster-whisper)",
    )
    asr.add_argument(
        "--language",
        metavar="CODE",
        help="Source language as ISO 639-1 code, or 'auto' (default: auto)",
    )
    asr.add_argument("--word-timestamps", action="store_true", help="Include word-level timestamps")

    fw = p.add_argument_group("FasterWhisper options (--asr faster-whisper)")
    fw.add_argument(
        "--fw-model",
        choices=["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large-v3-turbo"],
        help="Whisper model size (default: large-v3)",
    )
    fw.add_argument("--fw-device", choices=["auto", "cuda", "cpu"], help="Compute device (default: auto)")
    fw.add_argument(
        "--fw-vad-method",
        choices=["silero-v3", "silero-v4", "silero-v5", "silero-v4-fw", "pyannote-v3", "pyannote-onnx-v3", "webrtc", "auditok"],
        help="Voice activity detection method (default: silero-v4-fw)",
    )
    fw.add_argument("--fw-vad-threshold", type=float, metavar="N", help="VAD threshold 0.0-1.0 (default: 0.5)")
    fw.add_argument("--fw-voice-extraction", action="store_true", help="Enable vocal extraction before transcription")
    fw.add_argument("--fw-prompt", metavar="TEXT", help="Initial prompt for FasterWhisper")

    wa = p.add_argument_group("Whisper API options (--asr whisper-api)")
    wa.add_argument("--whisper-api-key", metavar="KEY", help="Whisper API key (separate from LLM)")
    wa.add_argument("--whisper-api-base", metavar="URL", help="Whisper API base URL")
    wa.add_argument("--whisper-model", metavar="NAME", help="Whisper model name (default: whisper-1)")
    wa.add_argument("--whisper-prompt", metavar="TEXT", help="Transcription prompt")

    p.set_defaults(func=_run_transcribe)


def _build_subtitle_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "subtitle",
        help="Optimize and/or translate subtitles",
        description="Process subtitle files — optimize text with LLM, translate to another language, or both.",
    )
    p.add_argument("input", help="Subtitle file path (.srt, .ass, .vtt)")
    _add_common_options(p)
    _add_llm_options(p)
    _add_output_options(p)

    proc = p.add_argument_group("Processing options")
    proc.add_argument("--no-optimize", action="store_true", help="Skip LLM subtitle optimization")
    proc.add_argument("--no-translate", action="store_true", help="Skip translation")
    proc.add_argument("--no-split", action="store_true", help="Skip subtitle re-segmentation")

    trans = p.add_argument_group("Translation options")
    trans.add_argument(
        "--translator",
        choices=["llm", "bing", "google"],
        help="Translation service (default: llm)",
    )
    trans.add_argument(
        "--target-language",
        metavar="CODE",
        help="Target language as BCP 47 code, e.g. zh-Hans, en, ja (default: zh-Hans)",
    )
    trans.add_argument("--reflect", action="store_true", help="Enable reflective translation (LLM only, slower but more accurate)")

    sub = p.add_argument_group("Subtitle options")
    sub.add_argument("--max-cjk", type=int, metavar="N", help="Max characters per line for CJK text (default: 18)")
    sub.add_argument("--max-english", type=int, metavar="N", help="Max words per line for English text (default: 12)")
    sub.add_argument("--prompt", metavar="TEXT", help="Custom prompt for LLM optimization/translation")
    sub.add_argument("--prompt-file", metavar="FILE", help="Read custom prompt from file")
    sub.add_argument("--thread-num", type=int, metavar="N", help="Number of concurrent threads (default: 4)")
    sub.add_argument("--batch-size", type=int, metavar="N", help="Batch size for processing (default: 10)")

    layout = p.add_argument_group("Layout options")
    layout.add_argument(
        "--layout",
        choices=["target-above", "source-above", "target-only", "source-only"],
        help="Subtitle layout for bilingual output (default: target-above)\n"
             "  target-above: Translation on top, original below\n"
             "  source-above: Original on top, translation below\n"
             "  target-only:  Translation only\n"
             "  source-only:  Original only",
    )

    p.set_defaults(func=_run_subtitle)


def _build_synthesize_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "synthesize",
        help="Burn subtitles into video",
        description="Combine a video file with a subtitle file — either as soft subtitles (embedded track) or hard subtitles (burned in).",
    )
    p.add_argument("video", help="Input video file path")
    _add_common_options(p)

    req = p.add_argument_group("Required")
    req.add_argument("-s", "--subtitle", required=True, metavar="FILE", help="Subtitle file path (.srt, .ass)")

    opt = p.add_argument_group("Synthesis options")
    opt.add_argument(
        "--subtitle-mode",
        choices=["soft", "hard"],
        help="Subtitle embedding mode (default: soft)\n"
             "  soft: Embedded as a selectable subtitle track\n"
             "  hard: Burned into video frames permanently",
    )
    opt.add_argument(
        "--quality",
        choices=["ultra", "high", "medium", "low"],
        help="Video quality (default: medium)\n"
             "  ultra:  CRF 18, slow preset — best quality, largest file\n"
             "  high:   CRF 23, medium preset\n"
             "  medium: CRF 28, medium preset — balanced\n"
             "  low:    CRF 32, fast preset — smallest file",
    )
    p.add_argument("-o", "--output", metavar="PATH", help="Output video file path")

    p.set_defaults(func=_run_synthesize)


def _build_process_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "process",
        help="Full pipeline: transcribe → optimize → translate → synthesize",
        description="Run the complete captioning pipeline on a video or audio file. "
                    "Equivalent to running transcribe, subtitle, and synthesize in sequence.",
    )
    p.add_argument("input", help="Video/audio file path, or online video URL")
    _add_common_options(p)
    _add_llm_options(p)
    _add_output_options(p)

    pipe = p.add_argument_group("Pipeline options")
    pipe.add_argument("--no-optimize", action="store_true", help="Skip subtitle optimization")
    pipe.add_argument("--no-translate", action="store_true", help="Skip translation")
    pipe.add_argument("--no-synthesize", action="store_true", help="Skip video synthesis (output subtitles only)")

    pipe.add_argument("--asr", choices=["faster-whisper", "whisper-api", "bijian", "jianying", "whisper-cpp"],
                      help="ASR engine (default: faster-whisper)")
    pipe.add_argument("--language", metavar="CODE", help="Source language ISO 639-1 code (default: auto)")
    pipe.add_argument("--translator", choices=["llm", "bing", "google"], help="Translation service (default: llm)")
    pipe.add_argument("--target-language", metavar="CODE", help="Target language BCP 47 code (default: zh-Hans)")
    pipe.add_argument("--reflect", action="store_true", help="Reflective translation")
    pipe.add_argument("--quality", choices=["ultra", "high", "medium", "low"], help="Video quality (default: medium)")
    pipe.add_argument("--subtitle-mode", choices=["soft", "hard"], help="Subtitle mode (default: soft)")
    pipe.add_argument("--layout", choices=["target-above", "source-above", "target-only", "source-only"],
                      help="Subtitle layout (default: target-above)")
    pipe.add_argument("--prompt", metavar="TEXT", help="Custom prompt")
    pipe.add_argument("--prompt-file", metavar="FILE", help="Read prompt from file")
    pipe.add_argument("--thread-num", type=int, metavar="N", help="Concurrent threads (default: 4)")
    pipe.add_argument("--batch-size", type=int, metavar="N", help="Batch size (default: 10)")

    p.set_defaults(func=_run_process)


def _build_download_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "download",
        help="Download online video (YouTube, Bilibili, etc.)",
        description="Download video from YouTube, Bilibili, and other sites supported by yt-dlp.",
    )
    p.add_argument("url", help="Video URL")
    _add_common_options(p)
    p.add_argument("-o", "--output", metavar="DIR", help="Output directory (default: current directory)")
    p.set_defaults(func=_run_download)


def _build_config_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "config",
        help="Manage configuration",
        description="View, edit, and manage VideoCaptioner configuration.",
    )
    config_sub = p.add_subparsers(dest="config_action", metavar="action")

    config_sub.add_parser("show", help="Display current configuration")
    config_sub.add_parser("path", help="Show config file path")
    config_sub.add_parser("init", help="Interactive configuration setup")
    config_sub.add_parser("edit", help="Open config file in $EDITOR")

    set_p = config_sub.add_parser("set", help="Set a configuration value")
    set_p.add_argument("key", help="Config key in dotted notation (e.g. llm.api_key)")
    set_p.add_argument("value", help="Value to set")

    get_p = config_sub.add_parser("get", help="Get a configuration value")
    get_p.add_argument("key", help="Config key in dotted notation")

    p.set_defaults(func=_run_config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videocaptioner",
        description="AI-powered video captioning — transcribe, optimize, translate, and synthesize subtitles.",
        epilog="Run 'videocaptioner <command> --help' for details on each command.",
    )
    parser.add_argument("--version", action="version", version=_get_version())

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    _build_transcribe_parser(subparsers)
    _build_subtitle_parser(subparsers)
    _build_synthesize_parser(subparsers)
    _build_process_parser(subparsers)
    _build_download_parser(subparsers)
    _build_config_parser(subparsers)

    return parser


def _get_version() -> str:
    # Read version without importing config.py (avoids side effects)
    try:
        import importlib.metadata
        return f"videocaptioner {importlib.metadata.version('videocaptioner')}"
    except Exception:
        return "videocaptioner (version unknown)"


# ── Command runners ──────────────────────────────────────────────────────────


def _build_cli_overrides(args: argparse.Namespace) -> dict:
    """Extract CLI arguments into a config override dict."""
    overrides: dict = {}

    def _set(key: str, value) -> None:
        if value is not None:
            from videocaptioner.cli.config import _set_nested
            _set_nested(overrides, key, value)

    # LLM
    _set("llm.api_key", getattr(args, "api_key", None))
    _set("llm.api_base", getattr(args, "api_base", None))
    _set("llm.model", getattr(args, "model", None))

    # Whisper API
    _set("whisper_api.api_key", getattr(args, "whisper_api_key", None))
    _set("whisper_api.api_base", getattr(args, "whisper_api_base", None))
    _set("whisper_api.model", getattr(args, "whisper_model", None))

    # Transcribe
    _set("transcribe.asr", getattr(args, "asr", None))
    _set("transcribe.language", getattr(args, "language", None))

    # FasterWhisper
    _set("transcribe.faster_whisper.model", getattr(args, "fw_model", None))
    _set("transcribe.faster_whisper.device", getattr(args, "fw_device", None))
    _set("transcribe.faster_whisper.vad_method", getattr(args, "fw_vad_method", None))
    _set("transcribe.faster_whisper.vad_threshold", getattr(args, "fw_vad_threshold", None))
    if getattr(args, "fw_voice_extraction", False):
        _set("transcribe.faster_whisper.voice_extraction", True)
    _set("transcribe.faster_whisper.prompt", getattr(args, "fw_prompt", None))

    # Whisper prompt
    _set("whisper_api.prompt", getattr(args, "whisper_prompt", None))

    # Subtitle
    if getattr(args, "no_optimize", False):
        _set("subtitle.optimize", False)
    if getattr(args, "no_translate", False):
        _set("subtitle.translate", False)
    if getattr(args, "no_split", False):
        _set("subtitle.split", False)
    _set("subtitle.max_word_count_cjk", getattr(args, "max_cjk", None))
    _set("subtitle.max_word_count_english", getattr(args, "max_english", None))
    _set("subtitle.thread_num", getattr(args, "thread_num", None))
    _set("subtitle.batch_size", getattr(args, "batch_size", None))

    # Translate
    _set("translate.service", getattr(args, "translator", None))
    _set("translate.target_language", getattr(args, "target_language", None))
    if getattr(args, "reflect", False):
        _set("translate.reflect", True)

    # Synthesize / Layout
    _set("synthesize.subtitle_mode", getattr(args, "subtitle_mode", None))
    _set("synthesize.quality", getattr(args, "quality", None))
    _set("synthesize.layout", getattr(args, "layout", None))

    # Output
    _set("output.format", getattr(args, "format", None))

    return overrides


def _load_config(args: argparse.Namespace) -> dict:
    """Load config with all layers merged."""
    from videocaptioner.cli.config import build_config
    config_path = Path(args.config) if getattr(args, "config", None) else None
    cli_overrides = _build_cli_overrides(args)
    return build_config(cli_overrides=cli_overrides, config_path=config_path)


def _run_transcribe(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.transcribe import run
    config = _load_config(args)
    return run(args, config)


def _run_subtitle(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.subtitle import run
    config = _load_config(args)
    return run(args, config)


def _run_synthesize(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.synthesize import run
    config = _load_config(args)
    return run(args, config)


def _run_process(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.process import run
    config = _load_config(args)
    return run(args, config)


def _run_download(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.download import run
    config = _load_config(args)
    return run(args, config)


def _run_config(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.config_cmd import run
    config = _load_config(args)
    return run(args, config)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        # No subcommand: try launching GUI if installed, otherwise show CLI help
        try:
            from videocaptioner.ui.main import main as gui_main
            gui_main()
            return EXIT.SUCCESS
        except ImportError:
            parser.print_help()
            return EXIT.USAGE_ERROR

    if not hasattr(args, "func"):
        parser.print_help()
        return EXIT.USAGE_ERROR

    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        from videocaptioner.cli.output import error
        error(str(e))
        if getattr(args, "verbose", False):
            import traceback
            traceback.print_exc()
        return EXIT.GENERAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
