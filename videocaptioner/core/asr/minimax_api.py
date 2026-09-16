"""MiniMax speech-to-text API provider."""

from __future__ import annotations

import io
import wave
from typing import Any, Callable, Optional, Union

import requests

from ..utils.logger import setup_logger
from .asr_data import ASRData, ASRDataSeg
from .base import BaseASR

logger = setup_logger("minimax_asr")

DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MINIMAX_MODEL = "asr-1.0"
MINIMAX_CONNECT_TIMEOUT = 10
MINIMAX_READ_TIMEOUT = 600
MINIMAX_SUPPORTED_LANGUAGES = {
    "zh",
    "yue",
    "en",
    "ja",
    "ko",
    "th",
    "vi",
    "id",
    "ms",
    "fil",
    "ar",
    "tr",
    "fr",
    "de",
    "es",
    "it",
    "pt",
    "pl",
    "ru",
    "uk",
}


class MiniMaxASR(BaseASR):
    """MiniMax ``/v1/speech_to_text`` provider.

    The provider deliberately requests SRT from MiniMax. SRT is an official
    response format and lets VideoCaptioner reuse its existing subtitle parser
    for both sentence- and word-level timestamps instead of duplicating a
    provider-specific timestamp model.
    """

    SUPPORTED_SOUND_FORMAT = ["wav", "aiff", "flac", "m4a", "mp3", "aac", "opus", "ogg"]

    def __init__(
        self,
        audio_input: Union[str, bytes],
        api_key: str,
        base_url: str = DEFAULT_MINIMAX_BASE_URL,
        model: str = DEFAULT_MINIMAX_MODEL,
        need_word_time_stamp: bool = False,
        language: str = "",
        use_cache: bool = False,
    ) -> None:
        super().__init__(audio_input, use_cache, need_word_time_stamp)
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("MiniMax ASR API key must be set")

        self.base_url = (base_url or DEFAULT_MINIMAX_BASE_URL).strip().rstrip("/")
        self.model = (model or DEFAULT_MINIMAX_MODEL).strip()
        self.language = (language or "").strip()
        self.need_word_time_stamp = need_word_time_stamp

        if self.language and self.language not in MINIMAX_SUPPORTED_LANGUAGES:
            supported = ", ".join(sorted(MINIMAX_SUPPORTED_LANGUAGES))
            raise ValueError(
                f"MiniMax ASR does not support language '{self.language}'. "
                f"Use auto detection or one of: {supported}"
            )

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/speech_to_text"):
            return self.base_url
        return f"{self.base_url}/speech_to_text"

    def _get_key(self) -> str:
        return (
            f"{self.crc32_hex}-{self.model}-{self.language}-"
            f"{self.need_word_time_stamp}-{self.base_url}"
        )

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        del kwargs
        if callback:
            callback(5, "Uploading to MiniMax ASR")

        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.language:
            headers["language"] = self.language

        data = {
            "model": self.model,
            "response_format": "srt",
            "timestamp_level": "word" if self.need_word_time_stamp else "sentence",
            "stream": "false",
        }
        files = {"file": self._upload_tuple()}

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=(MINIMAX_CONNECT_TIMEOUT, MINIMAX_READ_TIMEOUT),
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise RuntimeError("MiniMax ASR request timed out") from exc
        except requests.ConnectionError as exc:
            raise RuntimeError("MiniMax ASR connection failed") from exc
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {401, 403}:
                message = f"MiniMax ASR authentication failed (HTTP {status})"
            elif status == 429:
                message = "MiniMax ASR is rate limited (HTTP 429); retry later"
            elif status == 413:
                message = "MiniMax ASR rejected the audio as too large (HTTP 413)"
            elif status == 400:
                message = "MiniMax ASR rejected the audio request (HTTP 400)"
            else:
                message = f"MiniMax ASR request failed (HTTP {status or 'unknown'})"
            raise RuntimeError(message) from exc
        except requests.RequestException as exc:
            raise RuntimeError("MiniMax ASR request failed") from exc

        if callback:
            callback(100, "MiniMax ASR completed")
        return {"srt": response.text}

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        srt_text = resp_data.get("srt")
        if not isinstance(srt_text, str) or not srt_text.strip():
            return []
        return ASRData.from_srt(srt_text).segments

    def _upload_tuple(self) -> tuple[str, bytes, str]:
        payload = self.file_binary or b""
        if isinstance(self.audio_input, str):
            suffix = self.audio_input.rsplit(".", 1)[-1].lower()
            media_types = {
                "wav": "audio/wav",
                "aiff": "audio/aiff",
                "flac": "audio/flac",
                "m4a": "audio/mp4",
                "mp3": "audio/mpeg",
                "aac": "audio/aac",
                "opus": "audio/opus",
                "ogg": "audio/ogg",
            }
            return f"audio.{suffix}", payload, media_types.get(suffix, "application/octet-stream")
        return "audio.mp3", payload, "audio/mpeg"


def _silent_wav_bytes(duration_ms: int = 200) -> bytes:
    """Generate a tiny valid mono 16 kHz WAV for connection checks."""
    sample_rate = 16000
    frames = int(sample_rate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def check_minimax_connection(
    api_key: str,
    base_url: str = DEFAULT_MINIMAX_BASE_URL,
    model: str = DEFAULT_MINIMAX_MODEL,
) -> tuple[bool, str]:
    """Perform a tiny real ASR request without logging credentials."""
    try:
        MiniMaxASR(
            audio_input=_silent_wav_bytes(),
            api_key=api_key,
            base_url=base_url,
            model=model,
            language="",
        ).run()
        return True, "MiniMax ASR connection succeeded"
    except Exception as exc:
        logger.warning("MiniMax ASR connection check failed: %s", exc)
        return False, str(exc)
