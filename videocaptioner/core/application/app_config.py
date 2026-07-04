"""Canonical application configuration models.

The desktop UI and CLI can store settings differently, but task execution should
consume this module's plain data objects instead of UI widgets or CLI dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

from videocaptioner.core.entities import (
    FasterWhisperModelEnum,
    LLMServiceEnum,
    SubtitleLayoutEnum,
    SubtitleRenderModeEnum,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
    TranslatorServiceEnum,
    VadMethodEnum,
    VideoQualityEnum,
    WhisperModelEnum,
)
from videocaptioner.core.translate.types import TargetLanguage

EnumT = TypeVar("EnumT")


@dataclass(frozen=True)
class LLMSettings:
    service: LLMServiceEnum = LLMServiceEnum.OPENAI
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass(frozen=True)
class TranscribeSettings:
    model: TranscribeModelEnum = TranscribeModelEnum.BIJIAN
    language: str = ""
    language_label: str = "自动检测"
    output_format: TranscribeOutputFormatEnum = TranscribeOutputFormatEnum.SRT
    whisper_model: WhisperModelEnum = WhisperModelEnum.TINY
    whisper_api_key: str = ""
    whisper_api_base: str = ""
    whisper_api_model: str = ""
    whisper_api_prompt: str = ""
    fun_asr_api_key: str = ""
    fun_asr_api_base: str = "https://dashscope.aliyuncs.com"
    fun_asr_model: str = "fun-asr"
    faster_whisper_program: str = "faster-whisper-xxl.exe"
    faster_whisper_model: FasterWhisperModelEnum = FasterWhisperModelEnum.TINY
    faster_whisper_model_dir: str = ""
    faster_whisper_device: str = "auto"
    faster_whisper_vad_filter: bool = True
    faster_whisper_vad_threshold: float = 0.4
    faster_whisper_vad_method: VadMethodEnum = VadMethodEnum.SILERO_V4
    faster_whisper_ff_mdx_kim2: bool = False
    faster_whisper_one_word: bool = True
    faster_whisper_prompt: str = ""


@dataclass(frozen=True)
class SubtitleSettings:
    translator_service: TranslatorServiceEnum = TranslatorServiceEnum.BING
    need_reflect: bool = False
    deeplx_endpoint: str = ""
    thread_num: int = 10
    batch_size: int = 10
    need_optimize: bool = False
    need_translate: bool = False
    need_split: bool = False
    target_language: TargetLanguage = TargetLanguage.SIMPLIFIED_CHINESE
    max_word_count_cjk: int = 28
    max_word_count_english: int = 20
    custom_prompt_text: str = ""
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.TRANSLATE_ON_TOP
    style_name: str = "ass/default"


@dataclass(frozen=True)
class SynthesisSettings:
    need_video: bool = True
    soft_subtitle: bool = False
    video_quality: VideoQualityEnum = VideoQualityEnum.MEDIUM
    render_mode: SubtitleRenderModeEnum = SubtitleRenderModeEnum.ROUNDED_BG
    style_id: str = "rounded/default"


@dataclass(frozen=True)
class DubbingSettings:
    enabled: bool = False
    provider: str = "edge"
    preset: str = "edge-cn-female"
    voice: str = "zh-CN-XiaoxiaoNeural"
    text_track: str = "auto"
    timing: str = "balanced"
    audio_mode: str = "replace"
    api_key: str = ""
    api_base: str = ""
    model: str = ""
    tts_workers: int = 5
    clone_audio_path: str = ""
    clone_audio_text: str = ""

    @property
    def supports_clone(self) -> bool:
        return self.provider == "siliconflow"


@dataclass(frozen=True)
class AppConfig:
    work_dir: str = ""
    cache_enabled: bool = True
    llm: LLMSettings = field(default_factory=LLMSettings)
    transcribe: TranscribeSettings = field(default_factory=TranscribeSettings)
    subtitle: SubtitleSettings = field(default_factory=SubtitleSettings)
    synthesis: SynthesisSettings = field(default_factory=SynthesisSettings)
    dubbing: DubbingSettings = field(default_factory=DubbingSettings)


def enum_by_value(enum_class: type[EnumT], value: Any, default: EnumT) -> EnumT:
    """Resolve enum values from config strings while preserving existing enum values."""
    if isinstance(value, enum_class):
        return value
    for item in enum_class:  # type: ignore[attr-defined]
        if getattr(item, "value", None) == value or getattr(item, "name", None) == value:
            return item
    return default


def target_language_from_code(value: Any) -> TargetLanguage:
    if isinstance(value, TargetLanguage):
        return value

    raw = str(value or "").strip()
    if not raw:
        return TargetLanguage.SIMPLIFIED_CHINESE

    code_map = {
        "zh-hans": TargetLanguage.SIMPLIFIED_CHINESE,
        "zh-cn": TargetLanguage.SIMPLIFIED_CHINESE,
        "zh": TargetLanguage.SIMPLIFIED_CHINESE,
        "zh-hant": TargetLanguage.TRADITIONAL_CHINESE,
        "zh-tw": TargetLanguage.TRADITIONAL_CHINESE,
        "en": TargetLanguage.ENGLISH,
        "en-us": TargetLanguage.ENGLISH_US,
        "en-gb": TargetLanguage.ENGLISH_UK,
        "ja": TargetLanguage.JAPANESE,
        "ko": TargetLanguage.KOREAN,
        "yue": TargetLanguage.CANTONESE,
        "th": TargetLanguage.THAI,
        "vi": TargetLanguage.VIETNAMESE,
        "id": TargetLanguage.INDONESIAN,
        "ms": TargetLanguage.MALAY,
        "tl": TargetLanguage.TAGALOG,
        "fil": TargetLanguage.TAGALOG,
        "fr": TargetLanguage.FRENCH,
        "de": TargetLanguage.GERMAN,
        "es": TargetLanguage.SPANISH,
        "es-419": TargetLanguage.SPANISH_LATAM,
        "ru": TargetLanguage.RUSSIAN,
        "pt": TargetLanguage.PORTUGUESE,
        "pt-br": TargetLanguage.PORTUGUESE_BR,
        "pt-pt": TargetLanguage.PORTUGUESE_PT,
        "it": TargetLanguage.ITALIAN,
        "nl": TargetLanguage.DUTCH,
        "pl": TargetLanguage.POLISH,
        "tr": TargetLanguage.TURKISH,
        "el": TargetLanguage.GREEK,
        "cs": TargetLanguage.CZECH,
        "sv": TargetLanguage.SWEDISH,
        "da": TargetLanguage.DANISH,
        "fi": TargetLanguage.FINNISH,
        "nb": TargetLanguage.NORWEGIAN,
        "no": TargetLanguage.NORWEGIAN,
        "hu": TargetLanguage.HUNGARIAN,
        "ro": TargetLanguage.ROMANIAN,
        "bg": TargetLanguage.BULGARIAN,
        "uk": TargetLanguage.UKRAINIAN,
        "ar": TargetLanguage.ARABIC,
        "he": TargetLanguage.HEBREW,
        "fa": TargetLanguage.PERSIAN,
    }
    mapped = code_map.get(raw.lower())
    if mapped:
        return mapped

    for lang in TargetLanguage:
        if lang.value == raw or lang.name.lower() == raw.lower():
            return lang
    return TargetLanguage.SIMPLIFIED_CHINESE


# CLI 的 --asr 取值与枚举的唯一映射：parser choices 必须从这里派生，
# 不要再手写清单（曾因三处手写各自漂移漏掉 faster-whisper / fun-asr）。
CLI_ASR_MAPPING: dict[str, TranscribeModelEnum] = {
    "bijian": TranscribeModelEnum.BIJIAN,
    "jianying": TranscribeModelEnum.JIANYING,
    "fun-asr": TranscribeModelEnum.BAILIAN_FUN_ASR,
    "whisper-api": TranscribeModelEnum.WHISPER_API,
    "whisper-cpp": TranscribeModelEnum.WHISPER_CPP,
    "faster-whisper": TranscribeModelEnum.FASTER_WHISPER,
}
CLI_ASR_CHOICES: list[str] = list(CLI_ASR_MAPPING)


def transcribe_model_from_cli(value: str) -> TranscribeModelEnum:
    return CLI_ASR_MAPPING.get(value, TranscribeModelEnum.BIJIAN)


def transcribe_output_format_from_cli(value: str) -> TranscribeOutputFormatEnum:
    return {
        "srt": TranscribeOutputFormatEnum.SRT,
        "ass": TranscribeOutputFormatEnum.ASS,
        "vtt": TranscribeOutputFormatEnum.VTT,
        "txt": TranscribeOutputFormatEnum.TXT,
        "all": TranscribeOutputFormatEnum.ALL,
    }.get(str(value or "srt").lower(), TranscribeOutputFormatEnum.SRT)


def translator_from_cli(value: str) -> TranslatorServiceEnum:
    return {
        "llm": TranslatorServiceEnum.OPENAI,
        "bing": TranslatorServiceEnum.BING,
        "google": TranslatorServiceEnum.GOOGLE,
        "deeplx": TranslatorServiceEnum.DEEPLX,
    }.get(str(value or "bing").lower(), TranslatorServiceEnum.BING)


def layout_from_cli(value: str) -> SubtitleLayoutEnum:
    return {
        "target-above": SubtitleLayoutEnum.TRANSLATE_ON_TOP,
        "source-above": SubtitleLayoutEnum.ORIGINAL_ON_TOP,
        "target-only": SubtitleLayoutEnum.ONLY_TRANSLATE,
        "source-only": SubtitleLayoutEnum.ONLY_ORIGINAL,
    }.get(str(value or "target-above"), SubtitleLayoutEnum.TRANSLATE_ON_TOP)


def render_mode_from_cli(value: str) -> SubtitleRenderModeEnum:
    return {
        "ass": SubtitleRenderModeEnum.ASS_STYLE,
        "rounded": SubtitleRenderModeEnum.ROUNDED_BG,
    }.get(str(value or "ass"), SubtitleRenderModeEnum.ASS_STYLE)


def quality_from_cli(value: str) -> VideoQualityEnum:
    return {
        "ultra": VideoQualityEnum.ULTRA_HIGH,
        "high": VideoQualityEnum.HIGH,
        "medium": VideoQualityEnum.MEDIUM,
        "low": VideoQualityEnum.LOW,
    }.get(str(value or "medium"), VideoQualityEnum.MEDIUM)
