"""Speech synthesis provider layer for dubbing."""

from .models import SpeechProviderConfig, SynthesisRequest, SynthesisResult
from .providers import (
    GeminiSpeechSynthesizer,
    SiliconFlowSpeechSynthesizer,
    SpeechSynthesizer,
    create_speech_synthesizer,
)

__all__ = [
    "GeminiSpeechSynthesizer",
    "SiliconFlowSpeechSynthesizer",
    "SpeechProviderConfig",
    "SpeechSynthesizer",
    "SynthesisRequest",
    "SynthesisResult",
    "create_speech_synthesizer",
]
