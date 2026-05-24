"""doctor command -- diagnose local dependencies and configuration."""

import json
import shutil
import subprocess
import sys
from argparse import Namespace
from dataclasses import asdict, dataclass
from datetime import date

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli.config import CONFIG_FILE, DEFAULTS, get
from videocaptioner.core.dubbing.presets import (
    get_dubbing_preset,
    normalize_dubbing_voice,
    validate_dubbing_voice,
)


@dataclass
class Check:
    name: str
    status: str
    message: str
    fix: str = ""


def run(args: Namespace, config: dict) -> int:
    checks = _run_checks(config, check_api=bool(getattr(args, "check_api", False)))
    if getattr(args, "json", False):
        print(json.dumps({"checks": [asdict(c) for c in checks]}, ensure_ascii=False, indent=2))
    else:
        _print_checks(checks)
    return EXIT.DEPENDENCY_MISSING if any(c.status == "error" for c in checks) else EXIT.SUCCESS


def _run_checks(config: dict, *, check_api: bool = False) -> list[Check]:
    checks: list[Check] = []
    checks.append(_check_python())
    checks.append(_check_command("ffmpeg", "Required for audio extraction, timing fit, muxing, and hard subtitles."))
    checks.append(_check_command("ffprobe", "Required for media duration checks."))
    checks.append(_check_ytdlp())
    checks.append(_check_config_file())
    checks.extend(_check_transcribe(config))
    checks.extend(_check_subtitle(config))
    checks.extend(_check_dubbing(config))
    if check_api:
        checks.extend(_check_api(config))
    return checks


def _check_python() -> Check:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if (3, 10) <= sys.version_info[:2] < (3, 13):
        return Check("python", "ok", f"Python {version}")
    return Check("python", "error", f"Python {version} is unsupported", "Use Python >=3.10,<3.13")


def _check_command(name: str, purpose: str) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(name, "error", f"{name} not found. {purpose}", f"Install {name} and make sure it is on PATH")
    version = _command_version(name)
    return Check(name, "ok", f"{path}" + (f" ({version})" if version else ""))


def _check_ytdlp() -> Check:
    path = shutil.which("yt-dlp")
    if not path:
        return Check("yt-dlp", "error", "yt-dlp not found. Required by videocaptioner download.", "Install yt-dlp and make sure it is on PATH")
    version = _command_version("yt-dlp")
    if version and _yt_dlp_version_is_old(version):
        return Check("yt-dlp", "warn", f"{path} ({version}) may be old", "Update yt-dlp if online downloads fail")
    return Check("yt-dlp", "ok", f"{path}" + (f" ({version})" if version else ""))


def _yt_dlp_version_is_old(version: str) -> bool:
    try:
        year, month, _day = [int(part) for part in version.split(".")[:3]]
        release_date = date(year, month, _day)
    except Exception:
        return False
    # Stable yt-dlp versions are date-like.
    return (date.today() - release_date).days > 90


def _command_version(name: str) -> str:
    try:
        result = subprocess.run([name, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0][:100]
    except Exception:
        pass
    try:
        result = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0][:100]
    except Exception:
        pass
    return ""


def _check_config_file() -> Check:
    if CONFIG_FILE.exists():
        return Check("config.file", "ok", str(CONFIG_FILE))
    return Check(
        "config.file",
        "warn",
        f"Config file does not exist: {CONFIG_FILE}",
        "Run 'videocaptioner config init' or set values with environment variables",
    )


def _check_transcribe(config: dict) -> list[Check]:
    asr = get(config, "transcribe.asr", "bijian")
    checks = [Check("transcribe.asr", "ok", f"default ASR: {asr}")]
    if asr == "whisper-api" and not get(config, "whisper_api.api_key", ""):
        checks.append(Check("whisper_api.api_key", "error", "Whisper API key is missing", "Run 'videocaptioner config set whisper_api.api_key <key>'"))
    if asr == "whisper-cpp" and not any(shutil.which(n) for n in ["whisper-cpp", "whisper", "whisper-cpp-main"]):
        checks.append(Check("whisper-cpp", "error", "whisper.cpp binary not found", "Install whisper.cpp or choose --asr bijian/whisper-api"))
    return checks


