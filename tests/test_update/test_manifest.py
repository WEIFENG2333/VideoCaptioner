"""更新 manifest 解析 / 版本比较 / 平台资产选择 / 拉取的纯逻辑测试。"""

import pytest

from videocaptioner.core.update import manifest
from videocaptioner.core.update.manifest import (
    UpdateAsset,
    UpdateInfo,
    fetch_update,
    is_newer,
    parse_version,
    select_asset,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.5.0", (1, 5, 0)),
        ("v2.0.1", (2, 0, 1)),
        ("2.0.0.post1.dev0+g123", (2, 0, 0)),
        ("1.5.0-rc1", (1, 5, 0)),
        ("", (0,)),
        ("dev", (0,)),
        ("0.0.0-dev", (0, 0, 0)),
    ],
)
def test_parse_version(value, expected):
    assert parse_version(value) == expected


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("1.5.1", "1.5.0", True),
        ("2.0.0", "1.9.9", True),
        ("1.5.0", "1.5.0", False),
        ("1.4.9", "1.5.0", False),
        ("v1.6.0", "1.5.0", True),
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


def test_select_asset_exact_arch(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    platforms = {"windows-x64": {"url": "w"}, "macos-arm64": {"url": "m"}}
    assert select_asset(platforms) == {"url": "w"}


def test_select_asset_macos_arm_falls_back_to_x64(monkeypatch):
    """Apple Silicon 无原生包时回落 x64（Rosetta 可跑）。"""
    monkeypatch.setattr(manifest, "current_platform", lambda: ("macos", "arm64"))
    platforms = {"macos-x64": {"url": "intel"}}
    assert select_asset(platforms) == {"url": "intel"}


def test_select_asset_missing_returns_none(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("linux", "x64"))
    assert select_asset({"windows-x64": {"url": "w"}}) is None


def test_update_info_urls_mirror_then_direct():
    info = UpdateInfo(
        version="2.0.0",
        notes="",
        mandatory=False,
        asset=UpdateAsset(url="https://github.com/x/y.zip", sha256="", size=0, kind="app-zip"),
    )
    urls = info.urls
    # 镜像在前、直连兜底在后
    assert urls[-1] == "https://github.com/x/y.zip"
    assert all(u.endswith("https://github.com/x/y.zip") for u in urls)
    assert len(urls) >= 2


class _FakeResponse:
    def __init__(self, payload, *, status=200):
        self._payload = payload
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            import requests

            raise requests.HTTPError(f"status {self._status}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    """按 URL 顺序返回预设响应；记录访问过的 URL。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.seen = []

    def get(self, url, **kwargs):
        self.seen.append(url)
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _manifest(version="2.0.0", **extra):
    data = {
        "version": version,
        "notes": "新功能",
        "platforms": {
            "windows-x64": {"url": "https://github.com/x/win.zip", "sha256": "ab", "size": 10, "kind": "onedir-zip"},
            "macos-arm64": {"url": "https://github.com/x/mac.zip", "sha256": "cd", "size": 20, "kind": "app-zip"},
        },
    }
    data.update(extra)
    return data


def test_fetch_update_returns_info_when_newer(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    session = _FakeSession([_FakeResponse(_manifest("2.0.0"))])
    info = fetch_update("1.0.0", ("https://host/latest.json",), session=session)
    assert info is not None
    assert info.version == "2.0.0"
    assert info.asset.url == "https://github.com/x/win.zip"
    assert info.asset.sha256 == "ab"
    assert info.mandatory is False


def test_fetch_update_none_when_not_newer(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    session = _FakeSession([_FakeResponse(_manifest("1.0.0"))])
    assert fetch_update("1.0.0", ("https://host/latest.json",), session=session) is None


def test_fetch_update_none_when_no_asset_for_platform(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("linux", "x64"))
    session = _FakeSession([_FakeResponse(_manifest("9.9.9"))])
    assert fetch_update("1.0.0", ("https://host/latest.json",), session=session) is None


def test_fetch_update_min_supported_forces_mandatory(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    session = _FakeSession([_FakeResponse(_manifest("2.0.0", min_supported="1.5.0"))])
    info = fetch_update("1.0.0", ("https://host/latest.json",), session=session)
    assert info is not None and info.mandatory is True


def test_fetch_update_unreachable_returns_none(monkeypatch):
    import requests

    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    # 单 URL 会自动展开镜像兜底，给足等量的失败响应
    session = _FakeSession([requests.ConnectionError("boom")] * 5)
    assert fetch_update("1.0.0", ("https://host/latest.json",), session=session) is None
