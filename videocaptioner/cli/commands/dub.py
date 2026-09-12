"""dub command -- generate dubbed audio/video from subtitles."""

import tempfile
from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.validators import (
    validate_dubbing,
    validate_subtitle_input,
    validate_video_input,
)
from videocaptioner.core.application import output_paths
from videocaptioner.core.application.config_store import get
from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline, SpeakerProfile
from videocaptioner.core.dubbing.config_builder import build_dubbing_config

# 命令行里逐条展示的超时分段警告上限，其余折叠成一行计数
_MAX_INLINE_WARNINGS = 5


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

    try:
        dub_config = _build_dubbing_config(config, speaker_profiles)
    except ValueError as exc:
        output.error(str(exc))
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

    # 变速分段等中间产物进临时目录，跑完即清；原始 TTS 分段在全局缓存里复用。
    try:
        with tempfile.TemporaryDirectory(prefix="videocaptioner-dub-") as work_dir:
            result = DubbingPipeline(dub_config).run(
                str(subtitle_path),
                str(audio_output),
                work_dir=work_dir,
                video_path=str(video_path) if video_path else None,
                output_video_path=str(video_output) if video_output else None,
                text_track=getattr(args, "text_track", None) or "auto",
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
        output.warn(f"{len(result.warnings)} segment(s) exceeded their target duration:")
        for warning in result.warnings[:_MAX_INLINE_WARNINGS]:
            output.warn(f"  {warning}")
        hidden = len(result.warnings) - _MAX_INLINE_WARNINGS
        if hidden > 0:
            output.warn(f"  ... and {hidden} more")
    if quiet:
        print(final_path)
    return EXIT.SUCCESS


def _build_dubbing_config(config: dict, speaker_profiles: dict[str, SpeakerProfile]) -> DubbingConfig:
    return build_dubbing_config(
        provider=get(config, "dubbing.provider", "edge"),
        preset=get(config, "dubbing.preset", ""),
        api_key=get(config, "dubbing.api_key", ""),
        api_base=get(config, "dubbing.api_base", ""),
        model=get(config, "dubbing.model", ""),
        voice=get(config, "dubbing.voice", ""),
        response_format=get(config, "dubbing.response_format", "mp3"),
        sample_rate=int(get(config, "dubbing.sample_rate", 32000)),
        speed=float(get(config, "dubbing.speed", 1.0)),
        gain=float(get(config, "dubbing.gain", 0)),
        use_cache=bool(get(config, "dubbing.use_cache", True)),
        tts_workers=int(get(config, "dubbing.tts_workers", 5)),
        style_prompt=get(config, "dubbing.style_prompt", ""),
        timing=get(config, "dubbing.timing", "balanced"),
        audio_mode=get(config, "dubbing.audio_mode", "replace"),
        fit_mode=get(config, "dubbing.fit_mode", None),
        max_speed=float(get(config, "dubbing.max_speed", 2.0)),
        target_padding_ms=int(get(config, "dubbing.target_padding_ms", 80)),
        rewrite_too_long=bool(get(config, "dubbing.rewrite_too_long", False)),
        rewrite_threshold=float(get(config, "dubbing.rewrite_threshold", 1.15)),
        llm_api_key=get(config, "llm.api_key", ""),
        llm_api_base=get(config, "llm.api_base", ""),
        llm_model=get(config, "llm.model", ""),
        mix_original_audio=bool(get(config, "dubbing.mix_original_audio", False)),
        original_audio_volume=float(get(config, "dubbing.original_audio_volume", 0.25)),
        dubbed_audio_volume=float(get(config, "dubbing.dubbed_audio_volume", 1.0)),
        speaker_profiles=speaker_profiles,
    )


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
    """默认输出：{stem}.dubbed.{ext}，音频与视频共用 dubbed tag。"""
    audio_arg = getattr(args, "audio_output", None)
    output_arg = getattr(args, "output", None)

    if video_path:
        video_output = (
            Path(output_arg)
            if output_arg
            else output_paths.product_path(video_path, output_paths.TAG_DUBBED)
        )
        audio_output = (
            Path(audio_arg)
            if audio_arg
            else output_paths.product_path(video_path, output_paths.TAG_DUBBED, ext=".wav")
        )
        return audio_output, video_output

    chosen_output = output_arg or audio_arg
    audio_output = (
        Path(chosen_output)
        if chosen_output
        else output_paths.product_path(subtitle_path, output_paths.TAG_DUBBED, ext=".wav")
    )
    return audio_output, None
