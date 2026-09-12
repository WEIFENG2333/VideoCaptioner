"""LiveCaptionSession 终态契约：后端致命失败 latch 后音频泵立即退出。

锁住"并发配额满之类的硬失败 → 停链路（不再挂在监听中空转）"的行为。
"""

from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.realtime.session import LiveCaptionSession


class _StubAudio:
    def __init__(self):
        self.stopped = 0

    def read(self, timeout=0.1):
        return None

    def stop(self):
        self.stopped += 1


class _StubBackend:
    def __init__(self):
        self.stopped = 0

    def feed(self, pcm):  # noqa: ANN001
        pass

    def stop(self):
        self.stopped += 1


class _StubAssembler:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_fatal_error_latches_and_pump_exits():
    session = LiveCaptionSession(LiveCaptionConfig(), on_caption=lambda e: None)
    session._audio = _StubAudio()
    session._backend = _StubBackend()

    assert session.fatal_error is None
    session._forward_error("StartSession failed (code=40200011): concurrency quota exceeded")
    assert session.fatal_error is not None

    # latch 已置位 → pump 不应阻塞，立即返回
    session.pump(cancel_check=lambda: None)


def test_no_fatal_error_means_clean_state():
    session = LiveCaptionSession(LiveCaptionConfig(), on_caption=lambda e: None)
    assert session.fatal_error is None


def test_stop_tears_down_even_after_request_stop():
    """崩溃根因回归：request_stop 让 pump 退出后，stop() 仍必须真正收尾。

    曾经 stop() `if self._stopped: return`，而 request_stop 已置 _stopped=True，导致音频/
    后端/装配器永不关闭——接收线程+音频回调+翻译池继续向已销毁浮窗 emit → 整程序崩。
    """
    session = LiveCaptionSession(LiveCaptionConfig(), on_caption=lambda e: None)
    audio, backend, asm = _StubAudio(), _StubBackend(), _StubAssembler()
    session._audio = audio
    session._backend = backend
    session._assembler = asm

    session.request_stop()  # 用户点停止：只让 pump 退出
    assert session._stopped is True

    session.stop()  # _work finally 里在工作线程上真正收尾
    assert audio.stopped == 1 and backend.stopped == 1 and asm.closed == 1

    session.stop()  # 幂等：再调不重复收尾
    assert audio.stopped == 1 and backend.stopped == 1 and asm.closed == 1


