"""Pre-flight validation for CLI commands.

Each validator checks that required config/dependencies are available
BEFORE starting the actual task, so users get clear error messages upfront.
"""

import shutil
from pathlib import Path

from videocaptioner.cli import output
from videocaptioner.cli.config import get

# Shared file format constants
AUDIO_EXTENSIONS = frozenset({"flac", "m4a", "mp3", "wav", "ogg", "opus", "aac", "wma"})
VIDEO_EXTENSIONS = frozenset({"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "ts", "m4v", "mpg", "mpeg"})
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".vtt"})
OUTPUT_EXTENSIONS = frozenset({".srt", ".ass", ".txt", ".json"})


def resolve_layout(cli_name: str):
    """Convert CLI layout name to SubtitleLayoutEnum."""
    from videocaptioner.core.entities import SubtitleLayoutEnum
    mapping = {
        "target-above": SubtitleLayoutEnum.TRANSLATE_ON_TOP,
        "source-above": SubtitleLayoutEnum.ORIGINAL_ON_TOP,
        "target-only": SubtitleLayoutEnum.ONLY_TRANSLATE,
        "source-only": SubtitleLayoutEnum.ONLY_ORIGINAL,
    }
    return mapping.get(cli_name, SubtitleLayoutEnum.TRANSLATE_ON_TOP)


def validate_media_input(path: Path) -> int | None:
    """Validate input is a supported audio/video file. Returns exit code on failure, None on success."""
    from videocaptioner.cli import exit_codes as EXIT
    if not path.is_file():
        output.error(f"Input is not a file: {path}")
        return EXIT.FILE_NOT_FOUND
    ext = path.suffix.lstrip(".").lower()
    if not ext or (ext not in AUDIO_EXTENSIONS and ext not in VIDEO_EXTENSIONS):
        output.error(f"Unsupported file format: {path.suffix or '(no extension)'}")
        output.hint("Supported audio: " + ", ".join(sorted(AUDIO_EXTENSIONS)))
        output.hint("Supported video: " + ", ".join(sorted(VIDEO_EXTENSIONS)))
        return EXIT.FILE_NOT_FOUND
    return None


def validate_subtitle_input(path: Path) -> int | None:
    """Validate input is a supported subtitle file. Returns exit code on failure, None on success."""
    from videocaptioner.cli import exit_codes as EXIT
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        output.error(f"Unsupported subtitle format: {path.suffix}")
        output.hint(f"Supported formats: {', '.join(sorted(SUBTITLE_EXTENSIONS))}")
        return EXIT.FILE_NOT_FOUND
    return None


def validate_video_input(path: Path) -> int | None:
    """Validate input is a video file (not audio or other). Returns exit code on failure."""
    from videocaptioner.cli import exit_codes as EXIT
    ext = path.suffix.lower()
    if ext.lstrip(".") in AUDIO_EXTENSIONS:
        output.error(f"Input is an audio file ({ext}), not a video. Cannot burn subtitles into audio.")
        output.hint("Use a video file (mp4, mkv, etc.) as input.")
        return EXIT.USAGE_ERROR
    if ext and ext.lstrip(".") not in VIDEO_EXTENSIONS:
        output.error(f"Unsupported video format: {ext}")
        output.hint(f"Supported: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        return EXIT.USAGE_ERROR
    return None


def validate_output_format(path: Path) -> int | None:
    """Validate output file extension is supported. Returns exit code on failure."""
    from videocaptioner.cli import exit_codes as EXIT
    ext = Path(path).suffix.lower()
    if ext and ext not in OUTPUT_EXTENSIONS:
        output.error(f"Unsupported output format: {ext}")
        output.hint(f"Supported: {', '.join(sorted(OUTPUT_EXTENSIONS))}")
        return EXIT.USAGE_ERROR
    return None


def validate_llm(config: dict) -> bool:
    """Validate LLM configuration (required for optimize, LLM translate, split)."""
    api_key = get(config, "llm.api_key")
    model = get(config, "llm.model")

    if not api_key:
        output.config_missing_error(
            "LLM API key",
            "llm.api_key",
            "OPENAI_API_KEY",
            "--api-key",
        )
        return False
    if not model:
        output.config_missing_error(
            "LLM model",
            "llm.model",
            "OPENAI_MODEL",
            "--model",
        )
        return False
    return True


def validate_whisper_api(config: dict) -> bool:
    """Validate Whisper API configuration."""
    api_key = get(config, "whisper_api.api_key")
    if not api_key:
        output.config_missing_error(
            "Whisper API key",
            "whisper_api.api_key",
            "VIDEOCAPTIONER_WHISPER_API_KEY",
            "--whisper-api-key",
        )
        return False
    return True


def validate_ffmpeg() -> bool:
    """Check that FFmpeg is available on PATH."""
    if not shutil.which("ffmpeg"):
        output.error("FFmpeg not found on PATH")
        output.hint("Install FFmpeg: https://ffmpeg.org/download.html")
        return False
    return True


def validate_faster_whisper() -> bool:
    """Check that FasterWhisper executable is available."""
    if not shutil.which("faster-whisper-xxl") and not shutil.which("faster-whisper") and not shutil.which("faster_whisper"):
        output.error("FasterWhisper not found on PATH")
        output.hint("Download from the GUI (Settings > FasterWhisper), or install manually.")
        output.hint("See: https://github.com/Purfview/whisper-standalone-win")
        return False
    return True


def validate_whisper_cpp() -> bool:
    """Check that WhisperCpp executable is available."""
    # Check common names for whisper.cpp binary
    names = ["whisper-cpp", "whisper", "whisper-cpp-main"]
    if not any(shutil.which(n) for n in names):
        # Also check project's bin directory
        try:
            from videocaptioner.config import BIN_PATH
            if not any((BIN_PATH / n).exists() for n in names):
                output.error("WhisperCpp not found")
                output.hint("Download from the GUI (Settings > WhisperCpp), or install manually.")
                output.hint("See: https://github.com/ggerganov/whisper.cpp")
                return False
        except ImportError:
            output.error("WhisperCpp not found on PATH")
            output.hint("See: https://github.com/ggerganov/whisper.cpp")
            return False
    return True


def validate_transcribe(config: dict) -> bool:
    """Validate config for transcribe command."""
    asr = get(config, "transcribe.asr", "faster-whisper")

    if asr == "whisper-api":
        return validate_whisper_api(config)
    if asr == "faster-whisper":
        return validate_faster_whisper()
    if asr == "whisper-cpp":
        return validate_whisper_cpp()
    # bijian/jianying: no config needed (public endpoints)
    return True


def validate_subtitle(config: dict) -> bool:
    """Validate config for subtitle command."""
    needs_llm = False

    optimize = get(config, "subtitle.optimize", True)
    translate = get(config, "subtitle.translate", False)
    translator = get(config, "translate.service", "llm")

    if optimize:
        needs_llm = True
    if translate and translator == "llm":
        needs_llm = True

    if needs_llm:
        return validate_llm(config)
    return True


def validate_synthesize(config: dict) -> bool:
    """Validate config for synthesize command."""
    return validate_ffmpeg()


def validate_process(config: dict, no_synthesize: bool = False) -> bool:
    """Validate config for full process command."""
    if not validate_transcribe(config):
        return False
    if not validate_subtitle(config):
        return False
    if not no_synthesize and not validate_ffmpeg():
        return False
    return True
