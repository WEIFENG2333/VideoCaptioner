# -*- coding: utf-8 -*-
"""实时字幕转录流线程：core 层 :class:`LiveCaptionSession` 的 Qt 薄壳。

core 无 Qt 依赖；本线程只把会话的回调桥接成 Qt 信号，并把 ``WorkerThread`` 的
协作取消接到音频泵。识别/翻译事件可能来自后端接收线程或翻译线程，经 Qt 信号
自动跨线程投递到 GUI 线程。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.realtime.backends.base import LiveCaptionError
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.realtime.recording.history import LiveCaptionStore
from videocaptioner.core.realtime.session import LiveCaptionSession
from videocaptioner.ui.thread.worker import WorkerThread


class LiveCaptionThread(WorkerThread):
    """驱动一次实时字幕会话。"""

    # 一条字幕（新增/更新/定稿/译文回填），UI 按 entry.seg_id upsert
    caption = pyqtSignal(object)  # CaptionEntry
    # 后端连接状态变化（TranscriberState 的字符串值）
    stateChanged = pyqtSignal(str)
    # 会话结束并存盘后发出已保存的 LiveCaptionRecord（无内容则不发）
    recorded = pyqtSignal(object)
    # 实时拾音电平（0~1），驱动会话页波形/「有没有听到声音」指示
    level = pyqtSignal(float)

    def __init__(
        self, config: LiveCaptionConfig, store: Optional[LiveCaptionStore] = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store  # 录制存盘用，与宿主历史列表共用同一 root（工作目录下）
        self._session: Optional[LiveCaptionSession] = None

    def _work(self) -> None:
        session = LiveCaptionSession(
            self._config,
            on_caption=self._emit_caption,
            on_state=lambda s: self.stateChanged.emit(s.value),
            on_record=self.recorded.emit,
            on_level=self.level.emit,
            store=self._store,
        )
        self._session = session
        session.start()
        try:
            session.pump(self.checkpoint)  # 阻塞直到 stop / 取消 / 致命失败
        finally:
            session.stop()
        # 用户主动停止（取消）时，收尾里产生的错误（如对空缓冲 commit 报「empty buffer」）
        # 不是真失败，绝不上抛——否则 error 信号回到槽里抛异常会让 PyQt 直接 abort 整个程序。
        # 只有「非用户取消」的致命失败（如并发配额满）才作为终态上抛、弹一条提示。
        if session.fatal_error and not self.is_cancel_requested():
            raise LiveCaptionError(session.fatal_error)

    def stop(self, wait_ms: int = 22000) -> None:
        # 退出时 closeEvent 走阻塞 stop()。会话收尾是串行的、预算大（音频 ~5s + voxgate EOF
        # 冲刷末句 ~10s + 翻译 drain ~6s），基类默认 3s 会在收尾半途 terminate() 硬杀
        # （WAV 未关、记录未存）。给足等待，terminate 只作真卡死的最后兜底。
        super().stop(wait_ms=wait_ms)

    def _on_cancel(self) -> None:
        # 非阻塞：只让 pump 尽快退出（request_stop 不做收尾）；真正的链路收尾在
        # _work 的 finally 里、跑在本线程上，绝不阻塞调用方(GUI)线程。
        session = self._session
        if session is not None:
            session.request_stop()

    def set_paused(self, paused: bool) -> None:
        """暂停/恢复喂音频（GUI 线程调用，线程安全）。"""
        session = self._session
        if session is not None:
            session.set_paused(paused)

    def _emit_caption(self, entry: CaptionEntry) -> None:
        self.caption.emit(entry)
