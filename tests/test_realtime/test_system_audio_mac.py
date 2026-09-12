"""macOS 原生系统声音采集（MacSystemAudioCapture）契约：与 helper 子进程的 stdio 协议。

用「假 helper」脚本替身验证启动握手/读 PCM/EOF 停止/权限错误，不依赖真实 ScreenCaptureKit，
故跨平台可跑（真机 SCK 验证另行人工）。
"""

import os
import sys
import time

import pytest

import videocaptioner.core.realtime.audio.system_mac as sam
from videocaptioner.core.realtime.audio.capture import AudioSourceError
from videocaptioner.core.realtime.audio.system_mac import (
    MacSystemAudioCapture,
    MacSystemAudioPermissionError,
    find_macsysaudio_binary,
)

_HAPPY = """import sys, time
sys.stderr.write("STARTED\\n"); sys.stderr.flush()
end = time.time() + 2.0
while time.time() < end:
    sys.stdout.buffer.write(b"\\x01\\x02" * 800)  # 1600B ≈ 50ms @16k/mono/s16le
    sys.stdout.buffer.flush()
    time.sleep(0.05)
sys.stdin.read()  # 等父进程关 stdin（EOF）
"""

_PERMISSION = """import sys
sys.stderr.write("PERMISSION: user declined screen recording\\n"); sys.stderr.flush()
sys.exit(2)
"""


def _fake(tmp_path, name, body):
    # venv 路径含空格 → 不能用 #!<python> shebang（内核按空格切断解释器路径）。改用 /bin/sh
    # 启动器把带空格的 python 路径加引号 exec。
    impl = tmp_path / (name + "_impl.py")
    impl.write_text(body)
    launcher = tmp_path / name
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}"\n')
    launcher.chmod(0o755)
    return str(launcher)


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(sam, "find_macsysaudio_binary", lambda *a, **k: None)
    with pytest.raises(AudioSourceError):
        MacSystemAudioCapture().start()


@pytest.mark.skipif(sys.platform == "win32", reason="假 helper 是 /bin/sh 脚本，Windows 无法 exec")
def test_permission_denied_raises_friendly(tmp_path):
    cap = MacSystemAudioCapture(binary=_fake(tmp_path, "perm", _PERMISSION))
    with pytest.raises(MacSystemAudioPermissionError):
        cap.start()


@pytest.mark.skipif(sys.platform == "win32", reason="假 helper 是 /bin/sh 脚本，Windows 无法 exec")
def test_happy_path_reads_pcm_then_stops(tmp_path):
    cap = MacSystemAudioCapture(binary=_fake(tmp_path, "happy", _HAPPY))
    cap.start()
    got = b""
    t0 = time.time()
    while time.time() - t0 < 1.0:
        chunk = cap.read(timeout=0.2)
        if chunk:
            got += chunk
    cap.stop()  # 关 stdin → 假 helper 退出
    assert len(got) > 0  # 读到 PCM


def test_find_binary_prefers_configured(tmp_path):
    fake = _fake(tmp_path, "macsysaudio", _HAPPY)
    assert find_macsysaudio_binary(fake) == fake
    _ = find_macsysaudio_binary("")  # 配置路径空 → 回退发现，确保不抛


@pytest.mark.skipif(sys.platform != "darwin", reason="仅 macOS 有真 helper")
def test_real_binary_discoverable_if_built():
    found = find_macsysaudio_binary()
    if found:  # 未构建则不强求，构建过就应可执行
        assert os.access(found, os.X_OK)
