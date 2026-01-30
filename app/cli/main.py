"""VideoCaptioner CLI Entry Point

Usage:
    videocaptioner process video.mp4 --translate en
    videocaptioner transcribe audio.mp3 --model bcut
    videocaptioner subtitle input.srt --translate zh --translator bing
    videocaptioner config --init
"""

import argparse
import sys
from pathlib import Path

__version__ = "1.3.3"


def print_banner(quiet: bool = False):
    """Print startup banner."""
    if quiet:
        return

    try:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print(
            Panel.fit(
                f"[bold blue]VideoCaptioner[/bold blue] v{__version__}\n"
                "[dim]AI-powered video captioning tool[/dim]",
                border_style="blue",
            )
        )
    except ImportError:
        print(f"VideoCaptioner v{__version__}")
        print("-" * 40)


def print_result(result: dict, quiet: bool = False):
    """Print processing result."""
    if quiet:
        print(result.get("subtitle", ""))
        return

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print()

        table = Table(show_header=False, box=None)
        table.add_column(style="bold")
        table.add_column()

        table.add_row("Output", result.get("subtitle", ""))
        table.add_row("Segments", str(result.get("segments", 0)))

        console.print(table)
    except ImportError:
        print("-" * 40)
        print(f"Output: {result.get('subtitle', '')}")
        print(f"Segments: {result.get('segments', 0)}")


def cmd_process(args):
    """Process command: full pipeline (transcribe + subtitle + translate)."""
    from app.cli.config import (
        TRANSLATOR_MAP,
        load_config,
        parse_target_language,
        parse_transcribe_model,
    )
    from app.cli.pipeline import (
        CLIPipeline,
        create_subtitle_config,
        create_transcribe_config,
    )

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config(config_file=args.config, **vars(args))

    print_banner(args.quiet)
    if not args.quiet:
        print(f"Input: {input_path}")

    # Determine transcribe model
    model = config.transcribe.model
    if args.model:
        parsed_model = parse_transcribe_model(args.model)
        if parsed_model:
            model = parsed_model

    # Build transcribe config
    transcribe_config = create_transcribe_config(
        model=model,
        language=args.language or config.transcribe.language,
        word_timestamps=True,
        whisper_api_key=config.whisper.api_key,
        whisper_api_base=config.whisper.base_url,
        whisper_api_model=config.whisper.model,
    )

    # Build subtitle config
    need_translate = args.translate is not None
    target_language = None
    if args.translate:
        target_language = parse_target_language(args.translate)
        if not target_language:
            print(f"Warning: Unknown language '{args.translate}', using Chinese", file=sys.stderr)
            from app.core.translate.types import TargetLanguage
            target_language = TargetLanguage.SIMPLIFIED_CHINESE

    # Determine translator service
    translator_service = config.translate.service
    if args.translator:
        service_name = args.translator.lower()
        if service_name in TRANSLATOR_MAP:
            translator_service = TRANSLATOR_MAP[service_name]

    subtitle_config = create_subtitle_config(
        need_split=not args.no_split,
        need_translate=need_translate,
        target_language=target_language,
        translator_service=translator_service,
        need_reflect=args.reflect,
        llm_model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        thread_num=args.threads or config.translate.thread_num,
        batch_size=args.batch_size or config.translate.batch_size,
    )

    # Run pipeline
    pipeline = CLIPipeline(quiet=args.quiet)
    result = pipeline.process_full(
        input_path=str(input_path),
        output_dir=args.output,
        transcribe_config=transcribe_config,
        subtitle_config=subtitle_config,
        output_format=args.format,
    )

    print_result(result, args.quiet)


def cmd_transcribe(args):
    """Transcribe command: speech recognition only."""
    from app.cli.config import load_config, parse_transcribe_model
    from app.cli.pipeline import CLIPipeline, create_transcribe_config

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config(config_file=args.config, **vars(args))

    print_banner(args.quiet)
    if not args.quiet:
        print(f"Input: {input_path}")

    # Determine model
    model = config.transcribe.model
    if args.model:
        parsed_model = parse_transcribe_model(args.model)
        if parsed_model:
            model = parsed_model
        else:
            print(f"Warning: Unknown model '{args.model}', using default", file=sys.stderr)

    transcribe_config = create_transcribe_config(
        model=model,
        language=args.language or config.transcribe.language,
        word_timestamps=not args.no_word_timestamps,
        whisper_api_key=config.whisper.api_key,
        whisper_api_base=config.whisper.base_url,
        whisper_api_model=config.whisper.model,
    )

    pipeline = CLIPipeline(quiet=args.quiet)
    asr_data = pipeline.transcribe(str(input_path), transcribe_config)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(f".{args.format}")

    # Save result
    saved_path = pipeline.save_subtitle(asr_data, str(output_path), args.format)

    print_result({"subtitle": saved_path, "segments": len(asr_data.segments)}, args.quiet)


