"""UI i18n 运行时与枚举标签的确定性测试（无网络）。

工具链层面的「源码 key == .pot」「基准无空译文」由 `scripts/i18n.py check`（CI）负责。
"""

from __future__ import annotations

import pytest

from videocaptioner.config import I18N_PATH
from videocaptioner.ui import i18n
from videocaptioner.ui.common import enum_labels


def test_normalize_locale():
    n = i18n.catalog._normalize
    assert n("en_US") == "en"
    assert n("en") == "en"
    assert n("zh_CN") == "zh_Hans"
    assert n("zh_Hans") == "zh_Hans"
    assert n("zh_HK") == "zh_Hant"
    assert n("zh_TW") == "zh_Hant"
    assert n("fr_FR") == "zh_Hans"  # 未知归基准
    assert n("") == "zh_Hans"


def test_tr_fallback_returns_key_without_catalog():
    # 未 init / 缺 key 时回退 key 本身，永不抛。
    i18n.set_language("en")
    assert i18n.tr("nonexistent.key.xyz") == "nonexistent.key.xyz"


def test_tr_named_placeholder():
    # 无翻译时回退 key，但带 params 仍不抛（key 无占位则原样）。
    assert i18n.tr("nonexistent.key.fmt", n=3) == "nonexistent.key.fmt"


def test_N_is_identity():
    assert i18n.N_("enum.Foo.BAR") == "enum.Foo.BAR"


def test_enum_base_map_covers_all_members():
    base = enum_labels.enum_base_map()
    for cls in enum_labels.TRANSLATABLE_ENUMS:
        for member in cls:
            key = enum_labels.enum_key(member)
            assert key in base, f"缺枚举 key: {key}"
            assert base[key], f"枚举基准中文为空: {key}"


def test_enum_key_format():
    from videocaptioner.core.translate.types import TargetLanguage

    assert enum_labels.enum_key(TargetLanguage.JAPANESE) == "enum.TargetLanguage.JAPANESE"


@pytest.mark.skipif(
    not (I18N_PATH / "zh_Hans" / "LC_MESSAGES" / "videocaptioner.mo").exists(),
    reason="zh_Hans.mo 未编译（先跑 scripts/i18n.py compile）",
)
def test_compiled_base_catalog_translates_enum():
    from videocaptioner.core.entities import VideoQualityEnum
    from videocaptioner.core.translate.types import TargetLanguage

    i18n.init(I18N_PATH, "zh_CN")
    assert enum_labels.enum_label(TargetLanguage.JAPANESE) == "日本語"
    assert enum_labels.enum_label(VideoQualityEnum.ULTRA_HIGH) == "极高质量"
