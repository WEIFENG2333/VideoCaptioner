# -*- coding: utf-8 -*-
"""实时字幕页：会话 / 历史 / 详情三视图的宿主。

视图（``ui/components/live_caption``）只呈现 + 发信号；本宿主编排开始/暂停/结束、桌面浮窗、
录制存盘（``LiveCaptionStore``）、历史与详情回放。线程回调经 Qt 信号 queued 回 GUI 线程。
"""

from __future__ import annotations

import time
from typing import List, Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import InfoBar, InfoBarPosition

from videocaptioner.core.realtime.audio.capture import AudioDevice, list_input_devices
from videocaptioner.core.realtime.audio.system_mac import system_audio_supported
from videocaptioner.core.realtime.backends.base import TranscriberState
from videocaptioner.core.realtime.config import LiveCaptionConfig, LiveCaptionSource
from videocaptioner.core.realtime.recording.history import (
    LiveCaptionRecord,
    LiveCaptionStore,
    default_root,
)
from videocaptioner.core.translate.types import TranslatorType
from videocaptioner.ui.common.config import (
    cfg,
    source_language_options,
)
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.app_dialog import ConfirmDialog, InputDialog
from videocaptioner.ui.components.caption_overlay import CaptionOverlay
from videocaptioner.ui.components.live_caption.views import (
    MODE_ENDED,
    MODE_ERROR,
    MODE_LIVE,
    MODE_PAUSED,
    MODE_READY,
    DetailView,
    HistoryView,
    SessionView,
    _fmt_pos,
)
from videocaptioner.ui.config_adapter import _llm_from_ui
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.live_caption_thread import LiveCaptionThread

_PAGE_SESSION, _PAGE_HISTORY, _PAGE_DETAIL = 0, 1, 2
_SYSTEM_AUDIO_INDEX = -2  # 「系统声音（本机播放）」合成项的设备索引（非真实设备，走 SCK 原生捕获）


