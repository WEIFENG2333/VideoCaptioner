"""枚举 → UI 显示标签的 i18n 映射。

core 枚举只保留 identity（``.value``，是 TOML/CLI 主键）；UI 显示走
``enum.<类名>.<成员名>`` 这个 key → ``tr()``。基准中文 = 去掉装饰 ✨ 的 ``.value``
（保持原显示），由 ``enum_base_map()`` 程序化生成，供 i18n 工具链抽取/填充。

新增需要翻译的枚举：把类加进 ``TRANSLATABLE_ENUMS`` 即可，无需手写 key。
本模块不依赖 PyQt（tr 来自标准库 gettext 封装），i18n 工具链可直接 import。
"""

from __future__ import annotations

from enum import Enum

from videocaptioner.core.entities import (
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
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.ui.i18n import tr

# 在 UI 下拉里展示、需要随语言翻译的枚举（技术型如模型名/VAD 译文=原值，无害）。
TRANSLATABLE_ENUMS: tuple[type[Enum], ...] = (
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
    TranscribeLanguageEnum,
    WhisperModelEnum,
    FasterWhisperModelEnum,
    VadMethodEnum,
    LLMServiceEnum,
    TranslatorServiceEnum,
    TargetLanguage,
    SubtitleLayoutEnum,
    SubtitleRenderModeEnum,
    VideoQualityEnum,
)
_REGISTERED = set(TRANSLATABLE_ENUMS)


def enum_key(member: Enum) -> str:
    return f"enum.{type(member).__name__}.{member.name}"


def enum_base_text(member: Enum) -> str:
    """基准中文 = 去掉装饰 ✨ 的 .value。"""
    return str(member.value).replace(" ✨", "").strip()


def enum_label(value: object) -> str | None:
    """已注册枚举成员 → 当前语言标签；其余返回 None（调用方回退原值）。"""
    if isinstance(value, Enum) and type(value) in _REGISTERED:
        return tr(enum_key(value))
    return None


def enum_options(enum_cls: type[Enum]) -> list[str]:
    """枚举所有成员的当前语言标签列表（给按文本取值的 PillSelect 等用）。"""
    return [tr(enum_key(m)) for m in enum_cls]


def enum_from_label(enum_cls: type[Enum], label: str) -> Enum | None:
    """当前语言标签 → 枚举成员（PillSelect 回选用）。"""
    for m in enum_cls:
        if tr(enum_key(m)) == label:
            return m
    return None


def enum_base_map() -> dict[str, str]:
    """{enum key: 基准中文}，供 i18n 工具链抽取与填充 zh_Hans。"""
    return {enum_key(m): enum_base_text(m) for cls in TRANSLATABLE_ENUMS for m in cls}
