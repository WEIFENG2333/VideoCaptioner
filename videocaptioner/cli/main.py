"""VideoCaptioner CLI — AI-powered video captioning from the command line.

Usage:
    videocaptioner <command> [options]

Commands:
    gui          Launch the desktop app
    transcribe   Transcribe audio/video to subtitles
    subtitle     Optimize and/or translate subtitle files
    dub          Generate dubbed audio/video from subtitles
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
    group.add_argument("--api-key", metavar="KEY",
                       help="LLM API key (or set OPENAI_API_KEY env var)")
    group.add_argument("--api-base", metavar="URL",
                       help="LLM API base URL (or set OPENAI_BASE_URL env var)")
    group.add_argument("--model", metavar="NAME", help="LLM model name (e.g. gpt-4o-mini)")


def _add_hidden_llm_options(parser: argparse.ArgumentParser) -> None:
    """Keep script-compatible LLM overrides without showing them in task-first help."""
    parser.add_argument("--api-key", metavar="KEY", help=argparse.SUPPRESS)
    parser.add_argument("--api-base", metavar="URL", help=argparse.SUPPRESS)
    parser.add_argument("--model", metavar="NAME", help=argparse.SUPPRESS)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """Add output-related options."""
    group = parser.add_argument_group("Output options")
    group.add_argument("-o", "--output", metavar="PATH", help="Output file or directory path")
    group.add_argument(
        "--format",
        choices=["srt", "ass", "txt", "json"],
        help="Output subtitle format (default: srt)",
    )


def _add_style_options(parser: argparse.ArgumentParser) -> None:
    """Add subtitle style options (for hard subtitle mode)."""
    grp = parser.add_argument_group(
        "Subtitle style (--subtitle-mode hard only)",
        description="Style options only take effect with hard subtitles. "
                    "Soft subtitles are rendered by the video player.\n"
                    "Use 'videocaptioner style' to see available presets.",
    )
    grp.add_argument(
        "--render-mode",
        choices=["ass", "rounded"],
        help="Rendering mode (default: ass)\n"
             "  ass:     Traditional subtitle with outline/shadow (supports presets)\n"
             "  rounded: Modern rounded background boxes (customizable colors/size)",
    )
    grp.add_argument(
        "--style",
        metavar="NAME",
        help="Style preset name (default: default). "
             "Run 'videocaptioner style' to see options",
    )
    grp.add_argument(
        "--style-override",
        metavar="JSON",
        help='Inline JSON to override style fields, e.g. \'{"outline_color": "#ff0000", "font_size": 48}\'. '
             "Run 'videocaptioner style' to see available fields.",
    )
    grp.add_argument("--font-file", metavar="PATH", help="Custom font file (.ttf/.otf), overrides style font")


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
        choices=["bijian", "jianying", "whisper-api", "whisper-cpp"],
        help="ASR engine (default: bijian). "
             "bijian/jianying: free, no setup, Chinese & English only. "
             "For other languages use whisper-api or whisper-cpp",
    )
    asr.add_argument("--language", metavar="CODE",
                     help="Source language as ISO 639-1 code, or 'auto' (default: auto)")
    asr.add_argument("--word-timestamps", action="store_true",
                     help="Include word-level timestamps (for subtitle splitting)")
    asr.add_argument("--whisper-api-key", metavar="KEY",
                     help="Whisper API key (for --asr whisper-api)")
    asr.add_argument("--whisper-api-base", metavar="URL",
                     help="Whisper API base URL")

    asr.add_argument("--whisper-model", metavar="NAME",
                     help="Model name for whisper-api (default: whisper-1) "
                          "or whisper-cpp (default: large-v2)")

    # Advanced options (configurable via 'config set', hidden from --help)
    for arg in ["--fw-model", "--fw-device", "--fw-vad-method", "--fw-prompt", "--whisper-prompt"]:
        p.add_argument(arg, help=argparse.SUPPRESS)
    p.add_argument("--fw-vad-threshold", type=float, help=argparse.SUPPRESS)
    p.add_argument("--fw-voice-extraction", action="store_true", help=argparse.SUPPRESS)

    p.set_defaults(func=_run_transcribe)


def _build_gui_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "gui",
        help="Launch the desktop app",
        description="Launch the VideoCaptioner desktop app.",
    )
    p.set_defaults(func=_run_gui)


def _build_subtitle_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "subtitle",
        help="Optimize and/or translate subtitles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Process subtitle files with up to 3 steps:\n"
            "  1. Split — Re-segment subtitles by semantic boundaries (LLM)\n"
            "  2. Optimize — Fix ASR errors, punctuation, formatting (LLM)\n"
            "  3. Translate — Translate to another language (LLM, Bing, or Google)\n\n"
            "By default, optimize and split are enabled, translation is disabled.\n"
            "Use --translator or --target-language to enable translation.\n"
            "Bing and Google translators are free, LLM requires an API key."
        ),
    )
    p.add_argument("input", help="Subtitle file path (.srt, .ass, .vtt)")
    _add_common_options(p)

    llm = p.add_argument_group("LLM options")
    llm.add_argument("--api-key", metavar="KEY",
                     help="LLM API key (or set OPENAI_API_KEY env var)")
    llm.add_argument("--api-base", metavar="URL",
                     help="LLM API base URL (or set OPENAI_BASE_URL env var)")
    llm.add_argument("--model", metavar="NAME", help="LLM model name (e.g. gpt-4o-mini)")

    _add_output_options(p)

    proc = p.add_argument_group("Processing options")
    proc.add_argument("--no-optimize", action="store_true", help="Skip LLM subtitle optimization")
    proc.add_argument("--no-translate", action="store_true", help="Skip translation")
    proc.add_argument("--no-split", action="store_true", help="Skip subtitle re-segmentation")

    trans = p.add_argument_group("Translation options")
    trans.add_argument(
        "--translator",
        choices=["llm", "bing", "google"],
        help="Translation service (default: bing). bing and google are free",
    )
    trans.add_argument(
        "--target-language",
        metavar="CODE",
        help="Target language as BCP 47 code, e.g. zh-Hans, en, ja (default: zh-Hans)",
    )
    trans.add_argument("--reflect", action="store_true",
                       help="Enable reflective translation (LLM only, higher quality)")

    sub = p.add_argument_group("Subtitle options")
    sub.add_argument("--max-cjk", type=int, metavar="N", help="Max characters per line for CJK text (default: 18)")
    sub.add_argument("--max-english", type=int, metavar="N", help="Max words per line for English text (default: 12)")
    sub.add_argument("--prompt", metavar="TEXT", help="Custom prompt for LLM optimization/translation")
    sub.add_argument("--thread-num", type=int, metavar="N", help="Number of concurrent threads (default: 4)")
    sub.add_argument("--batch-size", type=int, metavar="N", help="Batch size for processing (default: 20)")

    layout = p.add_argument_group("Layout options")
    layout.add_argument(
        "--layout",
        choices=["target-above", "source-above", "target-only", "source-only"],
        help="Subtitle layout for bilingual output (default: target-above)",
    )

    # Hidden: --prompt-file (use --prompt instead)
    p.add_argument("--prompt-file", metavar="FILE", help=argparse.SUPPRESS)

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
    opt.add_argument(
        "--layout",
        choices=["target-above", "source-above", "target-only", "source-only"],
        help="Subtitle layout for bilingual output (default: target-above)",
    )

    _add_style_options(p)
    p.add_argument("-o", "--output", metavar="PATH", help="Output video file path")

    p.set_defaults(func=_run_synthesize)


def _build_dub_parser(subparsers) -> None:
    from videocaptioner.core.dubbing.presets import available_dubbing_presets

    p = subparsers.add_parser(
        "dub",
        help="Generate dubbed audio or video from subtitles",
        description=(
            "Generate a timed dubbing track from SRT/ASS/VTT/JSON subtitles. "
            "Speaker labels may be embedded as '[Alice] text' or 'Alice: text'."
        ),
    )
    p.add_argument("subtitle", help="Subtitle file path (.srt, .ass, .vtt, .json)")
    _add_common_options(p)

    p.add_argument("--video", metavar="FILE", help="Optional video file to mux with dubbed audio")
    p.add_argument("-o", "--output", metavar="PATH", help="Output audio/video path")
    p.add_argument("--audio-output", metavar="PATH", help="Output dubbed audio path")

    tts = p.add_argument_group("Dubbing options")
    tts.add_argument("--preset", dest="dub_preset", choices=available_dubbing_presets(), help="Voice preset")
    p.add_argument("--dub-preset", dest="dub_preset", choices=available_dubbing_presets(), help=argparse.SUPPRESS)
    tts.add_argument("--tts-api-key", metavar="KEY", help="TTS API key. Prefer config set dubbing.api_key")
    tts.add_argument("--voice", metavar="VOICE", help="Default voice, e.g. anna, alex, benjamin, Kore")
    tts.add_argument("--speak", dest="text_track", choices=["auto", "first", "second"], help="Subtitle line to speak for bilingual subtitles")
    p.add_argument("--text-track", dest="text_track", choices=["auto", "first", "second", "source", "target", "original", "translated"], help=argparse.SUPPRESS)
    tts.add_argument("--timing", choices=["balanced", "strict", "natural", "none"], help="Timing strategy")
    tts.add_argument("--adapt-length", dest="rewrite_too_long", action="store_true", help="Shorten lines that are too long for their subtitle slot")
    p.add_argument("--rewrite-too-long", dest="rewrite_too_long", action="store_true", help=argparse.SUPPRESS)
    tts.add_argument("--audio-mode", choices=["replace", "mix", "duck"], help="How to handle original video audio")

    speaker = p.add_argument_group("Speaker options")
    speaker.add_argument(
        "--speaker-voice",
        action="append",
        default=[],
        metavar="NAME=VOICE",
        help="Map subtitle speaker to a voice; repeatable",
    )
    speaker.add_argument(
        "--speaker-style",
        action="append",
        default=[],
        metavar="NAME=PROMPT",
        help=argparse.SUPPRESS,
    )
    speaker.add_argument(
        "--speaker-clone",
        action="append",
        default=[],
        metavar="NAME=AUDIO|TEXT",
        help="Map speaker to SiliconFlow clone reference audio and exact transcript; repeatable",
    )
    speaker.add_argument("--clone-audio", metavar="FILE", help="Default speaker clone reference audio")
    speaker.add_argument("--clone-text", metavar="TEXT", help="Exact transcript for --clone-audio")

    # Hidden advanced/provider options. They remain available for scripts and debugging.
    p.add_argument("--provider", choices=["siliconflow", "gemini"], help=argparse.SUPPRESS)
    p.add_argument("--tts-api-base", metavar="URL", help=argparse.SUPPRESS)
    p.add_argument("--tts-model", metavar="NAME", help=argparse.SUPPRESS)
    p.add_argument("--style-prompt", metavar="TEXT", help=argparse.SUPPRESS)
    p.add_argument("--tts-workers", type=int, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--sample-rate", type=int, metavar="HZ", help=argparse.SUPPRESS)
    p.add_argument("--speed", type=float, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--gain", type=float, metavar="DB", help=argparse.SUPPRESS)
    p.add_argument("--fit-mode", choices=["tempo", "none"], help=argparse.SUPPRESS)
    p.add_argument("--max-speed", type=float, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--target-padding-ms", type=int, metavar="MS", help=argparse.SUPPRESS)
    p.add_argument("--rewrite-threshold", type=float, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--mix-original-audio", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--original-audio-volume", type=float, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--dubbed-audio-volume", type=float, metavar="N", help=argparse.SUPPRESS)

    _add_hidden_llm_options(p)
    p.set_defaults(func=_run_dub)


def _build_process_parser(subparsers) -> None:
    from videocaptioner.core.dubbing.presets import available_dubbing_presets

    p = subparsers.add_parser(
        "process",
        help="Full pipeline: transcribe → optimize → translate → synthesize",
        description="Run the complete captioning pipeline on a video or audio file. "
                    "Equivalent to running transcribe, subtitle, and synthesize in sequence.",
    )
    p.add_argument("input", help="Video or audio file path")
    _add_common_options(p)
    _add_llm_options(p)
    _add_output_options(p)

    pipe = p.add_argument_group("Pipeline options")
    pipe.add_argument("--no-optimize", action="store_true", help="Skip AI subtitle polish")
    pipe.add_argument("--no-translate", action="store_true", help="Skip translation")
    pipe.add_argument("--no-split", action="store_true", help="Skip subtitle re-segmentation")
    pipe.add_argument("--no-synthesize", action="store_true", help="Skip video synthesis (output subtitles only)")
    pipe.add_argument("--dub", action="store_true", help="Generate dubbed audio/video after subtitle processing")
    pipe.add_argument("--dub-only", action="store_true", help="Output only the dubbed result, skipping subtitle burn/embedding")

    pipe.add_argument("--asr", choices=["bijian", "jianying", "whisper-api", "whisper-cpp"],
                      help="ASR engine (default: bijian)")
    pipe.add_argument("--language", metavar="CODE",
                      help="Source language as ISO 639-1 code, or 'auto' (default: auto)")
    pipe.add_argument("--whisper-api-key", metavar="KEY", help="Whisper API key (for --asr whisper-api)")
    pipe.add_argument("--translator", choices=["llm", "bing", "google"],
                      help="Translation service (default: bing). bing and google are free")
    pipe.add_argument("--to", dest="target_language", metavar="CODE", help="Target language BCP 47 code")
    p.add_argument("--target-language", dest="target_language", metavar="CODE", help=argparse.SUPPRESS)
    pipe.add_argument("--reflect", action="store_true", help="Reflective translation (LLM only)")
    pipe.add_argument("--quality", choices=["ultra", "high", "medium", "low"], help="Video quality (default: medium)")
    pipe.add_argument("--subtitle-mode", choices=["soft", "hard"], help="Subtitle mode (default: soft)")
    pipe.add_argument("--layout", choices=["target-above", "source-above", "target-only", "source-only"],
                      help="Subtitle layout (default: target-above)")
    pipe.add_argument("--preset", dest="dub_preset", choices=available_dubbing_presets(), help="Dubbing voice preset")
    p.add_argument("--dub-preset", dest="dub_preset", choices=available_dubbing_presets(), help=argparse.SUPPRESS)
    pipe.add_argument("--tts-api-key", metavar="KEY", help="Dubbing TTS API key")
    pipe.add_argument("--voice", metavar="VOICE", help="Default dubbing voice")
    pipe.add_argument("--timing", choices=["balanced", "strict", "natural", "none"], help="Dubbing timing strategy")
    pipe.add_argument("--adapt-length", dest="rewrite_too_long", action="store_true", help="Shorten lines that are too long for their subtitle slot")
    pipe.add_argument("--audio-mode", choices=["replace", "mix", "duck"], help="How to handle original video audio")
    pipe.add_argument("--speaker-voice", action="append", default=[], metavar="NAME=VOICE",
                      help="Map subtitle speaker to a voice; repeatable")
    pipe.add_argument("--speaker-clone", action="append", default=[], metavar="NAME=AUDIO|TEXT",
                      help="Map speaker to clone reference audio and transcript; repeatable")
    pipe.add_argument("--clone-audio", metavar="FILE", help="Default speaker clone reference audio")
    pipe.add_argument("--clone-text", metavar="TEXT", help="Exact transcript for --clone-audio")
    # Hidden options
    p.add_argument("--prompt-file", metavar="FILE", help=argparse.SUPPRESS)
    p.add_argument("--prompt", metavar="TEXT", help=argparse.SUPPRESS)
    p.add_argument("--thread-num", type=int, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--batch-size", type=int, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--whisper-api-base", help=argparse.SUPPRESS)
    p.add_argument("--whisper-model", help=argparse.SUPPRESS)
    p.add_argument("--dub-provider", choices=["siliconflow", "gemini"], help=argparse.SUPPRESS)
    p.add_argument("--tts-api-base", metavar="URL", help=argparse.SUPPRESS)
    p.add_argument("--tts-model", metavar="NAME", help=argparse.SUPPRESS)
    p.add_argument("--style-prompt", metavar="TEXT", help=argparse.SUPPRESS)
    p.add_argument("--tts-workers", type=int, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--speaker-style", action="append", default=[], metavar="NAME=PROMPT", help=argparse.SUPPRESS)
    p.add_argument("--fit-mode", choices=["tempo", "none"], help=argparse.SUPPRESS)
    p.add_argument("--max-speed", type=float, metavar="N", help=argparse.SUPPRESS)
    p.add_argument("--mix-original-audio", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--rewrite-too-long", dest="rewrite_too_long", action="store_true", help=argparse.SUPPRESS)

    _add_style_options(p)

    p.set_defaults(func=_run_process)


def _build_style_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "style",
        help="List subtitle style presets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Show all available subtitle style presets with their configurations.\n\n"
                    "Two rendering modes are supported:\n"
                    "  ass:     Traditional subtitle with outline/shadow\n"
                    "  rounded: Modern rounded background boxes\n\n"
                    "Use --style <name> in synthesize/process to apply a preset.\n"
                    "Use --style-override '{...}' to customize fields inline.",
    )
    p.set_defaults(func=_run_style, style_action="list")


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
    init_p = config_sub.add_parser(
        "init",
        help="Create an onboarding config file",
        description=(
            "Create a VideoCaptioner config file. By default this starts an interactive setup. "
            "Use --non-interactive for Agent/CI-friendly setup."
        ),
    )
    init_p.add_argument("--non-interactive", action="store_true", help="Write config without prompts")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing config file")
    init_p.add_argument("--print-template", action="store_true", help="Print a commented template instead of writing")
    init_p.add_argument("--profile", choices=["basic", "dubbing"], default="basic", help="Configuration profile")
    init_p.add_argument("--llm-api-key", metavar="KEY", help="LLM API key")
    init_p.add_argument("--llm-api-base", metavar="URL", help="LLM API base URL")
    init_p.add_argument("--llm-model", metavar="NAME", help="LLM model")
    init_p.add_argument("--asr", choices=["bijian", "jianying", "whisper-api", "whisper-cpp"], help="Default ASR engine")
    init_p.add_argument("--translator", choices=["llm", "bing", "google"], help="Default translation service")
    init_p.add_argument("--target-language", "--to", dest="target_language", metavar="CODE", help=argparse.SUPPRESS)
    init_p.add_argument("--no-optimize", action="store_true", help="Disable AI subtitle polish by default")
    init_p.add_argument("--no-split", action="store_true", help="Disable subtitle re-segmentation by default")
    init_p.add_argument("--tts-api-key", metavar="KEY", help="Dubbing TTS API key")
    init_p.add_argument("--dub-preset", "--preset", dest="dub_preset", help="Dubbing voice preset")
    init_p.add_argument("--voice", metavar="VOICE", help="Default dubbing voice")
    init_p.add_argument("--timing", choices=["balanced", "strict", "natural", "none"], help="Dubbing timing strategy")
    init_p.add_argument("--audio-mode", choices=["replace", "mix", "duck"], help="Original audio handling for dubbing")
    config_sub.add_parser("edit", help="Open config file in $EDITOR")

    set_p = config_sub.add_parser("set", help="Set a configuration value")
    set_p.add_argument("key", help="Config key in dotted notation (e.g. llm.api_key)")
    set_p.add_argument("value", help="Value to set")

    get_p = config_sub.add_parser("get", help="Get a configuration value")
    get_p.add_argument("key", help="Config key in dotted notation")

    p.set_defaults(func=_run_config)


def _build_doctor_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "doctor",
        help="Diagnose dependencies and configuration",
        description="Check local tools, config, and common workflow readiness.",
    )
    _add_common_options(p)
    p.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p.add_argument("--check-api", action="store_true", help="Also perform lightweight provider API checks")
    p.set_defaults(func=_run_doctor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videocaptioner",
        description="AI-powered video captioning — transcribe speech, optimize and translate subtitles, "
                    "then burn them into video with customizable styles (ASS or rounded background).",
        epilog="Run 'videocaptioner <command> --help' for details on each command.",
    )
    parser.add_argument("--version", action="version", version=_get_version())

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    _build_transcribe_parser(subparsers)
    _build_gui_parser(subparsers)
    _build_subtitle_parser(subparsers)
    _build_dub_parser(subparsers)
    _build_synthesize_parser(subparsers)
    _build_process_parser(subparsers)
    _build_download_parser(subparsers)
    _build_config_parser(subparsers)
    _build_doctor_parser(subparsers)
    _build_style_parser(subparsers)

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

    # Synthesize / Layout / Style
    _set("synthesize.subtitle_mode", getattr(args, "subtitle_mode", None))
    _set("synthesize.quality", getattr(args, "quality", None))
    _set("synthesize.layout", getattr(args, "layout", None))
    _set("synthesize.render_mode", getattr(args, "render_mode", None))
    _set("synthesize.style", getattr(args, "style", None))
    _set("synthesize.style_override", getattr(args, "style_override", None))
    _set("synthesize.font_file", getattr(args, "font_file", None))

    # Dubbing
    _set("dubbing.preset", getattr(args, "dub_preset", None))
    _set("dubbing.provider", getattr(args, "provider", None) or getattr(args, "dub_provider", None))
    _set("dubbing.api_key", getattr(args, "tts_api_key", None))
    _set("dubbing.api_base", getattr(args, "tts_api_base", None))
    _set("dubbing.model", getattr(args, "tts_model", None))
    _set("dubbing.voice", getattr(args, "voice", None))
    _set("dubbing.style_prompt", getattr(args, "style_prompt", None))
    _set("dubbing.tts_workers", getattr(args, "tts_workers", None))
    _set("dubbing.timing", getattr(args, "timing", None))
    _set("dubbing.audio_mode", getattr(args, "audio_mode", None))
    _set("dubbing.sample_rate", getattr(args, "sample_rate", None))
    _set("dubbing.speed", getattr(args, "speed", None))
    _set("dubbing.gain", getattr(args, "gain", None))
    _set("dubbing.fit_mode", getattr(args, "fit_mode", None))
    _set("dubbing.max_speed", getattr(args, "max_speed", None))
    _set("dubbing.target_padding_ms", getattr(args, "target_padding_ms", None))
    _set("dubbing.rewrite_threshold", getattr(args, "rewrite_threshold", None))
    _set("dubbing.original_audio_volume", getattr(args, "original_audio_volume", None))
    _set("dubbing.dubbed_audio_volume", getattr(args, "dubbed_audio_volume", None))
    if getattr(args, "rewrite_too_long", False):
        _set("dubbing.rewrite_too_long", True)
    if getattr(args, "mix_original_audio", False):
        _set("dubbing.mix_original_audio", True)
    audio_mode = getattr(args, "audio_mode", None)
    if audio_mode == "replace":
        _set("dubbing.mix_original_audio", False)
    elif audio_mode == "mix":
        _set("dubbing.mix_original_audio", True)
        _set("dubbing.original_audio_volume", 0.25)
    elif audio_mode == "duck":
        _set("dubbing.mix_original_audio", True)
        _set("dubbing.original_audio_volume", 0.12)

    # Output
    _set("output.format", getattr(args, "format", None))

    return overrides


def _load_config(args: argparse.Namespace) -> dict:
    """Load config with all layers merged."""
    from videocaptioner.cli.config import build_config
    config_path = None
    if getattr(args, "config", None):
        config_path = Path(args.config)
        if not config_path.exists():
            from videocaptioner.cli import output
            output.warn(f"Config file not found: {config_path}, using defaults")
            config_path = None
    cli_overrides = _build_cli_overrides(args)
    return build_config(cli_overrides=cli_overrides, config_path=config_path)


def _run_transcribe(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.transcribe import run
    config = _load_config(args)
    return run(args, config)


def _run_gui(_args: argparse.Namespace) -> int:
    try:
        from videocaptioner.ui.main import main as gui_main
    except ImportError as exc:
        print(f"GUI dependencies are not available: {exc}")
        print("Install the official package with: pip install videocaptioner")
        return EXIT.DEPENDENCY_MISSING
    gui_main()
    return EXIT.SUCCESS


def _run_subtitle(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.subtitle import run
    config = _load_config(args)
    return run(args, config)


def _run_synthesize(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.synthesize import run
    config = _load_config(args)
    return run(args, config)


def _run_dub(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.dub import run
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


def _run_doctor(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.doctor import run
    config = _load_config(args)
    return run(args, config)


def _run_style(args: argparse.Namespace) -> int:
    from videocaptioner.cli.commands.style_cmd import run
    config = _load_config(args)
    return run(args, config)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        return _run_gui(args)

    if not hasattr(args, "func"):
        parser.print_help()
        return EXIT.USAGE_ERROR

    # Control core logger output for CLI: quiet=CRITICAL, default=WARNING, verbose=DEBUG
    import logging
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)
    if quiet:
        logging.getLogger().setLevel(logging.CRITICAL)
    elif verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

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
