from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Optional

from videocaptioner.core.realtime.events import TranscriptSegment

# 统一的音频契约：所有后端都按这个格式喂音频。
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16


class LiveCaptionError(RuntimeError):
    """实时字幕链路错误（连接 / 鉴权 / 后端失败）。"""


class TranscriberState(str, Enum):
    """后端连接状态，用于 UI 状态指示。

    只保留各后端真正会发的三态；错误走 ``on_error`` 回调而非状态位。
    """

    CONNECTING = "connecting"
    LISTENING = "listening"
    STOPPED = "stopped"


# 后端 → 上层的回调签名
OnSegment = Callable[[TranscriptSegment], None]
OnState = Callable[[TranscriberState], None]
OnError = Callable[[str], None]


class LiveTranscriber(ABC):
    """流式转录后端基类。

    线程模型：``feed()`` 在调用方线程（音频泵）被频繁调用；后端内部通常另起一个
    接收线程解析事件并触发 ``on_segment``。回调可能在后端的接收线程被调用，上层
    （Qt 信号）需自行处理跨线程。
    """

    # 掉线续录治理参数（WS 后端共用）
    _RECONNECT_MAX_DELAY_S: float = 5.0   # 连不上时指数退避上限
    _RECONNECT_HEALTHY_S: float = 5.0     # 连接存活超此时长再断算偶发，否则计入抖动期
    _RECONNECT_MAX_FAILS: int = 12        # 连续建连失败上限（约 1 分钟）→ 上报致命并放弃

    def __init__(
        self,
        on_segment: Optional[OnSegment] = None,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
    ) -> None:
        self.on_segment = on_segment
        self.on_state = on_state
        self.on_error = on_error
        # 调试钩子（默认 None）：设置后，后端把每条原生事件原文回调出去供落盘排查；生产路径不设。
        self.on_raw: Optional[Callable[[str], None]] = None
        self._reconnect_wake = threading.Event()  # stop() set 它以立即结束退避等待
        self._reconnect_streak = 0                 # 连续重连次数，用于日志限频
        self._last_alive_at = 0.0                  # 上次确认连接存活的单调时刻

    # ----- 子类实现 -----

    @abstractmethod
    def start(self) -> None:
        """建立连接 / 会话；就绪后才可 ``feed``。失败抛 :class:`LiveCaptionError`。"""

    @abstractmethod
    def feed(self, pcm16: bytes) -> None:
        """送入一段 16k/mono/s16le PCM（chunk 大小任意）。"""

    @abstractmethod
    def stop(self) -> None:
        """收尾并断开；幂等。"""

    # ----- 给子类的便捷分发 -----

    def _emit_segment(self, segment: TranscriptSegment) -> None:
        if self.on_segment is not None:
            self.on_segment(segment)

    def _emit_state(self, state: TranscriberState) -> None:
        if self.on_state is not None:
            self.on_state(state)

    def _emit_error(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    # ----- 给 WS 后端共用的掉线续录治理 -----

    def _note_alive(self) -> None:
        """收到任意服务端数据时调用：刷新连接存活时刻，供重连治理区分偶发断与抖动期。"""
        self._last_alive_at = time.monotonic()

    def _reconnect_with_backoff(self, reason, *, attempt, is_stopping, logger, name) -> bool:
        """掉线 / 服务端中途结束时的统一续录治理（多个 WS 后端共用，消除各自重复实现）。

        ``attempt`` 由子类提供：建连 + 换 ws + 重置会话状态，成功正常返回、失败抛异常。偶发单断
        立即重连（首轮无等待）；连不上则指数退避至 ``_RECONNECT_MAX_DELAY_S``，连续失败超
        ``_RECONNECT_MAX_FAILS`` 才上报致命并放弃（不再一次失败就退线程）；连上又秒断的抖动期
        靠 streak 计数把日志限频，避免刷屏。``is_stopping`` 为真或 ``_reconnect_wake`` 被 set
        （stop()）时立即中断。
        """
        now = time.monotonic()
        flaky = self._last_alive_at and (now - self._last_alive_at) < self._RECONNECT_HEALTHY_S
        self._reconnect_streak = self._reconnect_streak + 1 if flaky else 1
        if self._reconnect_streak <= 2 or self._reconnect_streak % 10 == 0:
            logger.info("%s 连接中断，重连续录（第 %d 次，%s）", name, self._reconnect_streak, reason)
        delay = 0.0
        fails = 0
        while not is_stopping():
            if delay and self._reconnect_wake.wait(delay):
                return False  # 被 stop() 唤醒
            try:
                attempt()
            except Exception as exc:
                fails += 1
                if fails >= self._RECONNECT_MAX_FAILS:
                    self._emit_error(f"{name} 网络持续不可用（连续 {fails} 次重连失败）：{exc}")
                    return False
                delay = min(max(delay, 0.5) * 2, self._RECONNECT_MAX_DELAY_S)
                continue
            self._last_alive_at = time.monotonic()
            return True
        return False
