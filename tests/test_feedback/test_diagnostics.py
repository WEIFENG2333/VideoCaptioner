"""诊断采集：绝不含密钥；client_id 持久化稳定。"""

import json

from videocaptioner.core.application import config_store
from videocaptioner.core.feedback import diagnostics


def test_is_safe_rejects_secret_like():
    assert diagnostics._is_safe("openai")
    assert diagnostics._is_safe("bing")
    assert not diagnostics._is_safe("sk-abcdef123456")
    assert not diagnostics._is_safe("Bearer xyz")
    assert not diagnostics._is_safe("https://api.openai.com/v1")
    assert not diagnostics._is_safe("x" * 80)  # 过长


def test_gather_diagnostics_has_no_secret_values(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "CONFIG_FILE", cfg)
    # 即使有人把密钥误塞进白名单字段，_is_safe 也兜底丢弃
    config_store.save_config_value("llm.service", "sk-should-be-dropped")
    diag = diagnostics.gather_diagnostics()
    blob = json.dumps(diag).lower()
    for marker in ("sk-", "bearer", "api_key", "://", "token"):
        assert marker not in blob
    assert diag["app_version"]
    assert diag["platform"]
    assert diag.get("llm_service") != "sk-should-be-dropped"  # 被兜底丢弃


def test_gather_diagnostics_keeps_safe_provider_names(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "CONFIG_FILE", cfg)
    config_store.save_config_value("llm.service", "deepseek")
    config_store.save_config_value("dubbing.provider", "edge")
    diag = diagnostics.gather_diagnostics()
    assert diag["llm_service"] == "deepseek"
    assert diag["dubbing_provider"] == "edge"


def test_client_id_is_stable_and_persisted_to_file(monkeypatch, tmp_path):
    # client_id 存独立文件，不入配置文件
    id_file = tmp_path / "feedback_client_id"
    monkeypatch.setattr(diagnostics, "_CLIENT_ID_FILE", id_file)
    first = diagnostics.get_or_create_client_id()
    second = diagnostics.get_or_create_client_id()
    assert first and first == second
    assert id_file.read_text(encoding="utf-8").strip() == first


def test_platform_tag_shape():
    tag = diagnostics.platform_tag()
    assert tag.split("-")[0] in ("windows", "macos", "linux")
    assert tag.split("-")[1] in ("x64", "arm64")
