"""自动检测字幕区域（字幕本质：1-3 行水平居中、位置稳定、内容随时间变的文字）。

采样 N 帧 → 每帧文本检测 → 聚成居中文字段 → 跨帧聚成行候选 → 按「时间稳定 + 内容在变 +
偏底部」打分选主行 → 并入相邻同字号居中行 → 输出原始分辨率 ROI（横向近全宽）。检测不到返回 None。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from videocaptioner.core.hardsub.frames import probe_dimensions, sample_frames
from videocaptioner.core.ocr.base import BBox, OcrEngine
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("hardsub_region")

Roi = tuple[int, int, int, int]


@dataclass
class RegionResult:
    """区域检测结果：ROI + 顺带学到的主导字幕字号（原始分辨率像素）。

    字号来自主行段高换算回原始分辨率，供提取复用、省掉再独立采样学一遍。
    """

    roi: Roi
    font_height: float

# 段中心偏移 ≤ 此比例(0=正中)才算居中。字幕几乎总居中，两侧台标/卡片偏心更大被滤。
CENTER_TOL = 0.34


@dataclass
class _Line:
    """一条候选字幕行（缩放坐标系）：跨帧的同垂直位置居中文字段聚合。"""

    cy: float
    top: float
    bottom: float
    frames_hit: int
    widths: list[float]
    centers_x: list[float]
    font: float = 0.0  # 该行文字段的中位高度（字号）；并入相邻行时要求字号相近


def centered_segments(
    boxes: list[BBox], half_w: float, line_h: float, center_tol: float = CENTER_TOL
) -> list[list[BBox]]:
    """一组文本框 → 「居中文字段」列表：按 cy 聚行 → 行内按 >2 行高的间隙切段 → 只留居中段。

    检测与提取共用此原语。段从上到下、段内从左到右。
    """
    if not boxes:
        return []
    items = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2.0)
    rows: list[list[BBox]] = []
    for b in items:
        cy = (b[1] + b[3]) / 2.0
        if rows and cy - (rows[-1][-1][1] + rows[-1][-1][3]) / 2.0 <= line_h * 0.6:
            rows[-1].append(b)
        else:
            rows.append([b])
    out: list[list[BBox]] = []
    for row in rows:
        row.sort(key=lambda b: b[0])
        seg = [row[0]]
        for b in row[1:]:
            if b[0] - seg[-1][2] > line_h * 2.0:
                _keep_if_centered(seg, half_w, center_tol, out)
                seg = [b]
            else:
                seg.append(b)
        _keep_if_centered(seg, half_w, center_tol, out)
    return out


def _keep_if_centered(
    seg: list[BBox], half_w: float, center_tol: float, out: list[list[BBox]]
) -> None:
    cx = (seg[0][0] + seg[-1][2]) / 2.0
    if abs(cx - half_w) / max(1.0, half_w) <= center_tol:
        out.append(seg)


def detect_subtitle_region(
    video_path: str,
    engine: OcrEngine,
    sample_count: int = 20,
    max_width: int = 960,
    on_progress: Optional[Callable[[int], None]] = None,
) -> Optional[RegionResult]:
    """返回字幕区域 :class:`RegionResult`（原始分辨率 ROI + 主导字号），检测不到返回 None。

    ``on_progress(percent)``：抽帧 0-25%，逐帧检测 25-95%（耗时主体）。
    """
    def _report(pct: int) -> None:
        if on_progress is not None:
            on_progress(max(0, min(100, pct)))

    _report(2)
    dims = probe_dimensions(video_path)
    if dims is None:
        return None
    orig_w, orig_h, _, _ = dims

    frames = sample_frames(video_path, sample_count, max_width)
    if len(frames) < 3:
        return None
    fh, fw = frames[0][1].shape[:2]
    num_frames = len(frames)
    half_w = fw / 2.0
    _report(25)

    # 1) 每帧检测，收集原始框（单遍 OCR）；顺带累积框高估行高（聚行/切段的尺度）。
    raw: list[tuple[int, list[BBox]]] = []
    heights: list[float] = []
    for idx, (_, frame) in enumerate(frames):
        try:
            boxes = engine.detect(frame)
        except Exception as exc:  # noqa: BLE001 — 个别帧失败不致命
            logger.debug("第 %d 帧检测失败：%s", idx, exc)
            boxes = []
        raw.append((idx, boxes))
        heights.extend(b[3] - b[1] for b in boxes)
        _report(25 + int((idx + 1) / num_frames * 70))
    line_h = float(np.median(heights)) if heights else fh * 0.06
    if line_h <= 1:
        line_h = fh * 0.06

    # 2) 每帧 → 居中文字段，记 (帧序, cy, top, bottom, width, cx)
    segs: list[tuple[int, float, float, float, float, float]] = []
    for idx, boxes in raw:
        for seg in centered_segments(boxes, half_w, line_h):
            top = min(b[1] for b in seg)
            bottom = max(b[3] for b in seg)
            left, right = seg[0][0], seg[-1][2]
            segs.append((idx, (top + bottom) / 2.0, top, bottom, right - left, (left + right) / 2.0))
    if not segs:
        return None

    # 3) 居中段按 cy 聚成「行候选」
    lines = _cluster_lines(segs, eps=line_h * 0.6)
    scored = sorted(((_score_line(ln, num_frames, fh), ln) for ln in lines), key=lambda x: -x[0])
    scored = [(s, ln) for s, ln in scored if s > 0]
    if not scored or scored[0][0] < 0.35:
        return None

    # 4) 选主行 + 并入相邻「同字号」居中行（同号多行字幕一起取，异号译文/角标不并入）。最多 3 行、总高 ≤22%。
    main = scored[0][1]
    band = [main]
    max_band = fh * 0.22
    while len(band) < 3:
        cur_top = min(ln.top for ln in band)
        cur_bot = max(ln.bottom for ln in band)
        chosen = None
        for _, ln in scored:
            if ln in band:
                continue
            gap = ln.top - cur_bot if ln.top >= cur_bot else (cur_top - ln.bottom if ln.bottom <= cur_top else 0.0)
            merged_h = max(cur_bot, ln.bottom) - min(cur_top, ln.top)
            same_font = abs(ln.font - main.font) <= main.font * 0.35
            if 0 <= gap <= line_h * 0.9 and merged_h <= max_band and same_font:
                chosen = ln
                break
        if chosen is None:
            break
        band.append(chosen)

    top = min(ln.top for ln in band)
    bottom = max(ln.bottom for ln in band)

    # 5) 横向近全宽（只定位垂直带，长短句都容得下）；上下留白；缩放 → 原始分辨率。
    pad = line_h * 0.3
    sx, sy = orig_w / fw, orig_h / fh
    x0 = max(0, int(fw * 0.02 * sx))
    x1 = min(orig_w, int(fw * 0.98 * sx))
    y0 = max(0, int((top - pad) * sy))
    y1 = min(orig_h, int((bottom + pad) * sy))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    # 主行段高(缩放系)换算回原始分辨率 = 主导字号，供提取复用。
    font_height = max(1.0, main.font * sy)
    return RegionResult((x0, y0, x1 - x0, y1 - y0), font_height)


def _cluster_lines(
    segs: list[tuple[int, float, float, float, float, float]], eps: float
) -> list[_Line]:
    """居中段按 cy 一维聚类成行候选。"""
    items = sorted(segs, key=lambda s: s[1])
    lines: list[_Line] = []
    cur: list[tuple[int, float, float, float, float, float]] = []
    last_cy: Optional[float] = None
    for s in items:
        if last_cy is not None and s[1] - last_cy > eps:
            lines.append(_make_line(cur))
            cur = []
        cur.append(s)
        last_cy = s[1]
    if cur:
        lines.append(_make_line(cur))
    return lines


def _make_line(items: list[tuple[int, float, float, float, float, float]]) -> _Line:
    return _Line(
        cy=float(np.median([s[1] for s in items])),
        top=float(np.percentile([s[2] for s in items], 10)),
        bottom=float(np.percentile([s[3] for s in items], 90)),
        frames_hit=len({s[0] for s in items}),
        widths=[s[4] for s in items],
        centers_x=[s[5] for s in items],
        font=float(np.median([s[3] - s[2] for s in items])),  # 段高 ≈ 字号
    )


def _score_line(line: _Line, num_frames: int, fh: int) -> float:
    """给行候选打「像字幕」分：时间稳定(出现率) + 内容在变 + 偏底部；剔除恒定台标与上半部分。"""
    presence = line.frames_hit / max(1, num_frames)
    # 内容变化：字幕逐句换 → 段宽/水平中心在变；台标几乎恒定 → 方差≈0。
    change = _variation(line.widths) * 0.5 + _variation(line.centers_x) * 0.5
    cy_norm = line.cy / max(1, fh)
    if cy_norm < 0.55:
        return 0.0  # 上半部分基本不是字幕（标题/正文/台标）
    if presence > 0.95 and change < 0.06:
        return 0.0  # 一直在且几乎不变 = 台标/水印
    bottom_prior = math.exp(-((cy_norm - 0.9) ** 2) / (2 * 0.13 ** 2))
    return presence * 0.32 + change * 0.28 + bottom_prior * 0.6


def _variation(values: list[float]) -> float:
    """一组量的归一化离散度（0-1）：变异系数(std/mean)，尺度无关，近似「内容变化率」。"""
    if len(values) < 2:
        return 0.0
    mean = float(np.mean(values)) or 1.0
    return max(0.0, min(1.0, float(np.std(values)) / (mean * 0.6)))
