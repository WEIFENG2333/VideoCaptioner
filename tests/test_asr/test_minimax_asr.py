"""MiniMax speech-to-text provider tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from videocaptioner.core.asr.asr_data import ASRData

TOKEN = "[REDACTED_SECRET]"


@dataclass
class _FakeResponse:
    status_code: int = 200
    text: str = (
        "1\n00:00:00,100 --> 00:00:01,660\n你好\n\n"
        "2\n00:00:02,000 --> 00:00:03,100\n世界\n"
    )

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_minimax_asr_uses_official_srt_contract(monkeypatch):
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    captured = {}

    def fake_post(url, *, headers, data, files, timeout):
        captured.update(url=url, headers=headers, data=data, files=files, timeout=timeout)
        return _FakeResponse()

    monkeypatch.setattr("videocaptioner.core.asr.minimax_api.requests.post", fake_post)

    asr = MiniMaxASR(
        audio_input=b"ID3-test",
        api_key=TOKEN,
        base_url="https://api.minimaxi.com/v1",
        model="asr-1.0",
        language="zh",
        need_word_time_stamp=False,
    )
    result: ASRData = asr.run()

    assert captured["url"] == "https://api.minimaxi.com/v1/speech_to_text"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["headers"]["language"] == "zh"
    assert captured["data"] == {
        "model": "asr-1.0",
        "response_format": "srt",
        "timestamp_level": "sentence",
        "stream": "false",
    }
    filename, payload, media_type = captured["files"]["file"]
    assert filename == "audio.mp3"
    assert payload == b"ID3-test"
    assert media_type == "audio/mpeg"
    assert captured["timeout"][0] <= 15
    assert captured["timeout"][1] >= 120
    assert [seg.text for seg in result.segments] == ["你好", "世界"]
    assert result.segments[0].start_time == 100
    assert result.segments[1].end_time == 3100


def test_minimax_asr_word_timestamp_switch(monkeypatch):
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    captured = {}

    def fake_post(url, *, headers, data, files, timeout):
        captured["data"] = data
        return _FakeResponse(text="1\n00:00:00,000 --> 00:00:00,200\n你\n")

    monkeypatch.setattr("videocaptioner.core.asr.minimax_api.requests.post", fake_post)

    result = MiniMaxASR(
        audio_input=b"ID3-test",
        api_key=TOKEN,
        need_word_time_stamp=True,
    ).run()

    assert captured["data"]["timestamp_level"] == "word"
    assert result.is_word_timestamp()


def test_minimax_asr_auto_language_omits_language_header(monkeypatch):
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    captured = {}

    def fake_post(url, *, headers, data, files, timeout):
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr("videocaptioner.core.asr.minimax_api.requests.post", fake_post)

    MiniMaxASR(audio_input=b"ID3-test", api_key=TOKEN, language="").run()
    assert "language" not in captured["headers"]


def test_minimax_asr_rejects_unsupported_language_before_network():
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    with pytest.raises(ValueError, match="MiniMax ASR does not support language"):
        MiniMaxASR(audio_input=b"ID3-test", api_key=TOKEN, language="hi")


def test_minimax_asr_requires_api_key():
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    with pytest.raises(ValueError, match="API key"):
        MiniMaxASR(audio_input=b"ID3-test", api_key="")


def test_minimax_asr_http_error_is_actionable_and_does_not_leak_key(monkeypatch):
    from videocaptioner.core.asr.minimax_api import MiniMaxASR

    def fake_post(url, *, headers, data, files, timeout):
        return _FakeResponse(status_code=429, text='{"message":"rate limited"}')

    monkeypatch.setattr("videocaptioner.core.asr.minimax_api.requests.post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        MiniMaxASR(audio_input=b"ID3-test", api_key=TOKEN).run()

    message = str(exc_info.value)
    assert "429" in message
    assert TOKEN not in message
