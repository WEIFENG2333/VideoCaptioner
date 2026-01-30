"""CLI Configuration Management

Priority (high to low):
1. Command-line arguments
2. Environment variables
3. Config file (~/.videocaptioner/config.yaml or ./videocaptioner.yaml)
4. Default values

Environment Variables:
    VIDEOCAPTIONER_API_KEY      - LLM API key (also accepts OPENAI_API_KEY)
    VIDEOCAPTIONER_BASE_URL     - LLM API base URL (also accepts OPENAI_BASE_URL)
    VIDEOCAPTIONER_MODEL        - LLM model name
    VIDEOCAPTIONER_WHISPER_KEY  - Whisper API key
    VIDEOCAPTIONER_WHISPER_URL  - Whisper API base URL
    VIDEOCAPTIONER_OUTPUT_DIR   - Default output directory
    VIDEOCAPTIONER_LOG_LEVEL    - Logging level (DEBUG, INFO, WARNING, ERROR)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app.core.entities import (
    FasterWhisperModelEnum,
    SubtitleLayoutEnum,
    TranscribeModelEnum,
    TranslatorServiceEnum,
    VadMethodEnum,
    VideoQualityEnum,
    WhisperModelEnum,
)
from app.core.translate.types import TargetLanguage


# Language code to TargetLanguage mapping
LANG_CODE_MAP = {
    "zh": TargetLanguage.SIMPLIFIED_CHINESE,
    "zh-cn": TargetLanguage.SIMPLIFIED_CHINESE,
    "zh-tw": TargetLanguage.TRADITIONAL_CHINESE,
    "zh-hant": TargetLanguage.TRADITIONAL_CHINESE,
    "en": TargetLanguage.ENGLISH,
    "ja": TargetLanguage.JAPANESE,
    "ko": TargetLanguage.KOREAN,
    "fr": TargetLanguage.FRENCH,
    "de": TargetLanguage.GERMAN,
    "es": TargetLanguage.SPANISH,
    "ru": TargetLanguage.RUSSIAN,
    "pt": TargetLanguage.PORTUGUESE,
    "it": TargetLanguage.ITALIAN,
    "ar": TargetLanguage.ARABIC,
    "th": TargetLanguage.THAI,
    "vi": TargetLanguage.VIETNAMESE,
    "id": TargetLanguage.INDONESIAN,
    "nl": TargetLanguage.DUTCH,
    "pl": TargetLanguage.POLISH,
    "tr": TargetLanguage.TURKISH,
    "yue": TargetLanguage.CANTONESE,
}

# Transcribe model name mapping
TRANSCRIBE_MODEL_MAP = {
    "whisper-api": TranscribeModelEnum.WHISPER_API,
    "whisper": TranscribeModelEnum.WHISPER_API,
    "faster-whisper": TranscribeModelEnum.FASTER_WHISPER,
    "fasterwhisper": TranscribeModelEnum.FASTER_WHISPER,
    "whisper-cpp": TranscribeModelEnum.WHISPER_CPP,
    "whispercpp": TranscribeModelEnum.WHISPER_CPP,
    "bcut": TranscribeModelEnum.BIJIAN,
    "bijian": TranscribeModelEnum.BIJIAN,
    "jianying": TranscribeModelEnum.JIANYING,
}

# Translator service name mapping
TRANSLATOR_MAP = {
    "llm": TranslatorServiceEnum.OPENAI,
    "openai": TranslatorServiceEnum.OPENAI,
    "google": TranslatorServiceEnum.GOOGLE,
    "bing": TranslatorServiceEnum.BING,
    "deeplx": TranslatorServiceEnum.DEEPLX,
}

# Video quality name mapping
QUALITY_MAP = {
    "ultra-high": VideoQualityEnum.ULTRA_HIGH,
    "ultrahigh": VideoQualityEnum.ULTRA_HIGH,
    "high": VideoQualityEnum.HIGH,
    "medium": VideoQualityEnum.MEDIUM,
    "low": VideoQualityEnum.LOW,
}

# Subtitle layout name mapping
LAYOUT_MAP = {
    "translate-on-top": SubtitleLayoutEnum.TRANSLATE_ON_TOP,
    "original-on-top": SubtitleLayoutEnum.ORIGINAL_ON_TOP,
    "only-original": SubtitleLayoutEnum.ONLY_ORIGINAL,
    "only-translate": SubtitleLayoutEnum.ONLY_TRANSLATE,
}


@dataclass
class LLMConfig:
    """LLM API configuration"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass
