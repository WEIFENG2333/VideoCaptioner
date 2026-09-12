"""Audio helpers for dubbing timeline assembly."""

import subprocess
from pathlib import Path

from pydub import AudioSegment

from videocaptioner.core.utils.audio_io import load_audio
from videocaptioner.core.utils.media_info import probe_media


def get_audio_duration_ms(path: str) -> int:
    return len(load_audio(path))


def change_tempo(input_path: str, output_path: str, factor: float) -> None:
    """Change audio tempo without changing pitch using ffmpeg atempo."""
    factor = max(0.5, min(100.0, factor))
    filters = _atempo_filters(factor)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-filter:a",
        ",".join(filters),
        output_path,
    ]
    subprocess.run(cmd, check=True)


def create_timeline_audio(
    segments: list[tuple[str, int]],
    output_path: str,
    duration_ms: int,
    volume: float = 1.0,
) -> None:
    """Place segment audio files on a silent timeline."""
    timeline = AudioSegment.silent(duration=max(duration_ms, 1), frame_rate=48000)
    gain_db = _linear_to_db(volume)
    for audio_path, start_ms in segments:
        clip = load_audio(audio_path)
        if volume != 1.0:
            clip += gain_db
        timeline = timeline.overlay(clip, position=max(0, start_ms))
    suffix = Path(output_path).suffix.lower().lstrip(".") or "wav"
    fmt = "mp3" if suffix == "mp3" else "wav"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    timeline.export(output_path, format=fmt)


def mux_dubbed_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    *,
    mix_original_audio: bool = False,
    original_audio_volume: float = 0.25,
    dubbed_audio_volume: float = 1.0,
) -> None:
    """Replace or mix a media file's audio track with dubbed audio.

    源带视频流（mp4/mkv…）→ 复制视频 + 替换/混音音频，输出视频容器（aac）。
    源为纯音频（mp3/m4a…）→ 没有视频流可 map/copy，强行 ``-map 0:v:0`` 会让 ffmpeg
    以 exit 234 报 "Stream map '0:v:0' matches no streams"；此时只输出配音后的音频，
    编码器交给 ffmpeg 按输出扩展名自动选择。
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    info = probe_media(video_path)  # 一次探测同时拿视频/音频流有无
    has_video = info is not None and info.has_video
    mix = mix_original_audio and info is not None and info.has_audio

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_path, "-i", audio_path]
    if mix:
        cmd += [
            "-filter_complex",
            f"[0:a]volume={original_audio_volume}[a0];"
            f"[1:a]volume={dubbed_audio_volume}[a1];"
            "[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        ]
        audio_map = "[a]"
    else:
        audio_map = "1:a:0"

    if has_video:
        cmd += [
            "-map", "0:v:0",
            "-map", audio_map,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "-2",
            "-movflags", "+faststart",
        ]
    else:
        # 纯音频源：无视频流，只输出配音音频；不指定 -c:a，让 ffmpeg 按扩展名挑编码器。
        cmd += ["-map", audio_map]
    cmd.append(output_path)
    subprocess.run(cmd, check=True)


def _atempo_filters(factor: float) -> list[str]:
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return filters


def _linear_to_db(volume: float) -> float:
    if volume <= 0:
        return -120.0
    import math

    return 20 * math.log10(volume)


def _video_has_video_stream(video_path: str) -> bool:
    """探测失败时按无处理。"""
    info = probe_media(video_path)
    return info is not None and info.has_video


def _video_has_audio(video_path: str) -> bool:
    """探测失败时按无处理。"""
    info = probe_media(video_path)
    return info is not None and info.has_audio
