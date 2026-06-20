"""通用调试开关 VC_DEBUG（core/utils/debug.debug_enabled）。"""

import pytest

from videocaptioner.core.utils.debug import debug_enabled


def test_unset_is_off(monkeypatch):
    monkeypatch.delenv("VC_DEBUG", raising=False)
    assert debug_enabled() is False
    assert debug_enabled("live") is False


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "OFF", "False"])
def test_off_values_disable(monkeypatch, val):
    monkeypatch.setenv("VC_DEBUG", val)
    assert debug_enabled() is False
    assert debug_enabled("live") is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "all", "ALL", "True"])
def test_all_values_enable_everything(monkeypatch, val):
    monkeypatch.setenv("VC_DEBUG", val)
    assert debug_enabled() is True
    assert debug_enabled("live") is True
    assert debug_enabled("download") is True


def test_subsystem_filter(monkeypatch):
    monkeypatch.setenv("VC_DEBUG", "live")
    assert debug_enabled() is True             # 总开关：开着
    assert debug_enabled("live") is True        # 命中
    assert debug_enabled("download") is False   # 未列出 → 不开


def test_multi_subsystem_with_spaces(monkeypatch):
    monkeypatch.setenv("VC_DEBUG", "download, live")  # 逗号分隔、含空格
    assert debug_enabled("live") is True
    assert debug_enabled("download") is True
    assert debug_enabled("other") is False
