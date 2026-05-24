"""Audio helpers for dubbing timeline assembly."""

import json
import subprocess
from pathlib import Path

from pydub import AudioSegment


def get_audio_duration_ms(path: str) -> int:
    audio = AudioSegment.from_file(path)
    return len(audio)


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
        clip = AudioSegment.from_file(audio_path)
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
    """Replace or mix a video's audio track with dubbed audio."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if mix_original_audio and _video_has_audio(video_path):
        filter_complex = (
            f"[0:a]volume={original_audio_volume}[a0];"
            f"[1:a]volume={dubbed_audio_volume}[a1];"
            "[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0[a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-strict",
            "-2",
            "-movflags",
            "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-strict",
            "-2",
            "-movflags",
            "+faststart",
            output_path,
        ]
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


def _video_has_audio(video_path: str) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout or "{}")
    return bool(data.get("streams"))
