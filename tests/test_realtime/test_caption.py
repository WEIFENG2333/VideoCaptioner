"""CaptionAssembler 离线契约（无 Qt、无网络）。

分段在后端做（每段独立 seg_id）；装配器只做：按 seg_id upsert、双色(最长公共前缀)、
异步翻译回填、定稿守卫（定稿后忽略迟到的「当前段」更新，但允许 is_final 精修复述）、
close() 兜底定稿最后未定稿段。
"""

from videocaptioner.core.realtime.caption import CaptionAssembler
from videocaptioner.core.realtime.events import CaptionEntry, TranscriptSegment


def _collect():
    out: list[CaptionEntry] = []
    return out, out.append


def _seg(sid, text, final=False, st=None, et=None):
    return TranscriptSegment(sid, text, is_final=final, start_time=st, end_time=et)


class TestUpsert:
    def test_double_color_common_prefix(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "今天天气"))
        a.ingest(_seg("s0", "今天天气真不错"))  # 后端改写尾巴：公共前缀「今天天气」=稳定
        e = out[-1]
        assert e.seg_id == "s0" and not e.is_final
        assert e.source_text == "今天天气真不错"
        assert e.source_stable_len == 4  # 「今天天气」

    def test_final_marks_whole_stable_and_carries_timing(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "今天天气真不错", final=True, st=0.0, et=2.5))
        e = out[-1]
        assert e.is_final and e.source_stable_len == len("今天天气真不错")
        assert e.start_time == 0.0 and e.end_time == 2.5

    def test_distinct_seg_ids_get_increasing_seq(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "第一句", final=True))
        a.ingest(_seg("s1", "第二句"))
        seqs = {e.seg_id: e.seq for e in out}
        assert seqs["s0"] == 0 and seqs["s1"] == 1

    def test_finalized_seg_ignores_late_active_update(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "定稿文本", final=True))
        n = len(out)
        a.ingest(_seg("s0", "回退的临时文本"))  # 非 final 迟到更新 → 丢弃，防回退
        assert len(out) == n

    def test_finalized_seg_allows_final_polish(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "今天天气真不错", final=True))
        a.ingest(_seg("s0", "今天天气真不错。", final=True))  # is_final 精修复述 → 允许覆盖
        assert out[-1].source_text == "今天天气真不错。"

    def test_punctuation_only_skipped(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "，。 "))
        assert out == []

    def test_close_finalizes_last_active(self):
        out, cb = _collect()
        a = CaptionAssembler(cb)
        a.ingest(_seg("s0", "未定稿的话"))  # 后端没发 is_final 就停
        a.close()
        finals = [e for e in out if e.is_final]
        assert finals and finals[-1].source_text == "未定稿的话"


class TestTranslate:
    def test_final_force_translates_and_backfills(self):
        out, cb = _collect()
        a = CaptionAssembler(cb, translate_fn=lambda s: f"<{s}>")
        a.ingest(_seg("s0", "你好", final=True))
        a.close()  # 收尾会 drain 待译定稿句 → 等翻译落地
        assert any(e.target_text == "<你好>" for e in out)

    def test_finalized_seg_drops_late_active_translation(self):
        # 定稿段译文唯一且正确（定稿 force 译文为准）
        out, cb = _collect()
        a = CaptionAssembler(cb, translate_fn=lambda s: f"<{s}>")
        a.ingest(_seg("s0", "你好", final=True))
        a.close()
        targets = [e.target_text for e in out if e.target_text]
        assert targets and all(t == "<你好>" for t in targets)

    def test_active_then_final_translation(self):
        # 当前句先译（合并最新），定稿后定稿译文落地（覆盖当前句译文）
        out, cb = _collect()
        a = CaptionAssembler(cb, translate_fn=lambda s: f"<{s}>")
        a.ingest(_seg("s0", "今天"))            # 当前句
        a.ingest(_seg("s0", "今天天气真不错", final=True))  # 定稿
        a.close()
        finals = [e for e in out if e.is_final and e.target_text]
        assert finals and finals[-1].target_text == "<今天天气真不错>"

    def test_finals_translate_concurrently(self):
        # 定稿句并发翻译（非串行）：用 4-party 屏障——只有 ≥4 个翻译同时在飞才放行；串行则超时失败。
        import threading
        out, cb = _collect()
        barrier = threading.Barrier(4, timeout=5)

        def gated(s: str) -> str:
            barrier.wait()  # 并发度不足 → 超时抛 BrokenBarrierError → 该句译不出
            return f"<{s}>"

        a = CaptionAssembler(cb, translate_fn=gated)
        for i in range(4):
            a.ingest(_seg(f"s{i}", f"句{i}", final=True))
        a.close()
        finals = {e.seg_id for e in out if e.is_final and e.target_text}
        assert len(finals) == 4  # 4 句同时在飞翻译 → 屏障放行 → 全部译到（证明真并发）

    def test_high_latency_no_final_translation_lost(self):
        # 高延迟 API 下，定稿句快速连发也全部译到、一句不丢（旧实现会在停止时丢弃积压任务）。
        import time
        out, cb = _collect()

        def slow(s: str) -> str:
            time.sleep(0.03)  # 模拟高延迟翻译
            return f"<{s}>"

        a = CaptionAssembler(cb, translate_fn=slow)
        for i in range(8):  # 8 句飞快定稿（远快于翻译）
            a.ingest(_seg(f"s{i}", f"句子{i}", final=True))
        a.close()  # drain：把所有待译定稿句译完
        finals = {e.seg_id: e.target_text for e in out if e.is_final and e.target_text}
        assert len(finals) == 8  # 全部译到，无丢失
        assert all(finals[f"s{i}"] == f"<句子{i}>" for i in range(8))
