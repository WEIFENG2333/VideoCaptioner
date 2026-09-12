"""硬字幕提取状态机的离线测试（不依赖真实视频 / 真实 OCR）。

两类：
- 纯函数（``_changed`` / ``_is_blank`` / ``_norm`` / ``_similar``）用真实合成灰度帧测阈值；
- 状态机（变化检测跳保持帧、空白收尾、变化点 OCR、相似度合并、时长过滤、时间轴）用 marker 帧
  + monkeypatch 掉 ``_changed`` / ``_is_blank``，把「场景切换」简化成 marker 比较，精确锁状态转移。
"""

from __future__ import annotations

import numpy as np

import videocaptioner.core.hardsub.pipeline as P
from videocaptioner.core.hardsub.config import HardsubConfig
from videocaptioner.core.hardsub.pipeline import (
    HardsubCue,
    _changed,
    _is_blank,
    _norm,
    _read_lines,
    _similar,
    cues_to_asrdata,
    extract_hardsub,
)
from videocaptioner.core.ocr.base import OcrEngine, OcrLine

H, W = 40, 600


# ---------- 纯函数（真实合成帧 / 真实阈值）----------

def _scene(width: int) -> np.ndarray:
    """暗底 + 宽度=width 的亮块。width=0 即空白帧。"""
    arr = np.full((H, W), 20, np.uint8)
    if width > 0:
        arr[10:30, 10 : 10 + width] = 240
    return arr


def test_changed_detects_block_growth():
    assert _changed(_scene(100), _scene(200), area_thr=144)
    assert not _changed(_scene(100), _scene(100), area_thr=144)


def test_is_blank_only_when_uniform():
    assert _is_blank(_scene(0), blank_thr=43)
    assert not _is_blank(_scene(100), blank_thr=43)


def test_norm_strips_whitespace():
    assert _norm("a b\tc\n") == "abc"


def test_similar_identical_and_different():
    assert _similar("你好世界", "你好世界") == 100
    assert _similar("abcdef", "abcdef") == 100
    assert _similar("你好", "再见天涯") < 60


# ---------- 状态机（marker 帧 + 简化切换判定）----------

def _marker_frame(marker: int) -> np.ndarray:
    # 真实 ROI 尺寸的 RGB 帧（居中过滤要按 image 宽算偏移）；marker 编码在绿通道 [0,0,1]。
    arr = np.zeros((H, W, 3), np.uint8)
    arr[0, 0, 1] = marker  # 0 = 空白
    return arr


class _FakeEngine(OcrEngine):
    """按帧 marker（绿通道）取脚本文本（marker=0 视为无字幕）。"""

    def __init__(self, texts: dict[int, str]):
        self._texts = texts

    @property
    def name(self) -> str:
        return "fake"

    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        text = self._texts.get(int(image[0, 0, 1]), "")
        if not text:
            return []
        # 框居中（ROI 宽 600 → 中心 300）：烧录字幕都居中，过滤器按「居中+字号」留它。
        return [OcrLine(text=text, score=0.99, box=((250, 6), (350, 6), (350, 34), (250, 34)))]

    def detect(self, image: np.ndarray) -> list:
        return []


def _run(monkeypatch, markers, texts, interval=0.3, **cfg_kw):
    frames = [_marker_frame(m) for m in markers]
    monkeypatch.setattr(P, "probe_dimensions", lambda _p: (W, H, 25.0, len(frames) * interval))
    monkeypatch.setattr(
        P, "iter_roi_rgb",
        lambda _p, _roi, _iv: ((i * interval, f) for i, f in enumerate(frames)),
    )
    # 场景切换 = marker 变化；空白 = marker 0。g 是绿通道(2D)，g[0,0] 即 marker。
    monkeypatch.setattr(P, "_is_blank", lambda g, _thr: int(g[0, 0]) == 0)
    monkeypatch.setattr(P, "_changed", lambda a, b, _thr: int(a[0, 0]) != int(b[0, 0]))
    cfg = HardsubConfig(video_path="x.mp4", roi=(0, 0, W, H), sample_interval=interval, **cfg_kw)
    cues: list[HardsubCue] = []
    data = extract_hardsub(cfg, _FakeEngine(texts), on_cue=cues.append)
    return data, cues