class WhisperConfig:
    """Whisper API configuration"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "whisper-1"
    prompt: str = ""


@dataclass
class TranscribeSettings:
    """Transcription settings"""
    model: TranscribeModelEnum = TranscribeModelEnum.WHISPER_API
    language: str = ""  # Empty means auto-detect
    word_timestamps: bool = True
    # Whisper specific
    whisper_model: WhisperModelEnum = WhisperModelEnum.BASE
    # Faster Whisper specific
    faster_whisper_model: FasterWhisperModelEnum = FasterWhisperModelEnum.BASE
    faster_whisper_device: str = "cuda"
    faster_whisper_vad: bool = True
    faster_whisper_vad_method: VadMethodEnum = VadMethodEnum.SILERO_V3


@dataclass
class SubtitleSettings:
    """Subtitle processing settings"""
    split: bool = True
    split_method: str = "heuristic"  # heuristic or llm
    max_word_count_cjk: int = 12
    max_word_count_english: int = 18
    optimize: bool = False
    custom_prompt: str = ""


@dataclass
class TranslateSettings:
    """Translation settings"""
    enabled: bool = False
    service: TranslatorServiceEnum = TranslatorServiceEnum.OPENAI
    target_language: TargetLanguage = TargetLanguage.SIMPLIFIED_CHINESE
    reflect: bool = False
    thread_num: int = 10
    batch_size: int = 10
    deeplx_endpoint: str = ""


@dataclass
class RenderSettings:
    """Video rendering settings"""
    enabled: bool = False
    quality: VideoQualityEnum = VideoQualityEnum.MEDIUM
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ORIGINAL_ON_TOP
    soft_subtitle: bool = True
    style: str = "default"


@dataclass
class CLIConfig:
    """Complete CLI configuration"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    transcribe: TranscribeSettings = field(default_factory=TranscribeSettings)
    subtitle: SubtitleSettings = field(default_factory=SubtitleSettings)
    translate: TranslateSettings = field(default_factory=TranslateSettings)
    render: RenderSettings = field(default_factory=RenderSettings)
    output_dir: str = ""
    log_level: str = "INFO"


def get_env(key: str, fallback_keys: Optional[list] = None, default: str = "") -> str:
    """Get environment variable with fallback keys.

    Args:
        key: Primary environment variable name
        fallback_keys: List of fallback variable names
        default: Default value if not found

    Returns:
        Environment variable value or default
    """
    value = os.environ.get(key, "")
    if value:
        return value

    if fallback_keys:
        for fallback in fallback_keys:
            value = os.environ.get(fallback, "")
            if value:
                return value

    return default


def find_config_file() -> Optional[Path]:
    """Find configuration file.

    Search order:
    1. ./videocaptioner.yaml
    2. ./videocaptioner.yml
    3. ~/.videocaptioner/config.yaml
    4. ~/.videocaptioner/config.yml

    Returns:
        Path to config file or None
    """
    search_paths = [
        Path("./videocaptioner.yaml"),
        Path("./videocaptioner.yml"),
        Path.home() / ".videocaptioner" / "config.yaml",
        Path.home() / ".videocaptioner" / "config.yml",
    ]

    for path in search_paths:
        if path.exists():
            return path

    return None


