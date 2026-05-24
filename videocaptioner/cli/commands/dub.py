"""dub command -- generate dubbed audio/video from subtitles."""

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import get
from videocaptioner.cli.validators import (
    validate_dubbing,
    validate_subtitle_input,
    validate_video_input,
)
from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline, SpeakerProfile
from videocaptioner.core.dubbing.models import DubbingProvider, FitMode
from videocaptioner.core.dubbing.presets import (
    get_dubbing_preset,
    normalize_dubbing_voice,
    validate_dubbing_voice,
)


def run(args: Namespace, config: dict) -> int:
    subtitle_path = Path(args.subtitle)
    if not subtitle_path.exists():
        output.error(f"Subtitle file not found: {subtitle_path}")
        return EXIT.FILE_NOT_FOUND
    if subtitle_path.suffix.lower() != ".json" and validate_subtitle_input(subtitle_path) is not None:
        return EXIT.FILE_NOT_FOUND

    video_path = Path(args.video) if getattr(args, "video", None) else None
    if video_path:
        if not video_path.exists():
            output.error(f"Video file not found: {video_path}")
            return EXIT.FILE_NOT_FOUND
        err = validate_video_input(video_path)
        if err is not None:
            return err

    rewrite = bool(get(config, "dubbing.rewrite_too_long", False))
    if not validate_dubbing(config, needs_video=bool(video_path), rewrite=rewrite):
        return EXIT.DEPENDENCY_MISSING

    try:
        speaker_profiles = _build_speaker_profiles(args)
        _apply_config_speaker_profiles(config, speaker_profiles)
    except ValueError as exc:
        output.error(str(exc))
        return EXIT.USAGE_ERROR

    dub_config = _build_dubbing_config(config, speaker_profiles)
    capability_error = _validate_provider_capabilities(dub_config)
    if capability_error:
        output.error(capability_error)
        return EXIT.USAGE_ERROR

    audio_output, video_output = _resolve_outputs(args, subtitle_path, video_path)

    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)
    progress = None if quiet else output.ProgressLine("Dubbing subtitles").start()
    last_logged_bucket = -1

    def progress_callback(percent: int, message: str) -> None:
        nonlocal last_logged_bucket
        if progress:
            progress.update(percent, message)
        if verbose and not quiet:
            bucket = percent // 5
            if bucket != last_logged_bucket or percent >= 88:
                last_logged_bucket = bucket
                output.info(f"Dubbing progress: {percent}% - {message}")

    try:
        result = DubbingPipeline(dub_config).run(
            str(subtitle_path),
            str(audio_output),
            video_path=str(video_path) if video_path else None,
            output_video_path=str(video_output) if video_output else None,
            text_track=getattr(args, "text_track", None) or "auto",
            work_dir=str(audio_output.with_suffix("").with_name(audio_output.stem + "_parts")),
            callback=progress_callback,
        )
    except Exception as exc:
        msg = output.clean_error(str(exc))
        if progress:
            progress.fail(msg)
        else:
            output.error(msg)
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        return EXIT.RUNTIME_ERROR

    final_path = result.video_path or result.audio_path
    if progress:
        progress.finish(f"Done -> {final_path}")
    if result.warnings and not quiet:
        output.warn(f"{len(result.warnings)} segment(s) exceeded their target duration; see {result.audio_path.with_suffix('.dubbing.json')}")
    if quiet:
        print(final_path)
    return EXIT.SUCCESS


