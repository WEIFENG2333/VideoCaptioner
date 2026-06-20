"""实时翻译装配（factory._LazyTranslator）契约。

两道防线让「目标==所说语言」时不显冗余译文：
① **语言级跳过**（主）：按**每句文本的实际字符构成**判主语言，== 目标语言大类（如中文文本→简体中文）
   → 跳过、不联网、不显近似重复的同语言「译文」。**不依赖配置的识别语言**（用户可能设错、或多语模型
   自动识别成别的语言）——修了「识别语言设中文、实际说英文、目标中文 → 被误判同语言而整段不翻译」。
② 逐句兜底：跨语言时若引擎返回的译文恰好≈原文，也判为无译文。
跨语言（如英→中）正常返回译文。
"""

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.realtime.factory import _LazyTranslator, build_translate_fn
from videocaptioner.core.translate.types import TargetLanguage


class _FakeTranslator:
    """按预设把 original_text 映射成 translated_text，不联网。"""

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = 0

    def _translate_chunk(self, data: list[SubtitleProcessData]) -> None:
        self.calls += 1
        for d in data:
            d.translated_text = self._mapping(d.original_text)

    def stop(self):
        pass


def _lazy(mapping, source="en", target=TargetLanguage.SIMPLIFIED_CHINESE) -> _LazyTranslator:
    lt = _LazyTranslator(LiveCaptionConfig(source_language=source, target_language=target))
    lt._tr = _FakeTranslator(mapping)  # 注入，跳过联网构造
    return lt


def test_same_language_skips_by_text():
    # 中文文本 + 目标中文：按文本判定同语言 → 跳过，连引擎都不调
    lt = _lazy(lambda s: "x", source="zh", target=TargetLanguage.SIMPLIFIED_CHINESE)
    assert lt.translate("今天天气不错") == ""
    assert lt._tr.calls == 0  # 没联网/没调引擎


def test_wrong_source_lang_still_translates_english():
    # 关键回归：识别语言设成中文(source=zh)、目标中文、但实际说英文 → 必须翻译。
    # 旧逻辑按配置 source==target 整段跳过会漏翻（线上「开了翻译但全是英文」真因）。
    lt = _lazy(lambda s: "你好", source="zh", target=TargetLanguage.SIMPLIFIED_CHINESE)
    assert lt.translate("I think the weather is nice") == "你好"


def test_same_language_by_text_en_ja():
    # 按文本主语言判定：英文文本→目标英文 跳过；日文文本→目标日文 跳过；跨语言不跳。
    assert _lazy(lambda s: s, target=TargetLanguage.ENGLISH)._looks_same_language("hello world")
    assert _lazy(lambda s: s, target=TargetLanguage.JAPANESE)._looks_same_language("こんにちは、元気")
    assert not _lazy(lambda s: s, target=TargetLanguage.SIMPLIFIED_CHINESE)._looks_same_language("hello")


def test_cross_language_passes_through():
    # 英→中：译文≠原文 → 正常返回译文
    lt = _lazy(lambda s: "你好", source="en", target=TargetLanguage.SIMPLIFIED_CHINESE)
    assert lt.translate("hello") == "你好"


def test_cross_language_identical_output_dropped():
    # 跨语言但引擎恰好返回≈原文 → 逐句兜底判空
    lt = _lazy(lambda s: f"  {s} ", source="en", target=TargetLanguage.SIMPLIFIED_CHINESE)
    assert lt.translate("hello world") == ""


def test_empty_input_returns_empty():
    lt = _lazy(lambda s: "x", source="en", target=TargetLanguage.SIMPLIFIED_CHINESE)
    assert lt.translate("   ") == ""


def test_build_translate_fn_disabled_returns_none():
    cfg = LiveCaptionConfig(translate_enabled=False)
    assert build_translate_fn(cfg) is None


