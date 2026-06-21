"""UI 翻译目录：key-based gettext，运行时只读 .mo（标准库 gettext，无第三方依赖）。

msgid 是稳定 key（如 ``dubbing.btn.start``），msgstr 是各语言文案；基准语言 zh_Hans 存中文。
翻译边界只在 UI——core/CLI 不使用本模块。
"""

from __future__ import annotations

import gettext as _gettext
from pathlib import Path
from typing import Optional

_DOMAIN = "videocaptioner"
BASE_LANG = "zh_Hans"
SUPPORTED = ("zh_Hans", "zh_Hant", "en")

_lang = BASE_LANG
_trans: _gettext.NullTranslations = _gettext.NullTranslations()
_dir: Optional[Path] = None


def _normalize(name: str) -> str:
    """任意 locale 名（QLocale.name() / 'auto' 等）→ 受支持的 catalog 目录名；未知归基准。"""
    n = (name or "").replace("-", "_").lower()
    if n.startswith("en"):
        return "en"
    if "hant" in n or n in ("zh_tw", "zh_hk", "zh_mo"):
        return "zh_Hant"
    return "zh_Hans"


def init(i18n_dir: Path, locale_name: str) -> None:
    """启动时调用一次：记住资源目录并按 locale 装载当前语言。"""
    global _dir
    _dir = Path(i18n_dir)
    set_language(locale_name)


def set_language(locale_name: str) -> None:
    """切换当前语言。非基准语言缺译时回退到基准中文（而非显示 key），实现优雅降级。"""
    global _lang, _trans
    _lang = _normalize(locale_name)
    if _dir is None:
        _trans = _gettext.NullTranslations()
        return
    trans = _gettext.translation(
        _DOMAIN, localedir=str(_dir), languages=[_lang], fallback=True
    )
    if _lang != BASE_LANG:
        base = _gettext.translation(
            _DOMAIN, localedir=str(_dir), languages=[BASE_LANG], fallback=True
        )
        trans.add_fallback(base)
    _trans = trans


def current_language() -> str:
    return _lang


def translate(key: str) -> str:
    return _trans.gettext(key)
