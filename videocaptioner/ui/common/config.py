# coding:utf-8
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from PyQt5.QtCore import QLocale
from PyQt5.QtGui import QColor

from videocaptioner.config import WORK_PATH
from videocaptioner.core.application.app_config import (
    enum_by_value,
    layout_from_cli,
    quality_from_cli,
    render_mode_from_cli,
    target_language_from_code,
    transcribe_model_from_cli,
    transcribe_output_format_from_cli,
    translator_from_cli,
)
from videocaptioner.core.application.config_store import (
    build_config,
    get,
    save_many,
)
from videocaptioner.core.dubbing import available_dubbing_presets
from videocaptioner.core.entities import (
    LANGUAGES,
    FasterWhisperModelEnum,
    LLMServiceEnum,
    SubtitleLayoutEnum,
    SubtitleRenderModeEnum,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
    TranslatorServiceEnum,
    VadMethodEnum,
    VideoQualityEnum,
    WhisperModelEnum,
)
from videocaptioner.core.realtime.backends.languages import all_source_lang_codes, source_lang_codes
from videocaptioner.core.translate.types import BING_LANG_MAP, TargetLanguage
from videocaptioner.core.utils.platform_utils import get_available_transcribe_models
from videocaptioner.ui.common.settings_state import (
    BoolValidator,
    ChoiceSettingField,
    ChoiceValidator,
    EnumSettingSerializer,
    FolderValidator,
    RangeSettingField,
    RangeValidator,
    SettingField,
    SettingSerializer,
    SettingsState,
)
from videocaptioner.ui.i18n import tr

DEFAULT_THEME_COLOR = "#ff00e889"


class ThemeMode(Enum):
    LIGHT = "Light"
    DARK = "Dark"
    AUTO = "Auto"


class Language(Enum):
    """软件语言"""

    CHINESE_SIMPLIFIED = QLocale(QLocale.Chinese, QLocale.China)
    CHINESE_TRADITIONAL = QLocale(QLocale.Chinese, QLocale.HongKong)
    ENGLISH = QLocale(QLocale.English)
    AUTO = QLocale()


class LanguageSerializer(SettingSerializer):
    """Language serializer"""

    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


class PlatformAwareTranscribeModelValidator(ChoiceValidator):
    """平台相关的转录模型验证器，在 macOS 上自动过滤掉 FasterWhisper"""

    def __init__(self):
        # 不调用父类的 __init__，因为我们要自定义 options
        self._options = get_available_transcribe_models()

    @property
    def options(self):
        return self._options

    def validate(self, value):
        return value in self._options

    def correct(self, value):
        return value if self.validate(value) else self._options[0]


# 实时字幕识别语言：哪个 provider 支持哪些 code 是后端事实，单一来源在
# core/realtime/backends/languages.py（voxgate=中/英、fun-asr=多语种 7、qwen-asr=27，三家都含「自动识别」）。
# 这里只维护 code → 中文显示名（UI 文案），按 provider 取子集组装下拉，避免标签/选项漂移。
_SOURCE_LANG_LABELS = {
    "auto": "自动识别", "zh": "中文", "yue": "粤语", "en": "英语", "es": "西班牙语",
    "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语", "pt": "葡萄牙语",
    "ru": "俄语", "it": "意大利语", "ar": "阿拉伯语", "hi": "印地语", "id": "印尼语",
    "th": "泰语", "vi": "越南语", "tr": "土耳其语", "uk": "乌克兰语", "ms": "马来语",
    "fil": "菲律宾语", "pl": "波兰语", "cs": "捷克语", "sv": "瑞典语", "da": "丹麦语",
    "no": "挪威语", "fi": "芬兰语", "is": "冰岛语",
}


def source_language_i18n_map() -> dict[str, str]:
    """识别语言 lclang.<code>→基准中文。key 动态拼成、pybabel 抽不到，由 i18n 工具链注入。"""
    return {f"lclang.{code}": label for code, label in _SOURCE_LANG_LABELS.items()}


def source_language_options(provider: str) -> list[tuple[str, str]]:
    """该 provider 的识别语言下拉项 (code, 译文标签)；第一项总是「自动识别」。

    label 走 i18n（key=lclang.<code>）；_SOURCE_LANG_LABELS 为 zh 基准，未命中回落 code。
    """
    return [
        (code, tr(f"lclang.{code}") if code in _SOURCE_LANG_LABELS else code)
        for code in source_lang_codes(provider)
    ]


# 校验器接受所有 provider 支持语言的并集（任一 provider 的选择都能持久化）；UI 按当前 provider 取子集。
_LIVE_CAPTION_LANG_CODES = all_source_lang_codes()


