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
    TargetLanguage.SIMPLIFIED_CHINESE.value: "zh-CN",
    TargetLanguage.TRADITIONAL_CHINESE.value: "zh-TW",
    # 英语
    TargetLanguage.ENGLISH.value: "en",
    TargetLanguage.ENGLISH_US.value: "en",
    TargetLanguage.ENGLISH_UK.value: "en",
    # 亚洲语言
    TargetLanguage.JAPANESE.value: "ja",
    TargetLanguage.KOREAN.value: "ko",
    TargetLanguage.CANTONESE.value: "yue",
    TargetLanguage.THAI.value: "th",
    TargetLanguage.VIETNAMESE.value: "vi",
    TargetLanguage.INDONESIAN.value: "id",
    TargetLanguage.MALAY.value: "ms",
    TargetLanguage.TAGALOG.value: "tl",
    # 欧洲语言
    TargetLanguage.FRENCH.value: "fr",
    TargetLanguage.GERMAN.value: "de",
    TargetLanguage.SPANISH.value: "es",
    TargetLanguage.SPANISH_LATAM.value: "es",
    TargetLanguage.RUSSIAN.value: "ru",
    TargetLanguage.PORTUGUESE.value: "pt",
    TargetLanguage.PORTUGUESE_BR.value: "pt",
    TargetLanguage.PORTUGUESE_PT.value: "pt",
    TargetLanguage.ITALIAN.value: "it",
    TargetLanguage.DUTCH.value: "nl",
    TargetLanguage.POLISH.value: "pl",
    TargetLanguage.TURKISH.value: "tr",
    TargetLanguage.GREEK.value: "el",
    TargetLanguage.CZECH.value: "cs",
    TargetLanguage.SWEDISH.value: "sv",
    TargetLanguage.DANISH.value: "da",
    TargetLanguage.FINNISH.value: "fi",
    TargetLanguage.NORWEGIAN.value: "no",
    TargetLanguage.HUNGARIAN.value: "hu",
    TargetLanguage.ROMANIAN.value: "ro",
    TargetLanguage.BULGARIAN.value: "bg",
    TargetLanguage.UKRAINIAN.value: "uk",
    # 中东语言
    TargetLanguage.ARABIC.value: "ar",
    TargetLanguage.HEBREW.value: "he",
    TargetLanguage.PERSIAN.value: "fa",
}

# Bing Translator 语言代码映射
BING_LANG_MAP = {
    # 中文
    TargetLanguage.SIMPLIFIED_CHINESE.value: "zh-Hans",
    TargetLanguage.TRADITIONAL_CHINESE.value: "zh-Hant",
    # 英语
    TargetLanguage.ENGLISH.value: "en",
    TargetLanguage.ENGLISH_US.value: "en",
    TargetLanguage.ENGLISH_UK.value: "en",
    # 亚洲语言
    TargetLanguage.JAPANESE.value: "ja",
    TargetLanguage.KOREAN.value: "ko",
    TargetLanguage.CANTONESE.value: "yue",
    TargetLanguage.THAI.value: "th",
    TargetLanguage.VIETNAMESE.value: "vi",
    TargetLanguage.INDONESIAN.value: "id",
    TargetLanguage.MALAY.value: "ms",
    TargetLanguage.TAGALOG.value: "fil",
    # 欧洲语言
    TargetLanguage.FRENCH.value: "fr",
    TargetLanguage.GERMAN.value: "de",
    TargetLanguage.SPANISH.value: "es",
    TargetLanguage.SPANISH_LATAM.value: "es",
    TargetLanguage.RUSSIAN.value: "ru",
    TargetLanguage.PORTUGUESE.value: "pt",
    TargetLanguage.PORTUGUESE_BR.value: "pt",
    TargetLanguage.PORTUGUESE_PT.value: "pt-PT",
    TargetLanguage.ITALIAN.value: "it",
    TargetLanguage.DUTCH.value: "nl",
    TargetLanguage.POLISH.value: "pl",
    TargetLanguage.TURKISH.value: "tr",
    TargetLanguage.GREEK.value: "el",
    TargetLanguage.CZECH.value: "cs",
    TargetLanguage.SWEDISH.value: "sv",
    TargetLanguage.DANISH.value: "da",
    TargetLanguage.FINNISH.value: "fi",
    TargetLanguage.NORWEGIAN.value: "nb",
    TargetLanguage.HUNGARIAN.value: "hu",
    TargetLanguage.ROMANIAN.value: "ro",
    TargetLanguage.BULGARIAN.value: "bg",
    TargetLanguage.UKRAINIAN.value: "uk",
    # 中东语言
    TargetLanguage.ARABIC.value: "ar",
    TargetLanguage.HEBREW.value: "he",
    TargetLanguage.PERSIAN.value: "fa",
}

# DeepL 语言代码映射
DEEPL_LANG_MAP = {
    # 中文
    TargetLanguage.SIMPLIFIED_CHINESE.value: "zh-Hans",
    TargetLanguage.TRADITIONAL_CHINESE.value: "zh-Hant",
    # 英语
    TargetLanguage.ENGLISH.value: "en",
    TargetLanguage.ENGLISH_US.value: "en-US",
    TargetLanguage.ENGLISH_UK.value: "en-GB",
    # 亚洲语言
    TargetLanguage.JAPANESE.value: "ja",
    TargetLanguage.KOREAN.value: "ko",
    TargetLanguage.INDONESIAN.value: "id",
    # 欧洲语言
    TargetLanguage.FRENCH.value: "fr",
    TargetLanguage.GERMAN.value: "de",
    TargetLanguage.SPANISH.value: "es",
    TargetLanguage.RUSSIAN.value: "ru",
    TargetLanguage.PORTUGUESE.value: "pt",
    TargetLanguage.PORTUGUESE_BR.value: "pt-BR",
    TargetLanguage.PORTUGUESE_PT.value: "pt-PT",
    TargetLanguage.ITALIAN.value: "it",
    TargetLanguage.DUTCH.value: "nl",
    TargetLanguage.POLISH.value: "pl",
    TargetLanguage.TURKISH.value: "tr",
    TargetLanguage.GREEK.value: "el",
    TargetLanguage.CZECH.value: "cs",
    TargetLanguage.SWEDISH.value: "sv",
    TargetLanguage.DANISH.value: "da",
    TargetLanguage.FINNISH.value: "fi",
    TargetLanguage.NORWEGIAN.value: "nb",
    TargetLanguage.HUNGARIAN.value: "hu",
    TargetLanguage.ROMANIAN.value: "ro",
    TargetLanguage.BULGARIAN.value: "bg",
    TargetLanguage.UKRAINIAN.value: "uk",
    # 中东语言
    TargetLanguage.ARABIC.value: "ar",
}


def get_language_code(target_language: str, translator_type: str) -> str:
    """
    获取翻译服务对应的语言代码

    Args:
        target_language: 目标语言（中文名称）
        translator_type: 翻译器类型（google/bing/deeplx）

    Returns:
        语言代码字符串
    """
    lang_map = {
        "google": GOOGLE_LANG_MAP,
        "bing": BING_LANG_MAP,
        "deeplx": DEEPL_LANG_MAP,
    }

    # 如果传入的已经是语言代码（例如 "zh-CN"），直接返回
    if target_language in lang_map.get(translator_type, {}).values():
        return target_language

    # 获取对应的语言映射
    mapping = lang_map.get(translator_type, {})

    # 尝试直接获取
    if target_language in mapping:
        return mapping[target_language]

    # 默认返回简体中文
    return mapping.get(TargetLanguage.SIMPLIFIED_CHINESE.value, "zh-CN")
