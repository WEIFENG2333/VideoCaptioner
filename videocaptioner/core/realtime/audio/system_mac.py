"""macOS 原生系统声音采集。

起 ``macsysaudio`` 子进程（源见 ``native/macsysaudio/``）捕获本机播放声→16k/mono/s16le
PCM 写 stdout，本类读出入队，对外接口与 :class:`AudioCapture` 完全一致（drop-in），关
stdin（EOF）即停。SCK 音频归「屏幕录制」权限；未授权时 helper 退出码 2 + stderr
"PERMISSION"，这里抛 :class:`MacSystemAudioPermissionError` 供上层提示用户授权后重启。
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from videocaptioner import config
from videocaptioner.core.realtime.audio.capture import AudioSourceError
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_sysaudio")

_BINARY_NAME = "macsysaudio"
_READY_TOKEN = "STARTED"
_PERMISSION_EXIT = 2


class MacSystemAudioPermissionError(AudioSourceError):
    """未授予「屏幕录制」权限——系统声音捕获不可用。"""


def find_macsysaudio_binary(configured: str = "") -> Optional[str]:
    """按 配置路径 → 自带 bin → 用户 bin → PATH 的顺序发现 macsysaudio（与 voxgate 同规则）。"""
    candidates: List[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(config.BUNDLED_BIN_PATH / _BINARY_NAME)
    candidates.append(config.BIN_PATH / _BINARY_NAME)
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return shutil.which(_BINARY_NAME)


def system_audio_supported() -> bool:
    """当前平台是否支持原生系统声音捕获（仅 macOS 且找得到 helper）。"""
    return sys.platform == "darwin" and find_macsysaudio_binary() is not None


class MacSystemAudioCapture:
    """ScreenCaptureKit 系统声音采集，接口与 :class:`AudioCapture` 对齐（drop-in）。"""

    def __init__(self, binary: str = "", queue_max: int = 256) -> None:
        self._binary = binary
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=queue_max)
        self._proc: Optional[subprocess.Popen] = None
        self._read_thread: Optional[threading.Thread] = None
        self._stderr_lines: List[str] = []
        self._started = threading.Event()
        self._dropped = 0

    def start(self) -> None:
        binary = find_macsysaudio_binary(self._binary)
        if not binary:
            raise AudioSourceError(
                "未找到系统声音捕获程序 macsysaudio。请先构建 native/macsysaudio（build.sh）。"
            )
        try:
            self._proc = subprocess.Popen(
                [binary],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            raise AudioSourceError(f"启动系统声音捕获失败：{exc}") from exc

        threading.Thread(target=self._drain_stderr, daemon=True).start()
        # 等 helper 就绪（"STARTED"，SCK 异步启动给足 8s）；轮询进程状态，崩了立即报错而非干等。
        deadline = time.monotonic() + 8.0
        while not self._started.wait(timeout=0.1):
            code = self._proc.poll()
            if code is not None:
                self._raise_for_exit(code)
            if time.monotonic() >= deadline:
                self.stop()
                raise AudioSourceError("系统声音捕获启动超时（ScreenCaptureKit 未就绪）。")

        # 保留句柄：stop() 需 join 读线程到 EOF，确保尾音入队后再回收进程。
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        logger.info("系统声音采集已启动：%s", binary)

    def _raise_for_exit(self, code: int) -> None:
        detail = " ".join(self._stderr_lines[-3:]).strip()
        if code == _PERMISSION_EXIT or "PERMISSION" in detail:
            raise MacSystemAudioPermissionError(
                "未获得「屏幕录制」权限，无法捕获系统声音。请在 系统设置 → 隐私与安全性 → "
                "屏幕录制 中勾选本应用（或运行它的终端），然后重启应用重试。"
            )
        raise AudioSourceError(f"系统声音捕获启动失败（退出码 {code}）：{detail or '未知错误'}")

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            self._stderr_lines.append(line)
            if _READY_TOKEN in line:
                self._started.set()
            else:
                logger.debug("macsysaudio: %s", line)

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stdout = proc.stdout
        while True:
            chunk = stdout.read(3200)  # ~100ms @16k/mono/s16le
            if not chunk:
                break  # helper 退出 / 管道关闭
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                # 与 AudioCapture 一致：满则丢最新块，绝不丢最旧。
                self._dropped += 1
                if self._dropped % 20 == 1:
                    logger.warning("系统声音队列溢出丢帧 ×%d：消费端跟不上", self._dropped)

    def read(self, timeout: float = 0.1) -> Optional[bytes]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()  # EOF → helper 自行停止退出
        except Exception:
            pass
        # 先 join 读线程到 EOF，确保 helper 冲刷的尾音入队供上层排空，再回收进程。
        rt = self._read_thread
        self._read_thread = None
        if rt is not None:
            rt.join(timeout=2.0)
        try:
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
