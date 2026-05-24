"""Provider-neutral speech synthesis models."""

from dataclasses import dataclass
from typing import Literal, Optional

SpeechProvider = Literal["siliconflow", "gemini"]
AudioFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


@dataclass
class SpeechProviderConfig:
    """Connection and default synthesis options for one provider."""

    provider: SpeechProvider
    api_key: str
    model: str
    base_url: str = ""
    default_voice: str = ""
    response_format: AudioFormat = "mp3"
    sample_rate: int = 32000
    speed: float = 1.0
    gain: float = 0
    timeout: int = 90
    style_prompt: str = ""


@dataclass
class SynthesisRequest:
    """One utterance synthesis request."""

    text: str
    output_path: str
    voice: Optional[str] = None
    style_prompt: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None


@dataclass
class SynthesisResult:
    """Result from a provider call."""

    output_path: str
    voice: str
    format: AudioFormat
    provider_metadata: dict
