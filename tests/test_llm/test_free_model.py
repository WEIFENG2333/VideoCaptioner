"""公益大模型免费网关：令牌管理 + LLM client 接入（确定性单测，不打网络）。"""

import base64
import json

from videocaptioner.core.llm import free_model


def _fake_jwt(exp: int) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'exp': exp})}.sig"


def test_is_free_base():
    assert free_model.is_free_base(free_model.BASE_URL)
    assert free_model.is_free_base("https://aigw1.immersivetranslate.com/v1/free/")
    assert not free_model.is_free_base("https://api.openai.com/v1")
    assert not free_model.is_free_base("")


def test_jwt_exp_parses_and_degrades():
    assert free_model._jwt_exp(_fake_jwt(1782371006)) == 1782371006.0
    assert free_model._jwt_exp("garbage") == 0.0


def test_new_device_id_shape():
    a, b = free_model._new_device_id(), free_model._new_device_id()
    assert len(a) == 64 and a.isalnum() and a != b


def test_device_id_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(free_model, "_DEVICE_ID_FILE", tmp_path / "did")
    p = free_model._TokenProvider()
    first = p.device_id()
    assert (tmp_path / "did").read_text(encoding="utf-8").strip() == first
    assert free_model._TokenProvider().device_id() == first  # 跨实例读盘稳定


def test_token_caches_and_force_refreshes(monkeypatch, tmp_path):
    monkeypatch.setattr(free_model, "_DEVICE_ID_FILE", tmp_path / "did")
    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "data": _fake_jwt(2_000_000_000)}

    class _FakeCffi:
        def get(self, url, params=None, impersonate=None, timeout=None):
            calls["n"] += 1
            return _Resp()

    monkeypatch.setattr(free_model, "cffi_requests", _FakeCffi())
    p = free_model._TokenProvider()
    t1, t2 = p.token(), p.token()  # 第二次命中缓存
    assert t1 == t2 and calls["n"] == 1
    p.token(force=True)  # 强制续期
    assert calls["n"] == 2


def test_client_uses_free_token_for_free_base(monkeypatch):
    """get_llm_client 命中公益 base 时，忽略占位 key、用实时令牌建 client。"""
    from videocaptioner.core.llm import client as llm_client

    monkeypatch.setenv("OPENAI_BASE_URL", free_model.BASE_URL)
    monkeypatch.setenv("OPENAI_API_KEY", free_model.PLACEHOLDER_KEY)
    monkeypatch.setattr(free_model, "token", lambda force=False: "real-jwt-token")
    # 复位单例，避免上一个测试的指纹缓存串台
    monkeypatch.setattr(llm_client, "_global_client", None)
    monkeypatch.setattr(llm_client, "_client_fingerprint", None)
    c = llm_client.get_llm_client()
    assert c.api_key == "real-jwt-token"  # 占位 key 被实时令牌取代
