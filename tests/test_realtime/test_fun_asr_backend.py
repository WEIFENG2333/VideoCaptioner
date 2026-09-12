"""Fun-ASR 实时后端协议映射契约（离线，mock WebSocket）。

锁住：run-task 带正确 model/format/language_hints；result-generated.sentence 拼成单一
seg_id 的累积全文；**段落边界用 sentence_id 切换**（不是 sentence_end——后者同句会多次
触发且其后仍改写，据此累加会整句重复，见 test_repeated_sentence_end_no_duplicate）；
心跳跳过；task-finished 把末句作为 is_final 冲刷。真实联网调用在手动验证里做过。
"""

import json
import threading

import websocket

from videocaptioner.core.realtime.backends.fun_asr import FunAsrBackend


class _FakeWS:
    """脚本化的假 WebSocket：recv 依次吐预设服务端事件，send 记录下来。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.sent_json = []
        self.sent_binary = []
        self._closed = threading.Event()

    def settimeout(self, _t):
        pass

    def send(self, data, opcode=None):
        if opcode == websocket.ABNF.OPCODE_BINARY:
            self.sent_binary.append(data)
        else:
            self.sent_json.append(json.loads(data))

    def recv(self):
        if self._scripted:
            return self._scripted.pop(0)
        self._closed.wait(timeout=2)
        raise websocket.WebSocketConnectionClosedException()

    def close(self):
        self._closed.set()


def _ev(event, sentence=None, **header):
    h = {"task_id": "t", "event": event, **header}
    payload = {"output": {"sentence": sentence}} if sentence is not None else {}
    return json.dumps({"header": h, "payload": payload})


def test_protocol_mapping(monkeypatch):
    scripted = [
        _ev("task-started"),
        _ev("result-generated", {"text": "今天", "sentence_id": 1, "begin_time": 0, "end_time": 500}),
        _ev("result-generated", {"text": "今天深圳天气", "sentence_id": 1, "begin_time": 0, "end_time": 1500}),
        _ev("result-generated", {"text": "今天深圳天气怎么样？", "sentence_id": 1, "begin_time": 0, "end_time": 2000, "sentence_end": True}),
        _ev("result-generated", {"text": "心跳", "sentence_id": 2, "heartbeat": True}),
        _ev("result-generated", {"text": "走吧。", "sentence_id": 2, "begin_time": 2100, "end_time": 2600, "sentence_end": True}),
        _ev("task-finished"),
    ]
    fake = _FakeWS(scripted)
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)

    segs = []
    be = FunAsrBackend(api_key="sk-x", model="fun-asr-mtl-realtime", language="en",
                       on_segment=segs.append)
    be.start()
    be.feed(b"\x00\x01" * 100)
    be.stop()

    # run-task 参数正确
    run = next(m for m in fake.sent_json if m["header"]["action"] == "run-task")
    p = run["payload"]
    assert p["model"] == "fun-asr-mtl-realtime"
    assert p["parameters"]["format"] == "pcm"
    assert p["parameters"]["sample_rate"] == 16000
    assert p["parameters"]["language_hints"] == ["en"]
    # VAD 断句（非语义分句）：按停顿切句，段落细、定稿勤
    assert p["parameters"]["semantic_punctuation_enabled"] is False
    assert p["parameters"]["max_sentence_silence"] == 800
    assert p["parameters"]["multi_threshold_mode_enabled"] is True
    assert p["parameters"]["heartbeat"] is True
    assert fake.sent_binary == [b"\x00\x01" * 100]  # 喂的音频以二进制帧发出
    assert any(m["header"]["action"] == "finish-task" for m in fake.sent_json)

    # 映射：每句一个独立 seg_id（funasr#<gen>#<sentence_id>），心跳跳过
    assert {s.seg_id for s in segs} == {"funasr#0#1", "funasr#0#2"}
    assert not any(s.text == "心跳" for s in segs)
    # 句1 在句2 出现时定稿；时间戳 ms→s
    s1 = [s for s in segs if s.seg_id == "funasr#0#1" and s.is_final]
    assert s1 and s1[-1].text == "今天深圳天气怎么样？"
    assert s1[-1].start_time == 0.0 and s1[-1].end_time == 2.0
    # 句2 没有「下一句」触发边界 → task-finished 时定稿
    s2 = [s for s in segs if s.seg_id == "funasr#0#2" and s.is_final]
    assert s2 and s2[-1].text == "走吧。"


def test_repeated_sentence_end_no_duplicate(monkeypatch):
    """同一句多次 sentence_end + 改写：每句独立 seg_id、upsert 同一 id，绝不拼成重复段。

    这是「前后两句各重复一个词 / 整段重复」线上 bug 的回归锁：每句自己的 seg_id，同句改写
    只更新自己，不会累加进别人。
    """
    scripted = [
        _ev("task-started"),
        # 句1 在停顿处「过早」sentence_end，随后同 id 续写
        _ev("result-generated", {"text": "我觉得今天的天气非常的", "sentence_id": 1, "sentence_end": True}),
        _ev("result-generated", {"text": "我觉得今天的天气非常的不错。", "sentence_id": 1, "sentence_end": True}),
        _ev("result-generated", {"text": "下一句。", "sentence_id": 2, "sentence_end": True}),
        _ev("task-finished"),
    ]
    fake = _FakeWS(scripted)
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)
    segs = []
    be = FunAsrBackend(api_key="sk-x", on_segment=segs.append)
    be.start()
    be.feed(b"\x00\x01" * 100)
    be.stop()

    s1 = [s for s in segs if s.seg_id == "funasr#0#1"]
    assert s1 and s1[-1].text == "我觉得今天的天气非常的不错。"  # 句1 最新文本（改写覆盖，不重复）
    s2 = [s for s in segs if s.seg_id == "funasr#0#2"]
    assert s2 and s2[-1].text == "下一句。"
    assert all("非常的不错。我觉得" not in s.text for s in segs)  # 绝不出现整句重复拼接


def test_missing_api_key_raises():
    import pytest

    from videocaptioner.core.realtime.backends.base import LiveCaptionError

    with pytest.raises(LiveCaptionError):
        FunAsrBackend(api_key="")


def test_stop_without_audio_skips_finish_task(monkeypatch):
    # 没喂过音频就停（点开始立刻停）：不应发 finish-task（否则空缓冲会报错 → 曾导致崩溃）
    fake = _FakeWS([_ev("task-started")])
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)
    errors = []
    be = FunAsrBackend(api_key="sk-x", on_error=errors.append)
    be.start()
    be.stop()  # 没 feed 直接 stop
    assert not any(m["header"].get("action") == "finish-task" for m in fake.sent_json)
    assert errors == []


def test_task_failed_emits_error(monkeypatch):
    fake = _FakeWS([
        _ev("task-started"),
        _ev("task-failed", error_message="bad key"),
    ])
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: fake)
    errors = []
    be = FunAsrBackend(api_key="sk-x", on_error=errors.append)
    be.start()
    be.stop()
    assert errors and "bad key" in errors[0]


def test_midsession_task_finished_reconnects(monkeypatch):
    """服务端在会话中途发 task-finished（单 task 时长上限）→ 不当结束，重起 task 续录。

    这是「转录到一半突然什么都没了」的真因回归：旧逻辑把中途 task-finished 当正常结束、不重连，
    音频还在喂却再无结果。修复后应透明续录，新一代（gen）的句子照常产出。"""
    import time

    ws1 = _FakeWS([
        _ev("task-started"),
        _ev("result-generated", {"text": "hello", "sentence_id": 1,
                                 "begin_time": 0, "end_time": 1000}),
        _ev("task-finished"),  # 服务端中途结束（我们没 stopping）
    ])
    ws2 = _FakeWS([
        _ev("task-started"),
        _ev("result-generated", {"text": "world", "sentence_id": 1,
                                 "begin_time": 0, "end_time": 1000, "sentence_end": True}),
    ])
    pending = [ws1, ws2]
    monkeypatch.setattr(websocket, "create_connection",
                        lambda *a, **k: pending.pop(0) if pending else _FakeWS([]))

    segs = []
    be = FunAsrBackend(api_key="sk-x", model="fun-asr-mtl-realtime", language="zh",
                       on_segment=segs.append)
    be.start()
    be.feed(b"\x00\x01" * 100)  # 喂过音频 → 非空、非 stopping
    deadline = time.time() + 5
    while time.time() < deadline and not any(s.seg_id == "funasr#1#1" for s in segs):
        time.sleep(0.02)
    be.stop()

    seg_ids = {s.seg_id for s in segs}
    assert "funasr#0#1" in seg_ids   # 第一代（重连前）的句子
    assert "funasr#1#1" in seg_ids   # 中途 task-finished 后重起、续录出的句子
    assert len(pending) == 0          # 确实重连建立了第二个连接


def test_language_hints_auto_uses_model_supported_set():
    """auto：多语种模型给整套支持语言作 hint（中/粤/英/日/泰/越/印尼）；中英日模型给中英日。"""
    mtl = FunAsrBackend(api_key="sk-x", model="fun-asr-mtl-realtime", language="auto")
    assert mtl._language_hints() == ["zh", "yue", "en", "ja", "th", "vi", "id"]
    realtime = FunAsrBackend(api_key="sk-x", model="fun-asr-realtime", language="auto")
    assert realtime._language_hints() == ["zh", "en", "ja"]
    # 显式选语言：原样作单一 hint（即便模型多语种）
    one = FunAsrBackend(api_key="sk-x", model="fun-asr-mtl-realtime", language="yue")
    assert one._language_hints() == ["yue"]


def test_feed_gated_until_task_started():
    # 连接/重连后未收到 task-started 前不喂：服务端会丢弃这些帧 → 转录空洞。就绪后才喂。
    be = FunAsrBackend(api_key="sk-x", model="fun-asr-mtl-realtime", language="auto")
    fake = _FakeWS([])
    be._ws = fake
    be._started_event.clear()
    be.feed(b"\x00\x01" * 100)
    assert fake.sent_binary == []        # 未就绪 → 不喂
    be._started_event.set()
    be.feed(b"\x00\x01" * 100)
    assert len(fake.sent_binary) == 1    # 就绪 → 喂


def test_reconnect_backoff_gives_up_after_repeated_failures(monkeypatch):
    """连不上时退避重试，连续失败超上限 → 上报致命并放弃（与 qwen 共用 base 退避治理）。"""
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(websocket, "create_connection", boom)
    errs = []
    be = FunAsrBackend(api_key="sk-x", on_segment=lambda s: None, on_error=errs.append)
    be._RECONNECT_MAX_FAILS = 3
    be._RECONNECT_MAX_DELAY_S = 0.0  # 退避归零，测试不阻塞
    assert be._try_reconnect("boom") is False
    assert errs and "网络持续不可用" in errs[0]
