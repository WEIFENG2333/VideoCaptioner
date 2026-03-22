"""Tests for CLI config system — TOML read/write, merging, type safety."""

import pytest

from videocaptioner.cli.config import (
    DEFAULTS,
    _deep_merge,
    _get_nested,
    _parse_value,
    _set_nested,
    _toml_value,
    build_config,
    load_config_file,
    save_config_value,
)


class TestDeepMerge:
    def test_flat_override(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 3, "c": 4}}
        result = _deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 3, "c": 4}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        assert base == {"a": 1}

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}


class TestNestedAccess:
    def test_get_nested(self):
        d = {"a": {"b": {"c": 42}}}
        assert _get_nested(d, "a.b.c") == 42

    def test_get_nested_missing(self):
        assert _get_nested({"a": 1}, "b", "default") == "default"

    def test_get_nested_deep_missing(self):
        assert _get_nested({"a": {"b": 1}}, "a.c.d", None) is None

    def test_set_nested(self):
        d: dict = {}
        _set_nested(d, "a.b.c", 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_set_nested_overwrite(self):
        d = {"a": {"b": 1}}
        _set_nested(d, "a.b", 2)
        assert d == {"a": {"b": 2}}


class TestParseValue:
    def test_bool_true(self):
        assert _parse_value("true", "subtitle.optimize") is True
        assert _parse_value("yes", "subtitle.optimize") is True
        assert _parse_value("1", "subtitle.optimize") is True

    def test_bool_false(self):
        assert _parse_value("false", "subtitle.optimize") is False
        assert _parse_value("no", "subtitle.optimize") is False
        assert _parse_value("0", "subtitle.optimize") is False

    def test_bool_invalid(self):
        with pytest.raises(ValueError, match="Expected boolean"):
            _parse_value("maybe", "subtitle.optimize")

    def test_int(self):
        assert _parse_value("8", "subtitle.thread_num") == 8
        assert isinstance(_parse_value("8", "subtitle.thread_num"), int)

    def test_int_invalid(self):
        with pytest.raises(ValueError, match="Expected integer"):
            _parse_value("abc", "subtitle.thread_num")

    def test_string(self):
        assert _parse_value("gpt-4o", "llm.model") == "gpt-4o"

    def test_unknown_key_stays_string(self):
        # Key not in DEFAULTS → stays string
        assert _parse_value("anything", "unknown.key") == "anything"


class TestTomlValue:
    def test_bool(self):
        assert _toml_value(True) == "true"
        assert _toml_value(False) == "false"

    def test_int(self):
        assert _toml_value(42) == "42"

    def test_float(self):
        assert _toml_value(0.5) == "0.5"

    def test_string(self):
        assert _toml_value("hello") == '"hello"'

    def test_string_with_quotes(self):
        assert _toml_value('say "hi"') == '"say \\"hi\\""'

    def test_string_with_newline(self):
        assert _toml_value("line1\nline2") == '"line1\\nline2"'


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


class TestBuildConfig:
    def test_defaults_only(self):
        config = build_config(config_path=None)
        assert config["llm"]["model"] == DEFAULTS["llm"]["model"]

    def test_cli_overrides(self):
        config = build_config(cli_overrides={"llm": {"model": "custom"}})
        assert config["llm"]["model"] == "custom"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("VIDEOCAPTIONER_LLM_MODEL", "env-model")
        config = build_config()
        assert config["llm"]["model"] == "env-model"

    def test_priority_cli_over_env(self, monkeypatch):
        monkeypatch.setenv("VIDEOCAPTIONER_LLM_MODEL", "env-model")
        config = build_config(cli_overrides={"llm": {"model": "cli-model"}})
        assert config["llm"]["model"] == "cli-model"
