"""一次实时字幕会话的编排：音频采集 + 转录后端 + 装配器。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Optional, Union

from videocaptioner.core.realtime import factory
from videocaptioner.core.realtime.audio.capture import AudioCapture

if TYPE_CHECKING:
    from videocaptioner.core.realtime.audio.system_mac import MacSystemAudioCapture
from videocaptioner.core.realtime.backends.base import LiveTranscriber, TranscriberState
from videocaptioner.core.realtime.caption import CaptionAssembler, OnCaption
from videocaptioner.core.realtime.config import LiveCaptionConfig, LiveCaptionSource
from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.realtime.recording.history import LiveCaptionRecord, LiveCaptionStore
from videocaptioner.core.realtime.recording.recorder import SessionRecorder
from videocaptioner.core.translate.types import TranslatorType
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_session")

OnState = Callable[[TranscriberState], None]
OnError = Callable[[str], None]
OnRecord = Callable[[LiveCaptionRecord], None]

_TRANSLATE_LABELS = {
    TranslatorType.BING: "微软翻译",
    TranslatorType.GOOGLE: "谷歌翻译",
}


def _source_label(cfg: LiveCaptionConfig) -> str:
    return "系统声音" if cfg.source == LiveCaptionSource.SYSTEM else "麦克风"


def _translate_label(cfg: LiveCaptionConfig) -> str:
    if not cfg.translate_enabled:
        return "原文记录"
    return _TRANSLATE_LABELS.get(cfg.translator_type, "AI 翻译")


def _rms_level(pcm: bytes) -> float:
    """把一块 s16le PCM 折算成 0~1 的音量电平（给会话页波形/拾音指示用）。"""
    if not pcm:
        return 0.0
    import numpy as np

    a = np.frombuffer(pcm, dtype=np.int16)
    if a.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) / 32768.0
    return min(1.0, rms * 4.0)  # 语音 RMS 偏小，放大让电平条更直观


class LiveCaptionSession:
    def __init__(
        self,
        config: LiveCaptionConfig,
        on_caption: OnCaption,
        on_state: Optional[OnState] = None,
        on_error: Optional[OnError] = None,
        on_record: Optional[OnRecord] = None,
        on_level: Optional[Callable[[float], None]] = None,
        store: Optional[LiveCaptionStore] = None,
        record_enabled: bool = True,
    ) -> None:
        self._config = config
        self._on_caption = on_caption
        self._on_state = on_state
        self._on_error = on_error
        self._on_record = on_record
        self._on_level = on_level
        self._store = store if store is not None else LiveCaptionStore()
        self._record_enabled = record_enabled

        self._backend: Optional[LiveTranscriber] = None
        self._audio: Optional[Union[AudioCapture, "MacSystemAudioCapture"]] = None
        self._assembler: Optional[CaptionAssembler] = None
        self._translator_fn = None
        self._recorder: Optional[SessionRecorder] = None
        self._debug = None  # LiveDebugTap（VC_DEBUG=live 时；落原生事件/PCM/字幕便于排查）

        self._paused = False
        self._stopped = False  # 让 pump 尽快退出（request_stop 置位）
        self._torn_down = False  # 链路是否已收尾（stop 的幂等标记，与 _stopped 解耦）
        self._fatal_error: Optional[str] = None

    @property
    def fatal_error(self) -> Optional[str]:
        """后端致命失败（如并发配额满）的消息；非 None 表示会话已不可用。"""
        return self._fatal_error

    # ----- 生命周期 -----

    def start(self) -> None:
        cfg = self._config

        translate_fn = factory.build_translate_fn(cfg)
        self._translator_fn = translate_fn
        # 录制器：把音频录成 WAV、收集段落，结束时存成可回放的历史记录（无内容自动丢弃）。
        if self._record_enabled:
            self._recorder = SessionRecorder(
                self._store, _source_label(cfg), _translate_label(cfg)
            )

        # 调试落盘（VC_DEBUG=live 或全开时）：原生事件 + 喂送 PCM + 装配器输出，便于排查。
        from videocaptioner.core.realtime.recording.debug_tap import LiveDebugTap
        from videocaptioner.core.utils.debug import debug_enabled
        if debug_enabled("live"):
            try:
                self._debug = LiveDebugTap(time.strftime("%Y%m%d-%H%M%S"))
            except Exception:
                logger.exception("实时字幕调试落盘初始化失败（忽略）")

        recorder = self._recorder
        debug = self._debug
        ui_caption = self._on_caption

        def assembler_caption(entry: CaptionEntry) -> None:
            if recorder is not None:
                recorder.note_caption(entry)
            if debug is not None:
                debug.caption(entry)
            ui_caption(entry)

        self._assembler = CaptionAssembler(assembler_caption, translate_fn)

        self._backend = factory.build_backend(
            cfg,
            on_segment=self._assembler.ingest,
            on_state=self._forward_state,
            on_error=self._forward_error,
        )
        if self._debug is not None:  # 后端把原生事件原文回调出来落盘
            self._backend.on_raw = self._debug.raw_event

        # 先开采集（入队缓冲），再起后端（voxgate 自起子进程 / fun-asr 连云端）。
        # macOS 原生系统声音走 ScreenCaptureKit 子进程；否则走 PortAudio 输入设备。
        if cfg.system_audio_native:
            from videocaptioner.core.realtime.audio.system_mac import MacSystemAudioCapture

            self._audio = MacSystemAudioCapture()
        else:
            self._audio = AudioCapture(device_index=cfg.device_index)
        self._audio.start()
        self._backend.start()

    def pump(self, cancel_check: Callable[[], None]) -> None:
        """阻塞音频泵：读 PCM → 喂后端，直到 stop / 取消。"""
        assert self._audio is not None and self._backend is not None
        while not self._stopped and self._fatal_error is None:
            cancel_check()  # 取消点：抛 WorkerCancelled
            chunk = self._audio.read(timeout=0.1)
            if chunk is None:
                continue
            if not self._paused:
                self._backend.feed(chunk)
                if self._on_level is not None:
                    self._on_level(_rms_level(chunk))
                if self._recorder is not None:
                    self._recorder.write_pcm(chunk)
                if self._debug is not None:
                    self._debug.pcm(chunk)

    def request_stop(self) -> None:
        """非阻塞：只置停止标记让 pump 尽快退出；真正的链路收尾在 _work 的 finally。"""
        self._stopped = True

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def stop(self) -> None:
        # 用独立的 _torn_down 幂等，不能复用 _stopped：request_stop 已把 _stopped 置 True，
        # 若以 _stopped 为门会跳过整段收尾，残余回调向已销毁浮窗 emit 致硬 abort。
        if self._torn_down:
            return
        self._torn_down = True
        self._stopped = True
        audio, backend = self._audio, self._backend
        if audio is not None:
            audio.stop()  # 先停采集（不再有新帧入队）
            # 停后端前排空队列残留尾音，否则 pump 未拉完的尾巴被丢弃 → 末句被截。
            if backend is not None:
                while True:
                    chunk = audio.read(timeout=0.0)
                    if chunk is None:
                        break
                    backend.feed(chunk)
                    if self._recorder is not None:
                        self._recorder.write_pcm(chunk)
                    if self._debug is not None:
                        self._debug.pcm(chunk)
        if backend is not None:
            backend.stop()
        if self._assembler is not None:
            self._assembler.close()
        if self._translator_fn is not None:
            close = getattr(self._translator_fn, "__self__", None)
            if close is not None and hasattr(close, "close"):
                close.close()
        # 录制收尾：后端/装配器已 flush 末段（is_final），此时段落齐全；存盘并回调（空则丢弃）。
        if self._recorder is not None:
            recorder, self._recorder = self._recorder, None
            try:
                record = recorder.finalize()
            except Exception:
                logger.exception("保存实时字幕记录失败")
                record = None
            if record is not None and self._on_record is not None:
                self._on_record(record)
        if self._debug is not None:
            self._debug.close()  # 调试落盘收尾（flush + 打印路径）

    # ----- 回调转发 -----

    def _forward_state(self, state: TranscriberState) -> None:
        if self._on_state is not None:
            self._on_state(state)

    def _forward_error(self, message: str) -> None:
        # 后端致命失败：latch 后让 pump 尽快退出，由上层（线程）作为终态处理并停链路。
        self._fatal_error = message
        if self._on_error is not None:
            self._on_error(message)