def _build_dubbing_config(config: dict, speaker_profiles: dict[str, SpeakerProfile]) -> DubbingConfig:
    resolved = _resolve_dubbing_settings(config)
    provider = _resolve_provider(resolved["provider"])
    resolved["voice"] = normalize_dubbing_voice(provider, resolved["model"], resolved["voice"])
    for profile in speaker_profiles.values():
        if profile.voice:
            profile.voice = normalize_dubbing_voice(provider, resolved["model"], profile.voice)
    fit_mode, max_speed = _resolve_timing(config)
    mix_original_audio, original_audio_volume = _resolve_audio_mix(config)
    return DubbingConfig(
        provider=provider,
        api_key=get(config, "dubbing.api_key", ""),
        base_url=resolved["api_base"],
        model=resolved["model"],
        voice=resolved["voice"],
        response_format=get(config, "dubbing.response_format", "mp3"),
        sample_rate=int(get(config, "dubbing.sample_rate", 32000)),
        speed=float(get(config, "dubbing.speed", 1.0)),
        gain=float(get(config, "dubbing.gain", 0)),
        use_cache=bool(get(config, "dubbing.use_cache", True)),
        tts_workers=int(get(config, "dubbing.tts_workers", 5)),
        style_prompt=resolved["style_prompt"],
        fit_mode=fit_mode,
        max_speed=max_speed,
        target_padding_ms=int(get(config, "dubbing.target_padding_ms", 80)),
        rewrite_too_long=bool(get(config, "dubbing.rewrite_too_long", False)),
        rewrite_threshold=float(get(config, "dubbing.rewrite_threshold", 1.15)),
        llm_api_key=get(config, "llm.api_key", ""),
        llm_api_base=get(config, "llm.api_base", ""),
        llm_model=get(config, "llm.model", ""),
        mix_original_audio=mix_original_audio,
        original_audio_volume=original_audio_volume,
        dubbed_audio_volume=float(get(config, "dubbing.dubbed_audio_volume", 1.0)),
        speaker_profiles=speaker_profiles,
    )


def _resolve_dubbing_settings(config: dict) -> dict[str, str]:
    preset_name = get(config, "dubbing.preset", "")
    resolved = {
        "provider": get(config, "dubbing.provider", "siliconflow"),
        "api_base": get(config, "dubbing.api_base", ""),
        "model": get(config, "dubbing.model", ""),
        "voice": get(config, "dubbing.voice", ""),
        "style_prompt": get(config, "dubbing.style_prompt", ""),
    }
    if not preset_name:
        return resolved

    preset = get_dubbing_preset(preset_name)
    defaults = {
        "provider": get_dubbing_preset("siliconflow-cn-male").provider,
        "api_base": get_dubbing_preset("siliconflow-cn-male").api_base,
        "model": get_dubbing_preset("siliconflow-cn-male").model,
        "voice": get_dubbing_preset("siliconflow-cn-male").voice,
        "style_prompt": "",
    }
    preset_values = {
        "provider": preset.provider,
        "api_base": preset.api_base,
        "model": preset.model,
        "voice": preset.voice,
        "style_prompt": preset.style_prompt,
    }
    for key, value in preset_values.items():
        if not resolved[key] or resolved[key] == defaults[key]:
            resolved[key] = value
    return resolved


def _resolve_provider(value: str) -> DubbingProvider:
    if value == "siliconflow" or value == "gemini":
        return value
    raise ValueError(f"Unsupported dubbing provider: {value}")


def _resolve_timing(config: dict) -> tuple[FitMode, float]:
    timing = get(config, "dubbing.timing", "balanced")
    explicit_fit = get(config, "dubbing.fit_mode", None)
    explicit_max_speed = float(get(config, "dubbing.max_speed", 2.0))
    if timing == "none":
        return "none", explicit_max_speed
    fit_mode: FitMode = "tempo" if explicit_fit not in {"tempo", "none"} else explicit_fit
    if timing == "natural":
        return fit_mode, min(explicit_max_speed, 1.25)
    if timing == "strict":
        return fit_mode, max(explicit_max_speed, 2.0)
    return fit_mode, explicit_max_speed


def _resolve_audio_mix(config: dict) -> tuple[bool, float]:
    audio_mode = get(config, "dubbing.audio_mode", "replace")
    explicit_mix = bool(get(config, "dubbing.mix_original_audio", False))
    explicit_volume = float(get(config, "dubbing.original_audio_volume", 0.25))
    if audio_mode == "replace":
        return explicit_mix, explicit_volume
    if audio_mode == "mix":
        return True, explicit_volume
    if audio_mode == "duck":
        return True, min(explicit_volume, 0.12)
    return explicit_mix, explicit_volume


