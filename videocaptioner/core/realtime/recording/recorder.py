from __future__ import annotations

import threading
import time
import wave
from typing import Dict, List, Optional

from videocaptioner.core.realtime.backends.base import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.realtime.recording.history import (
    AUDIO_NAME,
    CaptionSegment,
    LiveCaptionRecord,
    LiveCaptionStore,
)


class SessionRecorder:
    """录一次会话：写 WAV + 收集段落 → :class:`LiveCaptionRecord`。线程安全。"""

    def __init__(
        self,
        store: LiveCaptionStore,
        source_label: str,
        translate_label: str,
        when: Optional[float] = None,
    ) -> None:
        self._store = store
        self._created_at = when if when is not None else time.time()
        self._id = store.make_id(self._created_at)
        self._name = store.display_name(self._created_at)
        self._source_label = source_label
        self._translate_label = translate_label
        self._t0 = self._created_at  # entry.started_at 转相对秒的基准
        self._dir = store.create_dir(self._id)
        self._lock = threading.Lock()
        self._frames = 0
        self._segs: Dict[str, dict] = {}  # seg_id -> {seq, start, source, target}
        self._finalized = False
        self._wav: Optional[wave.Wave_write] = None
        try:
            wav = wave.open(str(self._dir / AUDIO_NAME), "wb")
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            self._wav = wav
        except Exception:
            self._wav = None

    # ----- 采集 -----

    def write_pcm(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            if self._wav is not None:
                try:
                    self._wav.writeframes(pcm)
                    self._frames += len(pcm) // (SAMPLE_WIDTH * CHANNELS)
                except Exception:
                    pass

    def note_caption(self, entry: CaptionEntry) -> None:
        """记录段落最新文本（同 seg_id 覆盖，含译文回填）+ 首现时定下的相对起点。

        起点用已录音频位置（frames/采样率 = 该句在 WAV 里的偏移）：与回放对齐、≤ 总时长、且暂停
        感知（暂停期不录则 frames 不前进）；无音频时回退墙钟相对秒。刻意不用后端 start_time：
        Fun-ASR begin_time 重连后每 task 归零、句内还会漂移，会让详情页点句全跳到开头。
        """
        with self._lock:
            if self._wav is not None:
                start = self._frames / float(SAMPLE_RATE)  # WAV 偏移
            else:
                start = max(0.0, entry.started_at - self._t0)  # 回退墙钟相对秒
            cur = self._segs.get(entry.seg_id)
            if cur is None:
                self._segs[entry.seg_id] = {
                    "seq": entry.seq,
                    "start": start,
                    "source": entry.source_text,
                    "target": entry.target_text,
                }
            else:
                if entry.source_text:
                    cur["source"] = entry.source_text
                if entry.target_text:
                    cur["target"] = entry.target_text

    # ----- 状态 -----

    @property
    def duration(self) -> float:
        return self._frames / float(SAMPLE_RATE) if self._frames else 0.0

    # ----- 收尾 -----

    def finalize(self) -> Optional[LiveCaptionRecord]:
        """收尾：关 WAV、整理段落、存盘并返回记录；无内容则删目录返回 None。幂等。"""
        with self._lock:
            if self._finalized:
                return None
            self._finalized = True
            self._close_wav()
            dur = self.duration
            ordered = sorted(self._segs.values(), key=lambda s: s["seq"])
            segments: List[CaptionSegment] = []
            for i, s in enumerate(ordered):
                if not (s["source"].strip() or s["target"].strip()):
                    continue
                # 段终点 = 下一段起点（末段取总时长），并把 start/end 钳进 [0, dur]：
                # 保证点句落在区间内、cue 不越界或重叠。
                nxt = ordered[i + 1]["start"] if i + 1 < len(ordered) else dur
                start = min(s["start"], dur) if dur else s["start"]
                end = min(nxt, dur) if dur else nxt
                # 末句在 stop 期才首现时 start 会被钉到 ≈dur 而退化成零长 cue（点句直接跳结尾）：
                # 回退到上一段终点，保证仍是可点击的非零区间。
                if start >= end and segments:
                    start = segments[-1].end
                segments.append(
                    CaptionSegment(start=start, end=max(end, start),
                                   source=s["source"], target=s["target"])
                )
            has_audio = self._frames > 0
        if not segments:
            self._store.delete(self._id)
            return None
        record = LiveCaptionRecord(
            id=self._id,
            name=self._name,
            source=self._source_label,
            translate=self._translate_label,
            created_at=self._created_at,
            duration=dur,
            audio=AUDIO_NAME if has_audio else "",
            segments=segments,
        )
        self._store.save(record)
        return record

    def _close_wav(self) -> None:
        if self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass
            self._wav = None
