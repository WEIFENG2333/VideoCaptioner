"""doctor command -- diagnose local dependencies and configuration."""

import json
import shutil
import subprocess
import sys
import tempfile
from argparse import Namespace
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.core.application.config_store import CONFIG_FILE, DEFAULTS, get
from videocaptioner.core.dubbing import build_dubbing_config
from videocaptioner.core.dubbing.presets import (
    get_dubbing_preset,
    normalize_dubbing_voice,
    validate_dubbing_voice,
)
from videocaptioner.core.speech import (
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)
from videocaptioner.core.subtitle.ass_renderer import ffmpeg_supports_ass_filter


@dataclass
class Check:
    name: str
    status: str
    message: str
    fix: str = ""


def run(args: Namespace, config: dict) -> int:
    checks = run_diagnostics(config, check_api=bool(getattr(args, "check_api", False)))
    if getattr(args, "json", False):
        print(json.dumps({"checks": [asdict(c) for c in checks]}, ensure_ascii=False, indent=2))
    else:
        _print_checks(checks)
    return EXIT.DEPENDENCY_MISSING if any(c.status == "error" for c in checks) else EXIT.SUCCESS


def run_diagnostics(
    config: dict, *, check_api: bool = False, check_download: bool = False
) -> list[Check]:
    checks: list[Check] = []
    checks.append(_check_python())
    checks.append(_check_command("ffmpeg", "Required for audio extraction, media probing, timing fit, muxing, and hard subtitles."))
    checks.append(_check_ytdlp())
    checks.append(_check_config_file())
    checks.extend(_check_transcribe(config))
    checks.extend(_check_subtitle(config))
    checks.extend(_check_dubbing(config))
    checks.extend(_check_live_caption(config))
    if check_api or check_download:
        checks.extend(_check_download_sources())
    if check_api:
        checks.extend(_check_api(config))
    return checks


