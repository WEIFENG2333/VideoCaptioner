"""Shared configuration helpers for subtitle dubbing."""

from __future__ import annotations

from typing import Optional

from .models import DubbingConfig, DubbingProvider, FitMode, SpeakerProfile
from .presets import get_dubbing_preset, normalize_dubbing_voice, validate_dubbing_voice


def build_dubbing_config(
    *,
    provider: str = "edge",
    preset: str = "",
    api_key: str = "",
    api_base: str = "",
    model: str = "",
    voice: str = "",
    response_format: str = "mp3",
    sample_rate: int = 32000,
    speed: float = 1.0,
    gain: float = 0,
    use_cache: bool = True,
    tts_workers: int = 5,
    style_prompt: str = "",
    timing: str = "balanced",
    audio_mode: str = "replace",
    fit_mode: Optional[str] = None,
    max_speed: float = 2.0,
    stretch_to_fit: bool = True,
    min_speed: float = 0.5,
    target_padding_ms: int = 80,
    rewrite_too_long: bool = False,
    rewrite_threshold: float = 1.15,
    llm_api_key: str = "",
    llm_api_base: str = "",
    llm_model: str = "",
    mix_original_audio: bool = False,
    original_audio_volume: float = 0.25,
    dubbed_audio_volume: float = 1.0,
    speaker_profiles: Optional[dict[str, SpeakerProfile]] = None,
) -> DubbingConfig:
    """Build a validated provider-neutral dubbing config.

    This is intentionally shared by CLI and desktop UI so provider presets,
    aliases, timing policies, and capability errors behave the same way.
    """
    resolved = resolve_dubbing_settings(
        provider=provider,
        preset=preset,
        api_base=api_base,
        model=model,
        voice=voice,
        style_prompt=style_prompt,
    )
    resolved_provider = resolve_provider(resolved["provider"])
    resolved["voice"] = normalize_dubbing_voice(
        resolved_provider,
        resolved["model"],
        resolved["voice"],
    )

    profiles = speaker_profiles or {}
    for profile in profiles.values():
        if profile.voice:
            profile.voice = normalize_dubbing_voice(
                resolved_provider,
                resolved["model"],
                profile.voice,
            )

    resolved_fit_mode, resolved_max_speed = resolve_timing(
        timing=timing,
        explicit_fit=fit_mode,
        explicit_max_speed=max_speed,
    )
    resolved_mix, resolved_original_volume = resolve_audio_mix(
        audio_mode=audio_mode,
        explicit_mix=mix_original_audio,
        explicit_volume=original_audio_volume,
    )

    config = DubbingConfig(
        provider=resolved_provider,
        api_key=api_key.strip(),
        base_url=resolved["api_base"],
        model=resolved["model"],
        voice=resolved["voice"],
        response_format=response_format,  # type: ignore[arg-type]
        sample_rate=sample_rate,
        speed=speed,
        gain=gain,
        use_cache=use_cache,
        tts_workers=tts_workers,
        style_prompt=resolved["style_prompt"],
        fit_mode=resolved_fit_mode,
        max_speed=resolved_max_speed,
        stretch_to_fit=stretch_to_fit,
        min_speed=min_speed,
        target_padding_ms=target_padding_ms,
        rewrite_too_long=rewrite_too_long,
        rewrite_threshold=rewrite_threshold,
        llm_api_key=llm_api_key,
        llm_api_base=llm_api_base,
        llm_model=llm_model,
        mix_original_audio=resolved_mix,
        original_audio_volume=resolved_original_volume,
        dubbed_audio_volume=dubbed_audio_volume,
        speaker_profiles=profiles,
    )
    error = validate_provider_capabilities(config)
    if error:
        raise ValueError(error)
    return config


def resolve_dubbing_settings(
    *,
    provider: str,
    preset: str,
    api_base: str,
    model: str,
    voice: str,
    style_prompt: str,
) -> dict[str, str]:
    resolved = {
        "provider": provider or "edge",
        "api_base": api_base or "",
        "model": model or "",
        "voice": voice or "",
        "style_prompt": style_prompt or "",
    }
    if not preset:
        return resolved

    selected = get_dubbing_preset(preset)
    default = get_dubbing_preset("edge-cn-female")
    defaults = {
        "provider": default.provider,
        "api_base": default.api_base,
        "model": default.model,
        "voice": default.voice,
        "style_prompt": "",
    }
    preset_values = {
        "provider": selected.provider,
        "api_base": selected.api_base,
        "model": selected.model,
        "voice": selected.voice,
        "style_prompt": selected.style_prompt,
    }
    for key, value in preset_values.items():
        if not resolved[key] or resolved[key] == defaults[key]:
            resolved[key] = value
    return resolved


def resolve_provider(value: str) -> DubbingProvider:
    if value == "siliconflow":
        return "siliconflow"
    if value == "gemini":
        return "gemini"
    if value == "edge":
        return "edge"
    raise ValueError(f"Unsupported dubbing provider: {value}")


def resolve_timing(
    *,
    timing: str,
    explicit_fit: Optional[str],
    explicit_max_speed: float,
) -> tuple[FitMode, float]:
    if timing == "none":
        return "none", explicit_max_speed
    fit: FitMode = "tempo" if explicit_fit not in {"tempo", "none"} else explicit_fit  # type: ignore[assignment]
    if timing == "natural":
        return fit, min(explicit_max_speed, 1.25)
    if timing == "strict":
        return fit, max(explicit_max_speed, 2.0)
    if timing != "balanced":
        raise ValueError(f"Invalid dubbing timing: {timing}")
    return fit, explicit_max_speed


def resolve_audio_mix(
    *,
    audio_mode: str,
    explicit_mix: bool,
    explicit_volume: float,
) -> tuple[bool, float]:
    if audio_mode == "replace":
        return explicit_mix, explicit_volume
    if audio_mode == "mix":
        return True, explicit_volume
    if audio_mode == "duck":
        return True, min(explicit_volume, 0.12)
    raise ValueError(f"Invalid dubbing audio mode: {audio_mode}")


def validate_provider_capabilities(config: DubbingConfig) -> str | None:
    has_clone = any(p.clone_audio_path for p in config.speaker_profiles.values())
    if config.provider == "gemini" and has_clone:
        return "Gemini TTS does not support voice cloning. Use SiliconFlow for voice cloning."
    if config.provider == "edge" and has_clone:
        return "Edge TTS does not support voice cloning. Use SiliconFlow for voice cloning."
    voice_error = validate_dubbing_voice(config.provider, config.voice)
    if voice_error:
        return voice_error
    for name, profile in config.speaker_profiles.items():
        if profile.voice:
            voice_error = validate_dubbing_voice(config.provider, profile.voice)
            if voice_error:
                return f"Speaker {name}: {voice_error}"
    return None