def load_config_file(path: Optional[Path] = None) -> dict:
    """Load configuration from YAML file.

    Args:
        path: Config file path, or None to auto-detect

    Returns:
        Configuration dictionary
    """
    if path is None:
        path = find_config_file()

    if path is None or not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_config(
    config_file: Optional[str] = None,
    **cli_args,
) -> CLIConfig:
    """Load configuration from all sources.

    Priority: CLI args > Environment variables > Config file > Defaults

    Args:
        config_file: Path to config file
        **cli_args: Command-line arguments

    Returns:
        Merged CLIConfig
    """
    # Load config file
    file_config = load_config_file(Path(config_file) if config_file else None)

    # Create config with defaults
    config = CLIConfig()

    # Apply config file
    if "llm" in file_config:
        llm_conf = file_config["llm"]
        config.llm.api_key = llm_conf.get("api_key", config.llm.api_key)
        config.llm.base_url = llm_conf.get("base_url", config.llm.base_url)
        config.llm.model = llm_conf.get("model", config.llm.model)

    if "whisper" in file_config:
        whisper_conf = file_config["whisper"]
        config.whisper.api_key = whisper_conf.get("api_key", config.whisper.api_key)
        config.whisper.base_url = whisper_conf.get("base_url", config.whisper.base_url)
        config.whisper.model = whisper_conf.get("model", config.whisper.model)

    if "transcribe" in file_config:
        trans_conf = file_config["transcribe"]
        if "model" in trans_conf:
            model_name = trans_conf["model"].lower()
            if model_name in TRANSCRIBE_MODEL_MAP:
                config.transcribe.model = TRANSCRIBE_MODEL_MAP[model_name]
        config.transcribe.language = trans_conf.get("language", config.transcribe.language)

    if "translate" in file_config:
        tl_conf = file_config["translate"]
        if "service" in tl_conf:
            service_name = tl_conf["service"].lower()
            if service_name in TRANSLATOR_MAP:
                config.translate.service = TRANSLATOR_MAP[service_name]
        if "target_language" in tl_conf:
            lang = tl_conf["target_language"].lower()
            if lang in LANG_CODE_MAP:
                config.translate.target_language = LANG_CODE_MAP[lang]

    if "render" in file_config:
        render_conf = file_config["render"]
        if "quality" in render_conf:
            quality_name = render_conf["quality"].lower()
            if quality_name in QUALITY_MAP:
                config.render.quality = QUALITY_MAP[quality_name]

    # Apply environment variables
    config.llm.api_key = get_env(
        "VIDEOCAPTIONER_API_KEY",
        ["OPENAI_API_KEY"],
        config.llm.api_key
    )
    config.llm.base_url = get_env(
        "VIDEOCAPTIONER_BASE_URL",
        ["OPENAI_BASE_URL"],
        config.llm.base_url
    )
    config.llm.model = get_env(
        "VIDEOCAPTIONER_MODEL",
        default=config.llm.model
    )
    config.whisper.api_key = get_env(
        "VIDEOCAPTIONER_WHISPER_KEY",
        ["OPENAI_API_KEY"],
        config.whisper.api_key
    )
    config.whisper.base_url = get_env(
        "VIDEOCAPTIONER_WHISPER_URL",
        ["OPENAI_BASE_URL"],
        config.whisper.base_url
    )
    config.output_dir = get_env(
        "VIDEOCAPTIONER_OUTPUT_DIR",
        default=config.output_dir
    )
    config.log_level = get_env(
        "VIDEOCAPTIONER_LOG_LEVEL",
        default=config.log_level
    )

    # Apply CLI arguments (highest priority)
    if cli_args.get("api_key"):
        config.llm.api_key = cli_args["api_key"]
        config.whisper.api_key = cli_args["api_key"]

    if cli_args.get("base_url"):
        config.llm.base_url = cli_args["base_url"]

    if cli_args.get("model"):
        config.llm.model = cli_args["model"]

    if cli_args.get("transcribe_model"):
        model_name = cli_args["transcribe_model"].lower()
        if model_name in TRANSCRIBE_MODEL_MAP:
            config.transcribe.model = TRANSCRIBE_MODEL_MAP[model_name]

    if cli_args.get("language"):
        config.transcribe.language = cli_args["language"]

    if cli_args.get("translate"):
        config.translate.enabled = True
        lang = cli_args["translate"].lower()
        if lang in LANG_CODE_MAP:
            config.translate.target_language = LANG_CODE_MAP[lang]

    if cli_args.get("translator"):
        service_name = cli_args["translator"].lower()
        if service_name in TRANSLATOR_MAP:
            config.translate.service = TRANSLATOR_MAP[service_name]

    if cli_args.get("quality"):
        quality_name = cli_args["quality"].lower()
        if quality_name in QUALITY_MAP:
            config.render.quality = QUALITY_MAP[quality_name]

    if cli_args.get("output"):
        config.output_dir = cli_args["output"]

    if cli_args.get("split") is not None:
        config.subtitle.split = cli_args["split"]

    if cli_args.get("optimize") is not None:
        config.subtitle.optimize = cli_args["optimize"]

    if cli_args.get("render") is not None:
        config.render.enabled = cli_args["render"]

    return config


