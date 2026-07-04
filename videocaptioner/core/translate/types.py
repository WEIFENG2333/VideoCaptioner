"""翻译器类型枚举"""

from enum import Enum


class TranslatorType(Enum):
    """翻译器类型"""

    OPENAI = "openai"
    GOOGLE = "google"
    BING = "bing"
    DEEPLX = "deeplx"


class TargetLanguage(Enum):
    """目标语言枚举"""

    # 中文
    SIMPLIFIED_CHINESE = "简体中文"
    TRADITIONAL_CHINESE = "繁体中文"

    # 英语
    ENGLISH = "英语"
    ENGLISH_US = "英语(美国)"
    ENGLISH_UK = "英语(英国)"

    # 亚洲语言
    JAPANESE = "日本語"
    KOREAN = "韩语"
    CANTONESE = "粤语"
    THAI = "泰语"
    VIETNAMESE = "越南语"
    INDONESIAN = "印尼语"
    MALAY = "马来语"
    TAGALOG = "菲律宾语"

    # 欧洲语言
    FRENCH = "法语"
    GERMAN = "德语"
    SPANISH = "西班牙语"
    SPANISH_LATAM = "西班牙语(拉丁美洲)"
    RUSSIAN = "俄语"
    PORTUGUESE = "葡萄牙语"
    PORTUGUESE_BR = "葡萄牙语(巴西)"
    PORTUGUESE_PT = "葡萄牙语(葡萄牙)"
    ITALIAN = "意大利语"
    DUTCH = "荷兰语"
    POLISH = "波兰语"
    TURKISH = "土耳其语"
    GREEK = "希腊语"
    CZECH = "捷克语"
    SWEDISH = "瑞典语"
    DANISH = "丹麦语"
    FINNISH = "芬兰语"
    NORWEGIAN = "挪威语"
    HUNGARIAN = "匈牙利语"
    ROMANIAN = "罗马尼亚语"
    BULGARIAN = "保加利亚语"
    UKRAINIAN = "乌克兰语"

    # 中东语言
    ARABIC = "阿拉伯语"
    HEBREW = "希伯来语"
    PERSIAN = "波斯语"


# Google Translate 语言代码映射
GOOGLE_LANG_MAP = {
    # 中文
    TargetLanguage.SIMPLIFIED_CHINESE: "zh-CN",
    TargetLanguage.TRADITIONAL_CHINESE: "zh-TW",
    # 英语
    TargetLanguage.ENGLISH: "en",
    TargetLanguage.ENGLISH_US: "en",
    TargetLanguage.ENGLISH_UK: "en",
    # 亚洲语言
    TargetLanguage.JAPANESE: "ja",
    TargetLanguage.KOREAN: "ko",
    TargetLanguage.CANTONESE: "yue",
    TargetLanguage.THAI: "th",
    TargetLanguage.VIETNAMESE: "vi",
    TargetLanguage.INDONESIAN: "id",
    TargetLanguage.MALAY: "ms",
    TargetLanguage.TAGALOG: "tl",
    # 欧洲语言
    TargetLanguage.FRENCH: "fr",
    TargetLanguage.GERMAN: "de",
    TargetLanguage.SPANISH: "es",
    TargetLanguage.SPANISH_LATAM: "es",
    TargetLanguage.RUSSIAN: "ru",
    TargetLanguage.PORTUGUESE: "pt",
    TargetLanguage.PORTUGUESE_BR: "pt",
    TargetLanguage.PORTUGUESE_PT: "pt",
    TargetLanguage.ITALIAN: "it",
    TargetLanguage.DUTCH: "nl",
    TargetLanguage.POLISH: "pl",
    TargetLanguage.TURKISH: "tr",
    TargetLanguage.GREEK: "el",
    TargetLanguage.CZECH: "cs",
    TargetLanguage.SWEDISH: "sv",
    TargetLanguage.DANISH: "da",
    TargetLanguage.FINNISH: "fi",
    TargetLanguage.NORWEGIAN: "no",
    TargetLanguage.HUNGARIAN: "hu",
    TargetLanguage.ROMANIAN: "ro",
    TargetLanguage.BULGARIAN: "bg",
    TargetLanguage.UKRAINIAN: "uk",
    # 中东语言
    TargetLanguage.ARABIC: "ar",
    TargetLanguage.HEBREW: "he",
    TargetLanguage.PERSIAN: "fa",
}

