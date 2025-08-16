import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SupportedAudioFormats(Enum):
    """支持的音频格式"""

    AAC = "aac"
    AC3 = "ac3"
    AIFF = "aiff"
    AMR = "amr"
    APE = "ape"
    AU = "au"
    FLAC = "flac"
    M4A = "m4a"
    MP2 = "mp2"
    MP3 = "mp3"
    MKA = "mka"
    OGA = "oga"
    OGG = "ogg"
    OPUS = "opus"
    RA = "ra"
    WAV = "wav"
    WMA = "wma"


class SupportedVideoFormats(Enum):
    """支持的视频格式"""

    MP4 = "mp4"
    WEBM = "webm"
    OGM = "ogm"
    MOV = "mov"
    MKV = "mkv"
    AVI = "avi"
    WMV = "wmv"
    FLV = "flv"
    M4V = "m4v"
    TS = "ts"
    MPG = "mpg"
    MPEG = "mpeg"
    VOB = "vob"
    ASF = "asf"
    RM = "rm"
    RMVB = "rmvb"
    M2TS = "m2ts"
    MTS = "mts"
    DV = "dv"
    GXF = "gxf"
    TOD = "tod"
    MXF = "mxf"
    F4V = "f4v"


class SupportedSubtitleFormats(Enum):
    """支持的字幕格式"""

    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"


class OutputSubtitleFormatEnum(Enum):
    """字幕输出格式"""

    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"
    JSON = "json"
    TXT = "txt"


class LLMServiceEnum(Enum):
    """LLM服务"""

    OPENAI = "OpenAI"
    SILICON_CLOUD = "SiliconCloud"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"
    LM_STUDIO = "LM Studio"
    GEMINI = "Gemini"
    CHATGLM = "ChatGLM"
    PUBLIC = "软件公益模型"


class TranscribeModelEnum(Enum):
    """转录模型"""

    BIJIAN = "B 接口"
    JIANYING = "J 接口"
    FASTER_WHISPER = "FasterWhisper ✨"
    WHISPER_CPP = "WhisperCpp"
    WHISPER_API = "Whisper [API]"


class TranslatorServiceEnum(Enum):
    """翻译器服务"""

    OPENAI = "LLM 大模型翻译"
    DEEPLX = "DeepLx 翻译"
    BING = "微软翻译"
    GOOGLE = "谷歌翻译"


class VadMethodEnum(Enum):
    """VAD方法"""

    SILERO_V3 = "silero_v3"  # 通常比 v4 准确性低，但没有 v4 的一些怪癖
    SILERO_V4 = (
        "silero_v4"  # 与 silero_v4_fw 相同。运行原始 Silero 的代码，而不是适配过的代码
    )
    SILERO_V5 = (
        "silero_v5"  # 与 silero_v5_fw 相同。运行原始 Silero 的代码，而不是适配过的代码)
    )
    SILERO_V4_FW = (
        "silero_v4_fw"  # 默认模型。最准确的 Silero 版本，有一些非致命的小问题
    )
    # SILERO_V5_FW = "silero_v5_fw"  # 准确性差。不是 VAD，而是某种语音的随机检测器，有各种致命的小问题。避免使用！
    PYANNOTE_V3 = "pyannote_v3"  # 最佳准确性，支持 CUDA
    PYANNOTE_ONNX_V3 = "pyannote_onnx_v3"  # pyannote_v3 的轻量版。与 Silero v4 的准确性相似，可能稍好，支持 CUDA
    WEBRTC = "webrtc"  # 准确性低，过时的 VAD。仅接受 'vad_min_speech_duration_ms' 和 'vad_speech_pad_ms'
    AUDITOK = "auditok"  # 实际上这不是 VAD，而是 AAD - 音频活动检测


class SplitTypeEnum(Enum):
    """字幕分段类型"""

    SEMANTIC = "语义分段"
    SENTENCE = "句子分段"


