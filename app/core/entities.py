import datetime
from dataclasses import dataclass, field
from enum import Enum
from random import randint
from typing import List, Optional
from PyQt5.QtCore import QCoreApplication


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

    def __str__(self):
        translations = {
            "B 接口": QCoreApplication.translate("TranscribeModelEnum", "B 接口"),
            "J 接口": QCoreApplication.translate("TranscribeModelEnum", "J 接口"),
            "FasterWhisper ✨": QCoreApplication.translate("TranscribeModelEnum", "FasterWhisper ✨"),
            "WhisperCpp": QCoreApplication.translate("TranscribeModelEnum", "WhisperCpp"),
            "Whisper [API]": QCoreApplication.translate("TranscribeModelEnum", "Whisper [API]")
        }
        return translations.get(self.value, self.value)


class TranslatorServiceEnum(Enum):
    """翻译器服务"""

    OPENAI = "LLM 大模型翻译"
    DEEPLX = "DeepLx 翻译"
    BING = "微软翻译"
    GOOGLE = "谷歌翻译"

    def __str__(self):
        translations = {
            "LLM 大模型翻译": QCoreApplication.translate("TranslatorServiceEnum", "LLM 大模型翻译"),
            "DeepLx 翻译": QCoreApplication.translate("TranslatorServiceEnum", "DeepLx 翻译"),
            "微软翻译": QCoreApplication.translate("TranslatorServiceEnum", "微软翻译"),
            "谷歌翻译": QCoreApplication.translate("TranslatorServiceEnum", "谷歌翻译")
        }
        return translations.get(self.value, self.value)


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
    
    def __str__(self):
        translations = {
            "语义分段": QCoreApplication.translate("SplitTypeEnum", "语义分段"),
            "句子分段": QCoreApplication.translate("SplitTypeEnum", "句子分段")
        }
        return translations.get(self.value, self.value)