def _clock(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class LiveCaptionInterface(QWidget):
    """实时字幕主页（三视图宿主）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("liveCaptionInterface")
        self.setWindowTitle(tr("live.title"))
        # 根背景走 palette.bg，否则面板浮在未着色底上像格格不入的色块。
        self.setStyleSheet(
            f"QWidget#liveCaptionInterface {{ background: {app_palette().bg}; }}"
        )

        # 实时字幕历史归入工作目录（用户工作产物）。旧 APPDATA 记录的一次性迁移放在 GUI 启动
        # （main.py）做，不在此处——否则任何构造本页的测试/smoke 都会误迁真实数据。
        self._store = LiveCaptionStore(root=default_root(cfg.get(cfg.work_dir)))
        self._thread: Optional[LiveCaptionThread] = None
        self._overlay: Optional[CaptionOverlay] = None
        self._retiring: List[LiveCaptionThread] = []
        self._starting = False
        self._devices: List[AudioDevice] = []
        self._session_start = 0.0
        self._elapsed = 0
        self._paused = False
        self._seen_segs: set = set()
        self._last_record: Optional[LiveCaptionRecord] = None
        self._got_record = False
        self._errored = False  # 本次会话是否以错误收场（阻止 finished 把错误页重置回就绪）
        self._records_cache: Optional[List[LiveCaptionRecord]] = None  # 历史列表内存缓存
        self._detail_from = _PAGE_SESSION  # 详情返回目标（来源页）

        self.session = SessionView(self)
        self.history = HistoryView(self)
        self.detail = DetailView(self)
        self._stack = QStackedWidget(self)
        for view in (self.session, self.history, self.detail):
            page = QWidget(self._stack)
            pl = QVBoxLayout(page)
            pl.setContentsMargins(26, 20, 26, 22)
            pl.addWidget(view)
            self._stack.addWidget(page)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._wire()
        self._init_settings_state()
        self._refresh_devices()
        self._refresh_recent()
        self.session.set_mode(MODE_READY)

    # ----- 接线 -----

    def _wire(self) -> None:
        s = self.session
        s.startClicked.connect(self._start)  # 错误态「重试」复用同一按钮
        s.pauseClicked.connect(self._pause)
        s.resumeClicked.connect(self._resume)
        s.stopClicked.connect(self._finish)
        s.newSessionClicked.connect(self._reset_ready)  # 结束态「新建会话」→ 回就绪
        s.historyClicked.connect(self._show_history)
        s.recordOpened.connect(self._show_detail)
        s.exportClicked.connect(self._export_current)
        s.configClicked.connect(self._open_config)
        s.deviceChanged.connect(self._on_device)
        s.translateToggled.connect(
            lambda on: cfg.set(cfg.live_caption_translate, on, save=True))
        s.targetLanguageChanged.connect(
            lambda lang: cfg.set(cfg.live_caption_target_language, lang, save=True))
        s.sourceLanguageChanged.connect(
            lambda v: cfg.set(cfg.live_caption_source_language, v, save=True))
        s.overlayToggled.connect(
            lambda on: cfg.set(cfg.live_caption_show_overlay, on, save=True))
        # 设置页切转录引擎 → 立即按新引擎刷新主页识别语言下拉（不同引擎支持的语言不同）。
        cfg.live_caption_provider.valueChanged.connect(self._refresh_source_languages)
        # 工作目录改了：无会话进行时立即把历史 store 指向新目录（有会话则等本次结束、下次启动）。
        cfg.work_dir.valueChanged.connect(self._on_work_dir_changed)

        h = self.history
        h.backClicked.connect(self._show_session)
        h.refreshClicked.connect(self._refresh_history)
        h.openDirClicked.connect(self._open_dir)
        h.recordOpened.connect(self._show_detail)
        h.renameRequested.connect(self._rename_record)
        h.exportRequested.connect(lambda r: self._export_record(r, "srt"))
        h.deleteRequested.connect(self._delete_record)
        h.searchChanged.connect(self._on_search)

        self.detail.backClicked.connect(self._back_from_detail)
        self.detail.homeClicked.connect(self._reset_ready)  # 详情「主页」→ 真正回到实时字幕初始首页
        self.detail.exportRequested.connect(self._export_detail)
        self.detail.openFolderRequested.connect(self._open_record_dir)

    def _init_settings_state(self) -> None:
        self.session.set_translate(cfg.get(cfg.live_caption_translate))
        self.session.set_overlay(cfg.get(cfg.live_caption_show_overlay))
        # 翻译语言（目标语言）：选项=TargetLanguage 枚举，标签用其中文 .value
        lang_opts = cfg.live_caption_target_language.validator.options
        self.session.set_target_languages(
            [(o, getattr(o, "value", str(o))) for o in lang_opts],
            cfg.get(cfg.live_caption_target_language),
        )
        self._refresh_source_languages()

    def _on_work_dir_changed(self) -> None:
        """工作目录变更：无会话进行时把历史 store 重指向新目录并刷新；有会话则保持本次不变。"""
        if self._thread is not None:
            return
        self._store = LiveCaptionStore(root=default_root(cfg.get(cfg.work_dir)))
        self._records_cache = None
        self._refresh_recent()

    def _refresh_source_languages(self) -> None:
        """重填识别语言下拉：语言集随转录引擎而变。已存语言不在新引擎支持集时落库回退 auto。"""
        provider = cfg.get(cfg.live_caption_provider)
        options = source_language_options(provider)
        current = cfg.get(cfg.live_caption_source_language)
        if current not in {code for code, _ in options}:
            current = "auto"
            cfg.set(cfg.live_caption_source_language, current, save=True)
        self.session.set_source_languages(options, current)

    def showEvent(self, event) -> None:
        # 回到本页时按当前引擎刷新识别语言列表（构造时填的可能已过时）。
        self._refresh_source_languages()
        super().showEvent(event)

    # ----- 设备 -----

    def _refresh_devices(self) -> None:
        try:
            self._devices = list_input_devices()
        except Exception:
            self._devices = []
        items: List[tuple] = [(-1, tr("live.device.default_input"))]
        # macOS：原生「系统声音」（ScreenCaptureKit，免装 BlackHole）。其它平台仍靠选回环设备。
        if system_audio_supported():
            items.append((_SYSTEM_AUDIO_INDEX, tr("live.device.system_audio")))
        for dev in self._devices:
            tag = tr("live.device.default_tag") if dev.is_default else ""
            items.append((dev.index, f"{dev.name}{tag}"))
        current = cfg.get(cfg.live_caption_device_index)
        self.session.set_devices(items, current)

    def _on_device(self, index) -> None:
        cfg.set(cfg.live_caption_device_index, index, save=True)

    # ----- 导航 -----

    def _show_session(self) -> None:
        self._stack.setCurrentIndex(_PAGE_SESSION)

    def _reset_ready(self) -> None:
        """回到初始首页：停回放、清当前转录、就绪态、刷新最近、切会话页。「新建会话」与详情「主页」共用。"""
        self.detail.stop_playback()
        self._got_record = False
        self._last_record = None
        self.session.set_current_record(None)
        self.session.transcript.clear()
        self.session.set_mode(MODE_READY)
        self._refresh_recent()
        self._show_session()

    def _show_history(self) -> None:
        self._refresh_history()
        self._stack.setCurrentIndex(_PAGE_HISTORY)

    def _show_detail(self, record: LiveCaptionRecord) -> None:
        fresh = self._store.load(record.id) or record
        self.detail.load(fresh)
        # 返回目标只取 历史/会话，不能是详情页本身（否则返回是 no-op = 死按钮）
        self._detail_from = (
            _PAGE_HISTORY if self._stack.currentIndex() == _PAGE_HISTORY else _PAGE_SESSION
        )
        self._stack.setCurrentIndex(_PAGE_DETAIL)

    def _back_from_detail(self) -> None:
        self.detail.stop_playback()
        self._stack.setCurrentIndex(getattr(self, "_detail_from", _PAGE_SESSION))

    def _open_config(self) -> None:
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            window.openSettingsPage("live-caption")

    def _open_dir(self) -> None:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        self._store.root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._store.root)))

    def _open_record_dir(self) -> None:
        """详情「打开文件夹」：打开该条记录自己的目录。"""
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        rec = self.detail._record
        if rec is None:
            return
        path = self._store.dir_for(rec.id)
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ----- 历史 -----

    def _records(self, *, refresh: bool = False) -> List[LiveCaptionRecord]:
        """历史记录列表（内存缓存，让搜索过滤不必每次按键都扫盘）。增删改后传 refresh=True 失效重载。"""
        if refresh or self._records_cache is None:
            self._records_cache = self._store.list()
        return self._records_cache

    def _refresh_recent(self) -> None:
        self.session.set_recent(self._records(refresh=True))

    def _refresh_history(self) -> None:
        self.history.set_records(self._records(refresh=True))

    def _on_search(self, text: str) -> None:
        self.history.set_records([r for r in self._records() if r.matches(text)])

    # 整行卡片在 mouseReleaseEvent 发 opened，行内按钮走 clicked；在这些处理器里直接 exec() 模态会
    # 错乱本次按下/释放的鼠标抓取（点重命名却误触整行 opened）。延一轮事件循环再弹框。
    def _rename_record(self, record: LiveCaptionRecord) -> None:
        QTimer.singleShot(0, lambda: self._do_rename(record))

    def _do_rename(self, record: LiveCaptionRecord) -> None:
        dlg = InputDialog(
            tr("live.rename.title"),
            text=record.name,
            placeholder=tr("live.rename.placeholder"),
            parent=self,
        )
        if dlg.exec():
            new_name = dlg.value()
            # 只改显示名，文件夹仍以时间戳 id 为不可变主键；名为空 / 未变则不动盘
            if new_name and new_name != record.name and self._store.rename(record.id, new_name):
                self._refresh_history()
                self._refresh_recent()

    def _delete_record(self, record: LiveCaptionRecord) -> None:
        QTimer.singleShot(0, lambda: self._do_delete(record))

    def _do_delete(self, record: LiveCaptionRecord) -> None:
        dlg = ConfirmDialog(
            tr("live.delete.title"),
            tr("live.delete.confirm", name=record.name),
            parent=self,
            danger=True,
        )
        if dlg.exec():
            self._store.delete(record.id)
            self._refresh_history()
            self._refresh_recent()

    def _export_record(self, record: LiveCaptionRecord, fmt: str) -> None:
        fresh = self._store.load(record.id) or record
        QTimer.singleShot(0, lambda: self._do_export(fresh, fmt))

    def _export_detail(self, fmt: str) -> None:
        if self.detail._record is not None:
            self._do_export(self.detail._record, fmt)

    def _export_current(self) -> None:
        if self._last_record is not None:
            self._do_export(self._last_record, "srt")

    def _do_export(self, record: LiveCaptionRecord, fmt: str) -> None:
        from PyQt5.QtWidgets import QFileDialog

        ext = "srt" if fmt == "srt" else "txt"
        suggested = f"{record.name}.{ext}"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("live.export.dialog_title"), suggested, f"{ext.upper()} (*.{ext})"
        )
        if not path:
            return
        content = record.export_srt() if fmt == "srt" else record.export_txt()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            InfoBar.success(tr("live.export.success"), path, duration=3500,
                            position=InfoBarPosition.BOTTOM, parent=self)
        except Exception as exc:
            InfoBar.error(tr("live.export.failed"), str(exc), duration=5000,
                          position=InfoBarPosition.BOTTOM, parent=self)

    # ----- 启停 -----

    def _build_config(self) -> LiveCaptionConfig:
        device_index = cfg.get(cfg.live_caption_device_index)
        native_system = device_index == _SYSTEM_AUDIO_INDEX  # macOS 原生系统声音（SCK）
        dev = next((d for d in self._devices if d.index == device_index), None)
        loopback = native_system or bool(dev and _looks_like_loopback(dev.name))
        # 随会话传下当前 LLM provider 的 key/base/model，否则「大模型翻译」会因环境变量未设置而报错。
        llm = _llm_from_ui(cfg)
        return LiveCaptionConfig(
            backend=cfg.get(cfg.live_caption_provider),
            voxgate_binary=cfg.get(cfg.live_caption_voxgate_binary),
            api_key=str(cfg.get(cfg.fun_asr_api_key) or "").strip(),
            asr_model=cfg.get(cfg.live_caption_fun_asr_model),
            source_language=cfg.get(cfg.live_caption_source_language),
            source=LiveCaptionSource.SYSTEM if loopback else LiveCaptionSource.MICROPHONE,
            device_index=None if device_index in (None, -1, _SYSTEM_AUDIO_INDEX) else int(device_index),
            system_audio_native=native_system,
            translate_enabled=cfg.get(cfg.live_caption_translate),
            translator_type=TranslatorType[cfg.get(cfg.live_caption_translator_service).name],
            target_language=cfg.get(cfg.live_caption_target_language),
            llm_model=llm.model or "gpt-4o-mini",
            llm_api_key=llm.api_key,
            llm_api_base=llm.api_base,
        )

    def _start(self) -> None:
        if self._starting or (self._thread is not None and self._thread.isRunning()):
            return
        self._starting = True
        self._elapsed = 0
        self._paused = False
        self._seen_segs.clear()
        self._got_record = False
        self._errored = False
        self.session.transcript.clear()
        name = LiveCaptionStore.display_name()
        self.session.set_record_title(name, tr("live.status.connecting_with_time"))
        self.session.set_timer("00:00", tr("live.status.connecting"))
        self.session.set_mode(MODE_LIVE)
        QTimer.singleShot(0, self._launch)

    def _launch(self) -> None:
        if not self._starting:
            return
        try:
            self._do_launch()
        except Exception as exc:
            self._starting = False
            self._teardown_thread()
            self.session.set_mode(MODE_ERROR)
            self.session.set_error(tr("live.error.start_failed"), str(exc))
            self.session.set_record_title(tr("live.error.start_failed"), tr("live.error.start_failed_desc"))
            return
        self._starting = False

    def _do_launch(self) -> None:
        config = self._build_config()
        self._session_start = time.time()

        overlay = None
        if cfg.get(cfg.live_caption_show_overlay):
            overlay = self._make_overlay()
        self._overlay = overlay

        thread = LiveCaptionThread(config, self._store, self)
        thread.caption.connect(self._on_caption)
        thread.stateChanged.connect(self._on_state)
        thread.error.connect(self._on_error)
        thread.level.connect(self.session.set_level)  # 拾音电平 → 会话页波形
        thread.recorded.connect(self._on_recorded)
        thread.finished.connect(self._on_finished)
        self._thread = thread
        self._timer.start()
        thread.start()

    def _make_overlay(self) -> CaptionOverlay:
        overlay = CaptionOverlay()
        overlay.set_display_mode(cfg.get(cfg.live_caption_display_mode))
        overlay.set_bg_style(cfg.get(cfg.live_caption_bg_style))
        overlay.apply_font_scale(cfg.get(cfg.live_caption_font_scale))
        saved_mode = cfg.get(cfg.live_caption_overlay_mode)
        overlay.set_mode(saved_mode)
        overlay.restore_size(
            saved_mode, cfg.get(cfg.live_caption_overlay_w), cfg.get(cfg.live_caption_overlay_h)
        )
        overlay.displayModeChanged.connect(
            lambda v: cfg.set(cfg.live_caption_display_mode, v, save=True))
        overlay.bgStyleChanged.connect(
            lambda v: cfg.set(cfg.live_caption_bg_style, v, save=True))
        overlay.fontScaleChanged.connect(
            lambda v: cfg.set(cfg.live_caption_font_scale, v, save=True))
        overlay.modeChanged.connect(
            lambda v: cfg.set(cfg.live_caption_overlay_mode, v, save=True))
        overlay.sizeChanged.connect(self._on_overlay_size)
        overlay.requestClose.connect(self._finish)
        overlay.pauseToggled.connect(self._on_overlay_pause)
        self._place_overlay(overlay)
        overlay.show()
        return overlay

    def _pause(self) -> None:
        if self._thread is not None:
            self._thread.set_paused(True)
        self._paused = True
        if self._overlay is not None:
            self._overlay.set_paused(True)
        self.session.set_mode(MODE_PAUSED)
        self.session.set_timer(_clock(self._elapsed), tr("live.status.paused"))

    def _resume(self) -> None:
        if self._thread is not None:
            self._thread.set_paused(False)
        self._paused = False
        if self._overlay is not None:
            self._overlay.set_paused(False)
        self.session.set_mode(MODE_LIVE)

    def _finish(self) -> None:
        """结束保存：停链路、立即给「保存中…」反馈并禁按钮防连点。收尾在工作线程异步进行，
        记录经 recorded 信号回来后切 ended（空会话丢弃）。"""
        if self._thread is None and not self._starting:
            return  # 已在收尾 / 未运行：忽略重复触发
        if self._thread is None and self._starting:
            # 启动窗口期（线程还没建）就点结束：直接复位回就绪。不能走 set_saving——
            # 没有线程就没有 finished/recorded 回来复位，会永久卡「保存中…」。
            self._starting = False
            self._timer.stop()
            self.session.set_mode(MODE_READY)
            return
        self.session.set_saving()  # 立即禁用按钮 + 提示「正在保存…」（非阻塞）
        self._timer.stop()
        self._teardown_thread()

    def _release_thread_and_overlay(self, *, blocking: bool) -> None:
        """统一拆线程 + 拆浮窗（_teardown_thread 与 closeEvent 共用，关键不变量只一处定义）。

        必须先断 线程→浮窗 的跨线程信号再销毁浮窗：收尾期间后端线程仍可能 emit，排队信号投递到
        已释放的浮窗 C++ 对象会硬 abort。blocking=True（退出）阻塞 stop 确保无 QThread 残留；
        blocking=False（会话内拆换）非阻塞 request_cancel + 退役队列，不卡 GUI。
        """
        thread = self._thread
        overlay = self._overlay
        self._thread = None
        self._overlay = None
        if thread is not None:
            self._disconnect_signals(thread)
            if blocking:
                thread.stop()
            else:
                thread.request_cancel()
                self._retiring.append(thread)
                thread.finished.connect(lambda t=thread: self._retire(t))
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()

    def _teardown_thread(self) -> None:
        self._starting = False
        self._release_thread_and_overlay(blocking=False)

    def _disconnect_signals(self, thread) -> None:
        """断开 线程→本页 的 caption 信号。只需断 caption：它是唯一触达浮窗的实时信号；
        thread.level 接的是 SessionView（存活期长于线程），浮窗不接 level。"""
        try:
            thread.caption.disconnect(self._on_caption)
        except (TypeError, RuntimeError):
            pass

    def _retire(self, thread: LiveCaptionThread) -> None:
        if thread in self._retiring:
            self._retiring.remove(thread)
        thread.deleteLater()

    # ----- 线程回调（GUI 线程）-----

    def _on_caption(self, entry) -> None:
        rel = max(0.0, entry.started_at - self._session_start)
        self.session.transcript.upsert(entry, rel, _fmt_pos)
        if self._overlay is not None:
            self._overlay.upsert_caption(entry)
        self._seen_segs.add(entry.seg_id)

    def _on_state(self, state: str) -> None:
        if state == TranscriberState.LISTENING.value and self._timer.isActive():
            if not self._paused:
                self.session.set_timer(_clock(self._elapsed), tr("live.status.recording"))

    def _on_recorded(self, record: LiveCaptionRecord) -> None:
        self._got_record = True
        self._last_record = record
        self.session.set_current_record(record)
        self.session.set_record_title(record.name, record.summary)
        self.session.set_timer(record.duration_label, tr("live.status.saved"))
        self.session.set_mode(MODE_ENDED)
        self._refresh_recent()

    def _on_finished(self) -> None:
        # 线程结束但没有产生记录（空会话）→ 回到就绪态；
        # 错误收场除外：error 信号先于 finished 到达，就绪态会把错误页盖掉（用户就什么都看不到了）
        if not self._got_record and not self._errored and self._stack.currentIndex() == _PAGE_SESSION:
            self.session.set_mode(MODE_READY)
            self.session.set_timer("00:00", tr("live.status.waiting"))
            self.session.set_record_title(tr("live.ready.title"), tr("live.ready.desc"))

    def _on_error(self, message: str) -> None:
        try:
            self._errored = True
            lowered = message.lower()
            if "quota" in lowered or "concurren" in lowered or "并发" in message:
                friendly = tr("live.error.concurrency_full")
            else:
                friendly = message
            self._timer.stop()
            self._teardown_thread()
            self.session.set_mode(MODE_ERROR)
            self.session.set_error(tr("live.error.start_failed"), friendly)
            self.session.set_record_title(tr("live.error.start_failed"), tr("live.error.transcribe_failed"))
        except Exception:
            import logging

            logging.getLogger("live_caption_ui").exception("处理实时字幕错误时异常（已忽略）")

    def _tick(self) -> None:
        if self._thread is None or self._paused:
            return
        self._elapsed += 1
        self.session.set_timer(_clock(self._elapsed), tr("live.status.recording"))
        self.session.set_record_title(
            LiveCaptionStore.display_name(self._session_start),
            tr("live.status.progress", time=_clock(self._elapsed), count=len(self._seen_segs)),
        )

    # ----- 浮窗 -----

    def _on_overlay_pause(self, paused: bool) -> None:
        if paused:
            self._pause()
        else:
            self._resume()

    def _on_overlay_size(self, cw: int, ch: int) -> None:
        cfg.set(cfg.live_caption_overlay_w, cw, save=True)
        cfg.set(cfg.live_caption_overlay_h, ch, save=True)

    def _place_overlay(self, overlay: CaptionOverlay) -> None:
        win = self.window().windowHandle()
        screen = win.screen() if win is not None else None
        if screen is None:
            from PyQt5.QtWidgets import QApplication

            screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        overlay.adjustSize()
        x = geo.center().x() - overlay.width() // 2
        y = geo.bottom() - overlay.height() - 120
        overlay.move(max(geo.left(), x), max(geo.top(), y))

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._release_thread_and_overlay(blocking=True)  # 退出走阻塞收尾，确保无 QThread 残留
        for t in list(self._retiring):
            t.stop()
        self._retiring.clear()
        super().closeEvent(event)


def _looks_like_loopback(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in ("blackhole", "loopback", "stereo mix", "立体声混音",
                                  "vb-audio", "soundflower", "系统", "voicemeeter"))
