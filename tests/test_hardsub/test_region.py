"""自动字幕区域检测的离线测试：居中文字段 + 行聚类 + 打分 + 端到端选带。

验证字幕模型：水平居中 + 时间稳定 + 内容变化 + 偏底部；两侧台标/卡片(偏心)与顶部标题被剔除。
"""

from __future__ import annotations

import numpy as np

import videocaptioner.core.hardsub.region as R
from videocaptioner.core.hardsub.region import (
    _Line,
    _score_line,
    centered_segments,
    detect_subtitle_region,
)
from videocaptioner.core.ocr.base import OcrEngine


def _line(cy, frames_hit, widths, centers_x, top=None, bottom=None) -> _Line:
    return _Line(
        cy=cy,
        top=top if top is not None else cy - 20,
        bottom=bottom if bottom is not None else cy + 20,
        frames_hit=frames_hit,
        widths=widths,
        centers_x=centers_x,
    )


# ---------- 居中文字段 ----------

def test_centered_segments_keeps_center_drops_sides():
    # 同一行：居中字幕段保留；左/右两侧的角标/卡片(偏心)被丢弃，且大间隔切成独立段。
    half, line_h = 480.0, 30.0
    boxes = [
        (380, 470, 580, 510),   # 居中字幕 cx=480
        (10, 470, 120, 510),    # 左侧角标 cx=65
        (820, 470, 950, 510),   # 右侧 cx=885
    ]
    segs = centered_segments(boxes, half, line_h, center_tol=0.34)
    assert len(segs) == 1
    assert segs[0][0][0] == 380


def test_centered_segments_bilingual_two_lines():
    # 中英双行都居中、垂直分开 → 各自成段。
    half, line_h = 480.0, 24.0
    boxes = [
        (300, 440, 660, 470),   # 中文行 cx=480
        (320, 478, 640, 498),   # 英文行 cx=480（下一行）
    ]
    segs = centered_segments(boxes, half, line_h)
    assert len(segs) == 2


# ---------- 行打分 ----------

def test_score_static_logo_is_zero():
    # 底部但「一直在且不变」= 台标/水印 → 0 分。
    logo = _line(cy=500, frames_hit=30, widths=[100] * 30, centers_x=[480.0] * 30)
    assert _score_line(logo, num_frames=30, fh=540) == 0.0


def test_score_top_text_is_zero():
    # 画面上半部分（标题/正文）→ 0 分。
    top = _line(cy=60, frames_hit=10, widths=[200, 300, 250], centers_x=[480, 470, 490])
    assert _score_line(top, num_frames=10, fh=540) == 0.0


def test_score_subtitle_positive():
    # 底部、出现率中高、宽度/位置随句子变化 → 正分。
    widths = [300, 420, 360, 500, 280, 440]
    centers = [480, 500, 470, 520, 460, 510]
    sub = _line(cy=490, frames_hit=6, widths=widths, centers_x=centers, top=470, bottom=510)
    assert _score_line(sub, num_frames=8, fh=540) > 0.35


# ---------- 端到端（FakeDetEngine）----------

class _FakeDetEngine(OcrEngine):
    """detect 按调用顺序返回脚本框（每帧一组）。"""

    def __init__(self, boxes_per_frame: list[list[tuple]]):
        self._boxes = boxes_per_frame
        self._i = 0

    @property
    def name(self) -> str:
        return "fakedet"

    def recognize(self, image):
        return []

    def detect(self, image):
        boxes = self._boxes[self._i] if self._i < len(self._boxes) else []
        self._i += 1
        return boxes


def test_detect_region_picks_bottom_scaled_to_original(monkeypatch):
    fw, fh = 960, 540
    frame = np.zeros((fh, fw, 3), np.uint8)
    frames = [(i * 0.5, frame) for i in range(10)]
    boxes_per_frame = []
    for i in range(10):
        sub_w = 300 + (i % 4) * 70                  # 宽度逐帧变（内容变化）
        sub = (330.0, 470.0, 330.0 + sub_w, 512.0)   # 底部居中字幕带（cx≈480）
        logo = (20.0, 20.0, 120.0, 60.0)             # 顶部 + 偏心 logo
        boxes_per_frame.append([sub, logo])
    monkeypatch.setattr(R, "sample_frames", lambda *a, **k: frames)
    monkeypatch.setattr(R, "probe_dimensions", lambda _p: (1920, 1080, 25.0, 30.0))

    result = detect_subtitle_region("x.mp4", _FakeDetEngine(boxes_per_frame))
    assert result is not None
    _x, y, w, h = result.roi
    # 缩放回原始分辨率（×2）：字幕带应落在画面下方，不是顶部 logo。
    assert y > 1080 * 0.7
    assert w > 0 and h > 0
    assert result.font_height > 0  # 顺带学到主导字号（原始分辨率）


def test_detect_region_none_when_no_detections(monkeypatch):
    fw, fh = 960, 540
    frames = [(i * 0.5, np.zeros((fh, fw, 3), np.uint8)) for i in range(5)]
    monkeypatch.setattr(R, "sample_frames", lambda *a, **k: frames)
    monkeypatch.setattr(R, "probe_dimensions", lambda _p: (1920, 1080, 25.0, 30.0))
    roi = detect_subtitle_region("x.mp4", _FakeDetEngine([[] for _ in range(5)]))
    assert roi is None