def cmd_subtitle(args):
    """Subtitle command: process existing subtitle file."""
    from app.cli.config import TRANSLATOR_MAP, load_config, parse_target_language
    from app.cli.pipeline import CLIPipeline, create_subtitle_config
    from app.core.asr.asr_data import ASRData

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config(config_file=args.config, **vars(args))

    print_banner(args.quiet)
    if not args.quiet:
        print(f"Input: {input_path}")

    # Load subtitle
    asr_data = ASRData.from_subtitle_file(str(input_path))
    if not args.quiet:
        print(f"Loaded {len(asr_data.segments)} segments")

    # Build config
    need_translate = args.translate is not None
    target_language = None
    if args.translate:
        target_language = parse_target_language(args.translate)
        if not target_language:
            print(f"Warning: Unknown language '{args.translate}', using Chinese", file=sys.stderr)
            from app.core.translate.types import TargetLanguage
            target_language = TargetLanguage.SIMPLIFIED_CHINESE

    # Determine translator service
    translator_service = config.translate.service
    if args.translator:
        service_name = args.translator.lower()
        if service_name in TRANSLATOR_MAP:
            translator_service = TRANSLATOR_MAP[service_name]

    subtitle_config = create_subtitle_config(
        need_split=args.split,
        need_translate=need_translate,
        target_language=target_language,
        translator_service=translator_service,
        need_reflect=args.reflect,
        llm_model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        thread_num=args.threads or config.translate.thread_num,
        batch_size=args.batch_size or config.translate.batch_size,
    )

    pipeline = CLIPipeline(quiet=args.quiet)

    # Process
    if subtitle_config.need_split:
        asr_data = pipeline.split_subtitle(asr_data, subtitle_config)

    if subtitle_config.need_translate:
        asr_data = pipeline.translate_subtitle(asr_data, subtitle_config)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        suffix = "_processed" if not need_translate else f"_{args.translate}"
        output_path = input_path.with_stem(input_path.stem + suffix)

    # Save result
    saved_path = pipeline.save_subtitle(asr_data, str(output_path), args.format)

    print_result({"subtitle": saved_path, "segments": len(asr_data.segments)}, args.quiet)


def cmd_config(args):
    """Config command: manage configuration."""
    from app.cli.config import find_config_file, generate_sample_config, load_config

    if args.init:
        # Generate sample config
        config_path = Path.home() / ".videocaptioner" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists() and not args.force:
            print(f"Config file already exists: {config_path}")
            print("Use --force to overwrite")
            sys.exit(1)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(generate_sample_config())

        print(f"Created config file: {config_path}")

    elif args.show:
        # Show current configuration
        config = load_config()

        try:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(title="Current Configuration")
            table.add_column("Setting", style="cyan")
            table.add_column("Value")

            def mask_key(key):
                if not key:
                    return "(not set)"
                if len(key) <= 8:
                    return "****"
                return f"{key[:4]}...{key[-4:]}"

            table.add_row("LLM API Key", mask_key(config.llm.api_key))
            table.add_row("LLM Base URL", config.llm.base_url or "(default)")
            table.add_row("LLM Model", config.llm.model)
            table.add_row("Whisper API Key", mask_key(config.whisper.api_key))
            table.add_row("Whisper Base URL", config.whisper.base_url or "(default)")
            table.add_row("Transcribe Model", config.transcribe.model.value)
            table.add_row("Translate Service", config.translate.service.value)

            console.print(table)
        except ImportError:
            print("Current Configuration:")
            print("-" * 40)

            def mask_key(key):
                if not key:
                    return "(not set)"
                return f"***{key[-4:]}" if len(key) > 4 else "****"

            print(f"LLM API Key: {mask_key(config.llm.api_key)}")
            print(f"LLM Base URL: {config.llm.base_url}")
            print(f"LLM Model: {config.llm.model}")
            print(f"Whisper API Key: {mask_key(config.whisper.api_key)}")
            print(f"Whisper Base URL: {config.whisper.base_url}")
            print(f"Transcribe Model: {config.transcribe.model.value}")
            print(f"Translate Service: {config.translate.service.value}")

    elif args.path:
        # Show config file path
        config_file = find_config_file()
        if config_file:
            print(f"Config file: {config_file}")
        else:
            print("No config file found")
            print("Search paths:")
            print("  ./videocaptioner.yaml")
            print("  ~/.videocaptioner/config.yaml")

    else:
        # Default: show help
        print("Usage: videocaptioner config [--init|--show|--path]")
        print()
        print("Options:")
        print("  --init   Create sample config file at ~/.videocaptioner/config.yaml")
        print("  --show   Show current configuration")
        print("  --path   Show config file path")


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="videocaptioner",
        description="AI-powered video captioning tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline with free ASR (bcut) and translation (bing)
  videocaptioner process video.mp4 --model bcut --translate en --translator bing

  # Transcribe only with free ASR
  videocaptioner transcribe audio.mp3 --model bcut

  # Translate existing subtitle with free translator
  videocaptioner subtitle input.srt --translate ja --translator google

  # Initialize config
  videocaptioner config --init

