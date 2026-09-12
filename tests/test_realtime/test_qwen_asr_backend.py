"""Qwen-ASR 实时后端协议映射契约（离线，mock WebSocket，OpenAI-realtime 风格）。

锁住（均依据真实抓包）：连上即等 session.created → 回发 session.update（auto 省略 language）；
``.text`` 流式取 ``text+stash``（实测全文在 stash、text 恒空）→ 中间结果；``.completed`` 的
``transcript`` 定稿；每个 item_id = 一句独立 seg_id；中途 session.finished（非停止）→ 透明重连续录。
"""

import json
import threading
import time

import websocket

from videocaptioner.core.realtime.backends.qwen_asr import QwenAsrBackend


class _FakeWS:
    """脚本化假 WebSocket：recv 依次吐预设服务端事件，send 记录下来。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.sent = []
        self._closed = threading.Event()

    def settimeout(self, _t):
        pass

    def send(self, data, opcode=None):  # noqa: ARG002
        self.sent.append(json.loads(data))

    def recv(self):
        if self._scripted:
            return self._scripted.pop(0)
        self._closed.wait(timeout=2)
        raise websocket.WebSocketConnectionClosedException()

    def close(self):
        self._closed.set()


def _ev(type_, **fields):
    return json.dumps({"event_id": "e", "type": type_, **fields})


def _text(item, stash, text=""):
    return _ev("conversation.item.input_audio_transcription.text",
               item_id=item, text=text, stash=stash, language="es")


def _done(item, transcript):
    return _ev("conversation.item.input_audio_transcription.completed",
               item_id=item, transcript=transcript, language="es")


def _wait(pred, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline and not pred():
        time.sleep(0.02)


def test_protocol_mapping_es(monkeypatch):
    scripted = [
        _ev("session.created"),
        _text("A", "Hola"),
        _text("A", "Hola mundo"),
        _done("A", "Hola mundo."),
    ]
    fake = _FakeWS(scripted)
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)

    segs = []
    be = QwenAsrBackend(api_key="sk-x", language="es", on_segment=segs.append)
    be.start()
    be.feed(b"\x00\x01" * 100)
    _wait(lambda: any(s.is_final for s in segs))
    be.stop()

    # 连上回发 session.update，配 language=es + server_vad
    upd = next(m for m in fake.sent if m["type"] == "session.update")
    assert upd["session"]["input_audio_transcription"]["language"] == "es"
    assert upd["session"]["turn_detection"]["type"] == "server_vad"
    assert upd["session"]["input_audio_format"] == "pcm"
    # 喂音频以 input_audio_buffer.append + base64 发出
    assert any(m["type"] == "input_audio_buffer.append" and m.get("audio") for m in fake.sent)
    # 每句一个 seg_id；流式取 stash；completed 定稿
    assert {s.seg_id for s in segs} == {"qwen#A"}
    interim = [s.text for s in segs if not s.is_final]
    assert interim == ["Hola", "Hola mundo"]
    final = [s for s in segs if s.is_final]
    assert final and final[-1].text == "Hola mundo."


def test_auto_omits_language(monkeypatch):
    """source_language=auto → session.update 不带 language（服务端自动检测）。"""
    fake = _FakeWS([_ev("session.created"), _done("A", "hola")])
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)
    be = QwenAsrBackend(api_key="sk-x", language="auto", on_segment=lambda s: None)
    be.start()
    be.stop()
    upd = next(m for m in fake.sent if m["type"] == "session.update")
    assert upd["session"]["input_audio_transcription"] == {}  # 无 language


def test_midsession_session_finished_reconnects(monkeypatch):
    """服务端中途发 session.finished（实时单 session 时长上限）→ 不当结束，重连续录。

    「转录到一半突然没了」的同类回归：旧式只收尾不重连，音频还在喂却再无结果。"""
    ws1 = _FakeWS([_ev("session.created"), _done("A", "uno"), _ev("session.finished")])
    ws2 = _FakeWS([_ev("session.created"), _done("B", "dos")])
    pending = [ws1, ws2]
    monkeypatch.setattr(websocket, "create_connection",
                        lambda *a, **k: pending.pop(0) if pending else _FakeWS([]))

    segs = []
    be = QwenAsrBackend(api_key="sk-x", language="es", on_segment=segs.append)
    be.start()
    be.feed(b"\x00\x01" * 100)  # 非空、非 stopping
    _wait(lambda: any(s.seg_id == "qwen#B" for s in segs))
    be.stop()

    seg_ids = {s.seg_id for s in segs}
    assert "qwen#A" in seg_ids   # 重连前
    assert "qwen#B" in seg_ids   # 中途 session.finished 后重起续出
    assert len(pending) == 0      # 确实建立了第二个连接


def test_feed_gated_until_session_ready():
    """会话未配置好（没发出 session.update）时不喂音频——避免重连后「session already started」。"""
    fake = _FakeWS([])  # 不吐 session.created → 永不就绪
    be = QwenAsrBackend(api_key="sk-x", on_segment=lambda s: None)
    be._ws = fake  # 直接装连接，跳过 start()（不阻塞等就绪）
    be.feed(b"\x00\x01" * 100)
    assert not any(m.get("type") == "input_audio_buffer.append" for m in fake.sent)  # 未就绪不发
    be._session_ready.set()
    be.feed(b"\x00\x01" * 100)
    assert any(m.get("type") == "input_audio_buffer.append" for m in fake.sent)  # 就绪后才发


def test_error_session_already_is_non_fatal(monkeypatch):
    """重连后迟到的 session.update 被拒（session already …）是非致命的：不上报、会话继续出字幕。"""
    fake = _FakeWS([
        _ev("session.created"),
        _ev("error", error={"message":
            "Session update error: session already started or finished or failed."}),
        _done("A", "hola"),
    ])
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)
    segs, errs = [], []
    be = QwenAsrBackend(api_key="sk-x", language="es",
                        on_segment=segs.append, on_error=errs.append)
    be.start()
    _wait(lambda: any(s.seg_id == "qwen#A" for s in segs))
    be.stop()
    assert errs == []                                   # 非致命：不上报错误（不杀会话）
    assert any(s.seg_id == "qwen#A" for s in segs)      # 会话继续、照常出字幕


def test_missing_api_key_raises():
    import pytest
    with pytest.raises(Exception):
        QwenAsrBackend(api_key="")


def test_error_event_tolerates_non_dict_error_field():
    # 服务端 error 字段非 dict（字符串/None/缺失）时 _dispatch 不得抛 AttributeError 杀接收线程。
    be = QwenAsrBackend(api_key="sk-x", language="es", on_segment=lambda s: None)
    for ev in ({"type": "error", "error": "boom"},
               {"type": "error", "error": None},
               {"type": "error"}):
        be._dispatch(ev)  # 不抛异常即通过


def test_new_item_finalizes_previous_open():
    # 上一句 .completed 丢失/乱序时，新 item 的到来兜底定稿上一句，不丢句。
    segs = []
    be = QwenAsrBackend(api_key="sk-x", language="es", on_segment=segs.append)
    be._dispatch(json.loads(_text("i1", "hola")))   # interim i1
    be._dispatch(json.loads(_text("i2", "mundo")))  # 新 item → 兜底定稿 i1
    assert ("qwen#i1", "hola") in [(s.seg_id, s.text) for s in segs if s.is_final]


def test_reconnect_backoff_gives_up_after_repeated_failures(monkeypatch):
    """连不上时退避重试，连续失败超上限 → 上报致命并放弃（不再一次失败就静默退接收线程）。"""
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(websocket, "create_connection", boom)
    errs = []
    be = QwenAsrBackend(api_key="sk-x", language="es",
                        on_segment=lambda s: None, on_error=errs.append)
    be._RECONNECT_MAX_FAILS = 3
    be._RECONNECT_MAX_DELAY_S = 0.0  # 退避归零，测试不阻塞
    assert be._try_reconnect("boom") is False
    assert errs and "网络持续不可用" in errs[0]


def test_reconnect_terminates_on_accept_then_drop(monkeypatch):
    """抖动期（配额满 / 限流）：建连每次都成功但连接秒断，attempt 不抛 → fails 永不累加。

    这种 "accept-then-drop" 必须靠跨调用累计的 _reconnect_streak 兜底终止，否则会每 0.5s 无限
    重连、永不出字也永不报错（连不上的 fails 上限拦不住它，因为每次 attempt 都成功）。"""
    monkeypatch.setattr(websocket, "create_connection",
                        lambda *a, **k: _FakeWS([_ev("session.created")]))
    errs = []
    be = QwenAsrBackend(api_key="sk-x", language="es",
                        on_segment=lambda s: None, on_error=errs.append)
    be._RECONNECT_MAX_FAILS = 3
    be._note_alive()  # 最近确认存活 → 后续断连判为抖动期，streak 累计
    results = [be._try_reconnect("drop") for _ in range(5)]
    assert results[:3] == [True, True, True]  # 抖动期内每次都建连成功（fails 拦不住）
    assert results[3] is False                # streak 超上限 → 放弃续录
    assert errs and "反复连上即断" in errs[0]