def test_single_subtitle_one_cue(monkeypatch):
    data, cues = _run(monkeypatch, [0, 1, 1, 1, 0], {1: "第一句字幕"})
    assert len(data) == 1
    assert data.segments[0].text == "第一句字幕"
    assert len(cues) == 1


def test_two_subtitles_split_on_change(monkeypatch):
    data, _ = _run(monkeypatch, [0, 1, 1, 0, 2, 2, 0], {1: "第一句", 2: "第二句"})
    assert [s.text for s in data] == ["第一句", "第二句"]


def test_timeline_milliseconds(monkeypatch):
    # marker1 出现于 t=0.3，末次出现 t=0.6，t=0.9 空白：start=300，end=600+一个间隔=900。
    data, _ = _run(monkeypatch, [0, 1, 1, 0], {1: "句子"})
    seg = data.segments[0]
    assert seg.start_time == 300
    assert seg.end_time == 900


def test_min_duration_filters_blip(monkeypatch):
    data, _ = _run(monkeypatch, [0, 1, 0, 0], {1: "闪现"}, min_duration=1.0)
    assert len(data) == 0


def test_merge_keeps_longest_text(monkeypatch):
    # 同一句先识别半句(marker1)后识别全句(marker2)，文本相似 → 合并取更完整的。
    data, _ = _run(
        monkeypatch, [0, 1, 2, 2, 0],
        {1: "今天我们讲矩阵", 2: "今天我们讲矩阵和向量"},
        text_sim_threshold=60,
    )
    assert len(data) == 1
    assert data.segments[0].text == "今天我们讲矩阵和向量"


def test_cancel_stops_early(monkeypatch):
    markers = [1] * 50
    seen = {"n": 0}

    def should_cancel():
        seen["n"] += 1
        return seen["n"] > 5

    frames = [_marker_frame(m) for m in markers]
    monkeypatch.setattr(P, "probe_dimensions", lambda _p: (W, H, 25.0, 15.0))
    monkeypatch.setattr(
        P, "iter_roi_rgb",
        lambda _p, _roi, _iv: ((i * 0.3, f) for i, f in enumerate(frames)),
    )
    monkeypatch.setattr(P, "_is_blank", lambda g, _thr: int(g[0, 0]) == 0)
    monkeypatch.setattr(P, "_changed", lambda a, b, _thr: int(a[0, 0]) != int(b[0, 0]))
    cfg = HardsubConfig(video_path="x.mp4", roi=(0, 0, W, H))
    extract_hardsub(cfg, _FakeEngine({1: "x"}), should_cancel=should_cancel)
    assert seen["n"] <= 7


# ---------- 手动 ROI：尊重所见即所得（不学全局字号 / 不按字号过滤）----------

def test_manual_roi_skips_global_font_gate(monkeypatch):
    # 用户手动框选/--roi 指定区域：不学「全局主导字号」、提取不按字号门过滤——否则会把用户
    # 特意框进来的小字号译文挡掉。这里断言 manual 时根本不调用 _dominant_font_height。
    called = {"n": 0}

    def _spy(*_a, **_k):
        called["n"] += 1
        return 28.0

    monkeypatch.setattr(P, "_dominant_font_height", _spy)
    data, _ = _run(monkeypatch, [0, 1, 1, 0], {1: "字幕"}, roi_is_manual=True)
    assert called["n"] == 0
    assert data.segments[0].text == "字幕"


def test_auto_roi_learns_global_font(monkeypatch):
    # 自动检测区域（默认 roi_is_manual=False）：仍学一次全局主导字号用于过滤带内杂质。
    called = {"n": 0}

    def _spy(*_a, **_k):
        called["n"] += 1
        return 28.0

    monkeypatch.setattr(P, "_dominant_font_height", _spy)
    _run(monkeypatch, [0, 1, 1, 0], {1: "字幕"})
    assert called["n"] == 1


