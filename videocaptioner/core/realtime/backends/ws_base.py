"""WS 类实时后端（fun-asr / qwen-asr）的共性骨架。

抽出两后端逐字重复的部分：WS 连接状态、接收线程循环、送帧加锁、失败收尾；子类只实现协议差异
（start/stop/feed 的握手与编码、_dispatch 解析、_try_reconnect 续录）。掉线退避治理在更上层的
``LiveTranscriber._reconnect_with_backoff``。

voxgate 是子进程 stdio、不走这里——它直接继承 LiveTranscriber，避免把 websocket 拉进其启动路径
（backends 包刻意不 re-export，保持后端懒加载）。
"""

from __future__ import annotations

import json
import threading
from abc import abstractmethod
from typing import Optional

import websocket

from videocaptioner.core.realtime.backends.base import (
    LiveTranscriber,
    OnError,
    OnSegment,
    OnState,
    TranscriberState,
)


class WebSocketTranscriber(LiveTranscriber):
    """fun-asr / qwen-asr 共用：WS 连接 + 接收线程 + 送帧加锁 + 终态收尾。"""

    def __init__(
        self,
        on_segment: Optional[OnSegment] = None,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
    ) -> None:
        super().__init__(on_segment, on_state, on_error)
        self._ws: Optional[websocket.WebSocket] = None
        self._send_lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._closed = False    # ws 已关、接收线程应退出
        self._stopping = False  # 收尾中：停喂音频，接收线程仍接末句 + 结束帧
        self._fed_any = False   # 没喂过音频则跳过结束帧（空任务直接关更稳）

    def _send_json(self, obj: dict) -> None:
        with self._send_lock:  # 锁内取并用 ws，避免与 stop() / 重连换 ws 竞态
            ws = self._ws
            if ws is None:
                return
            ws.send(json.dumps(obj))

    def _recv_loop(self) -> None:
        while not self._closed:
            ws = self._ws
            if ws is None:
                break
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                if self._closed or self._stopping:
                    break  # 主动收尾：正常退出
                if not self._try_reconnect(exc):
                    break
                continue
            if not raw:  # 服务端关闭连接
                if self._closed or self._stopping or not self._try_reconnect(None):
                    break
                continue
            self._note_alive()  # 收到数据帧 → 连接存活（供重连治理判定抖动期）
            if isinstance(raw, bytes):
                continue  # 两后端都不回二进制
            if self.on_raw is not None:  # 调试落盘钩子（生产路径不设）
                try:
                    self.on_raw(raw)
                except Exception:
                    pass
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            self._dispatch(ev)

    def _fail_close(self) -> None:
        """重连彻底失败 / 服务端结束 session 的终态收尾：关 ws + 置 _closed + 发 STOPPED。

        与 stop() 的终态一致——否则只置 ``_closed`` 会泄漏 ws fd（stop() 因 _closed 已早退、不再
        close），且 UI 收不到 STOPPED 状态。
        """
        self._closed = True
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._emit_state(TranscriberState.STOPPED)

    # ----- 子类实现协议差异 -----

    @abstractmethod
    def _dispatch(self, ev: dict) -> None:
        """解析一条服务端 JSON 事件：emit 段落 / 处理就绪 / 结束 / 错误。"""

    @abstractmethod
    def _try_reconnect(self, reason) -> bool:
        """掉线 / 服务端中途结束时续录（通常委托 _reconnect_with_backoff）。"""