class TargetLanguageEnum(Enum):
    """翻译目标语言"""

    CHINESE_SIMPLIFIED = "简体中文"
    CHINESE_TRADITIONAL = "繁体中文"
    ENGLISH = "英语"
    JAPANESE = "日本語"
    KOREAN = "韩语"
    YUE = "粤语"
    FRENCH = "法语"
    GERMAN = "德语"
    SPANISH = "西班牙语"
    RUSSIAN = "俄语"
    PORTUGUESE = "葡萄牙语"
    TURKISH = "土耳其语"
    POLISH = "Polish"
    CATALAN = "Catalan"
    DUTCH = "Dutch"
    ARABIC = "Arabic"
    SWEDISH = "Swedish"
    ITALIAN = "Italian"
    INDONESIAN = "Indonesian"
    HINDI = "Hindi"
    FINNISH = "Finnish"
    VIETNAMESE = "Vietnamese"
    HEBREW = "Hebrew"
    UKRAINIAN = "Ukrainian"
    GREEK = "Greek"
    MALAY = "Malay"
    CZECH = "Czech"
    ROMANIAN = "Romanian"
    DANISH = "Danish"
    HUNGARIAN = "Hungarian"
    TAMIL = "Tamil"
    NORWEGIAN = "Norwegian"
    THAI = "Thai"
    URDU = "Urdu"
    CROATIAN = "Croatian"
    BULGARIAN = "Bulgarian"
    LITHUANIAN = "Lithuanian"
    LATIN = "Latin"
    MAORI = "Maori"
    MALAYALAM = "Malayalam"
    WELSH = "Welsh"
    SLOVAK = "Slovak"
    TELUGU = "Telugu"
    PERSIAN = "Persian"
    LATVIAN = "Latvian"
    BENGALI = "Bengali"
    SERBIAN = "Serbian"
    AZERBAIJANI = "Azerbaijani"
    SLOVENIAN = "Slovenian"
    KANNADA = "Kannada"
    ESTONIAN = "Estonian"
    MACEDONIAN = "Macedonian"
    BRETON = "Breton"
    BASQUE = "Basque"
    ICELANDIC = "Icelandic"
    ARMENIAN = "Armenian"
    NEPALI = "Nepali"
    MONGOLIAN = "Mongolian"
    BOSNIAN = "Bosnian"
    KAZAKH = "Kazakh"
    ALBANIAN = "Albanian"
    SWAHILI = "Swahili"
    GALICIAN = "Galician"
    MARATHI = "Marathi"
    PUNJABI = "Punjabi"
    SINHALA = "Sinhala"
    KHMER = "Khmer"
    SHONA = "Shona"
    YORUBA = "Yoruba"
    SOMALI = "Somali"
    AFRIKAANS = "Afrikaans"
    OCCITAN = "Occitan"
    GEORGIAN = "Georgian"
    BELARUSIAN = "Belarusian"
    TAJIK = "Tajik"
    SINDHI = "Sindhi"
    GUJARATI = "Gujarati"
    AMHARIC = "Amharic"
    YIDDISH = "Yiddish"
    LAO = "Lao"
    UZBEK = "Uzbek"
    FAROESE = "Faroese"
    HAITIAN_CREOLE = "Haitian Creole"
    PASHTO = "Pashto"
    TURKMEN = "Turkmen"
    NYNORSK = "Nynorsk"
    MALTESE = "Maltese"
    SANSKRIT = "Sanskrit"
    LUXEMBOURGISH = "Luxembourgish"
    MYANMAR = "Myanmar"
    TIBETAN = "Tibetan"
    TAGALOG = "Tagalog"
    MALAGASY = "Malagasy"
    ASSAMESE = "Assamese"
    TATAR = "Tatar"
    HAWAIIAN = "Hawaiian"
    LINGALA = "Lingala"
    HAUSA = "Hausa"
    BASHKIR = "Bashkir"
    JAVANESE = "Javanese"
    SUNDANESE = "Sundanese"
    CANTONESE = "Cantonese"


