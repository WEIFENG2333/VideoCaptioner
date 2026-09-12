"""更新检查客户端：解析后端 /api/update/check 响应（确定性单测，不打网络）。

真机联调（真实后端）见手动验证；这里只锁解析、容错、渠道判定、镜像兜底逻辑。
"""

import os

import pytest

from videocaptioner.core.download.downloader import gh_mirror_urls
from videocaptioner.core.update.client import (
    Announcement,
    UpdateInfo,
    app_channel,
    check_update,
)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status
        self.captured = {}

    def get(self, url, headers=None, timeout=None):
        self.captured["url"] = url
        self.captured["headers"] = headers or {}
        return _Resp(self._payload, self._status)


def _check(payload):
    sess = _Session(payload)
    return check_update("https://x/api/update/check", session=sess), sess


def test_parses_full_response():
    res, _ = _check(
        {
            "block": "此版本已停用",
            "update": {
                "version": "2.3.0",
                "notes": "修复…",
                "url": "https://github.com/x/y.zip",
                "sha256": "abc",
                "size": 123,
            },
            "announcement": {"id": "a1", "title": "标题", "content": "正文"},
        }
    )
    assert res.block == "此版本已停用"
    assert isinstance(res.update, UpdateInfo) and res.update.version == "2.3.0"
    assert res.update.size == 123 and res.update.sha256 == "abc"
    assert isinstance(res.announcement, Announcement) and res.announcement.id == "a1"
    # 镜像兜底：加速镜像在前，GitHub 直连在末位
    assert res.update.urls == gh_mirror_urls("https://github.com/x/y.zip")
    assert res.update.urls[-1] == "https://github.com/x/y.zip"


def test_all_null():
    res, _ = _check({"block": None, "update": None, "announcement": None})
    assert res.block is None and res.update is None and res.announcement is None


def test_sends_required_headers():
    _, sess = _check({"block": None, "update": None, "announcement": None})
    h = sess.captured["headers"]
    for key in ("X-App-Version", "X-App-Platform", "X-App-Channel", "X-Client-Id", "User-Agent"):
        assert h.get(key)
    assert h["X-App-Channel"] in ("desktop", "dev", "pip")


def test_blank_block_is_none():
    res, _ = _check({"block": "   ", "update": None, "announcement": None})
    assert res.block is None  # 空白字符串视为未封禁


def test_update_missing_url_dropped():
    res, _ = _check({"update": {"version": "2.3.0"}})  # 缺 url → 不冒进
    assert res.update is None


def test_update_bad_size_degrades_to_zero():
    res, _ = _check({"update": {"version": "2.3.0", "url": "https://x/y.zip", "size": "oops"}})
    assert res.update is not None and res.update.size == 0


def test_announcement_without_id_dropped():
    res, _ = _check({"announcement": {"content": "无 id 无法去重"}})
    assert res.announcement is None  # 无 id 不弹（没法去重）


def test_error_response_returns_none():
    res, _ = _check({"ok": False, "code": "invalid_request", "error": "缺少 X-App-Version"})
    assert res is None


def test_non_dict_response_returns_none():
    res, _ = _check(["not", "a", "dict"])
    assert res is None


def test_network_error_returns_none():
    import requests

    class _BoomSession:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    res = check_update("https://x", session=_BoomSession())
    assert res is None  # 失败静默，不抛给调用方


def test_app_channel_value():
    # 源码/editable 运行 = dev；本仓库测试环境包不在 site-packages
    assert app_channel() in ("desktop", "dev", "pip")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_UPDATE_CHECK_LIVE") != "1",
    reason="真实后端联调；设 RUN_UPDATE_CHECK_LIVE=1 运行。",
)
def test_live_backend():
    from videocaptioner.config import UPDATE_CHECK_URL

    res = check_update(UPDATE_CHECK_URL, timeout=20)
    assert res is not None  # 后端可达且返回合法 JSON
