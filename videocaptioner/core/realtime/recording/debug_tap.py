"""实时字幕调试落盘（``VC_DEBUG=live`` 时启用；默认不实例化，主链路零开销）。

每次会话把三路原始数据写进 ``APPDATA/live_captions/_debug/{ts}/``，用于离线定位
截断/卡住/清空出在后端、装配器还是 UI：后端原生事件 ``backend_events.ndjson``、
实际喂送 PCM ``fed_audio.wav``、装配器 emit ``captions.jsonl``。
"""

from __future__ import annotations

import json
import threading
import wave
from typing import Optional

from videocaptioner import config
from videocaptioner.core.realtime.backends.base import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_debug")


class LiveDebugTap:
    """把后端原生事件 / 喂送 PCM / 装配器输出三路落盘，便于离线核对原始事件流。线程安全。"""

    def __init__(self, ts: str) -> None:
        self.dir = config.APPDATA_PATH / "live_captions" / "_debug" / ts
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events = open(self.dir / "backend_events.ndjson", "w", encoding="utf-8")
        self._caps = open(self.dir / "captions.jsonl", "w", encoding="utf-8")
        self._wav: Optional[wave.Wave_write] = None
        try:
            self._wav = wave.open(str(self.dir / "fed_audio.wav"), "wb")
            self._wav.setnchannels(CHANNELS)
            self._wav.setsampwidth(SAMPLE_WIDTH)
            self._wav.setframerate(SAMPLE_RATE)
        except Exception:
            logger.debug("调试 WAV 打开失败", exc_info=True)
        logger.info("实时字幕调试落盘已开启：%s", self.dir)

    def raw_event(self, line: str) -> None:
        """后端原生事件原文（voxgate 一行 protocol 报文 / fun-asr 一条消息 JSON）。"""
        with self._lock:
            try:
                self._events.write(line.rstrip("\n") + "\n")
                self._events.flush()
            except Exception:
                pass

    def pcm(self, chunk: bytes) -> None:
        """实际喂给后端的一块 PCM。"""
        if self._wav is None:
            return
        try:
            self._wav.writeframes(chunk)
        except Exception:
            pass

    def caption(self, entry: CaptionEntry) -> None:
        """装配器 emit 的一条 CaptionEntry。"""
        with self._lock:
            try:
                self._caps.write(
                    json.dumps(
                        {
                            "seg_id": entry.seg_id,
                            "seq": entry.seq,
                            "source": entry.source_text,
                            "stable_len": entry.source_stable_len,
                            "target": entry.target_text,
                            "is_final": entry.is_final,
                            "started_at": entry.started_at,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                self._caps.flush()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            for f in (self._events, self._caps):
                try:
                    f.close()
                except Exception:
                    pass
            if self._wav is not None:
                try:
                    self._wav.close()
                except Exception:
                    pass
        logger.info("实时字幕调试落盘已保存：%s", self.dir)