class TranscribeLanguageEnum(Enum):
    """转录语言"""

    ENGLISH = "英语"
    CHINESE = "中文"
    JAPANESE = "日本語"
    KOREAN = "韩语"
    YUE = "粤语"
    FRENCH = "法语"
    GERMAN = "德语"
    SPANISH = "西班牙语"
    RUSSIAN = "俄语"
    PORTUGUESE = "葡萄牙语"
    TURKISH = "土耳其语"
    POLISH = "Polish"
    CATALAN = "Catalan"
    DUTCH = "Dutch"
    ARABIC = "Arabic"
    SWEDISH = "Swedish"
    ITALIAN = "Italian"
    INDONESIAN = "Indonesian"
    HINDI = "Hindi"
    FINNISH = "Finnish"
    VIETNAMESE = "Vietnamese"
    HEBREW = "Hebrew"
    UKRAINIAN = "Ukrainian"
    GREEK = "Greek"
    MALAY = "Malay"
    CZECH = "Czech"
    ROMANIAN = "Romanian"
    DANISH = "Danish"
    HUNGARIAN = "Hungarian"
    TAMIL = "Tamil"
    NORWEGIAN = "Norwegian"
    THAI = "Thai"
    URDU = "Urdu"
    CROATIAN = "Croatian"
    BULGARIAN = "Bulgarian"
    LITHUANIAN = "Lithuanian"
    LATIN = "Latin"
    MAORI = "Maori"
    MALAYALAM = "Malayalam"
    WELSH = "Welsh"
    SLOVAK = "Slovak"
    TELUGU = "Telugu"
    PERSIAN = "Persian"
    LATVIAN = "Latvian"
    BENGALI = "Bengali"
    SERBIAN = "Serbian"
    AZERBAIJANI = "Azerbaijani"
    SLOVENIAN = "Slovenian"
    KANNADA = "Kannada"
    ESTONIAN = "Estonian"
    MACEDONIAN = "Macedonian"
    BRETON = "Breton"
    BASQUE = "Basque"
    ICELANDIC = "Icelandic"
    ARMENIAN = "Armenian"
    NEPALI = "Nepali"
    MONGOLIAN = "Mongolian"
    BOSNIAN = "Bosnian"
    KAZAKH = "Kazakh"
    ALBANIAN = "Albanian"
    SWAHILI = "Swahili"
    GALICIAN = "Galician"
    MARATHI = "Marathi"
    PUNJABI = "Punjabi"
    SINHALA = "Sinhala"
    KHMER = "Khmer"
    SHONA = "Shona"
    YORUBA = "Yoruba"
    SOMALI = "Somali"
    AFRIKAANS = "Afrikaans"
    OCCITAN = "Occitan"
    GEORGIAN = "Georgian"
    BELARUSIAN = "Belarusian"
    TAJIK = "Tajik"
    SINDHI = "Sindhi"
    GUJARATI = "Gujarati"
    AMHARIC = "Amharic"
    YIDDISH = "Yiddish"
    LAO = "Lao"
    UZBEK = "Uzbek"
    FAROESE = "Faroese"
    HAITIAN_CREOLE = "Haitian Creole"
    PASHTO = "Pashto"
    TURKMEN = "Turkmen"
    NYNORSK = "Nynorsk"
    MALTESE = "Maltese"
    SANSKRIT = "Sanskrit"
    LUXEMBOURGISH = "Luxembourgish"
    MYANMAR = "Myanmar"
    TIBETAN = "Tibetan"
    TAGALOG = "Tagalog"
    MALAGASY = "Malagasy"
    ASSAMESE = "Assamese"
    TATAR = "Tatar"
    HAWAIIAN = "Hawaiian"
    LINGALA = "Lingala"
    HAUSA = "Hausa"
    BASHKIR = "Bashkir"
    JAVANESE = "Javanese"
    SUNDANESE = "Sundanese"
    CANTONESE = "Cantonese"


class WhisperModelEnum(Enum):
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V1 = "large-v1"
    LARGE_V2 = "large-v2"


