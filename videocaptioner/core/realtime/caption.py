"""把后端**已分段**的转录装配成双语字幕（:class:`CaptionEntry`）并按 ``seg_id`` upsert。

分段是后端的职责（voxgate 按 VAD、fun-asr 按句），本装配器不切段，只做三件事：双色
（后端改写未定文本，最长公共前缀=已听准/亮，尾巴=修正中/暗，定稿整段转亮）、翻译（定稿强制翻
一次，当前段节流翻译，译文用同一 ``seg_id`` 回填）、定稿守卫（段 ``is_final`` 后忽略迟到更新）。

当前段与它定稿后的历史段共享 ``seg_id``，「当前 → 历史」在 UI 端是同一条目的状态翻转。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as _futures_wait
from typing import Callable, Dict, List, Optional, Set, Tuple

from videocaptioner.core.realtime.events import CaptionEntry, TranscriptSegment
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_assembler")

# 当前段翻译节流（秒）：新段首帧立即翻一次，其后按节流。
_ACTIVE_TRANSLATE_INTERVAL = 0.4

# 翻译并发度：高延迟 LLM（一句几秒）下，定稿句必须并发翻译才追得上语速；串行（1）会越落越远。
_TR_WORKERS = 4

# 非内容字符（纯标点/空白）：纯标点段不该单独成卡片。
_NONCONTENT = set("。．.!?！？…，,、；;：:　 \t\r\n")

OnCaption = Callable[[CaptionEntry], None]
TranslateFn = Callable[[str], str]


def _noop_caption(_entry: CaptionEntry) -> None:
    """close 后替换 on_caption：在飞的翻译任务再 emit 也落到这里，杜绝投递到已销毁浮窗。"""


def _has_content(text: str) -> bool:
    """是否含「真内容」（除标点/空白外的字符）。纯标点段不该单独成卡片。"""
    return any(ch not in _NONCONTENT for ch in text)


def _common_prefix_len(a: str, b: str) -> int:
    """最长公共前缀长度。后端改写未定文本（非纯追加），公共前缀即稳定段（亮），其后为修正中（暗）。"""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class CaptionAssembler:
    """按 ``seg_id`` upsert 的双色 + 异步翻译装配器（不做分段，分段在后端）。"""

    def __init__(
        self,
        on_caption: OnCaption,
        translate_fn: Optional[TranslateFn] = None,
    ) -> None:
        self._on_caption = on_caption
        self._translate = translate_fn
        self._lock = threading.RLock()

        # 序号 / 起始时间：按 seg_id 分配一次，跨更新保持稳定
        self._seq = 0
        self._meta: Dict[str, Tuple[int, float]] = {}  # seg_id -> (seq, started_at_epoch)
        self._prev: Dict[str, str] = {}  # seg_id -> 上一帧源文（算 stable_len）
        self._entries: Dict[str, CaptionEntry] = {}  # seg_id -> 最新 entry（译文回填）
        self._final: Set[str] = set()  # 已定稿段：忽略其后更新/译文
        self._last_active: Optional[str] = None  # 最近未定稿段（异常停止时 close 补定稿）

        # 翻译：并发线程池 + 防泛滥，适配高延迟 API（如 LLM，一句几秒）。
        # - 定稿句：每句去重提交到 N-worker 池并发翻译（串行会追不上语速），各句独立回填自己 seg_id。
        # - 当前（未定稿）句：预览翻译，全局限 1 个在飞 + 节流，在飞时新请求丢弃，
        #   防止「每 0.4s 一份当前句全文」灌爆池、把定稿句挤到饿死。
        self._last_tr: Dict[str, float] = {}        # 当前句翻译节流时刻
        self._final_submitted: Set[str] = set()      # 已提交翻译的定稿句（去重，防重复翻译）
        self._final_futures: List = []               # 在飞定稿翻译 future（close 限时 drain 用）
        self._active_inflight: Optional[str] = None   # 当前句在飞的那一句（限 1，防泛滥）
        self._closed = False
        self._pool = ThreadPoolExecutor(
            max_workers=_TR_WORKERS, thread_name_prefix="livecap-tr")

    # ----- 主入口：后端 on_segment -----

    def ingest(self, segment: TranscriptSegment) -> None:
        """消费一个后端段落事件（同 seg_id 多次=同段生长/改写）。线程：后端接收线程。"""
        with self._lock:
            if self._closed:
                return
            sid = segment.seg_id
            if sid in self._final and not segment.is_final:
                # 段已定稿：丢弃迟到的非 final 更新（防回退）；同句再来 is_final 则放行覆盖。
                return
            text = segment.text or ""
            if not _has_content(text):
                return  # 空 / 纯标点：不画当前段、定稿空段也直接丢
            prev = self._prev.get(sid, "")
            stable_len = len(text) if segment.is_final else _common_prefix_len(prev, text)
            entry = self._build(sid, text, stable_len, segment.is_final,
                                segment.start_time, segment.end_time)
            self._prev[sid] = text
            self._entries[sid] = entry
            if segment.is_final:
                self._final.add(sid)
                # 定稿后该句不再算双色前缀 / 不再节流翻译 → 清掉临时态，防长会话内存线性增长。
                # （_entries 不清：force 译文回填仍要读它。）
                self._prev.pop(sid, None)
                self._last_tr.pop(sid, None)
                if self._last_active == sid:
                    self._last_active = None
                if self._active_inflight == sid:
                    # 该句定稿后，它那条在飞的当前句翻译已作废，立即释放在飞名额，
                    # 别让下一句的预览翻译干等它空跑完。
                    self._active_inflight = None
            else:
                self._last_active = sid
            self._on_caption(entry)
            self._maybe_translate(entry, force=segment.is_final)

    # ----- 构造 / 翻译 -----

    def _build(self, seg_id: str, source: str, stable_len: int, is_final: bool,
               start_time: Optional[float], end_time: Optional[float]) -> CaptionEntry:
        seq, started_at = self._meta.get(seg_id, (None, None))
        if seq is None:
            seq = self._seq
            self._seq += 1
            started_at = time.time()  # 段落首次出现的真实时刻（UI 显示 HH:MM）
            self._meta[seg_id] = (seq, started_at)
        return CaptionEntry(
            seg_id=seg_id,
            seq=seq,
            source_text=source,
            source_stable_len=max(0, min(stable_len, len(source))),
            target_text="",
            is_final=is_final,
            started_at=started_at,
            start_time=start_time,
            end_time=end_time,
        )

    def _maybe_translate(self, entry: CaptionEntry, force: bool) -> None:
        # 持 self._lock 调用。定稿句并发提交（去重）；当前句节流 + 全局限 1 在飞（防泛滥）。
        if not self._translate:
            return
        sid = entry.seg_id
        if force:
            self._submit_final(sid)
            return
        now = time.monotonic()
        if sid in self._last_tr and now - self._last_tr[sid] < _ACTIVE_TRANSLATE_INTERVAL:
            return  # 节流：别逐字狂翻
        if self._active_inflight is not None or sid in self._final:
            return  # 已有当前句在飞（合并）/ 该句已定稿 → 不另起
        self._last_tr[sid] = now
        self._active_inflight = sid
        self._pool.submit(self._do_translate, sid, False)

    def _submit_final(self, sid: str) -> None:
        """提交定稿句翻译到并发池（每句一次，去重）。持 self._lock 调用。"""
        if sid in self._final_submitted:
            return
        self._final_submitted.add(sid)
        self._final_futures = [f for f in self._final_futures if not f.done()]  # 顺手清理已完成
        self._final_futures.append(self._pool.submit(self._do_translate, sid, True))

    def _do_translate(self, sid: str, is_final: bool) -> None:
        """池 worker：翻译该句最新源文并回填（定稿句并发、各自独立；当前句完成后释放在飞名额）。"""
        translate = self._translate
        try:
            with self._lock:
                if (self._closed and not is_final) or translate is None:
                    return
                entry = self._entries.get(sid)
                if entry is None or (not is_final and sid in self._final):
                    return
                source = entry.source_text
            if not source:
                return
            try:
                translated = translate(source)
            except Exception as exc:  # 网络/接口失败不应中断识别
                logger.debug("实时翻译失败（已忽略）：%s", exc)
                return
            if not translated:
                return
            with self._lock:
                if self._closed and not is_final:
                    return  # 收尾后只补定稿译文，当前句译文丢弃
                cur = self._entries.get(sid)
                if cur is None or (not is_final and sid in self._final):
                    return  # 翻译期间该句定稿 → 当前句译文作废（定稿译文为准）
                out = cur.with_target(translated)  # 用最新源文 + 新译文回填，源文绝不回退
                self._entries[sid] = out
                on_caption = self._on_caption
            on_caption(out)  # 出锁再 emit，避免持锁跨 Qt 信号
        finally:
            if not is_final:  # 释放「当前句在飞」名额，允许下一次节流请求翻最新当前句
                with self._lock:
                    if self._active_inflight == sid:
                        self._active_inflight = None

    def close(self) -> None:
        # 1) 异常停止（后端被杀 / 未收到末段定稿）时给最后未定稿段补一次定稿，避免历史丢末段。
        #    必须趁 _on_caption 仍是真回调时做（让 recorder 捕获），并提交它的定稿翻译。
        with self._lock:
            sid = self._last_active
            if sid is not None and sid not in self._final:
                cur = self._entries.get(sid)
                if cur is not None and _has_content(cur.source_text):
                    try:
                        final = self._build(sid, cur.source_text, len(cur.source_text),
                                            True, cur.start_time, cur.end_time)
                        self._final.add(sid)
                        self._entries[sid] = final
                        self._on_caption(final)
                        if self._translate is not None:
                            self._submit_final(sid)
                    except Exception:
                        pass
            pending = [f for f in self._final_futures if not f.done()]
        # 2) 限时 drain 在飞的定稿翻译，使保存的记录尽量带译文（_closed 仍 False、回调仍真，
        #    译文经 note_caption 落到 recorder）。并发池下多句并行，drain 很快。
        if pending:
            _futures_wait(pending, timeout=6.0)
        # 3) 收尾：换 no-op 回调（杜绝在飞任务再向已销毁浮窗 emit）。
        with self._lock:
            self._closed = True
            self._on_caption = _noop_caption
        self._pool.shutdown(wait=False)
