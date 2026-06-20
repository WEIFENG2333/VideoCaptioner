"""AudioCapture 设备打开/下混契约（离线，mock sounddevice）。

锁住真机崩溃回归：部分设备（蓝牙耳机 / 聚合 / 虚拟 / 立体声麦克风）不接受以单声道打开
（PortAudio "Invalid number of channels"）。先试 1 声道，设备不收则回退到其原生声道数，
多声道时回调里取第一声道下混成 mono s16le。
"""

import types

import numpy as np
import pytest

from videocaptioner.core.realtime.audio import capture as audio_source
from videocaptioner.core.realtime.audio.capture import AudioCapture, AudioSourceError


class _FakeStream:
    def __init__(self, **kw):
        self.channels = kw["channels"]
        self.callback = kw["callback"]
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class _FakeSD:
    """只接受 accept 里那些声道数打开，其余抛错（模拟 PortAudio 声道校验）。"""

    def __init__(self, accept, max_channels=2):
        self._accept = set(accept)
        self._max_channels = max_channels
        self.default = types.SimpleNamespace(device=[3, 0])
        self.opened = []

    def InputStream(self, **kw):
        if kw["channels"] not in self._accept:
            raise RuntimeError(f"Invalid number of channels (ch={kw['channels']})")
        s = _FakeStream(**kw)
        self.opened.append(s)
        return s

    def query_devices(self, index=None):
        return {"max_input_channels": self._max_channels}


def _patch(monkeypatch, fake):
    monkeypatch.setattr(audio_source, "_sd", lambda: fake)


def test_mono_device_opens_with_one_channel(monkeypatch):
    fake = _FakeSD(accept={1})
    _patch(monkeypatch, fake)
    cap = AudioCapture(device_index=3)
    cap.start()
    assert cap._channels == 1
    assert [s.channels for s in fake.opened] == [1]  # 一次成功，不必回退


def test_falls_back_to_native_channels(monkeypatch):
    # 设备拒绝单声道、只接受 2 声道 → 回退到 2，且开流前的失败尝试不泄漏
    fake = _FakeSD(accept={2}, max_channels=2)
    _patch(monkeypatch, fake)
    cap = AudioCapture(device_index=3)
    cap.start()
    assert cap._channels == 2
    assert fake.opened[-1].channels == 2 and fake.opened[-1].started


def test_multichannel_callback_downmixes_by_mean(monkeypatch):
    fake = _FakeSD(accept={2})
    _patch(monkeypatch, fake)
    cap = AudioCapture(device_index=3)
    cap.start()
    indata = np.array([[10, 100], [20, 80], [30, 78]], dtype="int16")  # (frames, 2)
    cap._callback(indata, 3, None, None)
    pcm = cap.read(timeout=0.5)
    # 各声道均值（int32 累加防溢出，round 回 int16）：(10+100)/2=55, (20+80)/2=50, (30+78)/2=54
    assert pcm == np.array([[55], [50], [54]], dtype="int16").tobytes()


def test_all_channel_counts_fail_raises(monkeypatch):
    fake = _FakeSD(accept=set(), max_channels=0)  # 设备无效/无输入声道
    _patch(monkeypatch, fake)
    cap = AudioCapture(device_index=3)
    with pytest.raises(AudioSourceError):
        cap.start()