class FasterWhisperModelEnum(Enum):
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V1 = "large-v1"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"
    LARGE_V3_TURBO = "large-v3-turbo"


LANGUAGES = {
    "英语": "en",
    "中文": "zh",
    "日本語": "ja",
    "德语": "de",
    "粤语": "yue",
    "西班牙语": "es",
    "俄语": "ru",
    "韩语": "ko",
    "法语": "fr",
    "葡萄牙语": "pt",
    "土耳其语": "tr",
    "English": "en",
    "Chinese": "zh",
    "German": "de",
    "Spanish": "es",
    "Russian": "ru",
    "Korean": "ko",
    "French": "fr",
    "Japanese": "ja",
    "Portuguese": "pt",
    "Turkish": "tr",
    "Polish": "pl",
    "Catalan": "ca",
    "Dutch": "nl",
    "Arabic": "ar",
    "Swedish": "sv",
    "Italian": "it",
    "Indonesian": "id",
    "Hindi": "hi",
    "Finnish": "fi",
    "Vietnamese": "vi",
    "Hebrew": "he",
    "Ukrainian": "uk",
    "Greek": "el",
    "Malay": "ms",
    "Czech": "cs",
    "Romanian": "ro",
    "Danish": "da",
    "Hungarian": "hu",
    "Tamil": "ta",
    "Norwegian": "no",
    "Thai": "th",
    "Urdu": "ur",
    "Croatian": "hr",
    "Bulgarian": "bg",
    "Lithuanian": "lt",
    "Latin": "la",
    "Maori": "mi",
    "Malayalam": "ml",
    "Welsh": "cy",
    "Slovak": "sk",
    "Telugu": "te",
    "Persian": "fa",
    "Latvian": "lv",
    "Bengali": "bn",
    "Serbian": "sr",
    "Azerbaijani": "az",
    "Slovenian": "sl",
    "Kannada": "kn",
    "Estonian": "et",
    "Macedonian": "mk",
    "Breton": "br",
    "Basque": "eu",
    "Icelandic": "is",
    "Armenian": "hy",
    "Nepali": "ne",
    "Mongolian": "mn",
    "Bosnian": "bs",
    "Kazakh": "kk",
    "Albanian": "sq",
    "Swahili": "sw",
    "Galician": "gl",
    "Marathi": "mr",
    "Punjabi": "pa",
    "Sinhala": "si",
    "Khmer": "km",
    "Shona": "sn",
    "Yoruba": "yo",
    "Somali": "so",
    "Afrikaans": "af",
    "Occitan": "oc",
    "Georgian": "ka",
    "Belarusian": "be",
    "Tajik": "tg",
    "Sindhi": "sd",
    "Gujarati": "gu",
    "Amharic": "am",
    "Yiddish": "yi",
    "Lao": "lo",
    "Uzbek": "uz",
    "Faroese": "fo",
    "Haitian Creole": "ht",
    "Pashto": "ps",
    "Turkmen": "tk",
    "Nynorsk": "nn",
    "Maltese": "mt",
    "Sanskrit": "sa",
    "Luxembourgish": "lb",
    "Myanmar": "my",
    "Tibetan": "bo",
    "Tagalog": "tl",
    "Malagasy": "mg",
    "Assamese": "as",
    "Tatar": "tt",
    "Hawaiian": "haw",
    "Lingala": "ln",
    "Hausa": "ha",
    "Bashkir": "ba",
    "Javanese": "jw",
    "Sundanese": "su",
    "Cantonese": "yue",
}


@dataclass
class VideoInfo:
    """视频信息类"""

    file_name: str
    file_path: str
    width: int
    height: int
    fps: float
    duration_seconds: float
    bitrate_kbps: int
    video_codec: str
    audio_codec: str
    audio_sampling_rate: int
    thumbnail_path: str