class Config(SettingsState):
    """应用配置"""

    # ------------------- UI 外观配置 -------------------
    themeMode = ChoiceSettingField(
        "UI",
        "ThemeMode",
        ThemeMode.DARK,
        ChoiceValidator(ThemeMode),
        EnumSettingSerializer(ThemeMode),
    )
    themeColor = SettingField("UI", "ThemeColor", QColor(DEFAULT_THEME_COLOR))
    # 取色器「最近使用」颜色（#AARRGGBB 字符串列表，最新在前）
    recent_colors = SettingField("UI", "RecentColors", [])
    # 工作台页面右栏折叠状态（持久化）
    transcribe_panel_collapsed = SettingField(
        "UI", "TranscribePanelCollapsed", False, BoolValidator()
    )
    synthesis_panel_collapsed = SettingField(
        "UI", "SynthesisPanelCollapsed", False, BoolValidator()
    )
    subtitle_panel_collapsed = SettingField(
        "UI", "SubtitlePanelCollapsed", False, BoolValidator()
    )
    # 批量处理页：处理模式（full / trans_sub / transcribe / subtitle）与并发数
    batch_mode = SettingField("UI", "BatchMode", "full")
    batch_concurrency = RangeSettingField("UI", "BatchConcurrency", 1, RangeValidator(1, 3))

    # LLM配置
    llm_service = ChoiceSettingField(
        "LLM",
        "LLMService",
        LLMServiceEnum.OPENAI,
        ChoiceValidator(LLMServiceEnum),
        EnumSettingSerializer(LLMServiceEnum),
    )

    openai_model = SettingField("LLM", "OpenAI_Model", "gpt-4o-mini")
    openai_model_options = SettingField("LLM", "OpenAI_ModelOptions", [])
    openai_api_key = SettingField("LLM", "OpenAI_API_Key", "")
    openai_api_base = SettingField("LLM", "OpenAI_API_Base", "https://api.openai.com/v1")

    official_model = SettingField("LLM", "Official_Model", "gemini-2.5-flash")
    official_model_options = SettingField("LLM", "Official_ModelOptions", [])
    official_api_key = SettingField("LLM", "Official_API_Key", "")
    official_api_base = SettingField("LLM", "Official_API_Base", "https://api.videocaptioner.cn/v1")

    silicon_cloud_model = SettingField("LLM", "SiliconCloud_Model", "gpt-4o-mini")
    silicon_cloud_model_options = SettingField("LLM", "SiliconCloud_ModelOptions", [])
    silicon_cloud_api_key = SettingField("LLM", "SiliconCloud_API_Key", "")
    silicon_cloud_api_base = SettingField(
        "LLM", "SiliconCloud_API_Base", "https://api.siliconflow.cn/v1"
    )

    deepseek_model = SettingField("LLM", "DeepSeek_Model", "deepseek-chat")
    deepseek_model_options = SettingField("LLM", "DeepSeek_ModelOptions", [])
    deepseek_api_key = SettingField("LLM", "DeepSeek_API_Key", "")
    deepseek_api_base = SettingField("LLM", "DeepSeek_API_Base", "https://api.deepseek.com/v1")

    ollama_model = SettingField("LLM", "Ollama_Model", "llama2")
    ollama_model_options = SettingField("LLM", "Ollama_ModelOptions", [])
    ollama_api_key = SettingField("LLM", "Ollama_API_Key", "ollama")
    ollama_api_base = SettingField("LLM", "Ollama_API_Base", "http://localhost:11434/v1")

    lm_studio_model = SettingField("LLM", "LmStudio_Model", "qwen2.5:7b")
    lm_studio_model_options = SettingField("LLM", "LmStudio_ModelOptions", [])
    lm_studio_api_key = SettingField("LLM", "LmStudio_API_Key", "lmstudio")
    lm_studio_api_base = SettingField("LLM", "LmStudio_API_Base", "http://localhost:1234/v1")

    gemini_model = SettingField("LLM", "Gemini_Model", "gemini-pro")
    gemini_model_options = SettingField("LLM", "Gemini_ModelOptions", [])
    gemini_api_key = SettingField("LLM", "Gemini_API_Key", "")
    gemini_api_base = SettingField(
        "LLM",
        "Gemini_API_Base",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    chatglm_model = SettingField("LLM", "ChatGLM_Model", "glm-4")
    chatglm_model_options = SettingField("LLM", "ChatGLM_ModelOptions", [])
    chatglm_api_key = SettingField("LLM", "ChatGLM_API_Key", "")
    chatglm_api_base = SettingField("LLM", "ChatGLM_API_Base", "https://open.bigmodel.cn/api/paas/v4")

    # ------------------- 翻译配置 -------------------
    translator_service = ChoiceSettingField(
        "Translate",
        "TranslatorServiceEnum",
        TranslatorServiceEnum.BING,
        ChoiceValidator(TranslatorServiceEnum),
        EnumSettingSerializer(TranslatorServiceEnum),
    )
    need_reflect_translate = SettingField("Translate", "NeedReflectTranslate", False, BoolValidator())
    deeplx_endpoint = SettingField("Translate", "DeeplxEndpoint", "")
    batch_size = RangeSettingField("Translate", "BatchSize", 10, RangeValidator(5, 50))
    thread_num = RangeSettingField("Translate", "ThreadNum", 10, RangeValidator(1, 50))

    # ------------------- 转录配置 -------------------
    transcribe_model = ChoiceSettingField(
        "Transcribe",
        "TranscribeModel",
        TranscribeModelEnum.BIJIAN,
        PlatformAwareTranscribeModelValidator(),
        EnumSettingSerializer(TranscribeModelEnum),
    )
    transcribe_output_format = ChoiceSettingField(
        "Transcribe",
        "OutputFormat",
        TranscribeOutputFormatEnum.SRT,
        ChoiceValidator(TranscribeOutputFormatEnum),
        EnumSettingSerializer(TranscribeOutputFormatEnum),
    )
    transcribe_language = ChoiceSettingField(
        "Transcribe",
        "TranscribeLanguage",
        TranscribeLanguageEnum.AUTO,
        ChoiceValidator(TranscribeLanguageEnum),
        EnumSettingSerializer(TranscribeLanguageEnum),
    )
    # 默认句级时间轴：单独导出 SRT 时词级会按字分段，不适合直接使用；
    # 流水线（智能断句）所需的词级时间戳由 TaskBuilder 自行决定，不受此开关影响。
    transcribe_word_timestamp = SettingField(
        "Transcribe", "WordTimestamp", False, BoolValidator()
    )

    # ------------------- Whisper Cpp 配置 -------------------
    whisper_model = ChoiceSettingField(
        "Whisper",
        "WhisperModel",
        WhisperModelEnum.TINY,
        ChoiceValidator(WhisperModelEnum),
        EnumSettingSerializer(WhisperModelEnum),
    )

    # ------------------- Faster Whisper 配置 -------------------
    faster_whisper_program = SettingField(
        "FasterWhisper",
        "Program",
        "faster-whisper-xxl.exe",
    )
    faster_whisper_model = ChoiceSettingField(
        "FasterWhisper",
        "Model",
        FasterWhisperModelEnum.TINY,
        ChoiceValidator(FasterWhisperModelEnum),
        EnumSettingSerializer(FasterWhisperModelEnum),
    )
    faster_whisper_model_dir = SettingField("FasterWhisper", "ModelDir", "")
    faster_whisper_device = ChoiceSettingField(
        "FasterWhisper", "Device", "auto", ChoiceValidator(["auto", "cuda", "cpu"])
    )
    # VAD 参数
    faster_whisper_vad_filter = SettingField("FasterWhisper", "VadFilter", True, BoolValidator())
    faster_whisper_vad_threshold = RangeSettingField(
        "FasterWhisper", "VadThreshold", 0.4, RangeValidator(0, 1)
    )
    faster_whisper_vad_method = ChoiceSettingField(
        "FasterWhisper",
        "VadMethod",
        VadMethodEnum.SILERO_V4,
        ChoiceValidator(VadMethodEnum),
        EnumSettingSerializer(VadMethodEnum),
    )
    # 人声提取
    faster_whisper_ff_mdx_kim2 = SettingField("FasterWhisper", "FfMdxKim2", False, BoolValidator())
    # 文本处理参数
    faster_whisper_one_word = SettingField("FasterWhisper", "OneWord", True, BoolValidator())
    # 提示词
    faster_whisper_prompt = SettingField("FasterWhisper", "Prompt", "")

    # ------------------- Whisper API 配置 -------------------
    whisper_api_base = SettingField("WhisperAPI", "WhisperApiBase", "")
    whisper_api_key = SettingField("WhisperAPI", "WhisperApiKey", "")
    whisper_api_model = SettingField("WhisperAPI", "WhisperApiModel", "")
    whisper_api_prompt = SettingField("WhisperAPI", "WhisperApiPrompt", "")

    # ------------------- 百炼 Fun-ASR 配置 -------------------
    fun_asr_api_base = SettingField("FunASR", "FunAsrApiBase", "https://dashscope.aliyuncs.com")
    fun_asr_api_key = SettingField("FunASR", "FunAsrApiKey", "")
    fun_asr_model = SettingField("FunASR", "FunAsrModel", "fun-asr")

    # ------------------- 字幕配置 -------------------
    need_optimize = SettingField("Subtitle", "NeedOptimize", False, BoolValidator())
    need_translate = SettingField("Subtitle", "NeedTranslate", False, BoolValidator())
    need_split = SettingField("Subtitle", "NeedSplit", False, BoolValidator())
    target_language = ChoiceSettingField(
        "Subtitle",
        "TargetLanguage",
        TargetLanguage.SIMPLIFIED_CHINESE,
        ChoiceValidator(TargetLanguage),
        EnumSettingSerializer(TargetLanguage),
    )
    max_word_count_cjk = SettingField("Subtitle", "MaxWordCountCJK", 28, RangeValidator(8, 100))
    max_word_count_english = SettingField(
        "Subtitle", "MaxWordCountEnglish", 20, RangeValidator(8, 100)
    )
    custom_prompt_text = SettingField("Subtitle", "CustomPromptText", "")

    # ------------------- 字幕合成配置 -------------------
    soft_subtitle = SettingField("Video", "SoftSubtitle", False, BoolValidator())
    need_video = SettingField("Video", "NeedVideo", True, BoolValidator())
    video_quality = ChoiceSettingField(
        "Video",
        "VideoQuality",
        VideoQualityEnum.MEDIUM,
        ChoiceValidator(VideoQualityEnum),
        EnumSettingSerializer(VideoQualityEnum),
    )

    # ------------------- 配音配置 -------------------
    dubbing_enabled = SettingField("Dubbing", "Enabled", False, BoolValidator())
    dubbing_provider = ChoiceSettingField(
        "Dubbing",
        "Provider",
        "edge",
        ChoiceValidator(["edge", "gemini", "siliconflow"]),
    )
    dubbing_preset = ChoiceSettingField(
        "Dubbing",
        "Preset",
        "edge-cn-female",
        ChoiceValidator(available_dubbing_presets()),
    )
    dubbing_voice = SettingField("Dubbing", "Voice", "zh-CN-XiaoxiaoNeural")
    dubbing_text_track = ChoiceSettingField(
        "Dubbing",
        "TextTrack",
        "auto",
        ChoiceValidator(["auto", "first", "second"]),
    )
    dubbing_timing = ChoiceSettingField(
        "Dubbing",
        "Timing",
        "balanced",
        # 含 "none"：core/CLI（resolve_timing、--timing none）均支持不变速，
        # 此处必须保留该取值，否则从 CLI/TOML 设的 none 被 GUI 矫正成首项、再保存即丢配置。
        ChoiceValidator(["natural", "balanced", "strict", "none"]),
    )
    dubbing_audio_mode = ChoiceSettingField(
        "Dubbing",
        "AudioMode",
        "replace",
        ChoiceValidator(["replace", "mix", "duck"]),
    )
    dubbing_api_key = SettingField("Dubbing", "ApiKey", "")
    dubbing_api_base = SettingField("Dubbing", "ApiBase", "")
    dubbing_model = SettingField("Dubbing", "Model", "")
    dubbing_tts_workers = RangeSettingField("Dubbing", "Workers", 5, RangeValidator(1, 20))
    dubbing_clone_audio = SettingField("Dubbing", "CloneAudio", "")
    dubbing_clone_text = SettingField("Dubbing", "CloneText", "")

    # ------------------- 实时字幕配置 -------------------
    # 转录引擎（Provider）：voxgate 本地免费无密钥；fun-asr 阿里云实时（中/粤/英/日/泰/越/印尼）；
    # qwen-asr 阿里云实时（27 语言含西语等，看外语视频选它）。fun-asr/qwen-asr 共用百炼 Key。
    live_caption_provider = ChoiceSettingField(
        "LiveCaption", "Provider", "voxgate",
        ChoiceValidator(["voxgate", "fun-asr", "qwen-asr"]),
    )
    # Fun-ASR 实时模型与识别语言（仅 fun-asr provider 用；API Key 复用 fun_asr_api_key）
    live_caption_fun_asr_model = ChoiceSettingField(
        "LiveCaption", "FunAsrModel", "fun-asr-mtl-realtime",
        ChoiceValidator(["fun-asr-mtl-realtime", "fun-asr-realtime"]),
    )
    live_caption_source_language = ChoiceSettingField(
        "LiveCaption", "SourceLanguage", "auto",
        ChoiceValidator(_LIVE_CAPTION_LANG_CODES),  # 接受 Fun-ASR/Qwen 两套并集
    )
    live_caption_translate = SettingField("LiveCaption", "TranslateEnabled", True, BoolValidator())
    live_caption_translator_service = ChoiceSettingField(
        "LiveCaption",
        "TranslatorServiceEnum",
        TranslatorServiceEnum.BING,
        ChoiceValidator(TranslatorServiceEnum),
        EnumSettingSerializer(TranslatorServiceEnum),
    )
    live_caption_target_language = ChoiceSettingField(
        "LiveCaption",
        "TargetLanguage",
        TargetLanguage.SIMPLIFIED_CHINESE,
        ChoiceValidator(TargetLanguage),
        EnumSettingSerializer(TargetLanguage),
    )
    live_caption_source = ChoiceSettingField(
        "LiveCaption", "Source", "microphone", ChoiceValidator(["microphone", "system"])
    )
    live_caption_device_index = SettingField("LiveCaption", "DeviceIndex", -1)
    live_caption_voxgate_binary = SettingField("LiveCaption", "VoxgateBinary", "")
    live_caption_show_overlay = SettingField("LiveCaption", "ShowOverlay", True)
    live_caption_display_mode = ChoiceSettingField(
        "LiveCaption", "DisplayMode", "bilingual",
        ChoiceValidator(["bilingual", "target", "source"]),
    )
    live_caption_bg_style = ChoiceSettingField(
        "LiveCaption", "BgStyle", "translucent",
        ChoiceValidator(["translucent", "black"]),
    )
    live_caption_font_scale = RangeSettingField("LiveCaption", "FontScale", 60, RangeValidator(0, 100))
    # 浮窗形态与用户拖边尺寸：展开/收纳 + 自己拖的大小，跨会话保持（0=未设，用预设/自适应）
    live_caption_overlay_mode = ChoiceSettingField(
        "LiveCaption", "OverlayMode", "standard",
        ChoiceValidator(["standard", "tall"]),
    )
    live_caption_overlay_w = SettingField("LiveCaption", "OverlayWidth", 0)
    live_caption_overlay_h = SettingField("LiveCaption", "OverlayHeight", 0)

    # ------------------- 字幕样式配置 -------------------
    subtitle_style_name = SettingField("SubtitleStyle", "StyleName", "rounded/default")
    subtitle_layout = ChoiceSettingField(
        "SubtitleStyle",
        "Layout",
        SubtitleLayoutEnum.TRANSLATE_ON_TOP,
        ChoiceValidator(SubtitleLayoutEnum),
        EnumSettingSerializer(SubtitleLayoutEnum),
    )
    subtitle_preview_image = SettingField("SubtitleStyle", "PreviewImage", "")
    # 预览示例文字（原文 / 译文），可自定义
    subtitle_preview_source = SettingField(
        "SubtitleStyle", "PreviewSource",
        "Mathematics is the language in which the laws of the universe are written.",
    )
    subtitle_preview_target = SettingField(
        "SubtitleStyle", "PreviewTarget", "数学，是书写宇宙规律的语言。",
    )

    # 字幕渲染模式
    subtitle_render_mode = ChoiceSettingField(
        "SubtitleStyle",
        "RenderMode",
        SubtitleRenderModeEnum.ROUNDED_BG,
        ChoiceValidator(SubtitleRenderModeEnum),
        EnumSettingSerializer(SubtitleRenderModeEnum),
    )

    # ------------------- 保存配置 -------------------
    work_dir = SettingField("Save", "Work_Dir", WORK_PATH, FolderValidator())
    keep_intermediates = SettingField("Save", "KeepIntermediates", False, BoolValidator())

    # ------------------- 软件页面配置 -------------------
    micaEnabled = SettingField("MainWindow", "MicaEnabled", False, BoolValidator())
    dpiScale = ChoiceSettingField(
        "MainWindow",
        "DpiScale",
        "Auto",
        ChoiceValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]),
        restart=True,
    )
    language = ChoiceSettingField(
        "MainWindow",
        "Language",
        Language.AUTO,
        ChoiceValidator(Language),
        LanguageSerializer(),
        restart=True,
    )

    # ------------------- 更新配置 -------------------
    checkUpdateAtStartUp = SettingField("Update", "CheckUpdateAtStartUp", True, BoolValidator())

    # ------------------- 缓存配置 -------------------
    cache_enabled = SettingField("Cache", "CacheEnabled", True, BoolValidator())


