"""实时字幕历史存储 + 录制器契约。

锁住：① 记录往返（save→load）；② 列表按创建时间倒序；③ 搜索命中名称/正文；④ 删除；
⑤ 导出 SRT/TXT；⑥ 录制器写 WAV + 收集段落 + finalize 成可加载记录、空会话丢弃。
"""

import wave

from videocaptioner.core.realtime.events import CaptionEntry
from videocaptioner.core.realtime.recording.history import (
    CaptionSegment,
    LiveCaptionRecord,
    LiveCaptionStore,
)
from videocaptioner.core.realtime.recording.recorder import SessionRecorder


def _record(rid="20260617-164900", name="2026-06-17 16:49 记录", created=1_700_000_000.0):
    return LiveCaptionRecord(
        id=rid, name=name, source="系统声音", translate="微软翻译",
        created_at=created, duration=6.0, audio="",
        segments=[
            CaptionSegment(0.0, 3.0, "Hello everyone", "大家好"),
            CaptionSegment(3.0, 6.0, "How are you", "你好吗"),
        ],
    )


def test_save_and_load_round_trip(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    rec = _record()
    store.save(rec)
    loaded = store.load(rec.id)
    assert loaded is not None
    assert loaded.name == rec.name and loaded.source == "系统声音"
    assert len(loaded.segments) == 2
    assert loaded.segments[0].source == "Hello everyone"
    assert loaded.segments[1].target == "你好吗"
    assert loaded.dir == store.dir_for(rec.id)


def test_list_sorted_newest_first(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    store.save(_record("20260101-000000", "老记录", created=1_000.0))
    store.save(_record("20260617-164900", "新记录", created=2_000.0))
    ids = [r.id for r in store.list()]
    assert ids == ["20260617-164900", "20260101-000000"]


def test_search_matches_name_and_body(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    store.save(_record("20260101-000000", "会议纪要", created=1_000.0))
    store.save(_record("20260102-000000", "随便", created=2_000.0))
    assert [r.id for r in store.search("会议")] == ["20260101-000000"]
    # 正文命中（英文/中文都可）
    assert [r.id for r in store.search("大家好")] == ["20260102-000000", "20260101-000000"][:2]
    assert len(store.search("everyone")) == 2
    assert store.search("不存在的词") == []


def test_delete_removes_dir(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    rec = _record()
    store.save(rec)
    assert store.dir_for(rec.id).is_dir()
    store.delete(rec.id)
    assert not store.dir_for(rec.id).exists()
    assert store.load(rec.id) is None


def test_rename_changes_name_only_keeps_folder(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    rec = _record()
    store.save(rec)
    folder = store.dir_for(rec.id)
    out = store.rename(rec.id, "  改名后  ")
    assert out is not None and out.name == "改名后"  # 去空白
    assert store.dir_for(rec.id) == folder and folder.is_dir()  # 文件夹（id）不变
    assert store.load(rec.id).name == "改名后"  # 落盘生效
    # 空名 / 不存在的 id 不改动、返回 None
    assert store.rename(rec.id, "   ") is None
    assert store.load(rec.id).name == "改名后"
    assert store.rename("nope", "x") is None


def test_export_srt_and_txt(tmp_path):
    rec = _record()
    srt = rec.export_srt(bilingual=True)
    assert "00:00:00,000 --> 00:00:03,000" in srt
    assert "Hello everyone\n大家好" in srt
    assert srt.strip().startswith("1\n")
    txt = rec.export_txt(bilingual=False)
    assert txt == "Hello everyone\nHow are you"


def test_labels():
    rec = _record(created=1_700_000_000.0)
    rec.duration = 378.0  # 6 分 18 秒
    assert rec.duration_label == "06:18"
    assert rec.summary == "06:18 · 系统声音 · 微软翻译"


def _entry(seg_id, seq, source, target="", final=True, started_at=0.0):
    return CaptionEntry(
        seg_id=seg_id, seq=seq, source_text=source, source_stable_len=len(source),
        target_text=target, is_final=final, started_at=started_at,
    )


def test_recorder_writes_wav_and_collects_segments(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    rec = SessionRecorder(store, "麦克风", "微软翻译", when=1_700_000_000.0)
    # 起点取「该句首现时已录音频位置」（WAV 偏移），故两句间各写 1s 让偏移区分开。
    rec.write_pcm(b"\x00\x00" * 16000)  # 1s 16k/mono/s16le 静音
    rec.note_caption(_entry("voxgate#0", 0, "Hello", "你好", started_at=1_700_000_000.2))
    rec.write_pcm(b"\x00\x00" * 16000)  # +1s → 共 2s
    rec.note_caption(_entry("voxgate#1", 1, "World", "世界", started_at=1_700_000_000.6))
    # 译文回填：同 seg_id 覆盖
    rec.note_caption(_entry("voxgate#1", 1, "World", "世界！", started_at=1_700_000_000.6))
    record = rec.finalize()
    assert record is not None
    assert record.source == "麦克风" and record.translate == "微软翻译"
    assert abs(record.duration - 2.0) < 0.05
    assert [s.source for s in record.segments] == ["Hello", "World"]
    assert record.segments[1].target == "世界！"  # 取最新译文
    assert record.segments[0].start < record.segments[1].start  # 1.0 < 2.0（WAV 偏移）
    # WAV 真写了、可读
    assert record.audio_path is not None and record.audio_path.is_file()
    with wave.open(str(record.audio_path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
    # 存盘后能从 store 加载回来
    assert store.load(record.id) is not None


def test_recorder_discards_empty_session(tmp_path):
    store = LiveCaptionStore(root=tmp_path)
    rec = SessionRecorder(store, "麦克风", "原文记录")
    rec.write_pcm(b"\x00\x00" * 100)
    assert rec.finalize() is None  # 没有任何句子 → 丢弃
    assert store.list() == []


def test_migrate_legacy_root_moves_records(tmp_path, monkeypatch):
    """旧 APPDATA/live_captions 一次性迁入工作目录：新目录不存在 + 旧有内容 → 整体移过去。"""
    from videocaptioner.core.realtime.recording import history

    legacy = tmp_path / "legacy"
    (legacy / "20260101-000000").mkdir(parents=True)
    monkeypatch.setattr(history, "_LEGACY_ROOT", legacy)
    new_root = tmp_path / "work" / "live-caption"
    history.migrate_legacy_root(new_root)
    assert (new_root / "20260101-000000").is_dir()  # 记录迁过去
    assert not legacy.exists()                        # 旧目录已移走（幂等：下次不再迁）


def test_migrate_legacy_root_skips_when_new_exists(tmp_path, monkeypatch):
    """新目录已存在 → 绝不迁移/覆盖（保护用户已有记录）。"""
    from videocaptioner.core.realtime.recording import history

    legacy = tmp_path / "legacy"
    (legacy / "old").mkdir(parents=True)
    monkeypatch.setattr(history, "_LEGACY_ROOT", legacy)
    new_root = tmp_path / "work" / "live-caption"
    (new_root / "existing").mkdir(parents=True)
    history.migrate_legacy_root(new_root)
    assert legacy.exists()                   # 旧目录原封不动
    assert not (new_root / "old").exists()   # 没迁入
    assert (new_root / "existing").is_dir()  # 已有记录不受影响
