"""Bing 免费翻译器的解析与站点回退测试（mock 网络）。

回归防护：Bing 无公开 API，靠抓 bing.com/translator 页面取 IG/IID/token/key 再 POST
ttranslatev3。中国区 www.bing.com 会返回空、需回退 cn.bing.com。这里锁住页面解析正则
与站点自动择优逻辑，避免上游/区域变动悄悄把默认免费翻译打挂。
"""

import json

import pytest

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate import bing_translator as bt
from videocaptioner.core.translate.types import TargetLanguage

_PAGE_HTML = (
    'window.stuff;IG:"IG123456";more '
    '<div data-iid="translator.5023"></div>'
    "var params_AbusePreventionHelper = [1700000000000,\"TOKEN_ABC\",3600000];"
)


class _FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.text)


class _FakeSession:
    """www.bing.com POST 返回空（模拟中国区），cn.bing.com 返回正常 JSON。"""

    def __init__(self):
        self.posted_hosts = []

    def get(self, url, **kwargs):
        return _FakeResp(_PAGE_HTML)

    def post(self, url, data=None, **kwargs):
        self.posted_hosts.append(url)
        if "www.bing.com" in url:
            return _FakeResp("")  # 空响应 → 触发回退
        return _FakeResp(
            json.dumps([{"translations": [{"text": "你好世界", "to": "zh-Hans"}]}])
        )


@pytest.fixture
def fake_session(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(bt.requests, "Session", lambda: session)
    return session


def test_falls_back_to_cn_when_www_empty(fake_session):
    tr = bt.BingTranslator(
        thread_num=1,
        batch_num=5,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        update_callback=None,
    )
    # www 返回空 → 锁定 cn.bing.com
    assert tr._bing.host == "cn.bing.com"
    # 凭证解析正确
    assert tr._bing.ig == "IG123456"
    assert tr._bing.iid == "translator.5023"
    assert tr._bing.token == "TOKEN_ABC"
    assert tr._bing.key == "1700000000000"


def test_translate_chunk_fills_translation(fake_session):
    tr = bt.BingTranslator(
        thread_num=1,
        batch_num=5,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        update_callback=None,
    )
    chunk = [SubtitleProcessData(index=1, original_text="hello world", translated_text="")]
    out = tr._translate_chunk(chunk)
    assert out[0].translated_text == "你好世界"
