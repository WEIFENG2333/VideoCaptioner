"""LLM 客户端单例契约：按 (base, key) 指纹缓存，provider 变了要重建。

修「同进程内先用一个 provider 建好 client、再换 provider 时 env 改了却仍复用旧端点」的串台
bug——译文静默走错端点/模型，难排查。
"""

from videocaptioner.core.llm import client as cli


class _FakeOpenAI:
    def __init__(self, base_url, api_key, http_client=None):
        self.base_url = base_url
        self.api_key = api_key


def _reset():
    cli._global_client = None
    cli._client_fingerprint = None


def test_same_env_reuses_singleton(monkeypatch):
    _reset()
    built = []
    monkeypatch.setattr(cli, "OpenAI", lambda **k: built.append(k) or _FakeOpenAI(**k))
    monkeypatch.setattr(cli, "create_logging_http_client", lambda: None)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://a/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    c1 = cli.get_llm_client()
    c2 = cli.get_llm_client()
    assert c1 is c2 and len(built) == 1  # 同端点同 key → 复用，不重建


def test_provider_change_rebuilds_client(monkeypatch):
    _reset()
    built = []
    monkeypatch.setattr(cli, "OpenAI", lambda **k: built.append(k) or _FakeOpenAI(**k))
    monkeypatch.setattr(cli, "create_logging_http_client", lambda: None)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://a/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    c1 = cli.get_llm_client()
    # 切到另一个 provider（key 变）：必须重建，不能复用旧端点
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    c2 = cli.get_llm_client()
    assert c2 is not c1
    assert len(built) == 2 and built[-1]["api_key"] == "k2"
    # base 变同理
    monkeypatch.setenv("OPENAI_BASE_URL", "https://b/v1")
    c3 = cli.get_llm_client()
    assert c3 is not c2 and built[-1]["base_url"] == "https://b/v1"


def test_missing_env_raises(monkeypatch):
    _reset()
    monkeypatch.setattr(cli, "OpenAI", lambda **k: _FakeOpenAI(**k))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        cli.get_llm_client()
        assert False, "应因缺少环境变量而报错"
    except ValueError:
        pass
