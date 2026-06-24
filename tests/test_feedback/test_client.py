"""FeedbackClient：multipart 组装 + 头部 + 响应解析（用假 session，不联网）。"""

import json

import pytest
import requests

from videocaptioner.core.feedback import FeedbackAttachment, FeedbackClient, FeedbackReport
from videocaptioner.core.feedback import client as client_mod


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.captured = {}

    def post(self, url, **kwargs):
        self.captured = {"url": url, **kwargs}
        if self._exc is not None:
            raise self._exc
        return self._resp


@pytest.fixture(autouse=True)
def _no_proxy_no_real_config(monkeypatch):
    monkeypatch.setattr(client_mod, "system_proxy", lambda: None)
    monkeypatch.setattr(client_mod, "get_or_create_client_id", lambda: "cid-test")


def _report(**over):
    base = dict(
        category="bug",
        message="导出报错",
        contact="a@b.c",
        attachments=[FeedbackAttachment("s.png", b"PNGDATA", "image/png")],
        diagnostics={"app_version": "2.1.0", "platform": "windows-x64"},
    )
    base.update(over)
    return FeedbackReport(**base)


def _parse_parts(captured):
    """从 requests files=parts 还原 (字段名→值, 图片列表)。字段 part 为 (name, (None, value))。"""
    assert "data" not in captured  # 一切走 multipart，无 urlencoded data
    fields, images = {}, []
    for name, spec in captured["files"]:
        if name == "files":
            images.append(spec)  # (filename, data, mime)
        else:
            fields[name] = spec[1]
    return fields, images


def test_submit_success_builds_multipart():
    sess = _Session(resp=_Resp(200, {"ok": True, "id": "FB-1"}))
    result = FeedbackClient("https://host/api", session=sess).submit(_report())
    assert result.ok and result.id == "FB-1"
    cap = sess.captured
    assert cap["url"] == "https://host/api"
    headers = cap["headers"]
    assert headers["X-App-Version"] and headers["X-App-Platform"]
    assert headers["User-Agent"].startswith("VideoCaptioner/")
    fields, images = _parse_parts(cap)
    assert fields["category"] == "bug"
    assert fields["message"] == "导出报错"
    assert fields["client_id"] == "cid-test"
    assert fields["request_id"]  # 每次新 UUID
    assert fields["contact"] == "a@b.c"
    assert json.loads(fields["diagnostics"])["platform"] == "windows-x64"
    assert images[0][0] == "s.png" and images[0][2] == "image/png"


def test_no_image_still_multipart():
    # 关键回归：无截图也必须是 multipart（字段作为 part 发送），否则后端拒 invalid_request
    sess = _Session(resp=_Resp(200, {"ok": True, "id": "FB-2"}))
    FeedbackClient("https://host/api", session=sess).submit(
        _report(contact="", attachments=[], diagnostics={})
    )
    fields, images = _parse_parts(sess.captured)
    assert sess.captured["files"]  # 始终走 files（multipart），不退化成 data
    assert images == []
    assert "contact" not in fields  # 空联系方式省略
    assert "diagnostics" not in fields
    assert fields["category"] == "bug" and fields["message"]


def test_error_response_maps_code():
    sess = _Session(resp=_Resp(400, {"ok": False, "code": "invalid_request", "error": "问题描述需为 1-5000 字符"}))
    result = FeedbackClient("https://host/api", session=sess).submit(_report())
    assert not result.ok and result.code == "invalid_request"
    assert "1-5000" in result.error


def test_http_status_without_code_falls_back():
    sess = _Session(resp=_Resp(413, None))  # 非 JSON 响应体
    result = FeedbackClient("https://host/api", session=sess).submit(_report())
    assert not result.ok and result.code == "too_large"


def test_network_error_returns_network_code():
    sess = _Session(exc=requests.ConnectionError("boom"))
    result = FeedbackClient("https://host/api", session=sess).submit(_report())
    assert not result.ok and result.code == "network"


def test_invalid_report_raises_before_post():
    sess = _Session(resp=_Resp(200, {"ok": True, "id": "x"}))
    from videocaptioner.core.feedback import FeedbackValidationError

    with pytest.raises(FeedbackValidationError):
        FeedbackClient("https://host/api", session=sess).submit(_report(message=""))
    assert sess.captured == {}  # 校验失败不发请求
