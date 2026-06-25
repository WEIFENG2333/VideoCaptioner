"""沉浸式免费翻译器：确定性单测（不打网络）+ 可选真机集成。"""

import base64
import json
import os

import pytest

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate import immersive_translator as mod
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.immersive_translator import (
    MAX_CONCURRENCY,
    ImmersiveFreeTranslator,
    _FreeTokenProvider,
    _jwt_exp,
    _new_device_id,
)
from videocaptioner.core.translate.types import TargetLanguage, TranslatorType


def _fake_jwt(exp: int) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'exp': exp})}.sig"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """计数 get 调用的假 session，用于验证 token 缓存/续期。"""

    def __init__(self, token):
        self.token = token
        self.get_calls = 0

    def get(self, url, params=None, timeout=None):
        self.get_calls += 1
        return _Resp({"code": 0, "data": self.token})


def test_jwt_exp_parses_and_degrades():
    assert _jwt_exp(_fake_jwt(1782371006)) == 1782371006.0
    assert _jwt_exp("not-a-jwt") == 0.0
    assert _jwt_exp("") == 0.0


def test_new_device_id_shape():
    did = _new_device_id()
    assert len(did) == 64 and did.isalnum()
    assert did != _new_device_id()  # 随机


def test_device_id_persists(monkeypatch, tmp_path):
    f = tmp_path / "immersive_device_id"
    monkeypatch.setattr(mod, "_DEVICE_ID_FILE", f)
    p = _FreeTokenProvider()
    first = p.device_id()
    assert f.read_text(encoding="utf-8").strip() == first
    # 同进程缓存 + 跨实例读盘都稳定
    assert _FreeTokenProvider().device_id() == first


def test_token_caches_until_expiry_and_force_refreshes(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_DEVICE_ID_FILE", tmp_path / "did")
    p = _FreeTokenProvider()
    sess = _FakeSession(_fake_jwt(2_000_000_000))  # 远期，缓存有效
    t1 = p.token(sess)
    t2 = p.token(sess)  # 命中缓存，不再请求
    assert t1 == t2 and sess.get_calls == 1
    p.token(sess, force=True)  # 强制续期
    assert sess.get_calls == 2


def test_expired_token_triggers_refetch(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_DEVICE_ID_FILE", tmp_path / "did")
    p = _FreeTokenProvider()
    sess = _FakeSession(_fake_jwt(1))  # 已过期（exp - margin < now）
    p.token(sess)
    p.token(sess)  # 过期必须重取
    assert sess.get_calls == 2


def _chunk(texts):
    return [SubtitleProcessData(index=i, original_text=t) for i, t in enumerate(texts, 1)]


def _translator():
    tr = ImmersiveFreeTranslator(
        thread_num=2, batch_num=10, target_language=TargetLanguage.SIMPLIFIED_CHINESE
    )
    return tr


def test_translate_chunk_fills_and_strips(monkeypatch):
    tr = _translator()
    # 模型常在译文前带换行，需 strip
    monkeypatch.setattr(
        tr, "_post_chat", lambda messages: '\n{"1": "\\n你好", "2": "世界"}'
    )
    out = tr._translate_chunk(_chunk(["Hi", "World"]))
    assert out[0].translated_text == "你好"
    assert out[1].translated_text == "世界"
    tr.stop()


def test_chat_dict_retries_on_missing_keys(monkeypatch):
    tr = _translator()
    responses = iter(['{"1": "一"}', '{"1": "一", "2": "二"}'])  # 首次缺键，重试补全
    monkeypatch.setattr(tr, "_post_chat", lambda messages: next(responses))
    out = tr._translate_chunk(_chunk(["one", "two"]))
    assert out[0].translated_text == "一" and out[1].translated_text == "二"
    tr.stop()


def test_falls_back_to_single_when_batch_raises(monkeypatch):
    tr = _translator()

    def boom(system_prompt, subtitle_dict):
        raise RuntimeError("batch broke")

    monkeypatch.setattr(tr, "_chat_dict", boom)
    monkeypatch.setattr(tr, "_post_chat", lambda messages: "译文")  # 逐条兜底
    out = tr._translate_chunk(_chunk(["a", "b"]))
    assert [d.translated_text for d in out] == ["译文", "译文"]
    tr.stop()


def test_missing_key_kept_original_when_single_also_fails(monkeypatch):
    tr = _translator()
    calls = {"n": 0}

    def post(messages):
        calls["n"] += 1
        if calls["n"] <= tr.MAX_STEPS:
            return '{"1": "一"}'  # 批量 3 次都缺键2 → _chat_dict 用尽重试返回 {"1":"一"}
        raise RuntimeError("single failed")  # 第 2 段逐条补译也失败

    monkeypatch.setattr(tr, "_post_chat", post)
    out = tr._translate_chunk(_chunk(["one", "two"]))
    assert out[0].translated_text == "一"  # 批量译出，保留
    assert out[1].translated_text == "two"  # 单条也失败 → 回退原文，不丢段（局部失败可接受）
    tr.stop()


def test_total_failure_raises_not_silent_success(monkeypatch):
    # 高危回归：整块失败（端点不可用/429）必须抛错，绝不能静默把原文当译文返回，
    # 否则 BaseTranslator ≥50% 失败保护失效 + 全原文块被缓存 7 天毒化重试。
    tr = _translator()

    def boom(messages):
        raise RuntimeError("gateway 429 / down")

    monkeypatch.setattr(tr, "_post_chat", boom)
    with pytest.raises(RuntimeError):
        tr._translate_chunk(_chunk(["a", "b"]))
    tr.stop()


def test_invalid_response_body_raises_in_post_chat(monkeypatch):
    # 429/错误体常是 200+无 choices：明确抛错而非裸 KeyError/IndexError
    tr = _translator()

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "rate limited"}  # 无 choices

    monkeypatch.setattr(tr._tokens, "token", lambda session, force=False: "tok")
    monkeypatch.setattr(tr.session, "post", lambda *a, **k: _R())
    with pytest.raises(RuntimeError):
        tr._post_chat([{"role": "user", "content": "hi"}])
    tr.stop()


def test_factory_caps_concurrency_at_10():
    tr = TranslatorFactory.create_translator(
        TranslatorType.IMMERSIVE,
        thread_num=50,  # 超过免费额度上限
        batch_num=10,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
    )
    assert isinstance(tr, ImmersiveFreeTranslator)
    assert tr.thread_num == MAX_CONCURRENCY == 10
    tr.stop()


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TRANSLATION_TESTS") != "1"
    and os.getenv("RUN_IMMERSIVE_TRANSLATOR_TESTS") != "1",
    reason="沉浸式免费端点依赖网络；设 RUN_IMMERSIVE_TRANSLATOR_TESTS=1 运行真机测试。",
)
def test_live_translation():
    tr = ImmersiveFreeTranslator(
        thread_num=2, batch_num=5, target_language=TargetLanguage.SIMPLIFIED_CHINESE
    )
    out = tr._translate_chunk(_chunk(["Hello World.", "This is a test."]))
    assert all(d.translated_text and d.translated_text != d.original_text for d in out)
    tr.stop()