def test_openai_translator_sets_llm_env_from_config(monkeypatch):
    """LLM 翻译（OPENAI）建翻译器前，从配置把 key/base 写进 OPENAI_API_KEY/BASE_URL 环境变量。

    实时字幕之前漏了这步 → 选「大模型翻译」报「环境变量未设置」。"""
    import os

    from videocaptioner.core.translate import factory as tf
    from videocaptioner.core.translate.types import TranslatorType

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    class _FakeLLMTr:
        def _translate_chunk(self, data):
            for d in data:
                d.translated_text = "<译>"

        def stop(self):
            pass

    monkeypatch.setattr(tf.TranslatorFactory, "create_translator",
                        staticmethod(lambda **k: _FakeLLMTr()))

    lt = _LazyTranslator(LiveCaptionConfig(
        translate_enabled=True, translator_type=TranslatorType.OPENAI,
        llm_api_key="sk-test", llm_api_base="https://example.com/v1", llm_model="m",
        target_language=TargetLanguage.SIMPLIFIED_CHINESE))
    out = lt.translate("hola mundo")  # 英文/西文 latin → 非中文，照常翻

    assert os.environ.get("OPENAI_API_KEY") == "sk-test"
    assert os.environ.get("OPENAI_BASE_URL") == "https://example.com/v1"
    assert out == "<译>"


def test_openai_translator_without_key_disabled(monkeypatch):
    """LLM 翻译但没配 key/base → 禁用译文（不报错刷屏），不抛异常。"""
    from videocaptioner.core.translate.types import TranslatorType
    lt = _LazyTranslator(LiveCaptionConfig(
        translate_enabled=True, translator_type=TranslatorType.OPENAI,
        llm_api_key="", llm_api_base="", target_language=TargetLanguage.SIMPLIFIED_CHINESE))
    assert lt.translate("hola mundo") == ""  # 无 key → 空译文、禁用


def test_llm_translator_disable_thinking_extra_body():
    """disable_thinking=True 时翻译请求带 extra_body={'enable_thinking': False}；否则不带。"""
    from videocaptioner.core.translate.llm_translator import LLMTranslator
    common = dict(thread_num=1, batch_num=1, target_language=TargetLanguage.SIMPLIFIED_CHINESE,
                  model="m", custom_prompt="", is_reflect=False, update_callback=None)
    assert LLMTranslator(**common, disable_thinking=True)._llm_extra == {
        "extra_body": {"enable_thinking": False}}
    assert LLMTranslator(**common)._llm_extra == {}


def test_realtime_llm_translation_disables_thinking(monkeypatch):
    """实时字幕的 LLM 翻译建翻译器时带 disable_thinking=True（关思考求快）。"""
    from videocaptioner.core.translate import factory as tf
    from videocaptioner.core.translate.types import TranslatorType
    captured = {}

    class _FakeTr:
        def _translate_chunk(self, data):
            for d in data:
                d.translated_text = "<x>"

        def stop(self):
            pass

    def spy(**kw):
        captured.update(kw)
        return _FakeTr()

    monkeypatch.setattr(tf.TranslatorFactory, "create_translator", staticmethod(spy))
    lt = _LazyTranslator(LiveCaptionConfig(
        translate_enabled=True, translator_type=TranslatorType.OPENAI,
        llm_api_key="k", llm_api_base="https://x/v1", llm_model="m",
        target_language=TargetLanguage.SIMPLIFIED_CHINESE))
    lt.translate("hola mundo")
    assert captured.get("disable_thinking") is True


def test_call_llm_api_strips_enable_thinking_on_400(monkeypatch):
    """端点不认 enable_thinking（400）→ 去掉该参数重试成功，并记住该端点。"""
    from videocaptioner.core.llm import client as cli
    cli._thinking_unsupported.clear()
    seen = []

    class _Resp:
        choices = []

    def fake_create(**kw):
        has = "enable_thinking" in (kw.get("extra_body") or {})
        seen.append(has)
        if has:
            err = Exception("Error code: 400 - unknown parameter: enable_thinking")
            err.status_code = 400
            raise err
        return _Resp()

    fake_client = type("C", (), {"chat": type("ch", (), {
        "completions": type("co", (), {"create": staticmethod(fake_create)})})})()
    monkeypatch.setattr(cli, "get_llm_client", lambda: fake_client)
    monkeypatch.setattr(cli, "log_llm_response", lambda r: None)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://official.example/v1")

    r = cli._call_llm_api([{"role": "user", "content": "hi"}], "m",
                          extra_body={"enable_thinking": False})
    assert r is not None
    assert seen == [True, False]  # 先带→400，去掉后成功
    assert ("https://official.example/v1", "m") in cli._thinking_unsupported  # 按(端点,模型)记住
