"""net.py 浏览器登录态兜底阶梯的契约测试（纯函数，不联网、不依赖 yt-dlp）。"""

import pytest

import videocaptioner.core.download.net as net


class TestCookieErrorDetection:
    def test_known_login_failures(self):
        assert net.looks_like_cookie_error("BiliBili: HTTP Error 412 Precondition Failed")
        assert net.looks_like_cookie_error("Sign in to confirm you're not a bot")
        assert not net.looks_like_cookie_error("HTTP Error 404: File not found")


class TestDetectBrowsers:
    def test_detects_existing_profiles(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            net,
            "_BROWSER_PROFILES",
            {
                "chrome": (str(tmp_path / "chrome"),),
                "firefox": (str(tmp_path / "nope"),),
            },
        )
        (tmp_path / "chrome").mkdir()
        assert net.detect_cookie_browsers() == ["chrome"]

    def test_last_good_browser_promoted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            net,
            "_BROWSER_PROFILES",
            {"chrome": (str(tmp_path),), "edge": (str(tmp_path),)},
        )
        monkeypatch.setattr(net, "_last_good_browser", "edge")
        assert net.detect_cookie_browsers() == ["edge", "chrome"]


class TestFallbackLadder:
    """run_with_browser_cookie_fallback：下载与诊断共用的回退原语。"""

    def test_anonymous_success_short_circuits(self):
        result, used = net.run_with_browser_cookie_fallback(
            "https://example.com", lambda browser: f"ok:{browser}"
        )
        assert result == "ok:None" and used is None

    def test_non_cookie_error_fails_fast_with_friendly_message(self, monkeypatch):
        monkeypatch.setattr(net, "detect_cookie_browsers", lambda: ["chrome"])

        def attempt(browser):
            raise RuntimeError("HTTP Error 404: File not found")

        with pytest.raises(RuntimeError, match="不存在"):
            net.run_with_browser_cookie_fallback("https://example.com/v", attempt)

    def test_cookie_error_retries_with_browser_and_remembers_it(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(net, "detect_cookie_browsers", lambda: ["chrome"])
        monkeypatch.setattr(net, "cookies_file", lambda: tmp_path / "none.txt")
        monkeypatch.setattr(net, "_last_good_browser", None)
        attempts = []

        def attempt(browser):
            attempts.append(browser)
            if browser is None:
                raise RuntimeError("HTTP Error 412 Precondition Failed")
            return "title"

        result, used = net.run_with_browser_cookie_fallback(
            "https://www.bilibili.com/video/BVx", attempt
        )
        assert attempts == [None, "chrome"]
        assert result == "title" and used == "Chrome"
        assert net._last_good_browser == "chrome"

    def test_all_browsers_fail_raises_actionable_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(net, "detect_cookie_browsers", lambda: ["chrome", "edge"])
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        monkeypatch.setattr(net, "cookies_file", lambda: cookies)
        notified = []

        def attempt(browser):
            raise RuntimeError("HTTP Error 412 Precondition Failed")

        with pytest.raises(RuntimeError) as exc:
            net.run_with_browser_cookie_fallback(
                "https://www.bilibili.com/video/BVx",
                attempt,
                on_attempt=notified.append,
            )
        message = str(exc.value)
        assert "已用 Chrome、Edge 登录态重试仍被拒绝" in message
        assert "已失效" in message  # 提示清理失效的 cookies.txt
        assert notified == ["Chrome", "Edge"]

    def test_headline_uses_original_error_not_last_attempt(self, tmp_path, monkeypatch):
        """兜底自身的失败（如 Safari TCC 权限）不能反客为主成为报错标题。"""
        monkeypatch.setattr(net, "detect_cookie_browsers", lambda: ["chrome", "safari"])
        monkeypatch.setattr(net, "cookies_file", lambda: tmp_path / "none.txt")

        def attempt(browser):
            if browser == "safari":
                raise RuntimeError(
                    "[Errno 1] Operation not permitted: "
                    "'/Users/x/Library/Containers/com.apple.Safari/Data'"
                )
            raise RuntimeError("Sign in to confirm you're not a bot")

        with pytest.raises(RuntimeError) as exc:
            net.run_with_browser_cookie_fallback("https://youtube.com/watch?v=x", attempt)
        message = str(exc.value)
        # 标题来自最初的站点报错（登录验证），而不是 Safari 的本机权限错误
        assert message.startswith("YouTube 判定当前网络异常")
        assert "Operation not permitted" not in message
        # 权限问题与"被网站拒绝"分开表述；具体措辞按平台对症（macOS 给隐私放行指引）
        assert "已用 Chrome 登录态重试仍被拒绝" in message
        import platform as _platform

        if _platform.system() == "Darwin":
            assert "Safari 被系统隐私保护拦截" in message
            assert "完全磁盘访问权限" in message
        else:
            assert "Safari 登录态无法读取" in message

    def test_ansi_codes_stripped_from_messages(self):
        friendly = net.friendly_download_error(
            "https://example.com/v",
            "\x1b[0;31mERROR:\x1b[0m something exploded badly",
        )
        assert "\x1b" not in friendly and "[0;31m" not in friendly
        assert net.strip_ansi("\x1b[0;31mERROR:\x1b[0m boom") == "ERROR: boom"

    def test_cancel_check_called_between_attempts(self, monkeypatch):
        monkeypatch.setattr(net, "detect_cookie_browsers", lambda: ["chrome"])

        class Cancelled(Exception):
            pass

        def cancel_check():
            raise Cancelled

        def attempt(browser):
            raise RuntimeError("HTTP Error 412")

        # 取消异常必须原样穿透（不被包装成下载失败）
        with pytest.raises(Cancelled):
            net.run_with_browser_cookie_fallback(
                "https://example.com", attempt, cancel_check=cancel_check
            )
