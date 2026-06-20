"""
阿里云百炼 Qwen-ASR 实时转录后端（DashScope WS，OpenAI-realtime 风格，27 语种含自动识别）。
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from typing import Optional

import websocket

from videocaptioner.core.realtime.backends.base import (
    SAMPLE_RATE,
    LiveCaptionError,
    OnError,
    OnSegment,
    OnState,
    TranscriberState,
)
from videocaptioner.core.realtime.backends.ws_base import WebSocketTranscriber
from videocaptioner.core.realtime.events import TranscriptSegment
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_qwen_asr_backend")

_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
DEFAULT_MODEL = "qwen3-asr-flash-realtime"  # 多语种实时：27 种语言 + 自动识别
_SILENCE_MS = 800  # server_vad 停顿断句阈值

_TEXT_EVENT = "conversation.item.input_audio_transcription.text"
_DONE_EVENT = "conversation.item.input_audio_transcription.completed"
_FAIL_EVENT = "conversation.item.input_audio_transcription.failed"


class QwenAsrBackend(WebSocketTranscriber):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        language: str = "auto",
        *,
        on_segment: Optional[OnSegment] = None,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
    ) -> None:
        super().__init__(on_segment, on_state, on_error)
        if not api_key:
            raise LiveCaptionError("Qwen-ASR 实时转录需要阿里云百炼 API Key（在设置里填写）。")
        # 基类设 WS 共性状态：_ws / _send_lock / _recv_thread / _closed / _stopping / _fed_any
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._language = language or "auto"
        self._session_ready = threading.Event()  # 已收 session.created 并发出 session.update
        self._finished_event = threading.Event()  # 收尾用：已收 session.finished/error
        # 在途未定稿句，重连/收尾时补定稿以免丢末句。
        self._open_item: Optional[str] = None
        self._open_text = ""

    # ----- LiveTranscriber -----

    def start(self) -> None:
        self._emit_state(TranscriberState.CONNECTING)
        try:
            self._ws = self._connect()
        except Exception as exc:
            raise LiveCaptionError(f"连接 Qwen-ASR 实时服务失败：{exc}") from exc
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        # 收到 session.created 并回发 session.update（见 _dispatch）后才算就绪
        if not self._session_ready.wait(timeout=10):
            self.stop()
            raise LiveCaptionError("Qwen-ASR 实时服务未在 10s 内就绪（检查 API Key / 网络）。")
        self._emit_state(TranscriberState.LISTENING)

    def feed(self, pcm16: bytes) -> None:
        if self._closed or self._stopping or not pcm16:
            return
        if not self._session_ready.is_set():
            # 必须先 update 后喂音频：音频先到会被服务端拒为「session already started」。
            return
        msg = json.dumps({
            "event_id": uuid.uuid4().hex,
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm16).decode("ascii"),
        })
        try:
            with self._send_lock:  # 锁内取并用 ws：stop()/重连会换 ws，锁外取有竞态
                ws = self._ws
                if ws is None:
                    return
                ws.send(msg)
            self._fed_any = True
        except Exception as exc:
            if not self._closed:
                logger.debug("发送音频失败：%s", exc)

    def stop(self) -> None:
        if self._closed or self._stopping:
            return
        self._stopping = True  # 停喂音频，接收线程仍存活以接住末句 + session.finished
        self._reconnect_wake.set()  # 唤醒可能正在退避等待的重连，立即收尾
        ws = self._ws
        if ws is not None:
            self._finished_event.clear()
            if self._fed_any:  # 没喂过音频则跳过 session.finish（空任务直接关更稳）
                try:
                    self._send_json({"event_id": uuid.uuid4().hex, "type": "session.finish"})
                except Exception:
                    pass
                self._finished_event.wait(timeout=3.0)
            self._closed = True
            try:
                ws.close()
            except Exception:
                pass
        else:
            self._closed = True
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=2)
        self._finalize_open()  # 兜底：末句没等到 .completed 时用在途全文定稿
        self._emit_state(TranscriberState.STOPPED)

    # ----- 内部 -----

    def _connect(self) -> websocket.WebSocket:
        ws = websocket.create_connection(
            f"{_WS_URL}?model={self._model}", timeout=10, enable_multithread=True,
            header=[f"Authorization: Bearer {self._api_key}"],
        )
        ws.settimeout(0.5)
        return ws

    def _send_session_update(self) -> None:
        """配置会话（连上/重连收到 session.created 后回发）；auto 省略 language 走自动识别。"""
        transcription: dict = {} if self._language == "auto" else {"language": self._language}
        self._send_json({
            "event_id": uuid.uuid4().hex,
            "type": "session.update",
            "session": {
                "input_audio_format": "pcm",
                "sample_rate": SAMPLE_RATE,
                "input_audio_transcription": transcription,
                "turn_detection": {"type": "server_vad", "silence_duration_ms": _SILENCE_MS},
            },
        })

    def _try_reconnect(self, reason) -> bool:
        """掉线或服务端中途结束 session 时透明续录：定稿在途句，退避重连新连接（session.update
        由新连接的 session.created 自动回发）。退避 / 限频 / 失败上限见 base._reconnect_with_backoff。"""
        self._finalize_open()  # 续录前先定稿在途句，不丢

        def attempt() -> None:
            new = self._connect()
            with self._send_lock:
                old, self._ws = self._ws, new
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._session_ready.clear()  # 新连接的 session.created 会再次触发 session.update

        return self._reconnect_with_backoff(
            reason, attempt=attempt,
            is_stopping=lambda: self._closed or self._stopping,
            logger=logger, name="Qwen-ASR")

    def _finalize_open(self) -> None:
        """把在途句作为定稿段发出并清空（.completed / 重连 / 收尾时调用）；清空避免被二次定稿。"""
        if self._open_item and self._open_text:
            self._emit_segment(TranscriptSegment(
                f"qwen#{self._open_item}", self._open_text, is_final=True))
        self._open_item = None
        self._open_text = ""

    def _dispatch(self, ev: dict) -> None:
        etype = ev.get("type", "")
        if etype == "session.created":
            self._send_session_update()  # 连上/重连：收到 created 即配置会话
            self._session_ready.set()
        elif etype == _TEXT_EVENT:
            item = ev.get("item_id")
            text = ((ev.get("text") or "") + (ev.get("stash") or "")).strip()
            if not item or not text:
                return
            if self._open_item and item != self._open_item:
                # 新句到来兜底定稿上一句（不全信每句必有 .completed；upsert 幂等，迟到无害）。
                self._emit_segment(
                    TranscriptSegment(f"qwen#{self._open_item}", self._open_text, is_final=True))
            self._open_item, self._open_text = item, text
            self._emit_segment(TranscriptSegment(f"qwen#{item}", text, is_final=False))
        elif etype == _DONE_EVENT:
            item = ev.get("item_id")
            transcript = (ev.get("transcript") or "").strip()
            if item and transcript:
                self._emit_segment(TranscriptSegment(f"qwen#{item}", transcript, is_final=True))
            if item == self._open_item:  # 已定稿，清在途避免收尾/重连二次发
                self._open_item, self._open_text = None, ""
        elif etype == _FAIL_EVENT:
            logger.debug("Qwen-ASR 单句转写失败（跳过）：%s", ev.get("error"))
            if ev.get("item_id") == self._open_item:
                self._open_item, self._open_text = None, ""
        elif etype == "error":
            # error 字段不保证是 dict（可能 str/None）；非 dict 直接 .get 会 AttributeError 杀线程，故防御取值。
            err = ev.get("error")
            msg = err.get("message", "Qwen-ASR 实时错误") if isinstance(err, dict) else str(err or "Qwen-ASR 实时错误")
            low = msg.lower()
            # 「already…」「session update error」多为重连后迟到的 session.update 被拒，会话仍在跑：不致命。
            if "already" in low or "session update error" in low:
                logger.info("Qwen-ASR 忽略非致命错误：%s", msg)
                return
            self._emit_error(msg)
        elif etype == "session.finished":
            if self._stopping or self._closed:
                self._finalize_open()  # 主动 finish 后的正常收尾
                self._session_ready.set()
                self._finished_event.set()
            else:
                # 服务端中途结束 session（单 session 有时长上限）→ 重起续录，不当结束。
                logger.info("Qwen-ASR 服务端中途结束 session，重起续录")
                if not self._try_reconnect("服务端结束 session"):
                    self._fail_close()  # 重起失败：关 ws + 发 STOPPED，终态与 stop() 一致
        # speech_started/stopped、committed、conversation.item.created 等信息性事件：忽略