# ---------- cue → ASRData ----------

def test_cues_to_asrdata_ms_and_filter():
    cues = [
        HardsubCue(start=1.0, end=2.5, lines=["你好"]),
        HardsubCue(start=3.0, end=4.0, lines=["  "]),
    ]
    data = cues_to_asrdata(cues)
    assert len(data) == 1
    assert data.segments[0].start_time == 1000
    assert data.segments[0].end_time == 2500


def test_multiline_cue_joins_with_newline():
    cue = HardsubCue(start=0.0, end=1.0, lines=["中文行", "English line"])
    assert cue.text == "中文行\nEnglish line"


# ---------- 杂质过滤：居中（核心，与区域检测同模型）----------

def _poly(x0, y0, x1, y1):
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


class _ScriptedEngine(OcrEngine):
    """recognize 固定返回脚本里的 OcrLine（与图像无关），用于测过滤几何。"""

    def __init__(self, lines):
        self._lines = lines

    @property
    def name(self):
        return "scripted"

    def recognize(self, image):
        return list(self._lines)

    def detect(self, image):
        return []


def test_read_lines_drops_offcenter():
    # ROI 宽 1920：居中字幕 + 偏右计数(偏心)。同一视觉行被大间隙切段，只留居中段。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="当你第一次开始学他", score=0.99, box=_poly(600, 20, 1320, 138)),  # 居中=字幕
        OcrLine(text="49:00", score=0.99, box=_poly(1780, 50, 1860, 66)),               # 偏右=时长
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["当你第一次开始学他"]


def test_read_lines_font_height_drops_smaller():
    # 全局主导字号=大字(75)。小字行(40 < 0.6×75)被字号门挡掉，只留主导字号行。
    img = np.zeros((220, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="中文字幕大字", score=0.99, box=_poly(700, 20, 1220, 95)),   # 字高 75
        OcrLine(text="English smaller", score=0.99, box=_poly(740, 112, 1180, 152)),  # 字高 40
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6,
                      center_tolerance=0.34, font_height=75.0)
    assert [t for t, _ in out] == ["中文字幕大字"]


def test_read_lines_font_height_drops_translation_ratio():
    # 中英双语：英文译文 ≈ 0.65× 中文（实测比值），落在 0.75 门下界之下被稳定排除——
    # 不再逐帧骑门槛忽留忽丢。主导字号=中文 28。
    img = np.zeros((220, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="答案就是只因你太美", score=0.99, box=_poly(700, 20, 1220, 48)),    # 字高 28
        OcrLine(text="The answer is", score=0.99, box=_poly(740, 60, 1180, 78)),         # 字高 18 ≈0.64×
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6,
                      center_tolerance=0.34, font_height=28.0)
    assert [t for t, _ in out] == ["答案就是只因你太美"]


def test_read_lines_font_height_keeps_same_size_second_line():
    # 同一字幕的真·第二行（同字号，OCR 抖动 0.85×）仍保留——门下界 0.75 不误杀同号多行。
    img = np.zeros((220, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="第一行字幕内容", score=0.99, box=_poly(700, 20, 1220, 60)),   # 字高 40
        OcrLine(text="第二行字幕内容", score=0.99, box=_poly(710, 72, 1210, 106)),  # 字高 34 ≈0.85×
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6,
                      center_tolerance=0.34, font_height=40.0)
    assert [t for t, _ in out] == ["第一行字幕内容", "第二行字幕内容"]