class TargetLanguageEnum(Enum):
    """翻译目标语言"""

    CHINESE_SIMPLIFIED = "Chinese Simplified"
    CHINESE_TRADITIONAL = "Chinese Traditional"
    ENGLISH = "English"
    JAPANESE = "Japanese"
    KOREAN = "Korean"
    YUE = "Cantonese"
    FRENCH = "French"
    GERMAN = "German"
    SPANISH = "Spanish"
    RUSSIAN = "Russian"
    PORTUGUESE = "Portuguese"
    TURKISH = "Turkish"
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

    def __str__(self):
        translations = {
            "Chinese Simplified": QCoreApplication.translate("TargetLanguageEnum", "Chinese Simplified"),
            "Chinese Traditional": QCoreApplication.translate("TargetLanguageEnum", "Chinese Traditional"),
            "English": QCoreApplication.translate("TargetLanguageEnum", "English"),
            "Japanese": QCoreApplication.translate("TargetLanguageEnum", "Japanese"),
            "Korean": QCoreApplication.translate("TargetLanguageEnum", "Korean"),
            "Cantonese": QCoreApplication.translate("TargetLanguageEnum", "Cantonese"),
            "French": QCoreApplication.translate("TargetLanguageEnum", "French"),
            "German": QCoreApplication.translate("TargetLanguageEnum", "German"),
            "Spanish": QCoreApplication.translate("TargetLanguageEnum", "Spanish"),
            "Russian": QCoreApplication.translate("TargetLanguageEnum", "Russian"),
            "Portuguese": QCoreApplication.translate("TargetLanguageEnum", "Portuguese"),
            "Turkish": QCoreApplication.translate("TargetLanguageEnum", "Turkish"),
            "Polish": QCoreApplication.translate("TargetLanguageEnum", "Polish"),
            "Catalan": QCoreApplication.translate("TargetLanguageEnum", "Catalan"),
            "Dutch": QCoreApplication.translate("TargetLanguageEnum", "Dutch"),
            "Arabic": QCoreApplication.translate("TargetLanguageEnum", "Arabic"),
            "Swedish": QCoreApplication.translate("TargetLanguageEnum", "Swedish"),
            "Italian": QCoreApplication.translate("TargetLanguageEnum", "Italian"),
            "Indonesian": QCoreApplication.translate("TargetLanguageEnum", "Indonesian"),
            "Hindi": QCoreApplication.translate("TargetLanguageEnum", "Hindi"),
            "Finnish": QCoreApplication.translate("TargetLanguageEnum", "Finnish"),
            "Vietnamese": QCoreApplication.translate("TargetLanguageEnum", "Vietnamese"),
            "Hebrew": QCoreApplication.translate("TargetLanguageEnum", "Hebrew"),
            "Ukrainian": QCoreApplication.translate("TargetLanguageEnum", "Ukrainian"),
            "Greek": QCoreApplication.translate("TargetLanguageEnum", "Greek"),
            "Malay": QCoreApplication.translate("TargetLanguageEnum", "Malay"),
            "Czech": QCoreApplication.translate("TargetLanguageEnum", "Czech"),
            "Romanian": QCoreApplication.translate("TargetLanguageEnum", "Romanian"),
            "Danish": QCoreApplication.translate("TargetLanguageEnum", "Danish"),
            "Hungarian": QCoreApplication.translate("TargetLanguageEnum", "Hungarian"),
            "Tamil": QCoreApplication.translate("TargetLanguageEnum", "Tamil"),
            "Norwegian": QCoreApplication.translate("TargetLanguageEnum", "Norwegian"),
            "Thai": QCoreApplication.translate("TargetLanguageEnum", "Thai"),
            "Urdu": QCoreApplication.translate("TargetLanguageEnum", "Urdu"),
            "Croatian": QCoreApplication.translate("TargetLanguageEnum", "Croatian"),
            "Bulgarian": QCoreApplication.translate("TargetLanguageEnum", "Bulgarian"),
            "Lithuanian": QCoreApplication.translate("TargetLanguageEnum", "Lithuanian"),
            "Latin": QCoreApplication.translate("TargetLanguageEnum", "Latin"),
            "Maori": QCoreApplication.translate("TargetLanguageEnum", "Maori"),
            "Malayalam": QCoreApplication.translate("TargetLanguageEnum", "Malayalam"),
            "Welsh": QCoreApplication.translate("TargetLanguageEnum", "Welsh"),
            "Slovak": QCoreApplication.translate("TargetLanguageEnum", "Slovak"),
            "Telugu": QCoreApplication.translate("TargetLanguageEnum", "Telugu"),
            "Persian": QCoreApplication.translate("TargetLanguageEnum", "Persian"),
            "Latvian": QCoreApplication.translate("TargetLanguageEnum", "Latvian"),
            "Bengali": QCoreApplication.translate("TargetLanguageEnum", "Bengali"),
            "Serbian": QCoreApplication.translate("TargetLanguageEnum", "Serbian"),
            "Azerbaijani": QCoreApplication.translate("TargetLanguageEnum", "Azerbaijani"),
            "Slovenian": QCoreApplication.translate("TargetLanguageEnum", "Slovenian"),
            "Kannada": QCoreApplication.translate("TargetLanguageEnum", "Kannada"),
            "Estonian": QCoreApplication.translate("TargetLanguageEnum", "Estonian"),
            "Macedonian": QCoreApplication.translate("TargetLanguageEnum", "Macedonian"),
            "Breton": QCoreApplication.translate("TargetLanguageEnum", "Breton"),
            "Basque": QCoreApplication.translate("TargetLanguageEnum", "Basque"),
            "Icelandic": QCoreApplication.translate("TargetLanguageEnum", "Icelandic"),
            "Armenian": QCoreApplication.translate("TargetLanguageEnum", "Armenian"),
            "Nepali": QCoreApplication.translate("TargetLanguageEnum", "Nepali"),
            "Mongolian": QCoreApplication.translate("TargetLanguageEnum", "Mongolian"),
            "Bosnian": QCoreApplication.translate("TargetLanguageEnum", "Bosnian"),
            "Kazakh": QCoreApplication.translate("TargetLanguageEnum", "Kazakh"),
            "Albanian": QCoreApplication.translate("TargetLanguageEnum", "Albanian"),
            "Swahili": QCoreApplication.translate("TargetLanguageEnum", "Swahili"),
            "Galician": QCoreApplication.translate("TargetLanguageEnum", "Galician"),
            "Marathi": QCoreApplication.translate("TargetLanguageEnum", "Marathi"),
            "Punjabi": QCoreApplication.translate("TargetLanguageEnum", "Punjabi"),
            "Sinhala": QCoreApplication.translate("TargetLanguageEnum", "Sinhala"),
            "Khmer": QCoreApplication.translate("TargetLanguageEnum", "Khmer"),
            "Shona": QCoreApplication.translate("TargetLanguageEnum", "Shona"),
            "Yoruba": QCoreApplication.translate("TargetLanguageEnum", "Yoruba"),
            "Somali": QCoreApplication.translate("TargetLanguageEnum", "Somali"),
            "Afrikaans": QCoreApplication.translate("TargetLanguageEnum", "Afrikaans"),
            "Occitan": QCoreApplication.translate("TargetLanguageEnum", "Occitan"),
            "Georgian": QCoreApplication.translate("TargetLanguageEnum", "Georgian"),
            "Belarusian": QCoreApplication.translate("TargetLanguageEnum", "Belarusian"),
            "Tajik": QCoreApplication.translate("TargetLanguageEnum", "Tajik"),
            "Sindhi": QCoreApplication.translate("TargetLanguageEnum", "Sindhi"),
            "Gujarati": QCoreApplication.translate("TargetLanguageEnum", "Gujarati"),
            "Amharic": QCoreApplication.translate("TargetLanguageEnum", "Amharic"),
            "Yiddish": QCoreApplication.translate("TargetLanguageEnum", "Yiddish"),
            "Lao": QCoreApplication.translate("TargetLanguageEnum", "Lao"),
            "Uzbek": QCoreApplication.translate("TargetLanguageEnum", "Uzbek"),
            "Faroese": QCoreApplication.translate("TargetLanguageEnum", "Faroese"),
            "Haitian Creole": QCoreApplication.translate("TargetLanguageEnum", "Haitian Creole"),
            "Pashto": QCoreApplication.translate("TargetLanguageEnum", "Pashto"),
            "Turkmen": QCoreApplication.translate("TargetLanguageEnum", "Turkmen"),
            "Nynorsk": QCoreApplication.translate("TargetLanguageEnum", "Nynorsk"),
            "Maltese": QCoreApplication.translate("TargetLanguageEnum", "Maltese"),
            "Sanskrit": QCoreApplication.translate("TargetLanguageEnum", "Sanskrit"),
            "Luxembourgish": QCoreApplication.translate("TargetLanguageEnum", "Luxembourgish"),
            "Myanmar": QCoreApplication.translate("TargetLanguageEnum", "Myanmar"),
            "Tibetan": QCoreApplication.translate("TargetLanguageEnum", "Tibetan"),
            "Tagalog": QCoreApplication.translate("TargetLanguageEnum", "Tagalog"),
            "Malagasy": QCoreApplication.translate("TargetLanguageEnum", "Malagasy"),
            "Assamese": QCoreApplication.translate("TargetLanguageEnum", "Assamese"),
            "Tatar": QCoreApplication.translate("TargetLanguageEnum", "Tatar"),
            "Hawaiian": QCoreApplication.translate("TargetLanguageEnum", "Hawaiian"),
            "Lingala": QCoreApplication.translate("TargetLanguageEnum", "Lingala"),
            "Hausa": QCoreApplication.translate("TargetLanguageEnum", "Hausa"),
            "Bashkir": QCoreApplication.translate("TargetLanguageEnum", "Bashkir"),
            "Javanese": QCoreApplication.translate("TargetLanguageEnum", "Javanese"),
            "Sundanese": QCoreApplication.translate("TargetLanguageEnum", "Sundanese"),
        }
        return translations.get(self.value, self.value)