def parse_target_language(lang_str: str) -> Optional[TargetLanguage]:
    """Parse language string to TargetLanguage enum.

    Args:
        lang_str: Language code or name (e.g., "zh", "en", "Japanese")

    Returns:
        TargetLanguage enum or None
    """
    lang_lower = lang_str.lower().strip()

    # Try code mapping first
    if lang_lower in LANG_CODE_MAP:
        return LANG_CODE_MAP[lang_lower]

    # Try matching enum values
    for lang in TargetLanguage:
        if lang_lower in lang.value.lower() or lang_lower == lang.name.lower():
            return lang

    return None


def parse_transcribe_model(model_str: str) -> Optional[TranscribeModelEnum]:
    """Parse model string to TranscribeModelEnum.

    Args:
        model_str: Model name (e.g., "whisper-api", "faster-whisper")

    Returns:
        TranscribeModelEnum or None
    """
    model_lower = model_str.lower().strip().replace("_", "-")
    return TRANSCRIBE_MODEL_MAP.get(model_lower)


def generate_sample_config() -> str:
    """Generate sample configuration file content.

    Returns:
        YAML configuration string
    """
    return """# VideoCaptioner CLI Configuration
# Place this file at ~/.videocaptioner/config.yaml or ./videocaptioner.yaml

# LLM Configuration (for translation and optimization)
llm:
  api_key: ${OPENAI_API_KEY}  # Or set VIDEOCAPTIONER_API_KEY
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini

# Whisper API Configuration (for speech recognition)
whisper:
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  model: whisper-1

# Transcription Settings
transcribe:
  model: whisper-api  # whisper-api, faster-whisper, whisper-cpp, bcut, jianying
  language: ""  # Empty for auto-detect, or: zh, en, ja, ko, etc.
  word_timestamps: true

# Subtitle Processing Settings
subtitle:
  split: true
  split_method: heuristic  # heuristic or llm
  max_word_count_cjk: 12
  max_word_count_english: 18
  optimize: false

# Translation Settings
translate:
  service: llm  # llm, google, bing, deeplx
  target_language: zh  # zh, en, ja, ko, fr, de, es, etc.
  reflect: false  # Enable reflection for better quality
  thread_num: 10
  batch_size: 10

# Video Rendering Settings
render:
  quality: medium  # ultra-high, high, medium, low
  layout: original-on-top  # translate-on-top, original-on-top, only-original, only-translate
  soft_subtitle: true
  style: default

# Output Settings
output_dir: ""  # Empty uses input file directory
log_level: INFO
"""
