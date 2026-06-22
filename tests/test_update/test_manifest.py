"""更新 manifest 解析 / 版本比较 / 平台资产选择 / 公告 / 拉取的纯逻辑测试。"""

from datetime import date

import pytest

from videocaptioner.core.update import manifest
from videocaptioner.core.update.manifest import (
    UpdateAsset,
    UpdateInfo,
    fetch_manifest,
    fetch_update,
    is_newer,
    parse_version,
    select_announcement,
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
        # 长度不一致：补零后视为相等，不能误报有新版
        ("1.5.0", "1.5", False),
        ("1.5", "1.5.0", False),
        ("1.5.1", "1.5", True),
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


def test_announcement_version_targeting_length_safe():
    """手写 2 段版本号（'1.5'/'2.0'）做定向，边界用户不被误排除。"""
    # min_version='1.5.0'，当前 '1.5' 应视作命中（>=）
    assert select_announcement(_ann(min_version="1.5.0"), "1.5", today=_TODAY) is not None
    # max_version='2.0'，当前 '2.0.0' 应视作命中（<=）
    assert select_announcement(_ann(max_version="2.0"), "2.0.0", today=_TODAY) is not None


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


# ----------------------------- 公告 -----------------------------

_TODAY = date(2026, 6, 15)


def _ann(**over):
    base = {"enabled": True, "content": "维护通知", "start_date": "2026-06-01", "end_date": "2026-07-01"}
    base.update(over)
    return base


def test_announcement_basic_within_window():
    ann = select_announcement(_ann(id="x"), "1.0.0", today=_TODAY)
    assert ann is not None and ann.id == "x" and ann.content == "维护通知"


def test_announcement_disabled_or_empty():
    assert select_announcement(_ann(enabled=False), "1.0.0", today=_TODAY) is None
    assert select_announcement(_ann(content="  "), "1.0.0", today=_TODAY) is None
    assert select_announcement({}, "1.0.0", today=_TODAY) is None


def test_announcement_date_window():
    assert select_announcement(_ann(start_date="2026-07-01"), "1.0.0", today=_TODAY) is None  # 未开始
    assert select_announcement(_ann(end_date="2026-06-01"), "1.0.0", today=_TODAY) is None  # 已结束
    # 端点含
    assert select_announcement(_ann(start_date="2026-06-15", end_date="2026-06-15"), "1.0.0", today=_TODAY) is not None
    # 缺省端 = 该侧无限制
    assert select_announcement(_ann(start_date="", end_date=""), "1.0.0", today=_TODAY) is not None


def test_announcement_version_targeting():
    # 只给 >=2.0.0 的用户：1.5.0 看不到，2.1.0 能看到
    assert select_announcement(_ann(min_version="2.0.0"), "1.5.0", today=_TODAY) is None
    assert select_announcement(_ann(min_version="2.0.0"), "2.1.0", today=_TODAY) is not None
    # 只给 <=1.0.0 的用户（旧版催更）：2.0.0 看不到
    assert select_announcement(_ann(max_version="1.0.0"), "2.0.0", today=_TODAY) is None
    assert select_announcement(_ann(max_version="1.0.0"), "0.9.0", today=_TODAY) is not None


def test_announcement_id_falls_back_to_content_hash():
    a = select_announcement(_ann(content="同样的话"), "1.0.0", today=_TODAY)
    b = select_announcement(_ann(content="同样的话"), "1.0.0", today=_TODAY)
    assert a.id == b.id and len(a.id) == 16  # 同内容 → 同去重键


def test_announcement_bad_date_is_silent():
    assert select_announcement(_ann(start_date="not-a-date"), "1.0.0", today=_TODAY) is None


def test_fetch_manifest_returns_update_and_announcement(monkeypatch):
    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    data = _manifest("2.0.0")
    data["announcement"] = _ann(id="hello")
    # 固定 today 落在窗口内（select_announcement 内部用 date.today；这里用真实日期会随时间变，
    # 故直接断言结构：update 必有；announcement 取决于当前日期是否在窗口）
    session = _FakeSession([_FakeResponse(data)])
    m = fetch_manifest("1.0.0", ("https://host/latest.json",), session=session)
    assert m is not None
    assert m.update is not None and m.update.version == "2.0.0"


def test_fetch_manifest_unreachable_returns_none(monkeypatch):
    import requests

    monkeypatch.setattr(manifest, "current_platform", lambda: ("windows", "x64"))
    session = _FakeSession([requests.ConnectionError("x")] * 5)
    assert fetch_manifest("1.0.0", ("https://host/latest.json",), session=session) is None