def test_read_lines_frame_relative_drops_translation():
    # 英文译文 0.78×主导字号 → 过绝对字号门(0.75)，但同帧中文主行 1.1×；帧内相对门按「< 0.8×本帧最大」
    # 剔掉英文（治英文字高骑在绝对门上的忽中忽英）。主导字号 24.5。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="火焰就像丝绸一样", score=0.99, box=_poly(700, 18, 1220, 45)),       # 字高27
        OcrLine(text="theflameflowslikesilk", score=0.99, box=_poly(720, 60, 1200, 79)),  # 字高19 ≈0.7×主行
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6,
                      center_tolerance=0.34, font_height=24.5)
    assert [t for t, _ in out] == ["火焰就像丝绸一样"]


def test_read_lines_no_font_filter_keeps_both():
    # font_height=None：不按字号过滤，两行都居中 → 都保留。
    img = np.zeros((220, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="中文字幕大字", score=0.99, box=_poly(700, 20, 1220, 95)),
        OcrLine(text="English smaller", score=0.99, box=_poly(740, 112, 1180, 152)),
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["中文字幕大字", "English smaller"]


def test_read_lines_trims_offcenter_same_font_junk():
    # 片尾卡片标题与歌词同字号、同一视觉行、横向贴近（间隙 < 2×行高）——段级中心拦不住（合并后
    # 段中心仍接近画面中心），靠单框中心偏移从两端修剪剔掉。ROI 宽 1920，半宽 960。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="一课通", score=0.92, box=_poly(200, 20, 480, 138)),          # 卡片标题(左,偏移0.65)
        OcrLine(text="你会眼里泛着泪花", score=0.97, box=_poly(603, 22, 1243, 138)),  # 歌词(居中0.04)
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["你会眼里泛着泪花"]


def test_read_lines_keeps_ocr_split_centered_line():
    # 一条居中长字幕被 OCR 拆成左右两块：每块自身略偏中心(≈0.19)但都靠中心，不该被修剪，应合并保留。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="你会眼里", score=0.95, box=_poly(620, 22, 940, 138)),   # 左半(中心780,偏移0.19)
        OcrLine(text="泛着泪花", score=0.95, box=_poly(980, 22, 1300, 138)),  # 右半(中心1140,偏移0.19)
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["你会眼里 泛着泪花"]


def test_read_lines_drops_offcenter_single_line():
    # 单框行(完整一行)偏移 0.29：未达拆块容差 0.34，但单框行用更严的 0.25 门 → 偏置署名(如 MV 演唱者名
    # 「马嘉祺」)被剔除；居中主行保留。ROI 宽 1920，半宽 960。
    img = np.zeros((220, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="炎炎夏日万般滋味", score=0.99, box=_poly(700, 20, 1220, 60)),  # 居中(偏移≈0)
        OcrLine(text="马嘉祺", score=0.99, box=_poly(560, 80, 800, 118)),           # 偏左(中心680, 偏移0.29)
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["炎炎夏日万般滋味"]


def test_read_lines_keeps_fullwidth_centered_split():
    # 近全宽居中长句被 OCR 拆成两半：每半自身偏移≈0.47 > 0.45 会触发修剪，但修剪后不居中 → 回退
    # 保留整段（整体居中）→ 不该整条丢失。ROI 宽 1920，半宽 960。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="大家觉得声音为什么", score=0.96, box=_poly(60, 20, 960, 138)),   # 左半(中心510,偏移0.47)
        OcrLine(text="能熄灭蜡烛呢", score=0.96, box=_poly(960, 20, 1860, 138)),       # 右半(中心1410,偏移0.47)
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=0.34)
    assert [t for t, _ in out] == ["大家觉得声音为什么 能熄灭蜡烛呢"]


def test_read_lines_disabled_keeps_offcenter():
    # center_tolerance>=1：不过滤，居中与偏心段都留。
    img = np.zeros((150, 1920, 3), np.uint8)
    lines = [
        OcrLine(text="字幕", score=0.99, box=_poly(880, 20, 1040, 130)),
        OcrLine(text="49:00", score=0.99, box=_poly(1780, 50, 1860, 66)),
    ]
    out = _read_lines(_ScriptedEngine(lines), img, conf_threshold=0.6, center_tolerance=1.0)
    assert set(t for t, _ in out) == {"字幕", "49:00"}
