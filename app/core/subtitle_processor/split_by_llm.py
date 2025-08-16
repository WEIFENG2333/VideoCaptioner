import hashlib
import json
import re
from typing import List, Optional

import openai
import retry

from app.config import CACHE_PATH

from ..utils.logger import setup_logger
from .prompt import SPLIT_PROMPT_SEMANTIC

logger = setup_logger("split_by_llm")

MAX_WORD_COUNT = 20  # 英文单词或中文字符的最大数量


def count_words(text: str) -> int:
    """
    统计混合文本中英文单词数和中文字符数的总和
    """
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_text = re.sub(r"[\u4e00-\u9fff]", " ", text)
    english_words = len(english_text.strip().split())
    return english_words + chinese_chars


def get_cache_key(text: str, model: str) -> str:
    """
    生成缓存键值
    """
    return hashlib.md5(f"{text}_{model}".encode()).hexdigest()


def get_cache(text: str, model: str) -> Optional[List[str]]:
    """
    从缓存中获取断句结果
    """
    cache_key = get_cache_key(text, model)
    cache_file = CACHE_PATH / f"{cache_key}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return None
    return None


def set_cache(text: str, model: str, result: List[str]) -> None:
    """
    将断句结果设置到缓存中
    """
    cache_key = get_cache_key(text, model)
    cache_file = CACHE_PATH / f"{cache_key}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except IOError:
        pass


def split_by_llm(
    text: str,
    model: str = "gpt-4o-mini",
    use_cache: bool = False,
    max_word_count_cjk: int = 18,
    max_word_count_english: int = 12,
) -> List[str]:
    """
    包装 split_by_llm_retry 函数，确保在重试全部失败后返回空列表
    """
    try:
        return split_by_llm_retry(
            text, model, use_cache, max_word_count_cjk, max_word_count_english
        )
    except Exception as e:
        logger.error(f"断句失败: {e}")
        return [text]


@retry.retry(tries=2)
def split_by_llm_retry(
    text: str,
    model: str = "gpt-4o-mini",
    use_cache: bool = False,
    max_word_count_cjk: int = 18,
    max_word_count_english: int = 12,
) -> List[str]:
    """
    使用LLM进行文本断句
    """
    system_prompt = SPLIT_PROMPT_SEMANTIC.replace(
        "[max_word_count_cjk]", str(max_word_count_cjk)
    )
    system_prompt = system_prompt.replace(
        "[max_word_count_english]", str(max_word_count_english)
    )
    user_prompt = (
        f"Please use multiple <br> tags to separate the following sentence:\n{text}"
    )

    if use_cache:
        cached_result = get_cache(system_prompt + user_prompt, model)
        if cached_result:
            logger.info("从缓存中获取断句结果")
            return cached_result
    logger.info("未命中缓存，开始断句")
    # 初始化OpenAI客户端
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        timeout=80,
    )
    result = response.choices[0].message.content
    if result is None:
        raise Exception("获取断句结果失败")

    # print(f"断句结果: {result}")
    # 清理结果中的多余换行符
    result = re.sub(r"\n+", "", result)
    split_result = [
        segment.strip() for segment in result.split("<br>") if segment.strip()
    ]

    br_count = len(split_result)
    if br_count < count_words(text) / MAX_WORD_COUNT * 0.9:
        raise Exception("断句失败")
    set_cache(system_prompt + user_prompt, model, split_result)
    return split_result


if __name__ == "__main__":
    sample_text = "大家好我叫杨玉溪来自有着良好音乐氛围的福建厦门自记事起我眼中的世界就是朦胧的童话书是各色杂乱的线条电视机是颜色各异的雪花小伙伴是只听其声不便骑行的马赛克后来我才知道这是一种眼底黄斑疾病虽不至于失明但终身无法治愈"
    sentences = split_by_llm(sample_text, use_cache=True)
    print(sentences)
