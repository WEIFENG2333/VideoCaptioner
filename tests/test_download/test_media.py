"""core/download/media.py 下载引擎契约测试（不联网，FakeYoutubeDL 替身）。

GUI 线程与 CLI download 都是本引擎的薄壳，这里覆盖的行为对两端生效。
"""

from pathlib import Path

import pytest

import videocaptioner.core.download.media as media
from videocaptioner.core.download.media import (
    MediaDownloader,
    media_summary,
    resolve_downloaded_subtitle,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_forbidden_chars(self):
        assert sanitize_filename('a<b>:c"/d') == "a_b__c__d"

    def test_windows_reserved(self):
        assert sanitize_filename("CON.mp4") == "CON.mp4_"

    def test_empty_fallback(self):
        assert sanitize_filename("  ..") == "media"

    def test_strips_all_control_chars(self):
        # 旧正则 [\0-\31] 把 \31 当八进制(=chr25)，漏清 0x1a-0x1f；新版覆盖整段 0x00-0x1f
        name = "a\x00b\x19c\x1ad\x1fe"
        assert sanitize_filename(name) == "abcde"


class TestMediaSummary:
    def test_fields(self):
        info = {
            "title": "标题",
            "uploader": "UP主",
            "duration": 3725,
            "extractor_key": "BiliBili",
        }
        assert media_summary(info) == {
            "title": "标题",
            "uploader": "UP主",
            "duration": "1:02:05",
            "site": "BiliBili",
        }
        assert media_summary({"title": "x", "extractor_key": "Generic"}) == {"title": "x"}


class TestResolveSubtitle:
    def test_danmaku_and_other_videos_ignored(self, tmp_path):
        """字幕 sidecar 按视频名前缀匹配；弹幕 xml 与别的视频的字幕都不算。"""
        video = tmp_path / "BV Test.mp4"
        video.write_bytes(b"v")
        (tmp_path / "BV Test.danmaku.xml").write_text("<xml/>")
        (tmp_path / "Other Video.zh.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhi\n"
        )
        assert resolve_downloaded_subtitle({}, video, None) is None

        (tmp_path / "BV Test.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        resolved = resolve_downloaded_subtitle({}, video, None)
        assert resolved and resolved.endswith("BV Test.zh.srt")


def _fake_ydl(behaviors: dict):
    """构造 FakeYoutubeDL 类；behaviors 控制 extract_info/process_info 行为。"""

    class FakeYoutubeDL:
        instances: list = []

        def __init__(self, params):
            self.params = params
            FakeYoutubeDL.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return behaviors["extract_info"](self, url)

        def process_info(self, info):
            home = Path(self.params["paths"]["home"])
            home.mkdir(parents=True, exist_ok=True)
            (home / f"{info['title']}.mp4").write_bytes(b"video")

        def prepare_filename(self, info):
            return str(Path(self.params["paths"]["home"]) / f"{info['title']}.mp4")

    return FakeYoutubeDL


class TestSiteFallbacks:
    def test_ted_403_retries_with_hls(self, tmp_path, monkeypatch):
        used_formats: list[str] = []

        def extract_info(ydl, url):
            used_formats.append(ydl.params["format"])
            if "[ext=mp4]" in ydl.params["format"]:
                raise Exception("HTTP Error 403: Forbidden")
            return {"title": "TED Test", "ext": "mp4"}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        video, subtitle = MediaDownloader(
            "https://www.ted.com/talks/example", str(tmp_path)
        ).run()
        assert Path(video).exists() and subtitle is None
        assert used_formats == [media._DEFAULT_FORMAT, media._HLS_FORMAT]

    def test_youtube_403_falls_back_to_android_client(self, tmp_path, monkeypatch):
        clients: list = []

        def extract_info(ydl, url):
            clients.append(
                (ydl.params.get("extractor_args") or {}).get("youtube", {}).get("player_client")
            )
            if ydl.params.get("extractor_args") is None:
                raise Exception("unable to download video data: HTTP Error 403: Forbidden")
            return {"title": "YT", "ext": "mp4"}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        video, _sub = MediaDownloader(
            "https://www.youtube.com/watch?v=x", str(tmp_path)
        ).run()
        assert Path(video).exists()
        assert clients == [None, ["android", "web_safari"]]

    def test_412_falls_back_to_browser_cookies(self, tmp_path, monkeypatch):
        """登录态错误走 net 阶梯换浏览器 cookies 重试（与诊断同一条链路）。"""
        attempts: list = []

        def extract_info(ydl, url):
            attempts.append(ydl.params.get("cookiesfrombrowser"))
            if ydl.params.get("cookiesfrombrowser") is None:
                raise Exception("BiliBili: HTTP Error 412 Precondition Failed")
            return {"title": "BV Test", "ext": "mp4"}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        monkeypatch.setattr(
            "videocaptioner.core.download.net.detect_cookie_browsers", lambda: ["chrome"]
        )
        monkeypatch.setattr(
            "videocaptioner.core.download.net.cookies_file", lambda: tmp_path / "no.txt"
        )
        monkeypatch.setattr(
            "videocaptioner.core.download.net.fetch_bilibili_buvid", lambda **kw: {}
        )
        video, _sub = MediaDownloader(
            "https://www.bilibili.com/video/BVx", str(tmp_path)
        ).run()
        assert attempts == [None, ("chrome",)]
        assert Path(video).exists()


class TestGuards:
    def test_options_use_noplaylist(self, tmp_path, monkeypatch):
        """多分 P / 合集链接必须只取当前一集。"""
        captured = {}

        def extract_info(ydl, url):
            captured.update(ydl.params)
            return {"title": "T", "ext": "mp4"}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        MediaDownloader("https://example.com/v", str(tmp_path)).run()
        assert captured.get("noplaylist") is True

    def test_live_stream_rejected(self, tmp_path, monkeypatch):
        def extract_info(ydl, url):
            return {"title": "Live", "is_live": True}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        with pytest.raises(RuntimeError, match="直播"):
            MediaDownloader("https://example.com/live", str(tmp_path)).run()

    def test_probe_only_requires_no_target_dir_and_downloads_nothing(self, monkeypatch):
        probed = []

        def extract_info(ydl, url):
            return {"title": "T", "ext": "mp4", "formats": [], "subtitles": {}}

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", _fake_ydl({"extract_info": extract_info}))
        video, subtitle = MediaDownloader(
            "https://example.com/v", probe_only=True, on_probed=probed.append
        ).run()
        assert video is None and subtitle is None
        assert probed and probed[0]["title"] == "T"

    def test_download_requires_target_dir(self):
        with pytest.raises(ValueError):
            MediaDownloader("https://example.com/v")
