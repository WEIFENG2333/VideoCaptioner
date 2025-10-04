"""提示词管理模块

所有提示词以 Markdown 文件形式存储，支持模板变量替换。

使用示例:
    from app.core.prompts import get_prompt

    # 加载提示词
    prompt = get_prompt("split/semantic")

    # 带参数替换
    prompt = get_prompt("split/semantic", max_word_count_cjk=18)
    prompt = get_prompt("translate/reflect", target_language="简体中文")
"""

import functools
from pathlib import Path
from string import Template
from typing import Dict

PROMPTS_DIR = Path(__file__).parent


@functools.lru_cache(maxsize=32)
def _load_prompt_file(prompt_path: str) -> str:
    """从文件加载提示词（带LRU缓存）

    Args:
        prompt_path: 提示词相对路径，如 "split/semantic"

    Returns:
        提示词原始文本

    Raises:
        FileNotFoundError: 提示词文件不存在
    """
    file_path = PROMPTS_DIR / f"{prompt_path}.md"

    if not file_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}.md\n"
            f"Expected location: {file_path}"
        )

    return file_path.read_text(encoding="utf-8")


def get_prompt(prompt_path: str, **kwargs) -> str:
    """获取提示词并进行变量替换

    Args:
        prompt_path: 提示词路径，如 "split/semantic", "optimize/subtitle"
        **kwargs: 模板变量，用于替换提示词中的 $variable 或 ${variable}

    Returns:
        处理后的提示词文本

    Examples:
        >>> get_prompt("split/semantic")
        >>> get_prompt("split/semantic", max_word_count_cjk=18, max_word_count_english=12)
        >>> get_prompt("translate/reflect", target_language="简体中文", custom_prompt="保持术语")
    """
    # 加载原始提示词
    raw_prompt = _load_prompt_file(prompt_path)

    # 如果没有参数，直接返回
    if not kwargs:
        return raw_prompt

    # 使用 Template 进行变量替换
    template = Template(raw_prompt)
    return template.safe_substitute(**kwargs)


def list_prompts() -> list[str]:
    """列出所有可用的提示词路径

    Returns:
        提示词路径列表，如 ["split/semantic", "optimize/subtitle"]
    """
    prompts = []
    for md_file in PROMPTS_DIR.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        # 转换为相对路径，去掉 .md 后缀
        rel_path = md_file.relative_to(PROMPTS_DIR)
        prompt_path = str(rel_path.with_suffix("")).replace("\\", "/")
        prompts.append(prompt_path)
    return sorted(prompts)


def reload_cache():
    """清空提示词缓存（用于开发模式热重载）"""
    _load_prompt_file.cache_clear()


__all__ = ["get_prompt", "list_prompts", "reload_cache"]
