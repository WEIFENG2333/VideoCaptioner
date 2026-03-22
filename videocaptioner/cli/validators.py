"""Pre-flight validation for CLI commands.

Each validator checks that required config/dependencies are available
BEFORE starting the actual task, so users get clear error messages upfront.
"""

import shutil

from videocaptioner.cli import output
from videocaptioner.cli.config import get


def validate_llm(config: dict) -> bool:
    """Validate LLM configuration (required for optimize, LLM translate, split)."""
    api_key = get(config, "llm.api_key")
    model = get(config, "llm.model")

    if not api_key:
        output.config_missing_error(
            "LLM API key",
            "llm.api_key",
            "VIDEOCAPTIONER_LLM_API_KEY",
            "--api-key",
        )
        return False
    if not model:
        output.config_missing_error(
            "LLM model",
            "llm.model",
            "VIDEOCAPTIONER_LLM_MODEL",
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
