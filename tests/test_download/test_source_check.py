"""下载源检查与网络环境（core.download.net / source_check）契约测试，不联网。"""

import yt_dlp

from videocaptioner.core.download.net import (
    friendly_download_error,
    inject_bilibili_buvid,
    is_bilibili_url,
)
from videocaptioner.core.download.source_check import (
    DOWNLOAD_SOURCES,
    check_download_source,
)


class TestFriendlyError:
    def test_bilibili_412_gets_specific_hint(self):
        message = friendly_download_error(
            "https://www.bilibili.com/video/BVx", "HTTP Error 412: Precondition Failed"
        )
        assert "风控" in message

    def test_non_bilibili_412_keeps_generic_hint(self):
        message = friendly_download_error("https://example.com/v", "HTTP Error 412")
        assert "登录态" in message

    def test_youtube_bot_check(self):
        message = friendly_download_error(
            "https://youtube.com/watch?v=x", "Sign in to confirm you're not a bot"
        )
        assert "登录" in message


class TestBilibiliHelpers:
    def test_is_bilibili_url(self):
        assert is_bilibili_url("https://www.bilibili.com/video/BV1x")
        assert is_bilibili_url("https://b23.tv/abc")
        assert not is_bilibili_url("https://www.youtube.com/watch?v=x")

    def test_inject_without_cookiejar_is_noop(self):
        inject_bilibili_buvid(object())  # 不应抛错、不应联网

    def test_inject_skips_when_buvid_present(self, monkeypatch):
        from http.cookiejar import Cookie, CookieJar

        jar = CookieJar()
        jar.set_cookie(
            Cookie(
                0, "buvid3", "x", None, False, ".bilibili.com", True, True,
                "/", True, False, None, False, None, None, {},
            )
        )

        class FakeYdl:
            cookiejar = jar

        def boom(*args, **kwargs):
            raise AssertionError("已有 buvid3 时不应再请求 spi 接口")

        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", boom
        )
        inject_bilibili_buvid(FakeYdl())


class TestSourceCheck:
    def test_sources_cover_youtube_and_bilibili(self):
        keys = [source.key for source in DOWNLOAD_SOURCES]
        assert keys == ["youtube", "bilibili"]
        for source in DOWNLOAD_SOURCES:
            assert source.probe_url.startswith("https://")
            assert source.fix_hint

    def test_success_returns_title(self, monkeypatch):
        class FakeYdl:
            def __init__(self, params):
                from http.cookiejar import CookieJar

                self.cookiejar = CookieJar()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False, process=True):
                return {"title": "Me at the zoo"}

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYdl)
        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", lambda **kw: {}
        )
        result = check_download_source(DOWNLOAD_SOURCES[0])
        assert result.success and result.detail == "Me at the zoo"

    def test_412_falls_back_to_browser_cookies_and_reports_usable(self, monkeypatch):
        """匿名被风控但浏览器登录态能解析 → 站点判定为可用（带说明）。"""

        class FakeYdl:
            def __init__(self, params):
                from http.cookiejar import CookieJar

                self.cookiejar = CookieJar()
                self.params = params

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False, process=True):
                if self.params.get("cookiesfrombrowser") is None:
                    raise RuntimeError("HTTP Error 412: Precondition Failed")
                return {"title": "官方 MV"}

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYdl)
        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", lambda **kw: {}
        )
        monkeypatch.setattr(
            "videocaptioner.core.download.net.detect_cookie_browsers", lambda: ["chrome"]
        )
        result = check_download_source(DOWNLOAD_SOURCES[1])
        assert result.success
        assert "官方 MV" in result.detail and "Chrome 登录态" in result.detail

    def test_unavailable_only_after_browser_fallback_also_fails(self, monkeypatch):
        """连浏览器登录态都被拒绝，才报不可用，且说明已尝试过兜底。"""

        class FailingYdl:
            def __init__(self, params):
                from http.cookiejar import CookieJar

                self.cookiejar = CookieJar()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False, process=True):
                raise RuntimeError("HTTP Error 412: Precondition Failed")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FailingYdl)
        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", lambda **kw: {}
        )
        monkeypatch.setattr(
            "videocaptioner.core.download.net.detect_cookie_browsers", lambda: ["chrome"]
        )
        result = check_download_source(DOWNLOAD_SOURCES[1])
        assert not result.success
        # 结论说明兜底已试（点名浏览器）且给出可行动的出路
        assert "Chrome" in result.detail
        assert "cookies.txt" in result.detail

    def test_no_browser_available_reports_friendly_412(self, monkeypatch):
        class FailingYdl:
            def __init__(self, params):
                from http.cookiejar import CookieJar

                self.cookiejar = CookieJar()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False, process=True):
                raise RuntimeError("HTTP Error 412: Precondition Failed")

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FailingYdl)
        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", lambda **kw: {}
        )
        monkeypatch.setattr(
            "videocaptioner.core.download.net.detect_cookie_browsers", lambda: []
        )
        result = check_download_source(DOWNLOAD_SOURCES[1])
        assert not result.success
        assert "风控" in result.detail and "cookies.txt" in result.detail
