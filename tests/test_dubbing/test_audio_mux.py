"""mux_dubbed_audio 回归：源为纯音频（mp3/wav 等无视频流）时不能崩。

历史 bug：mux 恒 ``-map 0:v:0``，对纯音频源 ffmpeg 以 exit 234 报
"Stream map '0:v:0' matches no streams"，导致对 mp3 配音整条失败。
"""

import shutil
import subprocess

import pytest
from pydub import AudioSegment

from videocaptioner.core.dubbing.audio import (
    _video_has_audio,
    _video_has_video_stream,
    mux_dubbed_audio,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg/ffprobe on PATH",
)


def _stream_types(path: str) -> set[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True,
        text=True,
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


@pytest.fixture
def audio_only_source(tmp_path):
    src = tmp_path / "source.mp3"
    AudioSegment.silent(duration=1500, frame_rate=24000).export(str(src), format="mp3")
    dub = tmp_path / "dubbed.wav"
    AudioSegment.silent(duration=1500, frame_rate=24000).export(str(dub), format="wav")
    return str(src), str(dub)


def test_probe_distinguishes_audio_only(audio_only_source):
    src, _ = audio_only_source
    assert _video_has_video_stream(src) is False
    assert _video_has_audio(src) is True


def test_mux_audio_only_replace(audio_only_source, tmp_path):
    src, dub = audio_only_source
    out = tmp_path / "out.mp3"
    mux_dubbed_audio(src, dub, str(out))  # must not raise (used to fail exit 234)
    assert out.exists() and out.stat().st_size > 0
    types = _stream_types(str(out))
    assert "audio" in types and "video" not in types


def test_mux_audio_only_mix(audio_only_source, tmp_path):
    src, dub = audio_only_source
    out = tmp_path / "out_mix.mp3"
    mux_dubbed_audio(src, dub, str(out), mix_original_audio=True, original_audio_volume=0.25)
    assert out.exists() and out.stat().st_size > 0
    assert "audio" in _stream_types(str(out))
