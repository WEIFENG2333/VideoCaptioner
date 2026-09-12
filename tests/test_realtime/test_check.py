"""实时字幕「测试转录」核心检查（core.realtime.check.check_live_caption）契约。

锁住：抽 16k PCM → 喂后端 → 收到非空文本算通过；后端报错按错误返回；无字无错按
「结果为空」返回。用假后端 + 假 ffmpeg，不依赖 voxgate 二进制 / 网络，故可跨平台跑。
"""

import wave

import pytest

import videocaptioner.core.realtime.check as chk
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.realtime.events import TranscriptSegment


def _write_wav(path, seconds=0.3):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(chk.SAMPLE_RATE)
        wf.writeframes(b"\x00\x00" * int(chk.SAMPLE_RATE * seconds))


class _FakeBackend:
    """喂到 PCM 就吐一句累积文本；可配置成报错 / 沉默。"""

    def __init__(self, on_segment, on_error, text="hello world", err=None):
        self._on_segment = on_segment
        self._on_error = on_error
        self._text = text
        self._err = err
        self.stopped = False

    def start(self):
        if self._err:
            self._on_error(self._err)

    def feed(self, pcm16):
        if self._text and not self._err:
            self._on_segment(TranscriptSegment("s", self._text, False, False))

    def stop(self):
        self.stopped = True


@pytest.fixture()
def fast_audio(monkeypatch, tmp_path):
    """把 video2audio 换成写一段真 WAV；并把等待收紧，测试秒级返回。"""

    def fake_video2audio(_input, output="", **_kw):
        _write_wav(output)
        return True

    monkeypatch.setattr(chk, "video2audio", fake_video2audio)
    monkeypatch.setattr(chk, "_PACE_S", 0.0)
    monkeypatch.setattr(chk, "_GRACE_S", 0.3)
    monkeypatch.setattr(chk, "TEST_AUDIO_PATH", tmp_path / "src.mp3")
    (tmp_path / "src.mp3").write_bytes(b"fake-mp3")


def _patch_backend(monkeypatch, **kw):
    def fake_build_backend(_cfg, on_segment, on_state, on_error):
        return _FakeBackend(on_segment, on_error, **kw)

    monkeypatch.setattr(chk, "build_backend", fake_build_backend)


def test_success_returns_recognized_text(fast_audio, monkeypatch):
    _patch_backend(monkeypatch, text="What's the weather")
    res = chk.check_live_caption(LiveCaptionConfig(backend="voxgate"))
    assert res.success
    assert res.detail == "What's the weather"


def test_backend_error_returns_failure(fast_audio, monkeypatch):
    _patch_backend(monkeypatch, err="未找到 voxgate 可执行文件。")
    res = chk.check_live_caption(LiveCaptionConfig(backend="voxgate"))
    assert not res.success
    assert "voxgate" in res.detail


def test_silent_backend_reports_empty(fast_audio, monkeypatch):
    _patch_backend(monkeypatch, text="")
    res = chk.check_live_caption(LiveCaptionConfig(backend="voxgate"))
    assert not res.success
    assert "为空" in res.detail


def test_missing_audio_returns_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(chk, "TEST_AUDIO_PATH", tmp_path / "nope.mp3")
    res = chk.check_live_caption(LiveCaptionConfig(backend="voxgate"))
    assert not res.success
    assert "不存在" in res.detail