class TranscribeLanguageEnum(Enum):
    """转录语言"""

    ENGLISH = "English"
    CHINESE = "Chinese"
    JAPANESE = "Japanese"
    KOREAN = "Korean"
    CANTONESE = "Cantonese"
    FRENCH = "French"
    GERMAN = "German"
    SPANISH = "Spanish"
    RUSSIAN = "Russian"
    PORTUGUESE = "Portuguese"
    TURKISH = "Turkish"
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

    def __str__(self):
        translations = {
            "English": QCoreApplication.translate("TranscribeLanguageEnum", "English"),
            "Chinese": QCoreApplication.translate("TranscribeLanguageEnum", "Chinese"),
            "Japanese": QCoreApplication.translate("TranscribeLanguageEnum", "Japanese"),
            "Korean": QCoreApplication.translate("TranscribeLanguageEnum", "Korean"),
            "Cantonese": QCoreApplication.translate("TranscribeLanguageEnum", "Cantonese"),
            "French": QCoreApplication.translate("TranscribeLanguageEnum", "French"),
            "German": QCoreApplication.translate("TranscribeLanguageEnum", "German"),
            "Spanish": QCoreApplication.translate("TranscribeLanguageEnum", "Spanish"),
            "Russian": QCoreApplication.translate("TranscribeLanguageEnum", "Russian"),
            "Portuguese": QCoreApplication.translate("TranscribeLanguageEnum", "Portuguese"),
            "Turkish": QCoreApplication.translate("TranscribeLanguageEnum", "Turkish"),
            "Polish": QCoreApplication.translate("TranscribeLanguageEnum", "Polish"),
            "Catalan": QCoreApplication.translate("TranscribeLanguageEnum", "Catalan"),
            "Dutch": QCoreApplication.translate("TranscribeLanguageEnum", "Dutch"),
            "Arabic": QCoreApplication.translate("TranscribeLanguageEnum", "Arabic"),
            "Swedish": QCoreApplication.translate("TranscribeLanguageEnum", "Swedish"),
            "Italian": QCoreApplication.translate("TranscribeLanguageEnum", "Italian"),
            "Indonesian": QCoreApplication.translate("TranscribeLanguageEnum", "Indonesian"),
            "Hindi": QCoreApplication.translate("TranscribeLanguageEnum", "Hindi"),
            "Finnish": QCoreApplication.translate("TranscribeLanguageEnum", "Finnish"),
            "Vietnamese": QCoreApplication.translate("TranscribeLanguageEnum", "Vietnamese"),
            "Hebrew": QCoreApplication.translate("TranscribeLanguageEnum", "Hebrew"),
            "Ukrainian": QCoreApplication.translate("TranscribeLanguageEnum", "Ukrainian"),
            "Greek": QCoreApplication.translate("TranscribeLanguageEnum", "Greek"),
            "Malay": QCoreApplication.translate("TranscribeLanguageEnum", "Malay"),
            "Czech": QCoreApplication.translate("TranscribeLanguageEnum", "Czech"),
            "Romanian": QCoreApplication.translate("TranscribeLanguageEnum", "Romanian"),
            "Danish": QCoreApplication.translate("TranscribeLanguageEnum", "Danish"),
            "Hungarian": QCoreApplication.translate("TranscribeLanguageEnum", "Hungarian"),
            "Tamil": QCoreApplication.translate("TranscribeLanguageEnum", "Tamil"),
            "Norwegian": QCoreApplication.translate("TranscribeLanguageEnum", "Norwegian"),
            "Thai": QCoreApplication.translate("TranscribeLanguageEnum", "Thai"),
            "Urdu": QCoreApplication.translate("TranscribeLanguageEnum", "Urdu"),
            "Croatian": QCoreApplication.translate("TranscribeLanguageEnum", "Croatian"),
            "Bulgarian": QCoreApplication.translate("TranscribeLanguageEnum", "Bulgarian"),
            "Lithuanian": QCoreApplication.translate("TranscribeLanguageEnum", "Lithuanian"),
            "Latin": QCoreApplication.translate("TranscribeLanguageEnum", "Latin"),
            "Maori": QCoreApplication.translate("TranscribeLanguageEnum", "Maori"),
            "Malayalam": QCoreApplication.translate("TranscribeLanguageEnum", "Malayalam"),
            "Welsh": QCoreApplication.translate("TranscribeLanguageEnum", "Welsh"),
            "Slovak": QCoreApplication.translate("TranscribeLanguageEnum", "Slovak"),
            "Telugu": QCoreApplication.translate("TranscribeLanguageEnum", "Telugu"),
            "Persian": QCoreApplication.translate("TranscribeLanguageEnum", "Persian"),
            "Latvian": QCoreApplication.translate("TranscribeLanguageEnum", "Latvian"),
            "Bengali": QCoreApplication.translate("TranscribeLanguageEnum", "Bengali"),
            "Serbian": QCoreApplication.translate("TranscribeLanguageEnum", "Serbian"),
            "Azerbaijani": QCoreApplication.translate("TranscribeLanguageEnum", "Azerbaijani"),
            "Slovenian": QCoreApplication.translate("TranscribeLanguageEnum", "Slovenian"),
            "Kannada": QCoreApplication.translate("TranscribeLanguageEnum", "Kannada"),
            "Estonian": QCoreApplication.translate("TranscribeLanguageEnum", "Estonian"),
            "Macedonian": QCoreApplication.translate("TranscribeLanguageEnum", "Macedonian"),
            "Breton": QCoreApplication.translate("TranscribeLanguageEnum", "Breton"),
            "Basque": QCoreApplication.translate("TranscribeLanguageEnum", "Basque"),
            "Icelandic": QCoreApplication.translate("TranscribeLanguageEnum", "Icelandic"),
            "Armenian": QCoreApplication.translate("TranscribeLanguageEnum", "Armenian"),
            "Nepali": QCoreApplication.translate("TranscribeLanguageEnum", "Nepali"),
            "Mongolian": QCoreApplication.translate("TranscribeLanguageEnum", "Mongolian"),
            "Bosnian": QCoreApplication.translate("TranscribeLanguageEnum", "Bosnian"),
            "Kazakh": QCoreApplication.translate("TranscribeLanguageEnum", "Kazakh"),
            "Albanian": QCoreApplication.translate("TranscribeLanguageEnum", "Albanian"),
            "Swahili": QCoreApplication.translate("TranscribeLanguageEnum", "Swahili"),
            "Galician": QCoreApplication.translate("TranscribeLanguageEnum", "Galician"),
            "Marathi": QCoreApplication.translate("TranscribeLanguageEnum", "Marathi"),
            "Punjabi": QCoreApplication.translate("TranscribeLanguageEnum", "Punjabi"),
            "Sinhala": QCoreApplication.translate("TranscribeLanguageEnum", "Sinhala"),
            "Khmer": QCoreApplication.translate("TranscribeLanguageEnum", "Khmer"),
            "Shona": QCoreApplication.translate("TranscribeLanguageEnum", "Shona"),
            "Yoruba": QCoreApplication.translate("TranscribeLanguageEnum", "Yoruba"),
            "Somali": QCoreApplication.translate("TranscribeLanguageEnum", "Somali"),
            "Afrikaans": QCoreApplication.translate("TranscribeLanguageEnum", "Afrikaans"),
            "Occitan": QCoreApplication.translate("TranscribeLanguageEnum", "Occitan"),
            "Georgian": QCoreApplication.translate("TranscribeLanguageEnum", "Georgian"),
            "Belarusian": QCoreApplication.translate("TranscribeLanguageEnum", "Belarusian"),
            "Tajik": QCoreApplication.translate("TranscribeLanguageEnum", "Tajik"),
            "Sindhi": QCoreApplication.translate("TranscribeLanguageEnum", "Sindhi"),
            "Gujarati": QCoreApplication.translate("TranscribeLanguageEnum", "Gujarati"),
            "Amharic": QCoreApplication.translate("TranscribeLanguageEnum", "Amharic"),
            "Yiddish": QCoreApplication.translate("TranscribeLanguageEnum", "Yiddish"),
            "Lao": QCoreApplication.translate("TranscribeLanguageEnum", "Lao"),
            "Uzbek": QCoreApplication.translate("TranscribeLanguageEnum", "Uzbek"),
            "Faroese": QCoreApplication.translate("TranscribeLanguageEnum", "Faroese"),
            "Haitian Creole": QCoreApplication.translate("TranscribeLanguageEnum", "Haitian Creole"),
            "Pashto": QCoreApplication.translate("TranscribeLanguageEnum", "Pashto"),
            "Turkmen": QCoreApplication.translate("TranscribeLanguageEnum", "Turkmen"),
            "Nynorsk": QCoreApplication.translate("TranscribeLanguageEnum", "Nynorsk"),
            "Maltese": QCoreApplication.translate("TranscribeLanguageEnum", "Maltese"),
            "Sanskrit": QCoreApplication.translate("TranscribeLanguageEnum", "Sanskrit"),
            "Luxembourgish": QCoreApplication.translate("TranscribeLanguageEnum", "Luxembourgish"),
            "Myanmar": QCoreApplication.translate("TranscribeLanguageEnum", "Myanmar"),
            "Tibetan": QCoreApplication.translate("TranscribeLanguageEnum", "Tibetan"),
            "Tagalog": QCoreApplication.translate("TranscribeLanguageEnum", "Tagalog"),
            "Malagasy": QCoreApplication.translate("TranscribeLanguageEnum", "Malagasy"),
            "Assamese": QCoreApplication.translate("TranscribeLanguageEnum", "Assamese"),
            "Tatar": QCoreApplication.translate("TranscribeLanguageEnum", "Tatar"),
            "Hawaiian": QCoreApplication.translate("TranscribeLanguageEnum", "Hawaiian"),
            "Lingala": QCoreApplication.translate("TranscribeLanguageEnum", "Lingala"),
            "Hausa": QCoreApplication.translate("TranscribeLanguageEnum", "Hausa"),
            "Bashkir": QCoreApplication.translate("TranscribeLanguageEnum", "Bashkir"),
            "Javanese": QCoreApplication.translate("TranscribeLanguageEnum", "Javanese"),
            "Sundanese": QCoreApplication.translate("TranscribeLanguageEnum", "Sundanese"),
        }
        return translations.get(self.value, self.value)


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
    "English": "en",
    "Chinese": "zh",
    "Japanese": "ja",
    "German": "de",
    "Cantonese": "yue",
    "Spanish": "es",
    "Russian": "ru",
    "Korean": "ko",
    "French": "fr",
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
}