def _check_download_sources() -> list[Check]:
    """Resolve one stable public video per source (real network requests)."""
    from videocaptioner.core.download import DOWNLOAD_SOURCES, check_download_sources

    hints = {source.key: source.fix_hint for source in DOWNLOAD_SOURCES}
    checks = []
    for result in check_download_sources():
        if result.success:
            checks.append(Check(
                f"api.download.{result.key}", "ok",
                f"{result.title}: 解析成功（{result.detail[:48]}）",
            ))
        else:
            # friendly 文案可能已带站点主语（如「哔哩哔哩风控…」），避免重复前缀
            message = (
                result.detail
                if result.detail.startswith(result.title)
                else f"{result.title}: {result.detail}"
            )
            checks.append(Check(
                f"api.download.{result.key}", "error",
                message,
                hints.get(result.key, ""),
            ))
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
    if path:
        version = _command_version("yt-dlp")
        if version and _yt_dlp_version_is_old(version):
            return Check("yt-dlp", "warn", f"{path} ({version}) may be old", "Update yt-dlp if online downloads fail")
        return Check("yt-dlp", "ok", f"{path}" + (f" ({version})" if version else ""))
    try:
        import yt_dlp
        import yt_dlp.version

        version = getattr(yt_dlp.version, "__version__", "")
        return Check("yt-dlp", "ok", "embedded yt_dlp module" + (f" ({version})" if version else ""))
    except Exception:
        return Check("yt-dlp", "error", "yt-dlp not found. Required by videocaptioner download.", "Install yt-dlp and make sure it is on PATH")


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
        result = subprocess.run([name, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0][:100]
    except Exception:
        pass
    try:
        result = subprocess.run([name, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
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
    if asr == "fun-asr" and not get(config, "fun_asr.api_key", ""):
        checks.append(Check("fun_asr.api_key", "error", "Bailian Fun-ASR API key is missing", "Run 'videocaptioner config set fun_asr.api_key <key>'"))
    if asr == "whisper-cpp":
        checks.extend(_check_local_program("whisper-cpp"))
        checks.extend(_check_local_model("whisper-cpp", get(config, "transcribe.whisper_cpp.model", "tiny")))
    if asr == "faster-whisper":
        checks.extend(_check_local_program("faster-whisper"))
        checks.extend(_check_local_model("faster-whisper", get(config, "transcribe.faster_whisper.model", "tiny")))
    return checks


def _check_local_program(kind: str) -> list[Check]:
    from videocaptioner.core.download import detect_program, program_install_plan

    status = detect_program(kind)
    if status.installed:
        return [Check(f"{kind}.program", "ok", f"{status.name} ({status.path})")]
    plan = program_install_plan(kind)
    hint = plan.command or plan.summary
    return [Check(f"{kind}.program", "error", f"{kind} program not found", hint)]


def _check_local_model(kind: str, model_name: str) -> list[Check]:
    from videocaptioner.config import MODEL_PATH
    from videocaptioner.core.download import find_model, model_install_state

    spec = find_model(kind, str(model_name))
    if spec is None:
        return [Check(f"{kind}.model", "warn", f"Unknown model name: {model_name}", "Run 'videocaptioner models list' to see available models")]
    if model_install_state(spec, Path(MODEL_PATH)):
        return [Check(f"{kind}.model", "ok", f"model '{spec.name}' installed in {MODEL_PATH}")]
    return [
        Check(
            f"{kind}.model",
            "error",
            f"model '{spec.name}' is not downloaded",
            f"Run 'videocaptioner models download {kind} {spec.name}'",
        )
    ]


def _check_subtitle(config: dict) -> list[Check]:
    checks: list[Check] = []
    optimize = bool(get(config, "subtitle.optimize", True))
    split = bool(get(config, "subtitle.split", True))
    render_mode = str(get(config, "subtitle.render_mode", "ass"))
    translator = get(config, "translate.service", "bing")
    needs_llm = optimize or split or translator == "llm"
    checks.append(Check("subtitle.processing", "ok", f"ai_polish={optimize}, split={split}, translator={translator}"))
    if _is_ass_render_mode(render_mode) and shutil.which("ffmpeg"):
        if ffmpeg_supports_ass_filter():
            checks.append(Check("ffmpeg.ass_filter", "ok", "FFmpeg supports ASS hard-subtitle rendering"))
        else:
            checks.append(
                Check(
                    "ffmpeg.ass_filter",
                    "error",
                    "当前 FFmpeg 不支持 ASS 硬字幕渲染",
                    "安装带 libass 的完整 FFmpeg，或在字幕样式里切换为圆角背景",
                )
            )
    if needs_llm and not get(config, "llm.api_key", ""):
        checks.append(Check("llm.api_key", "warn", "LLM API key is missing; AI polish/split/LLM translation will fail", "Run 'videocaptioner config set llm.api_key <key>' or disable AI polish/split"))
    if needs_llm and not get(config, "llm.model", ""):
        checks.append(Check("llm.model", "error", "LLM model is missing", "Run 'videocaptioner config set llm.model <model>'"))
    return checks


def _is_ass_render_mode(render_mode: str) -> bool:
    normalized = render_mode.strip().lower()
    return normalized in {"ass", "ass_style", "ass-style", "ass 样式", "ass样式"}


def _check_dubbing(config: dict) -> list[Check]:
    checks: list[Check] = []
    preset_name = get(config, "dubbing.preset", "")
    provider = get(config, "dubbing.provider", "edge")
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
        checks.append(Check("dubbing.preset", "warn", "No dubbing preset configured", "Run 'videocaptioner config set dubbing.preset edge-cn-female'"))
    if provider != "edge" and not get(config, "dubbing.api_key", ""):
        checks.append(Check("dubbing.api_key", "warn", "Dubbing TTS API key is missing", "Run 'videocaptioner config set dubbing.api_key <key>'"))
    if provider not in {"siliconflow", "gemini", "edge"}:
        checks.append(Check("dubbing.provider", "error", f"Unsupported provider: {provider}", "Use siliconflow, gemini, or edge"))
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


def _check_live_caption(config: dict) -> list[Check]:
    """实时字幕（Live Caption）后端可用性。

    按 provider 分流：① fun-asr → 检查百炼 API Key 是否填了；② voxgate → 检测 voxgate
    二进制是否能找到（配置路径 → 自带 bin → 用户 bin → PATH，同 ``find_voxgate_binary``
    的真实发现顺序；voxgate 走 ``voxgate transcribe`` 子进程 stdio，不再有本地服务）。

    实时字幕是可选功能，缺失只给 ``warn``（不影响主字幕流程，doctor 不因此失败）。
    """
    provider = get(config, "live_caption.provider", "voxgate")
    if provider == "fun-asr":
        # 云后端：检查百炼 API Key 是否填了（联网探活留给「测试转录」，doctor 不刷接口）
        if get(config, "live_caption.api_key", "").strip():
            return [Check("live_caption.funasr", "ok", "Fun-ASR 实时：已配置百炼 API Key")]
        return [
            Check(
                "live_caption.funasr",
                "warn",
                "Fun-ASR 实时缺少百炼 API Key；实时字幕将无法启动（不影响其它功能）",
                "在 设置 → 实时字幕配置 填入阿里云百炼 API Key",
            )
        ]
    from videocaptioner.core.realtime.backends.voxgate import find_voxgate_binary

    configured = get(config, "live_caption.voxgate_binary", "").strip()
    binary = find_voxgate_binary(configured)
    if binary:
        return [Check("live_caption.voxgate", "ok", f"voxgate 转录程序已就绪：{binary}")]
    return [
        Check(
            "live_caption.voxgate",
            "warn",
            "未找到 voxgate 转录程序；实时字幕将无法启动（不影响其它功能）",
            "在 设置 → 实时字幕配置 指定 voxgate 路径，或把 voxgate 放到 PATH / resource/bin",
        )
    ]


def _check_api(config: dict) -> list[Check]:
    checks: list[Check] = []
    checks.extend(_check_api_transcribe(config))
    provider = get(config, "dubbing.provider", "edge")
    if provider != "edge" and not get(config, "dubbing.api_key", ""):
        checks.append(Check("api.dubbing", "warn", "Skipped real TTS request because dubbing API key is missing", "Run 'videocaptioner config set dubbing.api_key <key>'"))
        return checks
    try:
        preset_name = get(config, "dubbing.preset", "edge-cn-female")
        preset = get_dubbing_preset(preset_name)
        core_config = build_dubbing_config(
            provider=preset.provider,
            preset=preset_name,
            api_key=get(config, "dubbing.api_key", ""),
            api_base=get(config, "dubbing.api_base", "") or preset.api_base,
            model=get(config, "dubbing.model", "") or preset.model,
            voice=get(config, "dubbing.voice", "") or preset.voice,
            style_prompt=preset.style_prompt,
            tts_workers=1,
        )
        response_format = core_config.response_format
        if core_config.provider == "gemini":
            response_format = "wav"
        elif core_config.provider == "edge":
            response_format = "mp3"
        synthesizer = create_speech_synthesizer(
            SpeechProviderConfig(
                provider=core_config.provider,
                api_key=core_config.api_key,
                base_url=core_config.base_url,
                model=core_config.model,
                default_voice=core_config.voice,
                response_format=response_format,
                sample_rate=core_config.sample_rate,
                speed=core_config.speed,
                gain=core_config.gain,
                timeout=core_config.timeout,
                style_prompt=core_config.style_prompt,
            )
        )
        output = Path(tempfile.mkdtemp(prefix="videocaptioner-doctor-")) / "tts-preview.wav"
        result = synthesizer.synthesize(
            SynthesisRequest(
                text="你好，这是卡卡字幕助手的配音诊断。",
                output_path=str(output),
                voice=core_config.voice,
                style_prompt=core_config.style_prompt or None,
            )
        )
        size = Path(result.output_path).stat().st_size
        checks.append(Check("api.dubbing", "ok", f"Real TTS request succeeded: {core_config.provider}, {size} bytes"))
    except Exception as exc:
        checks.append(Check("api.dubbing", "error", f"Real TTS request failed: {exc}", "Open Settings > Dubbing and verify provider, API Key, Base URL, model, and voice"))
    return checks


def _check_api_transcribe(config: dict) -> list[Check]:
    """Run a real short-audio transcription with the configured ASR provider.

    Shares core.asr.check.check_transcribe with the Settings page test button.
    """
    asr = get(config, "transcribe.asr", "bijian")
    if asr == "whisper-api" and not get(config, "whisper_api.api_key", ""):
        return [Check("api.transcribe", "warn", "Skipped real ASR request because Whisper API key is missing", "Run 'videocaptioner config set whisper_api.api_key <key>'")]
    if asr == "fun-asr" and not get(config, "fun_asr.api_key", ""):
        return [Check("api.transcribe", "warn", "Skipped real ASR request because Bailian Fun-ASR API key is missing", "Run 'videocaptioner config set fun_asr.api_key <key>'")]
    try:
        from videocaptioner.cli.config_adapter import app_config_from_cli
        from videocaptioner.core.application import TaskBuilder
        from videocaptioner.core.asr.check import check_transcribe

        transcribe_config = TaskBuilder(
            app_config_from_cli(config)
        ).create_transcribe_config(need_word_timestamp=False)
        result = check_transcribe(transcribe_config)
    except Exception as exc:
        return [Check("api.transcribe", "error", f"Real ASR request failed: {exc}", "Open Settings > Transcribe and verify the provider configuration")]
    if result.success:
        return [Check("api.transcribe", "ok", f"Real ASR request succeeded: {asr}, recognized: {result.detail[:60]}")]
    return [Check("api.transcribe", "error", f"Real ASR request failed: {result.detail}", "Open Settings > Transcribe and verify the provider configuration")]


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
