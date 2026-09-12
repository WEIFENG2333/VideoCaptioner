"""UI 国际化入口（只在 UI 层使用；core/CLI 不翻译）。

    from videocaptioner.ui.i18n import tr
    label.setText(tr("home.drop.hint"))
    label.setText(tr("hardsub.toast.done", count=n))   # 命名占位插值

key 命名规范：``<域>.<组件>.<语义>``，小写点分（见 docs/dev/i18n-plan.md）。
"""

from __future__ import annotations

from videocaptioner.ui.i18n.catalog import (
    BASE_LANG,
    SUPPORTED,
    current_language,
    init,
    set_language,
)
from videocaptioner.ui.i18n.catalog import (
    translate as _translate,
)

__all__ = [
    "tr",
    "N_",
    "init",
    "set_language",
    "current_language",
    "BASE_LANG",
    "SUPPORTED",
]


def tr(key: str, /, **params: object) -> str:
    """按当前语言翻译 key。有 ``**params`` 时做命名占位插值；无则不 format（避免误伤含 ``{}`` 的文案）。"""
    text = _translate(key)
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def N_(key: str) -> str:
    """标记 key 供 pybabel 抽取，运行时原样返回。用于非 tr() 调用点的字面量（如枚举标签映射表）。"""
    return key
