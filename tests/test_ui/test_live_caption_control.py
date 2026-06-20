"""实时字幕页启停 + 崩溃防线契约（三视图宿主版）。

锁住：点了即时切到录制态、停止非阻塞且异步退役线程、销毁浮窗前先断开 caption
信号（否则收尾期排队信号投递到已释放浮窗 → 硬 abort）、暂停真停喂音频、退出阻塞收尾。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-livectl.toml")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from videocaptioner.ui.view import live_caption_interface as lci  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self.slots.clear()
            return
        if slot in self.slots:
            self.slots.remove(slot)
        else:
            raise TypeError("not connected")

    def emit(self, *a):
        for s in list(self.slots):
            s(*a)


class _FakeThread:
    """替身线程：记录调用，永远"在运行"，不真起后端。"""

    def __init__(self, config, store=None, parent=None):
        self.config = config
        self.store = store
        self.started = False
        self.cancelled = False
        self.stopped = False
        self.paused = None
        self._running = False
        for name in ("caption", "stateChanged", "error", "recorded", "finished", "level"):
            setattr(self, name, _Signal())

    def start(self):
        self.started = True
        self._running = True

    def isRunning(self):
        return self._running

    def request_cancel(self):
        self.cancelled = True
        self._running = False

    def stop(self, *a, **k):
        self.stopped = True
        self._running = False

    def set_paused(self, paused):
        self.paused = paused

    def deleteLater(self):
        self.deleted = True


@pytest.fixture()
def page(app, monkeypatch):
    monkeypatch.setattr(lci, "LiveCaptionThread", _FakeThread)
    p = lci.LiveCaptionInterface()
    yield p
    p._finish()
    p.deleteLater()


def test_start_switches_to_live_immediately_then_launches(page):
    page._start()
    assert page.session._mode == lci.MODE_LIVE  # 当帧就切录制态
    assert page._starting is True
    assert page._thread is None  # 线程构造推迟到下一轮事件循环
    QApplication.processEvents()
    assert page._starting is False
    assert page._thread is not None and page._thread.started is True


def test_pause_signal_is_wired_to_thread(page):
    page._start()
    QApplication.processEvents()
    overlay = page._overlay
    assert overlay is not None
    overlay._toggle_pause()  # 浮窗暂停 → 真停喂音频
    assert page._thread.paused is True
    overlay._toggle_pause()
    assert page._thread.paused is False


def test_finish_is_nonblocking_and_retires_thread(page):
    page._start()
    QApplication.processEvents()
    thread = page._thread
    page._finish()
    assert page._thread is None
    assert thread.cancelled is True and thread.stopped is False  # 非阻塞取消
    assert thread in page._retiring
    thread.finished.emit()
    QApplication.processEvents()
    assert thread not in page._retiring


def test_finish_disconnects_signals_before_teardown(page):
    page._start()
    QApplication.processEvents()
    thread = page._thread
    assert page._on_caption in thread.caption.slots

    page._finish()

    assert page._on_caption not in thread.caption.slots
    # 停止后后端线程仍可能 emit：现在落空、不触达已销毁浮窗、不崩
    from videocaptioner.core.realtime.events import CaptionEntry

    thread.caption.emit(CaptionEntry("s", 0, "x", 1, "", False, 0.0))


def test_restart_ignored_while_starting(page):
    page._start()
    assert page._starting is True
    page._start()  # 构造窗口内再点：忽略
    QApplication.processEvents()
    assert page._thread is not None and page._thread.started is True


def test_finish_during_starting_window_resets_to_ready(page):
    # 启动窗口期（singleShot 已排队、线程还没建）就点结束：必须复位回就绪，
    # 不能走 set_saving——否则没有线程触发 finished/recorded，会永久卡「保存中…」。
    page._start()
    assert page._starting is True and page._thread is None
    page._finish()
    assert page._starting is False
    assert page.session._mode == lci.MODE_READY
    QApplication.processEvents()  # 排队的 _launch 应空跑、不起线程
    assert page._thread is None
    assert page.session._mode == lci.MODE_READY


def test_close_event_blocks_for_clean_shutdown(page):
    page._start()
    QApplication.processEvents()
    thread = page._thread
    from PyQt5.QtGui import QCloseEvent

    page.closeEvent(QCloseEvent())
    assert thread.stopped is True  # 退出走阻塞 stop()
    assert page._thread is None


def test_finish_when_idle_is_safe(page):
    page._finish()  # 未运行就停：幂等、不崩
    assert page._thread is None


def test_recorded_signal_switches_to_ended(page, tmp_path):
    from videocaptioner.core.realtime.recording.history import LiveCaptionRecord
    from videocaptioner.ui.components.live_caption.views import MODE_ENDED

    page._start()
    QApplication.processEvents()
    rec = LiveCaptionRecord(id="x", name="记录", source="麦克风", translate="原文记录",
                            created_at=1.0, duration=12.0, audio="", segments=[])
    page._on_recorded(rec)
    assert page.session._mode == MODE_ENDED
    assert page._last_record is rec