class SubtitleLayoutEnum(Enum):
    """字幕布局"""

    TRANSLATE_ON_TOP = "译文在上"
    ORIGINAL_ON_TOP = "原文在上"
    ONLY_ORIGINAL = "仅原文"
    ONLY_TRANSLATE = "仅译文"
    
    def __str__(self):
        translations = {
            "译文在上": QCoreApplication.translate("SubtitleLayoutEnum", "译文在上"),
            "原文在上": QCoreApplication.translate("SubtitleLayoutEnum", "原文在上"),
            "仅原文": QCoreApplication.translate("SubtitleLayoutEnum", "仅原文"),
            "仅译文": QCoreApplication.translate("SubtitleLayoutEnum", "仅译文")
        }
        return translations.get(self.value, self.value)


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
    subtitle_layout: Optional[SubtitleLayoutEnum] = None
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
        translations = {
            "批量转录": QCoreApplication.translate("BatchTaskType", "批量转录"),
            "批量字幕": QCoreApplication.translate("BatchTaskType", "批量字幕"),
            "转录+字幕": QCoreApplication.translate("BatchTaskType", "转录+字幕"),
            "全流程处理": QCoreApplication.translate("BatchTaskType", "全流程处理")
        }
        return translations.get(self.value, self.value)


class BatchTaskStatus(Enum):
    """批量处理任务状态"""

    WAITING = "等待中"
    RUNNING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

    def __str__(self):
        translations = {
            "等待中": QCoreApplication.translate("BatchTaskStatus", "等待中"),
            "处理中": QCoreApplication.translate("BatchTaskStatus", "处理中"),
            "已完成": QCoreApplication.translate("BatchTaskStatus", "已完成"),
            "失败": QCoreApplication.translate("BatchTaskStatus", "失败")
        }
        return translations.get(self.value, self.value)


