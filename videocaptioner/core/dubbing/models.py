"""Data models for subtitle dubbing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

DubbingProvider = Literal["siliconflow", "gemini"]
FitMode = Literal["none", "tempo"]


@dataclass
class SpeakerProfile:
    """Voice settings for one speaker."""

    name: str
    voice: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None
    style_prompt: Optional[str] = None


@dataclass
class DubbingSegment:
    """One timed utterance to synthesize and place on the output timeline."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str = "default"
    voice: Optional[str] = None
    style_prompt: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None
    synthesized_path: str = ""
    fitted_path: str = ""
    synthesized_duration_ms: int = 0
    fitted_duration_ms: int = 0
    rewritten_text: Optional[str] = None
    speed_factor: float = 1.0
    warning: Optional[str] = None

    @property
    def target_duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def text_for_tts(self) -> str:
        return self.rewritten_text or self.text


@dataclass
class DubbingConfig:
    """Runtime configuration for dubbing."""

    provider: DubbingProvider
    api_key: str
    base_url: str
    model: str
    voice: str = ""
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    sample_rate: int = 32000
    speed: float = 1.0
    gain: float = 0
    timeout: int = 90
    use_cache: bool = True
    tts_workers: int = 5
    speaker_profiles: dict[str, SpeakerProfile] = field(default_factory=dict)
    style_prompt: str = ""
    fit_mode: FitMode = "tempo"
    max_speed: float = 1.35
    target_padding_ms: int = 80
    rewrite_too_long: bool = False
    rewrite_threshold: float = 1.15
    llm_api_key: str = ""
    llm_api_base: str = ""
    llm_model: str = ""
    mix_original_audio: bool = False
    original_audio_volume: float = 0.25
    dubbed_audio_volume: float = 1.0


@dataclass
class DubbingResult:
    """Outputs and per-segment metadata from a dubbing run."""

    audio_path: Path
    video_path: Optional[Path]
    segments: list[DubbingSegment]
    duration_ms: int
    warnings: list[str] = field(default_factory=list)