def _validate_provider_capabilities(config: DubbingConfig) -> str | None:
    if config.provider == "gemini" and any(p.clone_audio_path for p in config.speaker_profiles.values()):
        return "Gemini TTS does not support voice cloning. Use a SiliconFlow preset/provider for --clone-audio or --speaker-clone."
    voice_error = validate_dubbing_voice(config.provider, config.voice)
    if voice_error:
        return voice_error
    for name, profile in config.speaker_profiles.items():
        if profile.voice:
            voice_error = validate_dubbing_voice(config.provider, profile.voice)
            if voice_error:
                return f"Speaker {name}: {voice_error}"
    return None


def _apply_config_speaker_profiles(config: dict, profiles: dict[str, SpeakerProfile]) -> None:
    configured = get(config, "dubbing.speakers", {})
    if not isinstance(configured, dict):
        raise ValueError("dubbing.speakers must be a table/object")
    for name, values in configured.items():
        if not isinstance(values, dict):
            raise ValueError(f"dubbing.speakers.{name} must be a table/object")
        profile = profiles.setdefault(name, SpeakerProfile(name=name))
        if values.get("voice") and not profile.voice:
            profile.voice = str(values["voice"])
        if values.get("clone_audio") and not profile.clone_audio_path:
            profile.clone_audio_path = str(values["clone_audio"])
        if values.get("clone_text") and not profile.clone_audio_text:
            profile.clone_audio_text = str(values["clone_text"])
        if values.get("style_prompt") and not profile.style_prompt:
            profile.style_prompt = str(values["style_prompt"])


def _build_speaker_profiles(args: Namespace) -> dict[str, SpeakerProfile]:
    profiles: dict[str, SpeakerProfile] = {}
    clone_audio = getattr(args, "clone_audio", None)
    clone_text = getattr(args, "clone_text", None)
    if clone_audio or clone_text:
        if not clone_audio or not clone_text:
            raise ValueError("--clone-audio and --clone-text must be provided together")
        profile = profiles.setdefault("default", SpeakerProfile(name="default"))
        profile.clone_audio_path = clone_audio
        profile.clone_audio_text = clone_text
    for item in getattr(args, "speaker_voice", []) or []:
        name, value = _split_mapping(item, "--speaker-voice")
        profile = profiles.setdefault(name, SpeakerProfile(name=name))
        profile.voice = value
    for item in getattr(args, "speaker_style", []) or []:
        name, value = _split_mapping(item, "--speaker-style")
        profile = profiles.setdefault(name, SpeakerProfile(name=name))
        profile.style_prompt = value
    for item in getattr(args, "speaker_clone", []) or []:
        name, value = _split_mapping(item, "--speaker-clone")
        if "|" not in value:
            raise ValueError("--speaker-clone must use NAME=AUDIO|TEXT")
        audio_path, transcript = value.split("|", 1)
        profile = profiles.setdefault(name, SpeakerProfile(name=name))
        profile.clone_audio_path = audio_path
        profile.clone_audio_text = transcript
    return profiles


def _split_mapping(raw: str, flag: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"{flag} must use NAME=VALUE")
    name, value = raw.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not name or not value:
        raise ValueError(f"{flag} must use non-empty NAME=VALUE")
    return name, value


def _resolve_outputs(
    args: Namespace,
    subtitle_path: Path,
    video_path: Path | None,
) -> tuple[Path, Path | None]:
    audio_arg = getattr(args, "audio_output", None)
    output_arg = getattr(args, "output", None)

    if video_path:
        video_output = Path(output_arg) if output_arg else video_path.with_stem(video_path.stem + "_dubbed")
        audio_output = Path(audio_arg) if audio_arg else video_output.with_suffix(".dub.wav")
        return audio_output, video_output

    chosen_output = output_arg or audio_arg
    audio_output = Path(chosen_output) if chosen_output else subtitle_path.with_suffix(".dub.wav")
    return audio_output, None
