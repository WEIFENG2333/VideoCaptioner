"""多语言文本处理工具

统一的文本分析工具，支持CJK和世界多语言字符统计。
"""

import re

# Unicode字符范围 (中日韩 + 东南亚/南亚/其他语言)
_ASIAN_PATTERN = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u0900-\u0dff]"
_NON_LATIN_PATTERN = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u0900-\u0dff\u0600-\u06ff\u0400-\u04ff\u0590-\u05ff]"


def is_pure_punctuation(text: str) -> bool:
    """检查文本是否仅包含标点符号"""
    return not re.search(r"\w", text, re.UNICODE)


def is_mainly_cjk(text: str, threshold: float = 0.5) -> bool:
    """判断是否主要为亚洲语言文本

    支持: 中日韩、泰文、缅甸文、高棉文、印地语等
    """
    if not text:
        return False

    asian_count = len(re.findall(_ASIAN_PATTERN, text))
    total_chars = len("".join(text.split()))

    return asian_count / total_chars > threshold if total_chars > 0 else False


def count_words(text: str) -> int:
    """统计文本字符/单词数

    - 非拉丁字符(中日韩/泰文/阿拉伯文等): 按字符计数
    - 拉丁字符(英文等): 按单词计数
    """
    if not text:
        return 0

    # 统计非拉丁字符
    non_latin_count = len(re.findall(_NON_LATIN_PATTERN, text))

    # 移除非拉丁字符后统计拉丁单词
    latin_text = re.sub(_NON_LATIN_PATTERN, " ", text)
    latin_words = len(latin_text.strip().split())

    return non_latin_count + latin_words
