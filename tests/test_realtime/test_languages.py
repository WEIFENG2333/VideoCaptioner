"""实时转录各 provider 识别语言集的单一事实来源契约（core/realtime/languages.py）。

钉死「每个提供商区分好、命名好、都带自动识别」：voxgate 仅中/英、Fun-ASR 多语种 7、
Qwen-ASR 27，三家首项都是 auto；校验器用并集；UI 标签按 provider 取子集组装。
"""

from videocaptioner.core.realtime.backends.languages import (
    AUTO,
    FUN_ASR_LANGS,
    FUN_ASR_MTL_LANGS,
    FUN_ASR_REALTIME_LANGS,
    PROVIDER_SOURCE_LANGS,
    QWEN_ASR_LANGS,
    VOXGATE_LANGS,
    all_source_lang_codes,
    source_lang_codes,
)


def test_every_provider_starts_with_auto():
    # 三家都支持自动识别，且约定 auto 永远是第一项
    for codes in PROVIDER_SOURCE_LANGS.values():
        assert codes[0] == AUTO


def test_voxgate_is_chinese_english_only():
    # voxgate 豆包双语：仅中/英（+ auto），不再误用 Fun-ASR 的 7 语言集
    assert VOXGATE_LANGS == ("auto", "zh", "en")
    assert source_lang_codes("voxgate") == ("auto", "zh", "en")


def test_fun_asr_is_multilingual_seven():
    # Fun-ASR 下拉用多语种模型集（中/粤/英/日/泰/越/印尼）
    assert FUN_ASR_MTL_LANGS == ("zh", "yue", "en", "ja", "th", "vi", "id")
    assert FUN_ASR_REALTIME_LANGS == ("zh", "en", "ja")
    assert FUN_ASR_LANGS == (AUTO, *FUN_ASR_MTL_LANGS)
    assert len(source_lang_codes("fun-asr")) == 8


def test_qwen_has_27_languages_incl_spanish():
    assert source_lang_codes("qwen-asr") is QWEN_ASR_LANGS
    assert len(QWEN_ASR_LANGS) == 28  # auto + 27
    assert "es" in QWEN_ASR_LANGS  # 西班牙语（Fun-ASR 没有，看西语视频选 Qwen）
    assert "de" in QWEN_ASR_LANGS and "ko" in QWEN_ASR_LANGS


def test_unknown_provider_falls_back_to_voxgate():
    assert source_lang_codes("nope") == VOXGATE_LANGS


def test_union_dedupes_and_preserves_order():
    union = all_source_lang_codes()
    assert union[0] == AUTO
    assert len(union) == len(set(union))  # 去重
    # 并集 = qwen 的 28 种（它是各家的超集；voxgate/fun-asr 的码都在其中）
    assert set(union) == set(QWEN_ASR_LANGS)
    for codes in PROVIDER_SOURCE_LANGS.values():
        assert set(codes) <= set(union)


def test_ui_options_pair_codes_with_chinese_labels():
    from videocaptioner.config import I18N_PATH
    from videocaptioner.ui import i18n
    from videocaptioner.ui.common.config import source_language_options

    # 标签走 tr()，必须先装载目录；不能依赖恰好先跑的其它测试替本测试 init
    i18n.init(I18N_PATH, "zh_CN")

    assert source_language_options("voxgate") == [
        ("auto", "自动识别"), ("zh", "中文"), ("en", "英语")]
    qwen = dict(source_language_options("qwen-asr"))
    assert qwen["es"] == "西班牙语" and qwen["auto"] == "自动识别"
    # 每个 code 都有标签（不漏译成 code 本身）
    for code, label in source_language_options("fun-asr"):
        assert label and label != code


def test_fun_asr_backend_uses_shared_sets():
    # 后端 _language_hints 取自同一份常量：auto → 按模型给整套；显式 → 单一语言
    from videocaptioner.core.realtime.backends.fun_asr import FunAsrBackend

    noop = lambda *a, **k: None  # noqa: E731
    mtl = FunAsrBackend(api_key="k", model="fun-asr-mtl-realtime", language="auto",
                        on_segment=noop, on_state=noop, on_error=noop)
    assert tuple(mtl._language_hints()) == FUN_ASR_MTL_LANGS

    rt = FunAsrBackend(api_key="k", model="fun-asr-realtime", language="auto",
                       on_segment=noop, on_state=noop, on_error=noop)
    assert tuple(rt._language_hints()) == FUN_ASR_REALTIME_LANGS

    explicit = FunAsrBackend(api_key="k", model="fun-asr-mtl-realtime", language="ja",
                             on_segment=noop, on_state=noop, on_error=noop)
    assert explicit._language_hints() == ["ja"]
