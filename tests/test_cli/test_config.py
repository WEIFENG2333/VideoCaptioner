"""Tests for CLI config system — TOML read/write, merging, type safety."""

import pytest

from videocaptioner.core.application.config_store import (
    DEFAULTS,
    build_config,
    deep_merge,
    get_nested,
    load_config_file,
    load_env_overrides,
    parse_value,
    save_config_value,
    save_many,
    set_nested,
    toml_value,
)


def test_default_dubbing_uses_keyless_edge_tts():
    assert DEFAULTS["dubbing"]["provider"] == "edge"
    assert DEFAULTS["dubbing"]["preset"] == "edge-cn-female"
    assert DEFAULTS["dubbing"]["api_key"] == ""
    assert DEFAULTS["dubbing"]["voice"] == "zh-CN-XiaoxiaoNeural"


class TestDeepMerge:
    def test_flat_override(self):
        assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 3, "c": 4}}
        result = deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 3, "c": 4}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        deep_merge(base, {"a": 2})
        assert base == {"a": 1}

    def test_empty_override(self):
        base = {"a": 1}
        assert deep_merge(base, {}) == {"a": 1}


class TestNestedAccess:
    def test_get_nested(self):
        d = {"a": {"b": {"c": 42}}}
        assert get_nested(d, "a.b.c") == 42

    def test_get_nested_missing(self):
        assert get_nested({"a": 1}, "b", "default") == "default"

    def test_get_nested_deep_missing(self):
        assert get_nested({"a": {"b": 1}}, "a.c.d", None) is None

    def test_set_nested(self):
        d: dict = {}
        set_nested(d, "a.b.c", 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_set_nested_overwrite(self):
        d = {"a": {"b": 1}}
        set_nested(d, "a.b", 2)
        assert d == {"a": {"b": 2}}


class TestParseValue:
    def test_bool_true(self):
        assert parse_value("true", "subtitle.optimize") is True
        assert parse_value("yes", "subtitle.optimize") is True
        assert parse_value("1", "subtitle.optimize") is True

    def test_bool_false(self):
        assert parse_value("false", "subtitle.optimize") is False
        assert parse_value("no", "subtitle.optimize") is False
        assert parse_value("0", "subtitle.optimize") is False

    def test_bool_invalid(self):
        with pytest.raises(ValueError, match="Expected boolean"):
            parse_value("maybe", "subtitle.optimize")

    def test_int(self):
        assert parse_value("8", "subtitle.thread_num") == 8
        assert isinstance(parse_value("8", "subtitle.thread_num"), int)

    def test_int_invalid(self):
        with pytest.raises(ValueError, match="Expected integer"):
            parse_value("abc", "subtitle.thread_num")

    def test_string(self):
        assert parse_value("gpt-4o", "llm.model") == "gpt-4o"

    def test_list_from_comma_separated_text(self):
        assert parse_value(
            "gpt-5, gemini-2.5-pro",
            "llm.providers.openai.model_options",
        ) == ["gpt-5", "gemini-2.5-pro"]

    def test_list_from_toml_array(self):
        assert parse_value(
            '["gpt-5", "gemini-2.5-pro"]',
            "llm.providers.openai.model_options",
        ) == ["gpt-5", "gemini-2.5-pro"]

    def test_unknown_key_stays_string(self):
        # Key not in DEFAULTS → stays string
        assert parse_value("anything", "unknown.key") == "anything"


class TestTomlValue:
    def test_bool(self):
        assert toml_value(True) == "true"
        assert toml_value(False) == "false"

    def test_int(self):
        assert toml_value(42) == "42"

    def test_float(self):
        assert toml_value(0.5) == "0.5"

    def test_string(self):
        assert toml_value("hello") == '"hello"'

    def test_string_with_quotes(self):
        assert toml_value('say "hi"') == '"say \\"hi\\""'

    def test_string_with_newline(self):
        assert toml_value("line1\nline2") == '"line1\\nline2"'

    def test_list(self):
        assert toml_value(["gpt-5", "gemini-2.5-pro"]) == '["gpt-5", "gemini-2.5-pro"]'


class TestConfigRoundtrip:
    def test_save_and_load(self, tmp_path):
        config_file = tmp_path / "config.toml"

        save_config_value("llm.model", "gpt-4o", config_path=config_file)
        save_config_value("subtitle.thread_num", "8", config_path=config_file)
        save_config_value("subtitle.optimize", "false", config_path=config_file)

        loaded = load_config_file(config_file)
        assert loaded["llm"]["model"] == "gpt-4o"
        assert loaded["subtitle"]["thread_num"] == 8
        assert loaded["subtitle"]["optimize"] is False

    def test_active_provider_key_updates_generic_alias(self, tmp_path):
        config_file = tmp_path / "config.toml"

        save_config_value("llm.service", "silicon_cloud", config_path=config_file)
        save_config_value(
            "llm.providers.silicon_cloud.api_key",
            "sk-provider",
            config_path=config_file,
        )

        config = build_config(config_path=config_file)
        assert config["llm"]["api_key"] == "sk-provider"
        assert config["llm"]["providers"]["silicon_cloud"]["api_key"] == "sk-provider"

    def test_secret_values_are_stripped(self, tmp_path):
        config_file = tmp_path / "config.toml"

        save_config_value("llm.service", "silicon_cloud", config_path=config_file)
        save_config_value(
            "llm.providers.silicon_cloud.api_key",
            "  sk-provider\n",
            config_path=config_file,
        )

        config = build_config(config_path=config_file)
        assert config["llm"]["api_key"] == "sk-provider"
        assert config["llm"]["providers"]["silicon_cloud"]["api_key"] == "sk-provider"

    def test_generic_key_updates_active_provider(self, tmp_path):
        config_file = tmp_path / "config.toml"

        save_config_value("llm.service", "deepseek", config_path=config_file)
        save_config_value("llm.api_key", "sk-generic", config_path=config_file)

        config = build_config(config_path=config_file)
        assert config["llm"]["api_key"] == "sk-generic"
        assert config["llm"]["providers"]["deepseek"]["api_key"] == "sk-generic"

    def test_provider_model_options_roundtrip(self, tmp_path):
        config_file = tmp_path / "config.toml"

        save_many(
            {
                "llm.providers.silicon_cloud.model_options": [
                    "moonshotai/Kimi-K2-Instruct-0905",
                    "deepseek-ai/DeepSeek-V3",
                ]
            },
            config_path=config_file,
        )

        config = build_config(config_path=config_file)
        assert config["llm"]["providers"]["silicon_cloud"]["model_options"] == [
            "moonshotai/Kimi-K2-Instruct-0905",
            "deepseek-ai/DeepSeek-V3",
        ]


class TestBuildConfig:
    def test_defaults_only(self, tmp_path):
        config = build_config(config_path=tmp_path / "missing.toml")
        assert config["llm"]["model"] == DEFAULTS["llm"]["model"]

    def test_cli_overrides(self):
        config = build_config(cli_overrides={"llm": {"model": "custom"}})
        assert config["llm"]["model"] == "custom"

    def test_active_provider_aliases_are_normalized(self):
        config = build_config(
            cli_overrides={
                "llm": {
                    "service": "gemini",
                    "providers": {"gemini": {"api_key": "sk-gemini", "model": "gemini-test"}},
                }
            }
        )

        assert config["llm"]["api_key"] == "sk-gemini"
        assert config["llm"]["model"] == "gemini-test"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("VIDEOCAPTIONER_LLM_MODEL", "env-model")
        config = build_config()
        assert config["llm"]["model"] == "env-model"

    def test_priority_cli_over_env(self, monkeypatch):
        monkeypatch.setenv("VIDEOCAPTIONER_LLM_MODEL", "env-model")
        config = build_config(cli_overrides={"llm": {"model": "cli-model"}})
        assert config["llm"]["model"] == "cli-model"

    def test_env_values_are_typed(self, monkeypatch):
        monkeypatch.setenv("VIDEOCAPTIONER_TTS_MAX_SPEED", "2.0")
        monkeypatch.setenv("VIDEOCAPTIONER_TTS_WORKERS", "3")
        monkeypatch.setenv("VIDEOCAPTIONER_TTS_REWRITE_TOO_LONG", "true")
        monkeypatch.setenv("VIDEOCAPTIONER_TTS_MIX_ORIGINAL_AUDIO", "false")

        overrides = load_env_overrides()

        assert overrides["dubbing"]["max_speed"] == 2.0
        assert overrides["dubbing"]["tts_workers"] == 3
        assert overrides["dubbing"]["rewrite_too_long"] is True
        assert overrides["dubbing"]["mix_original_audio"] is False
