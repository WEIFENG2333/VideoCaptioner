"""Unit tests for WhisperAPI upload preparation."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

from videocaptioner.core.asr import whisper_api


def test_large_audio_is_compressed_before_upload(monkeypatch, tmp_path: Path):
    """Large file uploads should be compressed and temporary files cleaned up."""
    input_path = tmp_path / "large.wav"
    input_path.write_bytes(b"source")

    captured = {}
    temp_output = None

    def fake_run(cmd, **kwargs):
        nonlocal temp_output
        temp_output = Path(cmd[-1])
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        temp_output.write_bytes(b"compressed audio")
        return subprocess.CompletedProcess(cmd, 0, stderr=b"")

    def fake_create(**kwargs):
        captured["file"] = kwargs["file"]
        return SimpleNamespace(to_dict=lambda: {"segments": []})

    monkeypatch.setattr(whisper_api.subprocess, "run", fake_run)

    api = whisper_api.WhisperAPI.__new__(whisper_api.WhisperAPI)
    api.audio_input = str(input_path)
    api.file_binary = b"x" * (whisper_api.MAX_UPLOAD_BYTES + 1)
    api.language = "en"
    api.prompt = ""
    api.base_url = "https://example.test/v1"
    api.model = "whisper-1"
    api.need_word_time_stamp = False
    api.client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=fake_create))
    )

    result = api._submit()

    assert result == {"segments": []}
    assert captured["cmd"][:4] == ["ffmpeg", "-y", "-i", str(input_path)]
    assert captured["file"][1] == b"compressed audio"
    assert temp_output is not None
    assert not temp_output.exists()