@dataclass(frozen=True)
class SharedConfigBinding:
    item: SettingField
    key: str
    to_toml: Callable[[Any], Any] = lambda value: value
    from_toml: Callable[[Any], Any] = lambda value: value


LLM_SERVICE_KEYS = {
    LLMServiceEnum.OPENAI: "openai",
    LLMServiceEnum.OFFICIAL: "official",
    LLMServiceEnum.SILICON_CLOUD: "silicon_cloud",
    LLMServiceEnum.DEEPSEEK: "deepseek",
    LLMServiceEnum.OLLAMA: "ollama",
    LLMServiceEnum.LM_STUDIO: "lm_studio",
    LLMServiceEnum.GEMINI: "gemini",
    LLMServiceEnum.CHATGLM: "chatglm",
    LLMServiceEnum.IMMERSIVE: "immersive",
}
KEY_TO_LLM_SERVICE = {value: key for key, value in LLM_SERVICE_KEYS.items()}

TRANSCRIBE_MODEL_KEYS = {
    TranscribeModelEnum.BIJIAN: "bijian",
    TranscribeModelEnum.JIANYING: "jianying",
    TranscribeModelEnum.BAILIAN_FUN_ASR: "fun-asr",
    TranscribeModelEnum.WHISPER_API: "whisper-api",
    TranscribeModelEnum.FASTER_WHISPER: "faster-whisper",
    TranscribeModelEnum.WHISPER_CPP: "whisper-cpp",
}