# Bing Translator 语言代码映射
BING_LANG_MAP = {
    # 中文
    TargetLanguage.SIMPLIFIED_CHINESE: "zh-Hans",
    TargetLanguage.TRADITIONAL_CHINESE: "zh-Hant",
    # 英语
    TargetLanguage.ENGLISH: "en",
    TargetLanguage.ENGLISH_US: "en",
    TargetLanguage.ENGLISH_UK: "en",
    # 亚洲语言
    TargetLanguage.JAPANESE: "ja",
    TargetLanguage.KOREAN: "ko",
    TargetLanguage.CANTONESE: "yue",
    TargetLanguage.THAI: "th",
    TargetLanguage.VIETNAMESE: "vi",
    TargetLanguage.INDONESIAN: "id",
    TargetLanguage.MALAY: "ms",
    TargetLanguage.TAGALOG: "fil",
    # 欧洲语言
    TargetLanguage.FRENCH: "fr",
    TargetLanguage.GERMAN: "de",
    TargetLanguage.SPANISH: "es",
    TargetLanguage.SPANISH_LATAM: "es",
    TargetLanguage.RUSSIAN: "ru",
    TargetLanguage.PORTUGUESE: "pt",
    TargetLanguage.PORTUGUESE_BR: "pt",
    TargetLanguage.PORTUGUESE_PT: "pt-PT",
    TargetLanguage.ITALIAN: "it",
    TargetLanguage.DUTCH: "nl",
    TargetLanguage.POLISH: "pl",
    TargetLanguage.TURKISH: "tr",
    TargetLanguage.GREEK: "el",
    TargetLanguage.CZECH: "cs",
    TargetLanguage.SWEDISH: "sv",
    TargetLanguage.DANISH: "da",
    TargetLanguage.FINNISH: "fi",
    TargetLanguage.NORWEGIAN: "nb",
    TargetLanguage.HUNGARIAN: "hu",
    TargetLanguage.ROMANIAN: "ro",
    TargetLanguage.BULGARIAN: "bg",
    TargetLanguage.UKRAINIAN: "uk",
    # 中东语言
    TargetLanguage.ARABIC: "ar",
    TargetLanguage.HEBREW: "he",
    TargetLanguage.PERSIAN: "fa",
}

# DeepL 语言代码映射
DEEPL_LANG_MAP = {
    # 中文
    TargetLanguage.SIMPLIFIED_CHINESE: "zh-Hans",
    TargetLanguage.TRADITIONAL_CHINESE: "zh-Hant",
    # 英语
    TargetLanguage.ENGLISH: "en",
    TargetLanguage.ENGLISH_US: "en-US",
    TargetLanguage.ENGLISH_UK: "en-GB",
    # 亚洲语言
    TargetLanguage.JAPANESE: "ja",
    TargetLanguage.KOREAN: "ko",
    TargetLanguage.INDONESIAN: "id",
    # 欧洲语言
    TargetLanguage.FRENCH: "fr",
    TargetLanguage.GERMAN: "de",
    TargetLanguage.SPANISH: "es",
    TargetLanguage.RUSSIAN: "ru",
    TargetLanguage.PORTUGUESE: "pt",
    TargetLanguage.PORTUGUESE_BR: "pt-BR",
    TargetLanguage.PORTUGUESE_PT: "pt-PT",
    TargetLanguage.ITALIAN: "it",
    TargetLanguage.DUTCH: "nl",
    TargetLanguage.POLISH: "pl",
    TargetLanguage.TURKISH: "tr",
    TargetLanguage.GREEK: "el",
    TargetLanguage.CZECH: "cs",
    TargetLanguage.SWEDISH: "sv",
    TargetLanguage.DANISH: "da",
    TargetLanguage.FINNISH: "fi",
    TargetLanguage.NORWEGIAN: "nb",
    TargetLanguage.HUNGARIAN: "hu",
    TargetLanguage.ROMANIAN: "ro",
    TargetLanguage.BULGARIAN: "bg",
    TargetLanguage.UKRAINIAN: "uk",
    # 中东语言
    TargetLanguage.ARABIC: "ar",
}


def get_language_code(target_language: TargetLanguage, translator_type: str) -> str:
    """
    获取翻译服务对应的语言代码

    Args:
        target_language: 目标语言枚举
        translator_type: 翻译器类型（google/bing/deeplx）

    Returns:
        语言代码字符串
    """
    lang_map = {
        "google": GOOGLE_LANG_MAP,
        "bing": BING_LANG_MAP,
        "deeplx": DEEPL_LANG_MAP,
    }

    # 获取对应的语言映射
    mapping = lang_map.get(translator_type, {})

    # 使用枚举的 value（中文名称）查找语言代码
    if target_language in mapping:
        return mapping[target_language]

    # 默认返回简体中文
    return mapping.get(TargetLanguage.SIMPLIFIED_CHINESE, "zh-CN")