Environment Variables:
  VIDEOCAPTIONER_API_KEY      LLM API key (or OPENAI_API_KEY)
  VIDEOCAPTIONER_BASE_URL     LLM API base URL
  VIDEOCAPTIONER_WHISPER_KEY  Whisper API key
  VIDEOCAPTIONER_WHISPER_URL  Whisper API base URL

Free Services (no API key required):
  ASR Models: bcut, jianying
  Translators: google, bing
        """,
    )

    parser.add_argument(
        "-v", "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "-c", "--config",
        metavar="FILE",
        help="Config file path",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output (only print result path)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Process command
    process_parser = subparsers.add_parser(
        "process",
        help="Full pipeline: transcribe + split + translate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    process_parser.add_argument("input", help="Input video/audio file")
    process_parser.add_argument("-o", "--output", help="Output directory")
    process_parser.add_argument("-f", "--format", default="srt",
                                choices=["srt", "ass", "txt", "json"],
                                help="Output format (default: srt)")
    process_parser.add_argument("-m", "--model",
                                help="ASR model: bcut, jianying, whisper-api, faster-whisper")
    process_parser.add_argument("-l", "--language", help="Source language (auto-detect if empty)")
    process_parser.add_argument("-t", "--translate", metavar="LANG",
                                help="Translate to language: zh, en, ja, ko, etc.")
    process_parser.add_argument("--translator", choices=["llm", "google", "bing", "deeplx"],
                                help="Translation service (google/bing are free)")
    process_parser.add_argument("--reflect", action="store_true",
                                help="Enable reflection for LLM translation")
    process_parser.add_argument("--no-split", action="store_true",
                                help="Disable subtitle splitting")
    process_parser.add_argument("--threads", type=int, help="Concurrent threads")
    process_parser.add_argument("--batch-size", type=int, help="Batch size")

    # Transcribe command
    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Speech recognition only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    transcribe_parser.add_argument("input", help="Input video/audio file")
    transcribe_parser.add_argument("-o", "--output", help="Output file path")
    transcribe_parser.add_argument("-f", "--format", default="srt",
                                   choices=["srt", "ass", "txt", "json"],
                                   help="Output format (default: srt)")
    transcribe_parser.add_argument("-m", "--model",
                                   help="ASR model: bcut, jianying, whisper-api, faster-whisper")
    transcribe_parser.add_argument("-l", "--language", help="Source language (auto-detect if empty)")
    transcribe_parser.add_argument("--no-word-timestamps", action="store_true",
                                   help="Disable word-level timestamps")

    # Subtitle command
    subtitle_parser = subparsers.add_parser(
        "subtitle",
        help="Process existing subtitle file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subtitle_parser.add_argument("input", help="Input subtitle file (srt, ass)")
    subtitle_parser.add_argument("-o", "--output", help="Output file path")
    subtitle_parser.add_argument("-f", "--format", default="srt",
                                 choices=["srt", "ass", "txt", "json"],
                                 help="Output format (default: srt)")
    subtitle_parser.add_argument("-t", "--translate", metavar="LANG",
                                 help="Translate to language: zh, en, ja, ko, etc.")
    subtitle_parser.add_argument("--translator", choices=["llm", "google", "bing", "deeplx"],
                                 help="Translation service (google/bing are free)")
    subtitle_parser.add_argument("--split", action="store_true", help="Enable subtitle splitting")
    subtitle_parser.add_argument("--reflect", action="store_true",
                                 help="Enable reflection for LLM translation")
    subtitle_parser.add_argument("--threads", type=int, help="Concurrent threads")
    subtitle_parser.add_argument("--batch-size", type=int, help="Batch size")

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Manage configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_parser.add_argument("--init", action="store_true", help="Create sample config file")
    config_parser.add_argument("--show", action="store_true", help="Show current configuration")
    config_parser.add_argument("--path", action="store_true", help="Show config file path")
    config_parser.add_argument("--force", action="store_true", help="Overwrite existing config")

    return parser


def main():
    """CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle version
    if args.version:
        print(f"VideoCaptioner CLI v{__version__}")
        sys.exit(0)

    # Handle no command
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Dispatch command
    try:
        if args.command == "process":
            cmd_process(args)
        elif args.command == "transcribe":
            cmd_transcribe(args)
        elif args.command == "subtitle":
            cmd_subtitle(args)
        elif args.command == "config":
            cmd_config(args)
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
