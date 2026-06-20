"""阿里云百炼 Fun-ASR 实时转录后端（DashScope WS）。

后端负责切句：一个 sentence_id 一句，映射成独立 seg_id（``funasr#<gen>#<sentence_id>``），句文本是生长式全文，同句改写 upsert 同一 seg_id。
关键坑：``sentence_end`` 不可靠，故定稿靠「下一句出现」触发、末句靠 ``task-finished``。
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Optional

import websocket

from videocaptioner.core.realtime.backends.base import (
    LiveCaptionError,
    LiveTranscriber,
    OnError,
    OnSegment,
    OnState,
    TranscriberState,
)
from videocaptioner.core.realtime.backends.languages import (
    FUN_ASR_MTL_LANGS,
    FUN_ASR_REALTIME_LANGS,
)
from videocaptioner.core.realtime.events import TranscriptSegment
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_fun_asr_backend")

_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DEFAULT_MODEL = "fun-asr-mtl-realtime"  # 多语种实时：中/粤/英/日/泰/越/印尼


class FunAsrBackend(LiveTranscriber):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        language: str = "zh",
        *,
        on_segment: Optional[OnSegment] = None,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
    ) -> None:
        super().__init__(on_segment, on_state, on_error)
        if not api_key:
            raise LiveCaptionError("Fun-ASR 实时转录需要阿里云百炼 API Key（在设置里填写）。")
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._language = language or "zh"
        self._ws: Optional[websocket.WebSocket] = None
        self._task_id = uuid.uuid4().hex
        self._send_lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._closed = False  # ws 已关、接收线程应退出
        self._stopping = False  # 收尾中：停止喂音频，但接收线程仍要收 task-finished
        self._started_event = threading.Event()  # 收到 task-started
        self._finished_event = threading.Event()  # 收到 task-finished/failed
        self._fed_any = False  # 没喂过音频就别 finish-task（空任务直接关更稳）
        self._gen = 0  # 重连代数：seg_id 带 gen 避免新旧 task 的 sentence_id 撞号
        self._open_sid: object = None     # 正在生长、尚未定稿的句 id
        self._open_seg_id: Optional[str] = None  # 该句完整 seg_id（带 gen），定稿用
        self._open_text = ""              # 该句最新文本
        self._open_start: Optional[float] = None
        self._open_end: Optional[float] = None

    # ----- LiveTranscriber -----

    def start(self) -> None:
        self._emit_state(TranscriberState.CONNECTING)
        header = [f"Authorization: Bearer {self._api_key}"]
        try:
            self._ws = websocket.create_connection(
                _WS_URL, timeout=10, enable_multithread=True, header=header)
            self._ws.settimeout(0.5)
        except Exception as exc:
            raise LiveCaptionError(f"连接 Fun-ASR 实时服务失败：{exc}") from exc

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        self._send_run_task()
        # 等 task-started 再宣布就绪：之前喂的音频会被服务端丢弃
        if not self._started_event.wait(timeout=10):
            self.stop()
            raise LiveCaptionError("Fun-ASR 实时服务未在 10s 内就绪（检查 API Key / 网络）。")
        self._emit_state(TranscriberState.LISTENING)

    def feed(self, pcm16: bytes) -> None:
        if self._closed or self._stopping or not pcm16:
            return
        # 未收到 task-started（含重连缝隙）前不喂：服务端会丢弃该时段的二进制帧。
        if not self._started_event.is_set():
            return
        try:
            with self._send_lock:  # 锁内取并用 ws，避免与 stop() 关 ws 的竞态
                ws = self._ws
                if ws is None:
                    return
                ws.send(pcm16, opcode=websocket.ABNF.OPCODE_BINARY)
            self._fed_any = True
        except Exception as exc:
            if not self._closed:
                logger.debug("发送音频失败：%s", exc)

    def stop(self) -> None:
        if self._closed or self._stopping:
            return
        self._stopping = True  # 停止喂音频，但接收线程仍存活以接住末句 + task-finished
        self._reconnect_wake.set()  # 唤醒可能正在退避等待的重连，立即收尾
        ws = self._ws
        if ws is not None:
            self._finished_event.clear()
            if self._fed_any:  # 没喂过音频就别 finish-task（空任务直接关更稳）
                try:
                    self._send_json(
                        {
                            "header": {
                                "action": "finish-task",
                                "task_id": self._task_id,
                                "streaming": "duplex",
                            },
                            "payload": {"input": {}},
                        }
                    )
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
        self._emit_state(TranscriberState.STOPPED)

    # ----- 内部 -----

    def _send_json(self, obj: dict) -> None:
        with self._send_lock:  # 同 feed()：避免与 stop() 关 ws 的竞态
            ws = self._ws
            if ws is None:
                return
            ws.send(json.dumps(obj))

    def _language_hints(self) -> list:
        """language_hints：显式选了语言就用它；auto 则给该模型支持的整套语言由模型自动识别。"""
        if self._language and self._language != "auto":
            return [self._language]
        return list(FUN_ASR_MTL_LANGS if "mtl" in self._model else FUN_ASR_REALTIME_LANGS)

    def _send_run_task(self) -> None:
        """开一个 ASR 任务（start 首连 + 重连续录共用）。"""
        self._send_json({
            "header": {"action": "run-task", "task_id": self._task_id, "streaming": "duplex"},
            "payload": {
                "task_group": "audio", "task": "asr", "function": "recognition",
                "model": self._model,
                "parameters": {
                    "format": "pcm", "sample_rate": 16000,
                    "language_hints": self._language_hints(),
                    # 用 VAD 断句而非语义分句：语义分句会关闭 VAD，连续语音下单句过长、段落过粗。
                    "semantic_punctuation_enabled": False,
                    "max_sentence_silence": 800,        # 停顿 ~0.8s 即断句（默认 1300 偏大）
                    "multi_threshold_mode_enabled": True,  # 长句也能切，单句不拖太长
                    "heartbeat": True,                  # 连续静音也保活，减少空闲断连/重连
                },
                "input": {},
            },
        })

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
            if not raw:  # 服务端正常关闭连接
                if self._closed or self._stopping or not self._try_reconnect(None):
                    break
                continue
            self._note_alive()  # 收到数据帧 → 连接存活（供重连治理判定抖动期）
            if isinstance(raw, bytes):
                continue  # Fun-ASR 不回二进制
            if self.on_raw is not None:  # 调试落盘钩子（与 voxgate 对齐；生产路径不设）
                try:
                    self.on_raw(raw)
                except Exception:
                    pass
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            self._dispatch(ev)

    def _try_reconnect(self, reason) -> bool:
        """掉线或服务端中途 task-finished（实时单 task 有时长上限）时透明续录：定稿在途句，退避重连
        新连接并重发 run-task + bump gen。退避 / 限频 / 失败上限见 base._reconnect_with_backoff。"""
        self._finalize_open()  # 续录前最后一句先定稿，不丢

        def attempt() -> None:
            new = websocket.create_connection(
                _WS_URL, timeout=10, enable_multithread=True,
                header=[f"Authorization: Bearer {self._api_key}"])
            new.settimeout(0.5)
            with self._send_lock:
                old, self._ws = self._ws, new
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._gen += 1  # 新 task 的 sentence_id 又从 1 起，bump gen 避免 seg_id 撞号
            self._task_id = uuid.uuid4().hex
            self._started_event.clear()
            self._send_run_task()  # task-started 由本循环后续自然收到

        return self._reconnect_with_backoff(
            reason, attempt=attempt,
            is_stopping=lambda: self._closed or self._stopping,
            logger=logger, name="Fun-ASR")

    @staticmethod
    def _ms_to_s(v) -> Optional[float]:
        return v / 1000.0 if isinstance(v, (int, float)) else None

    def _finalize_open(self) -> None:
        """把当前句作为定稿段发出并清空在途状态（下一句出现 / 收尾时调用）；清空避免被二次定稿。"""
        if self._open_seg_id and self._open_text:
            self._emit_segment(TranscriptSegment(
                self._open_seg_id, self._open_text, is_final=True,
                start_time=self._open_start, end_time=self._open_end))
        self._open_sid = None
        self._open_seg_id = None
        self._open_text = ""
        self._open_start = self._open_end = None

    def _dispatch(self, ev: dict) -> None:
        event = ev.get("header", {}).get("event", "")
        if event == "task-started":
            self._started_event.set()
        elif event == "result-generated":
            sentence = ev.get("payload", {}).get("output", {}).get("sentence") or {}
            if sentence.get("heartbeat"):
                return  # 心跳结果可跳过
            text = (sentence.get("text") or "").strip()
            if not text:
                return
            sid = sentence.get("sentence_id")
            if sid is None:
                sid = sentence.get("begin_time")  # 兜底身份（极少缺 sentence_id）
            st = self._ms_to_s(sentence.get("begin_time"))
            et = self._ms_to_s(sentence.get("end_time"))
            # 新句出现 → 上一句可靠定稿（不信 sentence_end）。同句改写只 upsert 自己的 seg_id。
            if self._open_sid is not None and sid != self._open_sid:
                self._finalize_open()
            seg_id = f"funasr#{self._gen}#{sid}"
            self._open_sid, self._open_seg_id, self._open_text = sid, seg_id, text
            self._open_start, self._open_end = st, et
            self._emit_segment(TranscriptSegment(
                seg_id, text, is_final=False, start_time=st, end_time=et))
        elif event == "task-failed":
            msg = ev.get("header", {}).get("error_message", "Fun-ASR 实时任务失败")
            self._emit_error(str(msg))
            self._started_event.set()  # 解开可能在等就绪的 start()
            self._finished_event.set()
        elif event == "task-finished":
            if self._stopping or self._closed:
                # 我们主动 finish-task 后的正常收尾：末句没有「下一句」触发边界，这里定稿。
                self._finalize_open()
                self._started_event.set()  # 解开可能在等就绪的 start()
                self._finished_event.set()
            else:
                # 服务端中途结束 task（实时单 task 有时长上限）但音频还在喂 → 重起续录，不当结束。
                logger.info("Fun-ASR 服务端中途结束 task，重起续录")
                if not self._try_reconnect("服务端结束 task"):
                    self._closed = True  # 重起失败 → 退出接收线程（错误已上报）