@dataclass
class TranscribeConfig:
    """转录配置类"""

    transcribe_model: Optional[TranscribeModelEnum] = None
    transcribe_language: str = ""
    use_asr_cache: bool = True
    need_word_time_stamp: bool = True
    # Whisper Cpp 配置
    whisper_model: Optional[WhisperModelEnum] = None
    # Whisper API 配置
    whisper_api_key: Optional[str] = None
    whisper_api_base: Optional[str] = None
    whisper_api_model: Optional[str] = None
    whisper_api_prompt: Optional[str] = None
    # Faster Whisper 配置
    faster_whisper_program: Optional[str] = None
    faster_whisper_model: Optional[FasterWhisperModelEnum] = None
    faster_whisper_model_dir: Optional[str] = None
    faster_whisper_device: str = "cuda"
    faster_whisper_vad_filter: bool = True
    faster_whisper_vad_threshold: float = 0.5
    faster_whisper_vad_method: Optional[VadMethodEnum] = VadMethodEnum.SILERO_V3
    faster_whisper_ff_mdx_kim2: bool = False
    faster_whisper_one_word: bool = True
    faster_whisper_prompt: Optional[str] = None


@dataclass
class SubtitleConfig:
    """字幕处理配置类"""

    # 翻译配置
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    llm_model: Optional[str] = None
    deeplx_endpoint: Optional[str] = None
    # 翻译服务
    translator_service: Optional[TranslatorServiceEnum] = None
    need_translate: bool = False
    need_optimize: bool = False
    need_reflect: bool = False
    thread_num: int = 10
    batch_size: int = 10
    # 字幕布局和分割
    split_type: Optional[SplitTypeEnum] = None
    subtitle_layout: Optional[str] = None
    max_word_count_cjk: int = 12
    max_word_count_english: int = 18
    need_split: bool = True
    target_language: Optional[TargetLanguageEnum] = None
    subtitle_style: Optional[str] = None
    need_remove_punctuation: bool = False
    custom_prompt_text: Optional[str] = None


@dataclass
class SynthesisConfig:
    """视频合成配置类"""

    need_video: bool = True
    soft_subtitle: bool = True


@dataclass
class TranscribeTask:
    """转录任务类"""

    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    # 输入文件
    file_path: Optional[str] = None

    # 输出字幕文件
    output_path: Optional[str] = None

    # 是否需要执行下一个任务（字幕处理）
    need_next_task: bool = False

    transcribe_config: Optional[TranscribeConfig] = None


@dataclass
class SubtitleTask:
    """字幕任务类"""

    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    # 输入原始字幕文件
    subtitle_path: str = ""
    # 输入原始视频文件
    video_path: Optional[str] = None

    # 输出 断句、优化、翻译 后的字幕文件
    output_path: Optional[str] = None

    # 是否需要执行下一个任务（视频合成）
    need_next_task: bool = True

    subtitle_config: Optional[SubtitleConfig] = None


@dataclass
class SynthesisTask:
    """视频合成任务类"""

    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    # 输入
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None

    # 输出
    output_path: Optional[str] = None

    # 是否需要执行下一个任务（预留）
    need_next_task: bool = False

    synthesis_config: Optional[SynthesisConfig] = None


@dataclass
class TranscriptAndSubtitleTask:
    """转录和字幕任务类"""

    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    # 输入
    file_path: Optional[str] = None

    # 输出
    output_path: Optional[str] = None

    transcribe_config: Optional[TranscribeConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None


@dataclass
class FullProcessTask:
    """完整处理任务类(转录+字幕+合成)"""

    queued_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    # 输入
    file_path: Optional[str] = None
    # 输出
    output_path: Optional[str] = None

    transcribe_config: Optional[TranscribeConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None
    synthesis_config: Optional[SynthesisConfig] = None


class BatchTaskType(Enum):
    """批量处理任务类型"""

    TRANSCRIBE = "批量转录"
    SUBTITLE = "批量字幕"
    TRANS_SUB = "转录+字幕"
    FULL_PROCESS = "全流程处理"

    def __str__(self):
        return self.value


class BatchTaskStatus(Enum):
    """批量处理任务状态"""

    WAITING = "等待中"
    RUNNING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

    def __str__(self):
        return self.value
