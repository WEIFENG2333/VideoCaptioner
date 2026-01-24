import difflib
import re
from typing import List, Tuple

from ..llm import call_llm
from ..prompts import get_prompt
from ..utils.logger import setup_logger
from ..utils.text_utils import count_words, is_mainly_cjk

logger = setup_logger("split_by_llm")

MAX_WORD_COUNT = 20  # 英文单词或中文字符的最大数量
MAX_STEPS = 2  # Agent loop最大尝试次数


def split_by_llm(
    text: str,
    model: str = "gpt-4o-mini",
    max_word_count_cjk: int = 18,
    max_word_count_english: int = 12,
) -> List[str]:
    """使用LLM进行文本断句（固定使用句子分段）

    Args:
        text: 待断句的文本
        model: LLM模型名称
        max_word_count_cjk: 中文最大字符数
        max_word_count_english: 英文最大单词数

    Returns:
        断句后的文本列表
    """
    try:
        return _split_with_agent_loop(
            text, model, max_word_count_cjk, max_word_count_english
        )
    except Exception as e:
        logger.error(f"断句失败: {e}")
        return [text]


def _split_with_agent_loop(
    text: str,
    model: str,
    max_word_count_cjk: int,
    max_word_count_english: int,
) -> List[str]:
    """使用agent loop 建立反馈循环进行文本断句，自动验证和修正"""
    prompt_path = "split/sentence"
    system_prompt = get_prompt(
        prompt_path,
        max_word_count_cjk=max_word_count_cjk,
        max_word_count_english=max_word_count_english,
    )

    user_prompt = (
        f"Please use multiple <br> tags to separate the following sentence:\n{text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_result = None

    for step in range(MAX_STEPS):
        response = call_llm(
            messages=messages,
            model=model,
            temperature=0.1,
        )

        result_text = response.choices[0].message.content

        # 解析结果
        result_text_cleaned = re.sub(r"\n+", "", result_text)
        split_result = [
            segment.strip()
            for segment in result_text_cleaned.split("<br>")
            if segment.strip()
        ]
        last_result = split_result

        # 验证结果
        is_valid, error_message = _validate_split_result(
            original_text=text,
            split_result=split_result,
            max_word_count_cjk=max_word_count_cjk,
            max_word_count_english=max_word_count_english,
        )

        if is_valid:
            return split_result

        # 添加反馈到对话
        logger.warning(
            f"模型输出错误，断句验证失败，频繁出现建议更换更智能的模型或者调整最大字数限制。开始反馈循环 (第{step + 1}次尝试):\n {error_message}\n\n"
        )
        messages.append({"role": "assistant", "content": result_text})
        messages.append(
            {
                "role": "user",
                "content": f"Error: {error_message}\nFix the errors above and output the COMPLETE corrected text with <br> tags (include ALL segments, not just the fixed ones), no explanation.",
            }
        )

    return last_result if last_result else [text]


def _validate_split_result(
    original_text: str,
    split_result: List[str],
    max_word_count_cjk: int,
    max_word_count_english: int,
) -> Tuple[bool, str]:
    """验证断句结果：内容一致性、分段数量、长度限制

    返回: (是否有效, 错误反馈)
    """
    # 检查是否为空
    if not split_result:
        return False, "No segments found. Split the text with <br> tags."

    # 检查内容是否被修改（使用difflib精确定位差异）
    original_cleaned = re.sub(r"\s+", " ", original_text)
    text_is_cjk = is_mainly_cjk(original_cleaned)

    merged_char = "" if text_is_cjk else " "
    merged = merged_char.join(split_result)
    merged_cleaned = re.sub(r"\s+", " ", merged)

    # 使用SequenceMatcher计算相似度和差异
    matcher = difflib.SequenceMatcher(None, original_cleaned, merged_cleaned)
    similarity_ratio = matcher.ratio()

    # 允许98%以上的相似度（容忍少量标点或空格差异）
    if similarity_ratio < 0.96:
        differences = []
        context_size = 5 if text_is_cjk else 20

        for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
            if opcode == "replace":
                # 获取前后文
                before = original_cleaned[max(0, a0 - context_size) : a0]
                orig_part = original_cleaned[a0:a1]
                after = original_cleaned[a1 : a1 + context_size]

                new_part = merged_cleaned[b0:b1]

                if orig_part.isspace() or new_part.isspace():
                    continue

                differences.append(
                    f"...{before}[{orig_part}]{after}... → changed to [{new_part}]"
                )

            elif opcode == "delete":
                before = original_cleaned[max(0, a0 - context_size) : a0]
                deleted_part = original_cleaned[a0:a1]
                after = original_cleaned[a1 : a1 + context_size]

                if deleted_part.isspace():
                    continue

                differences.append(f"...{before}[{deleted_part}]{after}... → deleted")

            elif opcode == "insert":
                # 对于插入，显示插入位置的上下文
                before = merged_cleaned[max(0, b0 - context_size) : b0]
                inserted_part = merged_cleaned[b0:b1]
                after = merged_cleaned[b1 : b1 + context_size]

                if inserted_part.isspace():
                    continue

                differences.append(
                    f"Wrongly inserted [{inserted_part}] between '...{before}' and '{after}...'"
                )

        if differences:
            error_msg = f"Content modified (similarity: {similarity_ratio:.1%}):\n"
            error_msg += "\n".join(f"- {diff}" for diff in differences)
            error_msg += (
                "\nKeep original text unchanged, only insert <br> between words."
            )
            return False, error_msg

    # 检查每段长度是否超限
    violations = []
    for i, segment in enumerate(split_result, 1):
        word_count = count_words(segment)

        max_allowed = max_word_count_cjk if text_is_cjk else max_word_count_english
        tolerance = max_allowed * 1  # 0容差

        if word_count > tolerance:
            segment_preview = segment[:40] + "..." if len(segment) > 40 else segment
            violations.append(
                f"Segment {i} '{segment_preview}': {word_count} {'chars' if text_is_cjk else 'words'} > {max_allowed} limit"
            )

    if violations:
        error_msg = "Length violations:\n" + "\n".join(f"- {v}" for v in violations)
        error_msg += "\n\nSplit these long segments further with <br>, then output the COMPLETE text with ALL segments (not just the fixed ones)."
        return False, error_msg

    return True, ""


if __name__ == "__main__":
    sample_text = "大家好我叫杨玉溪来自有着良好音乐氛围的福建厦门自记事起我眼中的世界就是朦胧的童话书是各色杂乱的线条电视机是颜色各异的雪花小伙伴是只听其声不便骑行的马赛克后来我才知道这是一种眼底黄斑疾病虽不至于失明但终身无法治愈"
    sentences = split_by_llm(sample_text)
    print(f"断句结果 ({len(sentences)} 段):")
    for i, seg in enumerate(sentences, 1):
        print(f"  {i}. {seg}")
