"""Speech synthesis provider implementations."""

import base64
import hashlib
import time
import wave
from pathlib import Path
from typing import Any, Protocol

import requests

from videocaptioner.core.utils.cache import get_tts_cache
from videocaptioner.core.utils.logger import setup_logger

from .models import SpeechProviderConfig, SynthesisRequest, SynthesisResult

logger = setup_logger("speech")


class SpeechSynthesizer(Protocol):
    """Provider-neutral synthesis interface used by the dubbing pipeline."""

    config: SpeechProviderConfig

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Synthesize one utterance to ``request.output_path``."""
        ...


def create_speech_synthesizer(config: SpeechProviderConfig) -> SpeechSynthesizer:
    if config.provider == "siliconflow":
        return SiliconFlowSpeechSynthesizer(config)
    if config.provider == "gemini":
        return GeminiSpeechSynthesizer(config)
    raise ValueError(f"Unsupported speech provider: {config.provider}")


class SiliconFlowSpeechSynthesizer:
    """SiliconFlow CosyVoice2-compatible synthesizer."""

    DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"

    def __init__(self, config: SpeechProviderConfig):
        if not config.api_key:
            raise ValueError("SiliconFlow API key is required")
        self.config = config
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.cache = get_tts_cache()

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = self._resolve_voice(request)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": self._build_input(request),
            "voice": voice,
            "response_format": self.config.response_format,
            "sample_rate": self.config.sample_rate,
            "speed": self.config.speed,
            "gain": self.config.gain,
            "stream": False,
        }
        response = self._post_speech(payload)
        path = Path(request.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format=self.config.response_format,
            provider_metadata={"content_type": response.headers.get("content-type", "")},
        )

    def _post_speech(self, payload: dict[str, Any]) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if not response.content:
                    raise ValueError("SiliconFlow TTS returned an empty audio body")
                if "json" in content_type.lower():
                    raise ValueError(f"SiliconFlow TTS returned JSON instead of audio: {response.text[:300]}")
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"SiliconFlow TTS failed after retries: {last_error}")

    def _resolve_voice(self, request: SynthesisRequest) -> str:
        if request.clone_audio_path and request.clone_audio_text:
            return self._upload_voice(request.clone_audio_path, request.clone_audio_text)
        voice = request.voice or self.config.default_voice
        if not voice:
            voice = f"{self.config.model}:alex"
        return voice

    def _build_input(self, request: SynthesisRequest) -> str:
        prompt = request.style_prompt or self.config.style_prompt
        if prompt:
            return f"{prompt.strip()}<|endofprompt|>{request.text.strip()}"
        return request.text

    def _upload_voice(self, audio_path: str, transcript: str) -> str:
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Voice clone reference audio not found: {audio_path}")
        cache_key = self._voice_cache_key(audio_file, transcript)
        cached = self.cache.get(cache_key)
        if cached:
            return str(cached)

        custom_name = f"videocaptioner_{hashlib.md5(cache_key.encode()).hexdigest()[:12]}"
        with audio_file.open("rb") as f:
            response = requests.post(
                f"{self.base_url}/uploads/audio/voice",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                files={"file": (audio_file.name, f, _guess_mime(audio_file))},
                data={
                    "model": self.config.model,
                    "customName": custom_name,
                    "text": transcript,
                },
                timeout=self.config.timeout,
            )
        response.raise_for_status()
        uri = response.json().get("uri")
        if not uri:
            raise ValueError(f"SiliconFlow upload did not return a voice uri: {response.text}")
        self.cache.set(cache_key, uri, expire=86400 * 2)
        return str(uri)

    def _voice_cache_key(self, audio_file: Path, transcript: str) -> str:
        digest = hashlib.md5(audio_file.read_bytes()).hexdigest()
        raw = f"speech_voice:{self.config.model}:{digest}:{transcript}"
        return hashlib.md5(raw.encode()).hexdigest()


class GeminiSpeechSynthesizer:
    """Gemini native speech generation synthesizer."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    SAMPLE_RATE = 24000

    def __init__(self, config: SpeechProviderConfig):
        if not config.api_key:
            raise ValueError("Gemini API key is required")
        self.config = config

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = request.voice or self.config.default_voice or "Kore"
        prompt = self._build_prompt(request)
        response = requests.post(
            self._model_url(),
            headers={
                "x-goog-api-key": self.config.api_key,
                "Content-Type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": voice,
                            }
                        }
                    },
                },
            },
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        pcm = self._extract_pcm(response.json())
        path = Path(request.output_path).with_suffix(".wav")
        self._write_wav(pcm, path)
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format="wav",
            provider_metadata={"sample_rate": self.SAMPLE_RATE},
        )

    def _model_url(self) -> str:
        base_url = (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        if base_url.endswith("/v1beta"):
            return f"{base_url}/models/{self.config.model}:generateContent"
        return f"{base_url}/v1beta/models/{self.config.model}:generateContent"

    def _build_prompt(self, request: SynthesisRequest) -> str:
        prompt = request.style_prompt or self.config.style_prompt
        if prompt:
            return f"{prompt.strip()}\n\nTranscript:\n{request.text.strip()}"
        return f"Read this subtitle line naturally and clearly.\n\nTranscript:\n{request.text.strip()}"

    @staticmethod
    def _extract_pcm(data: dict[str, Any]) -> bytes:
        try:
            for part in data["candidates"][0]["content"]["parts"]:
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data and inline_data.get("data"):
                    return base64.b64decode(inline_data["data"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Invalid Gemini TTS response: {data}") from exc
        raise ValueError(f"Gemini TTS response did not include audio: {data}")

    @classmethod
    def _write_wav(cls, pcm: bytes, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(cls.SAMPLE_RATE)
            wf.writeframes(pcm)


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".opus":
        return "audio/opus"
    if suffix == ".pcm":
        return "audio/pcm"
    return "audio/mpeg"