def _check_subtitle(config: dict) -> list[Check]:
    checks: list[Check] = []
    optimize = bool(get(config, "subtitle.optimize", True))
    split = bool(get(config, "subtitle.split", True))
    translator = get(config, "translate.service", "bing")
    needs_llm = optimize or split or translator == "llm"
    checks.append(Check("subtitle.processing", "ok", f"ai_polish={optimize}, split={split}, translator={translator}"))
    if needs_llm and not get(config, "llm.api_key", ""):
        checks.append(Check("llm.api_key", "warn", "LLM API key is missing; AI polish/split/LLM translation will fail", "Run 'videocaptioner config set llm.api_key <key>' or disable AI polish/split"))
    if needs_llm and not get(config, "llm.model", ""):
        checks.append(Check("llm.model", "error", "LLM model is missing", "Run 'videocaptioner config set llm.model <model>'"))
    return checks


def _check_dubbing(config: dict) -> list[Check]:
    checks: list[Check] = []
    preset_name = get(config, "dubbing.preset", "")
    provider = get(config, "dubbing.provider", "siliconflow")
    model = get(config, "dubbing.model", "")
    voice = get(config, "dubbing.voice", "")
    if preset_name:
        try:
            preset = get_dubbing_preset(preset_name)
            provider, model = preset.provider, preset.model
            if not voice or voice == DEFAULTS["dubbing"]["voice"]:
                voice = preset.voice
            checks.append(Check("dubbing.preset", "ok", f"{preset_name} ({provider})"))
        except ValueError as exc:
            checks.append(Check("dubbing.preset", "error", str(exc), "Choose one of the presets shown in 'videocaptioner dub --help'"))
    else:
        checks.append(Check("dubbing.preset", "warn", "No dubbing preset configured", "Run 'videocaptioner config set dubbing.preset siliconflow-cn-female'"))
    if not get(config, "dubbing.api_key", ""):
        checks.append(Check("dubbing.api_key", "warn", "Dubbing TTS API key is missing", "Run 'videocaptioner config set dubbing.api_key <key>'"))
    if provider not in {"siliconflow", "gemini"}:
        checks.append(Check("dubbing.provider", "error", f"Unsupported provider: {provider}", "Use siliconflow or gemini"))
    normalized_voice = normalize_dubbing_voice(provider, model, voice)
    voice_error = validate_dubbing_voice(provider, normalized_voice)
    if voice_error:
        checks.append(Check("dubbing.voice", "error", voice_error, "Use a preset or a provider-supported voice"))
    else:
        checks.append(Check("dubbing.voice", "ok", normalized_voice or "(provider default)"))
    timing = get(config, "dubbing.timing", "balanced")
    audio_mode = get(config, "dubbing.audio_mode", "replace")
    if timing not in {"balanced", "strict", "natural", "none"}:
        checks.append(Check("dubbing.timing", "error", f"Invalid timing: {timing}", "Use balanced, strict, natural, or none"))
    if audio_mode not in {"replace", "mix", "duck"}:
        checks.append(Check("dubbing.audio_mode", "error", f"Invalid audio mode: {audio_mode}", "Use replace, mix, or duck"))
    return checks


def _check_api(config: dict) -> list[Check]:
    checks: list[Check] = []
    if not get(config, "dubbing.api_key", ""):
        return checks
    checks.append(Check("api.dubbing", "warn", "--check-api is currently limited to configuration validation", "Run a short 'videocaptioner dub sample.srt' to verify billing/provider access"))
    return checks


def _print_checks(checks: list[Check]) -> None:
    for check in checks:
        prefix = {"ok": "OK", "warn": "WARN", "error": "ERROR"}.get(check.status, check.status.upper())
        print(f"{prefix:5} {check.name}: {check.message}")
        if check.fix:
            print(f"      fix: {check.fix}")
    errors = sum(1 for c in checks if c.status == "error")
    warnings = sum(1 for c in checks if c.status == "warn")
    if errors:
        print(f"ERROR Doctor found {errors} error(s) and {warnings} warning(s)")
    elif warnings:
        print(f"WARN  Doctor found {warnings} warning(s)")
    else:
        print("OK    Doctor found no issues")