TRANSLATOR_KEYS = {
    TranslatorServiceEnum.OPENAI: "llm",
    TranslatorServiceEnum.BING: "bing",
    TranslatorServiceEnum.GOOGLE: "google",
    TranslatorServiceEnum.DEEPLX: "deeplx",
}

SUBTITLE_LAYOUT_KEYS = {
    SubtitleLayoutEnum.TRANSLATE_ON_TOP: "target-above",
    SubtitleLayoutEnum.ORIGINAL_ON_TOP: "source-above",
    SubtitleLayoutEnum.ONLY_TRANSLATE: "target-only",
    SubtitleLayoutEnum.ONLY_ORIGINAL: "source-only",
}

RENDER_MODE_KEYS = {
    SubtitleRenderModeEnum.ASS_STYLE: "ass",
    SubtitleRenderModeEnum.ROUNDED_BG: "rounded",
}

VIDEO_QUALITY_KEYS = {
    VideoQualityEnum.ULTRA_HIGH: "ultra",
    VideoQualityEnum.HIGH: "high",
    VideoQualityEnum.MEDIUM: "medium",
    VideoQualityEnum.LOW: "low",
}


def _llm_service_to_key(value: Any) -> str:
    return LLM_SERVICE_KEYS.get(value, "openai")


def _llm_service_from_key(value: Any) -> LLMServiceEnum:
    # 兼容 CLI/手编 TOML 的非下划线别名（siliconcloud/lmstudio），与
    # cli/config_adapter 接受的写法一致；否则 GUI 读不到会回落 openai 丢配置。
    key = str(value or "openai").lower()
    key = {"siliconcloud": "silicon_cloud", "lmstudio": "lm_studio"}.get(key, key)
    return KEY_TO_LLM_SERVICE.get(key, LLMServiceEnum.OPENAI)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _transcribe_model_to_key(value: Any) -> str:
    return TRANSCRIBE_MODEL_KEYS.get(value, "bijian")


