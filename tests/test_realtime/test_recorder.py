"""录制器时间轴契约（无 Qt，写真实临时 WAV）。

锁住：段落起点用**已录音频位置**（WAV 偏移）而非后端 start_time / 墙钟——

- 后端 start_time 不可靠（Fun-ASR 重连后 begin_time 归零/漂移）→ 不采信。
- WAV 偏移天生暂停感知（暂停期不录、frames 不前进），恢复后段落不把暂停时长算进去；
  用墙钟（started_at-t0）则会把暂停时长算进去、超过总时长被钳到末尾 → 多段重叠、点句失效。
- start/end 钳进 [0, dur] 且 end=下一段起点 → 单调、不重叠、不越界（SRT 导出也据此）。
"""

from pathlib import Path

import pytest

from videocaptioner.core.realtime.backends.base import SAMPLE_RATE
from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.realtime.recording.history import LiveCaptionStore
from videocaptioner.core.realtime.recording.recorder import SessionRecorder


def _entry(seg_id, seq, src, tgt="", started_at=0.0):
    return CaptionEntry(
        seg_id=seg_id, seq=seq, source_text=src, source_stable_len=len(src),
        target_text=tgt, is_final=False, started_at=started_at,
    )


def _pcm(seconds):
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)  # 16k/mono/s16le 静音


def _rec(tmp_path):
    return SessionRecorder(LiveCaptionStore(root=Path(tmp_path)), "麦克风", "微软翻译", when=1000.0)


def test_start_is_wav_offset_not_backend_time(tmp_path):
    """段落起点 = 该句首现时已录音频的秒数（WAV 偏移），与回放对齐。"""
    r = _rec(tmp_path)
    r.write_pcm(_pcm(3))
    r.note_caption(_entry("s1", 0, "hello"))      # 已录 3s
    r.write_pcm(_pcm(5))
    r.note_caption(_entry("s2", 1, "world"))      # 已录 8s
    r.write_pcm(_pcm(2))                           # 共 10s
    rec = r.finalize()
    assert rec is not None
    assert [round(s.start, 1) for s in rec.segments] == [3.0, 8.0]
    assert rec.segments[0].end == pytest.approx(8.0, abs=0.05)          # = 下一段起点
    assert rec.segments[-1].end == pytest.approx(rec.duration, abs=0.05)  # 末段 → 总时长
    assert all(0.0 <= s.start <= s.end <= rec.duration + 1e-6 for s in rec.segments)


def test_pause_does_not_inflate_timeline(tmp_path):
    """暂停后段落起点不含暂停时长，不会被钳到末尾、不重叠（审查发现的真 bug 的回归测试）。"""
    r = _rec(tmp_path)
    r.write_pcm(_pcm(3))
    r.note_caption(_entry("s1", 0, "before", started_at=1003.0))
    # —— 暂停 100s：不写 PCM、无新 caption（无音频喂入）——
    r.write_pcm(_pcm(2))                            # 恢复后再录 2s → 共 5s
    # started_at 含了暂停的 100s（墙钟），但起点应取 WAV 偏移 5s
    r.note_caption(_entry("s2", 1, "after", started_at=1105.0))
    r.write_pcm(_pcm(2))                            # 共 7s，给末段留区间
    rec = r.finalize()
    starts = [round(s.start, 1) for s in rec.segments]
    assert starts == [3.0, 5.0]                     # 5.0 而非 105.0/被钳到 7.0
    assert starts[0] < starts[1]                    # 不重叠、不倒退、不堆叠
    assert all(s.start <= rec.duration for s in rec.segments)
    assert rec.segments[0].end <= rec.duration      # SRT 不越界


def test_end_covers_to_next_start_no_overlap(tmp_path):
    """每段终点 = 下一段起点；空段被跳过但仍是合法前向时间点，不产生重叠/倒退。"""
    r = _rec(tmp_path)
    r.write_pcm(_pcm(2))
    r.note_caption(_entry("a", 0, "first"))         # 2.0
    r.write_pcm(_pcm(3))
    r.note_caption(_entry("blank", 1, "   "))       # 5.0 但内容为空 → finalize 跳过
    r.write_pcm(_pcm(4))
    r.note_caption(_entry("c", 2, "third"))         # 9.0
    r.write_pcm(_pcm(1))                             # 共 10s
    rec = r.finalize()
    assert [s.source for s in rec.segments] == ["first", "third"]
    # a 的终点覆盖到被跳过的 blank 起点(5.0)，仍 < c 起点；全程单调
    assert rec.segments[0].end == pytest.approx(5.0, abs=0.05)
    assert all(rec.segments[i].start <= rec.segments[i + 1].start
               for i in range(len(rec.segments) - 1))


def test_no_audio_falls_back_to_wallclock(tmp_path):
    """没录到音频（WAV 建失败）时回退墙钟相对秒，SRT 时间轴仍可用、单调。"""
    r = _rec(tmp_path)
    r._wav = None  # 模拟录音不可用
    r.note_caption(_entry("s1", 0, "a", started_at=1002.0))
    r.note_caption(_entry("s2", 1, "b", started_at=1005.0))
    rec = r.finalize()
    assert [round(s.start, 1) for s in rec.segments] == [2.0, 5.0]
    assert rec.audio == ""  # 无音频


def test_translation_backfill_keeps_first_start(tmp_path):
    """译文/改写以同 seg_id 回填时，起点保持首现值不变。"""
    r = _rec(tmp_path)
    r.write_pcm(_pcm(4))
    r.note_caption(_entry("s1", 0, "hello"))                 # 首现 → 4.0
    r.write_pcm(_pcm(6))                                     # 又录 6s
    r.note_caption(_entry("s1", 0, "hello world", tgt="你好世界"))  # 回填，不应改起点
    rec = r.finalize()
    assert rec.segments[0].start == pytest.approx(4.0, abs=0.05)
    assert rec.segments[0].source == "hello world"
    assert rec.segments[0].target == "你好世界"
