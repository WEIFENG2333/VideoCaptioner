"""多语言文本处理工具

统一的文本分析工具，支持CJK和世界多语言字符统计。
"""

import re

# ==================== Unicode 字符范围定义 ====================

# 按字符计数的语言（不使用空格分词）
# 包括：CJK（中日韩）+ 东南亚/南亚语言（泰文/缅甸文/高棉文/印地语等）
_NO_SPACE_LANGUAGES = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u0900-\u0dff]"

# 需要空格分隔的语言（按单词计数）
# 包括：拉丁字母、西里尔字母、希腊字母、阿拉伯字母、希伯来字母、泰文
_SPACE_SEPARATED_LANGUAGES = (
    r"^[a-zA-Z0-9\'\u0400-\u04ff\u0370-\u03ff\u0600-\u06ff\u0590-\u05ff\u0e00-\u0e7f]+$"
)


def is_pure_punctuation(text: str) -> bool:
    """检查文本是否仅包含标点符号"""
    return not re.search(r"\w", text, re.UNICODE)


def is_mainly_cjk(text: str, threshold: float = 0.5) -> bool:
    """判断是否主要为不使用空格的亚洲语言文本

    包括：中日韩、泰文、缅甸文、高棉文、印地语等

    Args:
        text: 待检测的文本
        threshold: 阈值比例（默认0.5，即超过50%）

    Returns:
        True表示主要为不使用空格的亚洲语言，False表示其他
    """
    if not text:
        return False

    no_space_count = len(re.findall(_NO_SPACE_LANGUAGES, text))
    total_chars = len("".join(text.split()))

    return no_space_count / total_chars > threshold if total_chars > 0 else False


def is_space_separated_language(text: str) -> bool:
    """判断文本是否为需要空格分隔的语言

    需要空格的语言包括：
    - 拉丁字母语言：英语、法语、德语、西班牙语等
    - 西里尔字母语言：俄语、乌克兰语、保加利亚语等
    - 希腊字母语言：希腊语
    - 阿拉伯字母语言：阿拉伯语、波斯语、乌尔都语等
    - 希伯来字母语言：希伯来语

    不需要空格的语言（返回False）：
    - 中文、日文、韩文（CJK）
    - 泰文、缅甸文、高棉文等

    Args:
        text: 待检测的文本

    Returns:
        True表示需要空格分隔，False表示不需要
    """
    if not text:
        return False
    return bool(re.match(_SPACE_SEPARATED_LANGUAGES, text.strip()))


def count_words(text: str) -> int:
    """统计文本字符/单词数

    按字符计数的语言（不使用空格分词）：
    - CJK (中文、日文、韩文)
    - 泰文、缅甸文、高棉文、印地语等

    按单词计数的语言（使用空格分词）：
    - 拉丁字母语言 (英语、法语、德语、西班牙语等)
    - 西里尔字母语言 (俄语、乌克兰语、保加利亚语等)
    - 希腊字母、阿拉伯字母、希伯来字母等

    混合文本处理：
    - 按字符计数的语言统计字符数
    - 按单词计数的语言统计单词数
    - 返回总和

    Args:
        text: 待统计的文本

    Returns:
        字符数 + 单词数
    """
    if not text:
        return 0

    # 统计不使用空格的语言的字符数（CJK + 泰文/缅甸文等）
    char_count = len(re.findall(_NO_SPACE_LANGUAGES, text))

    # 移除不使用空格的字符后，统计使用空格的语言的单词数
    word_text = re.sub(_NO_SPACE_LANGUAGES, " ", text)
    word_count = len(word_text.strip().split())

    return char_count + word_count