def _transcribe_language_to_key(value: Any) -> str:
    label = _enum_value(value)
    return LANGUAGES.get(label, "") or "auto"


def _transcribe_language_from_key(value: Any) -> TranscribeLanguageEnum:
    raw = str(value or "auto").lower()
    if raw in {"", "auto"}:
        return TranscribeLanguageEnum.AUTO

    for language in TranscribeLanguageEnum:
        if LANGUAGES.get(language.value, "").lower() == raw:
            return language
        if language.value.lower() == raw or language.name.lower() == raw:
            return language
    return TranscribeLanguageEnum.AUTO


def _output_format_to_key(value: Any) -> str:
    return str(_enum_value(value) or "srt").lower()


def _target_language_to_key(value: Any) -> str:
    return BING_LANG_MAP.get(value, "zh-Hans")


def _translator_to_key(value: Any) -> str:
    return TRANSLATOR_KEYS.get(value, "bing")


def _subtitle_layout_to_key(value: Any) -> str:
    return SUBTITLE_LAYOUT_KEYS.get(value, "target-above")


def _render_mode_to_key(value: Any) -> str:
    return RENDER_MODE_KEYS.get(value, "rounded")


def _video_quality_to_key(value: Any) -> str:
    return VIDEO_QUALITY_KEYS.get(value, "medium")


def _theme_from_toml(value: Any) -> ThemeMode:
    raw = str(value or "Dark").strip().lower()
    for theme in ThemeMode:
        if theme.value.lower() == raw or theme.name.lower() == raw:
            return theme
    return ThemeMode.DARK


def _theme_to_toml(value: Any) -> str:
    return _enum_value(value) or "Dark"