class FilenamePrefixEnum(Enum):
    """文件名前缀"""

    ORIGINAL_SUBTITLE = "【原始字幕】"
    DOWNLOADED_SUBTITLE = "【下载字幕】"
    SEGMENTED_SUBTITLE = "【断句字幕】"
    SMART_SEGMENTATION = "【智能断句】"
    STYLED_SUBTITLE = "【样式字幕】"
    SUBTITLE = "【字幕】"
    KAKA_VIDEO = "【卡卡】"

    def __str__(self):
        translations = {
            "【原始字幕】": QCoreApplication.translate("FilenamePrefixEnum", "【原始字幕】"),
            "【下载字幕】": QCoreApplication.translate("FilenamePrefixEnum", "【下载字幕】"),
            "【断句字幕】": QCoreApplication.translate("FilenamePrefixEnum", "【断句字幕】"),
            "【智能断句】": QCoreApplication.translate("FilenamePrefixEnum", "【智能断句】"),
            "【样式字幕】": QCoreApplication.translate("FilenamePrefixEnum", "【样式字幕】"),
            "【字幕】": QCoreApplication.translate("FilenamePrefixEnum", "【字幕】"),
            "【卡卡】": QCoreApplication.translate("FilenamePrefixEnum", "【卡卡】")
        }
        return translations.get(self.value, self.value)

