"""硬字幕提取主流程：抽帧 → 变化检测 → 变化点 OCR → 去重合并 → 时间轴 → ASRData。

只在字幕变化点 OCR（靠 ROI 灰度差分跳过保持帧），把 OCR 次数压到字幕条数级。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.hardsub.config import HardsubConfig, HardsubProgress
from videocaptioner.core.hardsub.frames import grab_frame, iter_roi_rgb, probe_dimensions
from videocaptioner.core.hardsub.region import centered_segments
from videocaptioner.core.ocr.base import OcrEngine, OcrLine
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("hardsub_pipeline")

OnCue = Callable[["HardsubCue"], None]
OnProgress = Callable[[HardsubProgress], None]
ShouldCancel = Callable[[], bool]

# 判硬切（无空白间隔的连切新句）时，新读与当前读都得「足够自信」才算真换句，
# 否则淡入淡出的低置信残字会被误判成新句。
_STABLE_CONF = 0.85

# 段内按「单框自身中心偏移 > 此值」从两端剔偏心框（两侧卡片标题/角标）。比段级 center_tolerance 宽：
# 字幕被 OCR 拆成几块时每块自身也略偏，要留住这些半块。
_BOX_CENTER_TOL = 0.45

# 单框行（完整一行、无拆块）的居中门，比段级 center_tolerance 严：整行字幕几乎总居中，偏置的署名/角标
# 虽未达拆块容差仍明显偏心，在此剔除。
_LINE_CENTER_TOL = 0.25

# 帧内相对字号门：同一帧里字高 < 最大行 × 此比例的次要行被剔（双语英文译文≈0.7×主行）。
# 比绝对字号门稳：同帧主/次比例恒定，不受 fh 估计或逐帧测高抖动影响。
_SECONDARY_LINE_RATIO = 0.8

# 提取阶段 OCR 检测输入最长边上限，小于区域检测的 960：提取 ROI 已贴字幕、字号大，768 更快且质量不降
# （区域检测对分辨率敏感不可用，见 rapid.py）。
EXTRACT_DET_LIMIT = 768


@dataclass
class HardsubCue:
    """一条提取出的字幕：起止时间（秒）+ 多行文本（按从上到下排序，中英分行天然保留）。"""

    start: float
    end: float
    lines: list[str] = field(default_factory=list)
    score: float = 0.0
    stable_ocr: bool = False  # 是否已在「稳定帧」补过一次 OCR（那帧最干净）

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def consider(self, cand_lines: list[str], score: float) -> None:
        """用更干净的一次识别替换：优先置信度（稳定帧 ≈1.0、淡帧偏低），接近时取更完整（更长）。"""
        cand_len = sum(len(x) for x in cand_lines)
        cur_len = sum(len(x) for x in self.lines)
        if (round(score, 2), cand_len) > (round(self.score, 2), cur_len):
            self.lines = cand_lines
            self.score = score


def default_bottom_roi(width: int, height: int) -> tuple[int, int, int, int]:
    """硬字幕先验默认带：底部 ~18% 高、左右各留 5%。自动检测/手动框选未给时的兜底。"""
    x = int(width * 0.05)
    w = int(width * 0.90)
    y = int(height * 0.78)
    h = int(height * 0.18)
    return x, y, w, h


def extract_hardsub(
    config: HardsubConfig,
    engine: OcrEngine,
    on_cue: Optional[OnCue] = None,
    on_progress: Optional[OnProgress] = None,
    should_cancel: Optional[ShouldCancel] = None,
) -> ASRData:
    """跑完整提取，流式回调每条字幕，返回 :class:`ASRData`（已按时间排序、过滤空段）。"""
    dims = probe_dimensions(config.video_path)
    if dims is None:
        raise ValueError(f"无法读取视频信息：{config.video_path}")
    width, height, _, duration = dims
    roi = config.roi or default_bottom_roi(width, height)
    _, _, roi_w, roi_h = roi
    area = max(1, roi_w * roi_h)
    change_pixels = max(80, int(area * config.change_area_ratio))
    blank_pixels = max(40, int(area * config.blank_area_ratio))
    # 字号门 + 居中门只在自动检测区域时启用（自动 ROI 近全宽，需挑主导字号、挡两侧异号杂质）；
    # 手动框选/--roi 指定区域时所见即所得，不二次过滤。
    if config.roi_is_manual:
        font_height: Optional[float] = None
        center_tol = float("inf")  # 不按居中过滤
    else:
        # 优先复用区域检测顺带学到的主导字号；缺失时(默认带/未给)才独立采样现学。
        font_height = (
            config.font_height if config.font_height is not None
            else _dominant_font_height(engine, config.video_path, roi, config.center_tolerance)
        )
        center_tol = config.center_tolerance

    cues: list[HardsubCue] = []
    active: Optional[HardsubCue] = None
    prev: Optional[np.ndarray] = None
    ocr_calls = 0
    last_emit_pct = -1

    def finalize() -> None:
        """定稿在途字幕：end 取「最后一次出现的帧」+ 一个采样间隔（否则系统性偏早半个间隔）。"""
        nonlocal active
        if active is None:
            return
        active.end += config.sample_interval
        if active.lines and (active.end - active.start) >= config.min_duration:
            cues.append(active)
            if on_cue is not None:
                on_cue(active)
        active = None

    for t, frame in iter_roi_rgb(config.video_path, roi, config.sample_interval):
        if should_cancel is not None and should_cancel():
            break
        # 变化/空白检测用绿通道近似亮度（廉价）；OCR 喂原 RGB（灰度会丢白色描边字的对比度）。
        gray = frame[:, :, 1]

        # 1) 近似均匀帧 = 字幕空档：收尾在途字幕，跳过 OCR（保守，只命中真·空白带）。
        if _is_blank(gray, blank_pixels):
            if active is not None:
                finalize()
            prev = gray
            _emit(on_progress, t, duration, len(cues), ocr_calls)
            continue

        # 2) 与上一帧几乎相同 = 字幕保持：延长当前条不 OCR（性能核心）；稳定后补一次 OCR（无淡入残影最干净）。
        if prev is not None and active is not None and not _changed(prev, gray, change_pixels):
            active.end = t
            if not active.stable_ocr:
                active.stable_ocr = True
                ocr_calls += 1
                slines = _read_lines(
                    engine, frame, config.conf_threshold, center_tol, font_height
                )
                if slines:
                    active.consider([s for s, _ in slines], _mean_score(slines))
            prev = gray
            continue

        # 3) 变化点：真正 OCR（用 RGB 原帧）。
        ocr_calls += 1
        lines = _read_lines(
            engine, frame, config.conf_threshold, center_tol, font_height
        )
        prev = gray
        if not lines:
            # 字幕消失 → 收尾在途条。
            if active is not None:
                finalize()
            _emit(on_progress, t, duration, len(cues), ocr_calls)
            continue

        cand_lines = [line for line, _ in lines]
        text_norm = _norm("".join(cand_lines))
        score = sum(s for _, s in lines) / len(lines)

        # 同一显示块（时间紧邻、中间无空白）默认并入，不靠相似度（淡入残字相似度低会误分裂）；
        # 仅紧邻出现「高置信且与当前相似度很低」的文本才判硬切（无空白的连切新句）。
        same_block = active is not None and t - active.end <= config.merge_gap
        hard_cut = False
        if same_block:
            sim = _similar(text_norm, _norm("".join(active.lines)))
            hard_cut = (
                sim < config.text_sim_threshold
                and score >= _STABLE_CONF
                and active.score >= _STABLE_CONF
            )

        if same_block and not hard_cut:
            active.end = t
            active.consider(cand_lines, score)
            active.stable_ocr = False  # 内容仍在变（淡入），稳定后再补一次干净 OCR
        else:
            finalize()
            active = HardsubCue(start=t, end=t, lines=cand_lines, score=score)

        pct = int(t / duration * 100) if duration > 0 else 0
        if pct != last_emit_pct or on_progress is None:
            last_emit_pct = pct
            _emit(on_progress, t, duration, len(cues), ocr_calls)

    finalize()
    logger.info("硬字幕提取完成：%d 条字幕，OCR %d 次", len(cues), ocr_calls)
    return cues_to_asrdata(cues)


def cues_to_asrdata(cues: list[HardsubCue]) -> ASRData:
    """HardsubCue（秒）→ ASRData（毫秒整数段）。"""
    segs = [
        ASRDataSeg(cue.text, int(round(cue.start * 1000)), int(round(cue.end * 1000)))
        for cue in cues
        if cue.text.strip()
    ]
    return ASRData(segs)


def _mean_score(lines: list[tuple[str, float]]) -> float:
    return sum(s for _, s in lines) / len(lines) if lines else 0.0


def _dominant_font_height(
    engine: OcrEngine,
    video_path: str,
    roi: tuple[int, int, int, int],
    center_tolerance: float,
    n: int = 12,
) -> Optional[float]:
    """全局学「主导字幕字号」：采样 ROI 带内若干帧，取居中文字段高度里加权最大的那类（中位）。

    字幕字号整段稳定为一类，计数/时长/角标/译文等明显更小——据此挡掉小字杂质。学不到返回 None。
    """
    dims = probe_dimensions(video_path)
    if dims is None:
        return None
    duration = dims[3]
    x, y, w, h = roi
    half_w = max(1.0, w / 2.0)
    times = [duration * (i + 0.5) / n for i in range(n)] if duration > 0 else [0.0]
    heights: list[float] = []
    for t in times:
        frame = grab_frame(video_path, t)
        if frame is None:
            continue
        crop = frame[y : y + h, x : x + w]
        try:
            boxes = engine.detect(crop)
        except Exception:  # noqa: BLE001
            continue
        if not boxes:
            continue
        line_h = float(np.median([b[3] - b[1] for b in boxes])) or 1.0
        for seg in centered_segments(boxes, half_w, line_h, center_tolerance):
            heights.append(max(b[3] for b in seg) - min(b[1] for b in seg))
    if not heights:
        return None
    hs = sorted(heights)
    clusters: list[list[float]] = [[hs[0]]]
    for v in hs[1:]:
        if v > clusters[-1][-1] * 1.4:   # 字号跳变 >40% → 另一类字号
            clusters.append([v])
        else:
            clusters[-1].append(v)
    # 主导字号类：按 出现次数 × 字号 加权，偏向次数多且字号大的主字幕行（双语取原文行、混剪取大歌词）。
    best = max(clusters, key=lambda c: len(c) * float(np.median(c)))
    return float(np.median(best))


def _center_offset(seg: list[OcrLine], half_w: float) -> float:
    """一段框整体的水平中心偏移（0=正中，1=贴边）：(左缘+右缘)/2 距画面中心的归一化距离。"""
    cx = (seg[0].bbox[0] + seg[-1].bbox[2]) / 2.0
    return abs(cx - half_w) / half_w


def _trim_offcenter_ends(seg: list[OcrLine], half_w: float, box_tol: float) -> list[OcrLine]:
    """按 x 排序的一段框，反复剔除「自身中心」偏离画面中心 > ``box_tol`` 的端框，只剔两端、中间不动。

    两侧卡片标题/角标常与字幕同字号、同行紧挨，段级中心拦不住（混入后整段仍近居中）；但它们自身偏在
    两侧，按单框偏移从两端剔即可，又保住被 OCR 拆成几块、每块都靠中心的真字幕。
    """
    bs = list(seg)
    while len(bs) > 1:
        loff = abs((bs[0].bbox[0] + bs[0].bbox[2]) / 2.0 - half_w) / half_w
        roff = abs((bs[-1].bbox[0] + bs[-1].bbox[2]) / 2.0 - half_w) / half_w
        if loff >= roff and loff > box_tol:
            bs = bs[1:]
        elif roff > box_tol:
            bs = bs[:-1]
        else:
            break
    return bs


def _read_lines(
    engine: OcrEngine,
    image: np.ndarray,
    conf_threshold: float,
    center_tolerance: float = 1.0,
    font_height: Optional[float] = None,
) -> list[tuple[str, float]]:
    """OCR 一帧 → 居中的文字行 [(文本, 置信度)]，从上到下。

    按 cy 聚行 → 行内按「> ~2 行高的横向间隙」切段 → 段内修剪两端偏心框 → 留下「居中 + 属于全局
    主导字号」的段。``center_tolerance >= 1`` 关闭居中过滤（手动框选所见即所得 / 测试），
    ``font_height=None`` 关闭字号过滤。
    """
    result = engine.recognize(image)
    kept: list[OcrLine] = [ln for ln in result if ln.score >= conf_threshold and ln.text.strip()]
    if not kept:
        return []
    line_h = float(np.median([ln.height for ln in kept])) or 20.0
    half_w = max(1.0, image.shape[1] / 2.0)
    kept.sort(key=lambda ln: ln.cy)
    rows: list[list[OcrLine]] = []
    for ln in kept:
        if rows and abs(ln.cy - rows[-1][-1].cy) <= line_h * 0.6:
            rows[-1].append(ln)
        else:
            rows.append([ln])

    out: list[tuple[float, str, float, float]] = []  # (cy, text, score, seg_h)
    for row in rows:
        row.sort(key=lambda ln: ln.bbox[0])
        seg: list[OcrLine] = [row[0]]
        segments: list[list[OcrLine]] = []
        for ln in row[1:]:
            if ln.bbox[0] - seg[-1].bbox[2] > line_h * 2.0:
                segments.append(seg)
                seg = [ln]
            else:
                seg.append(ln)
        segments.append(seg)
        centering_on = center_tolerance < 1.0
        for s in segments:
            if centering_on:
                # 修剪两端偏心框；若修剪后反不居中（被 OCR 拆成两半的居中长句会被误剪），回退原段兜底。
                trimmed = _trim_offcenter_ends(s, half_w, _BOX_CENTER_TOL)
                cand = trimmed if (trimmed and _center_offset(trimmed, half_w) <= center_tolerance) else s
                # 单框行用更严的居中门（剔偏置署名/角标）；多框行可能是拆开的居中长句，用 center_tolerance。
                seg_tol = min(_LINE_CENTER_TOL, center_tolerance) if len(cand) == 1 else center_tolerance
                if not cand or _center_offset(cand, half_w) > seg_tol:
                    continue
                s = cand
            seg_h = max(ln.bbox[3] for ln in s) - min(ln.bbox[1] for ln in s)
            # 全局字号门：段高在主导字号 0.75–1.7× 内才算同字幕字号；更小的译文/计数/角标被挡。
            if font_height and not (font_height * 0.75 <= seg_h <= font_height * 1.7):
                continue
            # 段内只取主导字号的框（字幕一行字号一致；异常大小的覆盖框不算）
            med_h = float(np.median([ln.height for ln in s])) or 1.0
            core = [ln for ln in s if 0.5 * med_h <= ln.height <= 1.8 * med_h] or s
            text = " ".join(ln.text.strip() for ln in core)
            score = sum(ln.score for ln in core) / len(core)
            out.append((s[0].cy, text, score, seg_h))
    # 帧内相对字号门：只留本帧最大字号那一档，比它小一档的次要行（中英双语的英文译文≈0.7×主行）剔除。
    # 比绝对字号门稳——同帧主/次行比例恒定，不受 fh 估计误差或英文逐帧测高抖动影响（治忽中忽英）。
    if font_height and out:
        max_h = max(h for *_, h in out)
        out = [c for c in out if c[3] >= max_h * _SECONDARY_LINE_RATIO]
    out.sort(key=lambda x: x[0])
    return [(text, score) for _, text, score, _h in out]


def _changed(prev: np.ndarray, cur: np.ndarray, area_thr: int) -> bool:
    """两帧 ROI 灰度的「不同像素」数是否达到阈值（纯 numpy，单帧 < 1ms）。"""
    diff = np.abs(cur.astype(np.int16) - prev.astype(np.int16))
    return int(np.count_nonzero(diff > 25)) >= area_thr


def _is_blank(gray: np.ndarray, blank_thr: int) -> bool:
    """ROI 是否近似无文字：偏离中值较多的「前景像素」极少。保守判定，避免误杀有字帧。"""
    median = float(np.median(gray))
    fg = int(np.count_nonzero(np.abs(gray.astype(np.int16) - median) > 35))
    return fg < blank_thr


def _norm(text: str) -> str:
    """归一化用于相似度比较：去所有空白（OCR 空格不稳定）。"""
    return "".join(text.split())


def _similar(a: str, b: str) -> int:
    """文本相似度 0-100。优先 rapidfuzz，退化到标准库 difflib。"""
    if not a and not b:
        return 100
    try:
        from rapidfuzz import fuzz
        return int(fuzz.ratio(a, b))
    except Exception:  # noqa: BLE001
        from difflib import SequenceMatcher
        return int(SequenceMatcher(None, a, b).ratio() * 100)


def _emit(
    on_progress: Optional[OnProgress], t: float, duration: float, cue_count: int, ocr_calls: int
) -> None:
    if on_progress is not None:
        on_progress(HardsubProgress(t, duration, cue_count, ocr_calls))