def _theme_color_from_toml(value: Any) -> QColor:
    color = QColor(str(value or "#ff28f08b"))
    return color if color.isValid() else QColor("#ff28f08b")


def _theme_color_to_toml(value: Any) -> str:
    if isinstance(value, QColor):
        return value.name(QColor.HexRgb)
    color = QColor(str(value))
    return color.name(QColor.HexRgb) if color.isValid() else "#28f08b"


def _work_dir_from_toml(value: Any) -> str:
    """共享配置里 work_dir 空串表示“未设置”；回退到应用默认工作目录。

    不能交给 FolderValidator 纠正：Path("") 会被纠正成当前进程 CWD，
    新配置文件的用户会把工作产物写进启动目录（曾把仓库根当工作目录）。
    """
    return str(value).strip() or str(WORK_PATH)


def _language_from_toml(value: Any) -> Language:
    try:
        return LanguageSerializer().deserialize(str(value or "Auto"))
    except Exception:
        return Language.AUTO


def _language_to_toml(value: Any) -> str:
    return LanguageSerializer().serialize(value)


def _model_options_from_toml(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _clean_model_options(value)


def _model_options_to_toml(value: Any) -> list[str]:
    return _clean_model_options(value)


def _clean_model_options(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    options: list[str] = []
    seen: set[str] = set()
    for item in value:
        model = str(item or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        options.append(model)
    return options


def _bindings() -> list[SharedConfigBinding]:
    return [
        SharedConfigBinding(cfg.themeMode, "ui.theme_mode", _theme_to_toml, _theme_from_toml),
        SharedConfigBinding(
            cfg.transcribe_panel_collapsed, "ui.transcribe_panel_collapsed"
        ),
        SharedConfigBinding(cfg.subtitle_panel_collapsed, "ui.subtitle_panel_collapsed"),
        SharedConfigBinding(
            cfg.synthesis_panel_collapsed, "ui.synthesis_panel_collapsed"
        ),
        SharedConfigBinding(cfg.batch_mode, "ui.batch_mode"),
        SharedConfigBinding(cfg.batch_concurrency, "ui.batch_concurrency"),
        SharedConfigBinding(
            cfg.themeColor, "ui.theme_color", _theme_color_to_toml, _theme_color_from_toml
        ),
        SharedConfigBinding(cfg.dpiScale, "ui.dpi_scale"),
        SharedConfigBinding(cfg.language, "ui.language", _language_to_toml, _language_from_toml),
        SharedConfigBinding(cfg.micaEnabled, "ui.mica_enabled"),
        SharedConfigBinding(cfg.checkUpdateAtStartUp, "ui.check_update_at_startup"),
        SharedConfigBinding(cfg.subtitle_preview_image, "ui.subtitle_preview_image"),
        SharedConfigBinding(cfg.subtitle_preview_source, "ui.subtitle_preview_source"),
        SharedConfigBinding(cfg.subtitle_preview_target, "ui.subtitle_preview_target"),
        SharedConfigBinding(cfg.recent_colors, "ui.recent_colors"),
        SharedConfigBinding(cfg.work_dir, "app.work_dir", from_toml=_work_dir_from_toml),
        SharedConfigBinding(cfg.keep_intermediates, "app.keep_intermediates"),
        SharedConfigBinding(cfg.cache_enabled, "app.cache_enabled"),
        SharedConfigBinding(
            cfg.llm_service, "llm.service", _llm_service_to_key, _llm_service_from_key
        ),
        SharedConfigBinding(cfg.openai_api_key, "llm.providers.openai.api_key"),
        SharedConfigBinding(cfg.openai_api_base, "llm.providers.openai.api_base"),
        SharedConfigBinding(cfg.openai_model, "llm.providers.openai.model"),
        SharedConfigBinding(
            cfg.openai_model_options,
            "llm.providers.openai.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.official_api_key, "llm.providers.official.api_key"),
        SharedConfigBinding(cfg.official_api_base, "llm.providers.official.api_base"),
        SharedConfigBinding(cfg.official_model, "llm.providers.official.model"),
        SharedConfigBinding(
            cfg.official_model_options,
            "llm.providers.official.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.silicon_cloud_api_key, "llm.providers.silicon_cloud.api_key"),
        SharedConfigBinding(cfg.silicon_cloud_api_base, "llm.providers.silicon_cloud.api_base"),
        SharedConfigBinding(cfg.silicon_cloud_model, "llm.providers.silicon_cloud.model"),
        SharedConfigBinding(
            cfg.silicon_cloud_model_options,
            "llm.providers.silicon_cloud.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.deepseek_api_key, "llm.providers.deepseek.api_key"),
        SharedConfigBinding(cfg.deepseek_api_base, "llm.providers.deepseek.api_base"),
        SharedConfigBinding(cfg.deepseek_model, "llm.providers.deepseek.model"),
        SharedConfigBinding(
            cfg.deepseek_model_options,
            "llm.providers.deepseek.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.ollama_api_key, "llm.providers.ollama.api_key"),
        SharedConfigBinding(cfg.ollama_api_base, "llm.providers.ollama.api_base"),
        SharedConfigBinding(cfg.ollama_model, "llm.providers.ollama.model"),
        SharedConfigBinding(
            cfg.ollama_model_options,
            "llm.providers.ollama.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.lm_studio_api_key, "llm.providers.lm_studio.api_key"),
        SharedConfigBinding(cfg.lm_studio_api_base, "llm.providers.lm_studio.api_base"),
        SharedConfigBinding(cfg.lm_studio_model, "llm.providers.lm_studio.model"),
        SharedConfigBinding(
            cfg.lm_studio_model_options,
            "llm.providers.lm_studio.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.gemini_api_key, "llm.providers.gemini.api_key"),
        SharedConfigBinding(cfg.gemini_api_base, "llm.providers.gemini.api_base"),
        SharedConfigBinding(cfg.gemini_model, "llm.providers.gemini.model"),
        SharedConfigBinding(
            cfg.gemini_model_options,
            "llm.providers.gemini.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(cfg.chatglm_api_key, "llm.providers.chatglm.api_key"),
        SharedConfigBinding(cfg.chatglm_api_base, "llm.providers.chatglm.api_base"),
        SharedConfigBinding(cfg.chatglm_model, "llm.providers.chatglm.model"),
        SharedConfigBinding(
            cfg.chatglm_model_options,
            "llm.providers.chatglm.model_options",
            _model_options_to_toml,
            _model_options_from_toml,
        ),
        SharedConfigBinding(
            cfg.transcribe_model,
            "transcribe.asr",
            _transcribe_model_to_key,
            transcribe_model_from_cli,
        ),
        SharedConfigBinding(
            cfg.transcribe_output_format,
            "transcribe.output_format",
            _output_format_to_key,
            transcribe_output_format_from_cli,
        ),
        SharedConfigBinding(
            cfg.transcribe_language,
            "transcribe.language",
            _transcribe_language_to_key,
            _transcribe_language_from_key,
        ),
        SharedConfigBinding(cfg.transcribe_word_timestamp, "transcribe.word_timestamp"),
        SharedConfigBinding(
            cfg.whisper_model,
            "transcribe.whisper_cpp.model",
            _enum_value,
            lambda value: enum_by_value(WhisperModelEnum, str(value), WhisperModelEnum.TINY),
        ),
        SharedConfigBinding(cfg.whisper_api_key, "whisper_api.api_key"),
        SharedConfigBinding(cfg.whisper_api_base, "whisper_api.api_base"),
        SharedConfigBinding(cfg.whisper_api_model, "whisper_api.model"),
        SharedConfigBinding(cfg.whisper_api_prompt, "whisper_api.prompt"),
        SharedConfigBinding(cfg.fun_asr_api_key, "fun_asr.api_key"),
        SharedConfigBinding(cfg.fun_asr_api_base, "fun_asr.api_base"),
        SharedConfigBinding(cfg.fun_asr_model, "fun_asr.model"),
        SharedConfigBinding(cfg.faster_whisper_program, "transcribe.faster_whisper.program"),
        SharedConfigBinding(
            cfg.faster_whisper_model,
            "transcribe.faster_whisper.model",
            _enum_value,
            lambda value: enum_by_value(
                FasterWhisperModelEnum, str(value), FasterWhisperModelEnum.TINY
            ),
        ),
        SharedConfigBinding(cfg.faster_whisper_model_dir, "transcribe.faster_whisper.model_dir"),
        SharedConfigBinding(cfg.faster_whisper_device, "transcribe.faster_whisper.device"),
        SharedConfigBinding(cfg.faster_whisper_vad_filter, "transcribe.faster_whisper.vad_filter"),
        SharedConfigBinding(
            cfg.faster_whisper_vad_threshold, "transcribe.faster_whisper.vad_threshold"
        ),
        SharedConfigBinding(
            cfg.faster_whisper_vad_method,
            "transcribe.faster_whisper.vad_method",
            _enum_value,
            lambda value: enum_by_value(
                VadMethodEnum, str(value).replace("-", "_"), VadMethodEnum.SILERO_V4
            ),
        ),
        SharedConfigBinding(
            cfg.faster_whisper_ff_mdx_kim2, "transcribe.faster_whisper.voice_extraction"
        ),
        SharedConfigBinding(cfg.faster_whisper_one_word, "transcribe.faster_whisper.one_word"),
        SharedConfigBinding(cfg.faster_whisper_prompt, "transcribe.faster_whisper.prompt"),
        SharedConfigBinding(
            cfg.translator_service, "translate.service", _translator_to_key, translator_from_cli
        ),
        SharedConfigBinding(cfg.need_reflect_translate, "translate.reflect"),
        SharedConfigBinding(cfg.deeplx_endpoint, "translate.deeplx_endpoint"),
        SharedConfigBinding(cfg.batch_size, "subtitle.batch_size"),
        SharedConfigBinding(cfg.thread_num, "subtitle.thread_num"),
        SharedConfigBinding(cfg.need_optimize, "subtitle.optimize"),
        SharedConfigBinding(cfg.need_translate, "subtitle.translate"),
        SharedConfigBinding(cfg.need_split, "subtitle.split"),
        SharedConfigBinding(
            cfg.target_language,
            "translate.target_language",
            _target_language_to_key,
            target_language_from_code,
        ),
        SharedConfigBinding(cfg.max_word_count_cjk, "subtitle.max_word_count_cjk"),
        SharedConfigBinding(cfg.max_word_count_english, "subtitle.max_word_count_english"),
        SharedConfigBinding(cfg.custom_prompt_text, "subtitle.custom_prompt"),
        SharedConfigBinding(cfg.soft_subtitle, "synthesize.soft_subtitle"),
        SharedConfigBinding(cfg.need_video, "synthesize.need_video"),
        SharedConfigBinding(
            cfg.video_quality, "synthesize.quality", _video_quality_to_key, quality_from_cli
        ),
        SharedConfigBinding(cfg.subtitle_style_name, "synthesize.style"),
        SharedConfigBinding(
            cfg.subtitle_layout, "synthesize.layout", _subtitle_layout_to_key, layout_from_cli
        ),
        SharedConfigBinding(
            cfg.subtitle_render_mode,
            "synthesize.render_mode",
            _render_mode_to_key,
            render_mode_from_cli,
        ),
        SharedConfigBinding(cfg.dubbing_enabled, "dubbing.enabled"),
        SharedConfigBinding(cfg.dubbing_provider, "dubbing.provider"),
        SharedConfigBinding(cfg.dubbing_preset, "dubbing.preset"),
        SharedConfigBinding(cfg.dubbing_voice, "dubbing.voice"),
        SharedConfigBinding(cfg.dubbing_text_track, "dubbing.text_track"),
        SharedConfigBinding(cfg.dubbing_timing, "dubbing.timing"),
        SharedConfigBinding(cfg.dubbing_audio_mode, "dubbing.audio_mode"),
        SharedConfigBinding(cfg.dubbing_api_key, "dubbing.api_key"),
        SharedConfigBinding(cfg.dubbing_api_base, "dubbing.api_base"),
        SharedConfigBinding(cfg.dubbing_model, "dubbing.model"),
        SharedConfigBinding(cfg.dubbing_tts_workers, "dubbing.tts_workers"),
        # 克隆参考音频/文本：绑定后 valueChanged 会触发共享持久化，重启不再丢；
        # 与 config_store DEFAULTS、cli/config_adapter 的读取保持闭环。
        SharedConfigBinding(cfg.dubbing_clone_audio, "dubbing.clone_audio"),
        SharedConfigBinding(cfg.dubbing_clone_text, "dubbing.clone_text"),
        SharedConfigBinding(cfg.live_caption_provider, "live_caption.backend"),
        SharedConfigBinding(cfg.live_caption_fun_asr_model, "live_caption.fun_asr_model"),
        SharedConfigBinding(cfg.live_caption_source_language, "live_caption.source_language"),
        SharedConfigBinding(cfg.live_caption_translate, "live_caption.translate_enabled"),
        SharedConfigBinding(
            cfg.live_caption_translator_service,
            "live_caption.translator_service",
            _translator_to_key,
            translator_from_cli,
        ),
        SharedConfigBinding(
            cfg.live_caption_target_language,
            "live_caption.target_language",
            _target_language_to_key,
            target_language_from_code,
        ),
        SharedConfigBinding(cfg.live_caption_source, "live_caption.source"),
        SharedConfigBinding(cfg.live_caption_device_index, "live_caption.device_index"),
        SharedConfigBinding(cfg.live_caption_voxgate_binary, "live_caption.voxgate_binary"),
        SharedConfigBinding(cfg.live_caption_show_overlay, "live_caption.show_overlay"),
        SharedConfigBinding(cfg.live_caption_display_mode, "live_caption.display_mode"),
        SharedConfigBinding(cfg.live_caption_bg_style, "live_caption.bg_style"),
        SharedConfigBinding(cfg.live_caption_font_scale, "live_caption.font_scale"),
        SharedConfigBinding(cfg.live_caption_overlay_mode, "live_caption.overlay_mode"),
        SharedConfigBinding(cfg.live_caption_overlay_w, "live_caption.overlay_w"),
        SharedConfigBinding(cfg.live_caption_overlay_h, "live_caption.overlay_h"),
    ]


_syncing_shared_config = False


def _load_shared_config_to_state() -> None:
    global _syncing_shared_config
    shared_config = build_config()
    _syncing_shared_config = True
    try:
        # 归一别名（siliconcloud/lmstudio -> silicon_cloud/lm_studio），否则手编/CLI
        # 写入的别名拼出的 provider 段键匹配不上 binding，generic_api_key 兜底失效。
        active_provider = _llm_service_to_key(
            _llm_service_from_key(get(shared_config, "llm.service", "openai"))
        )
        generic_api_key = get(shared_config, "llm.api_key", "")
        for binding in _bindings():
            raw_value = get(shared_config, binding.key, None)
            if (
                raw_value in (None, "")
                and binding.key == f"llm.providers.{active_provider}.api_key"
            ):
                raw_value = generic_api_key
            if raw_value is None:
                continue
            try:
                binding.item.value = binding.from_toml(raw_value)
            except Exception:
                continue
    finally:
        _syncing_shared_config = False


def _collect_shared_config_values() -> dict[str, Any]:
    values = {binding.key: binding.to_toml(binding.item.value) for binding in _bindings()}
    provider_key = _llm_service_to_key(cfg.llm_service.value)
    values["llm.api_key"] = values.get(f"llm.providers.{provider_key}.api_key", "")
    values["llm.api_base"] = values.get(f"llm.providers.{provider_key}.api_base", "")
    values["llm.model"] = values.get(f"llm.providers.{provider_key}.model", "")
    values["dubbing.use_cache"] = values["app.cache_enabled"]
    values["output.format"] = values["transcribe.output_format"]
    values["synthesize.subtitle_mode"] = "soft" if bool(cfg.soft_subtitle.value) else "hard"
    return values


def _save_shared_config() -> None:
    if _syncing_shared_config:
        return
    try:
        save_many(_collect_shared_config_values())
    except OSError:
        return


def _install_shared_config_sync() -> None:
    for binding in _bindings():
        binding.item.valueChanged.connect(lambda _value, _binding=binding: _save_shared_config())


cfg = Config()
cfg.themeMode.value = ThemeMode.DARK
cfg.themeColor.value = QColor(DEFAULT_THEME_COLOR)
_load_shared_config_to_state()
_install_shared_config_sync()
cfg.save = _save_shared_config
