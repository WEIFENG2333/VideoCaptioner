"""硬字幕提取的配置数据类与预设（无 PyQt，CLI/GUI 共用）。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional


class RecognizeMode(str, Enum):
    """识别模式：速度/精度档位。"""

    FAST = "fast"
    STANDARD = "standard"
    ACCURATE = "accurate"


# 主面板语言下拉：(rec 语言码, 中文显示名)。"ch" 模型中英通吃，是默认。
LANGUAGES: list[tuple[str, str]] = [
    ("ch", "中文 + 英文"),
    ("en", "英文"),
    ("japan", "日语"),
    ("korean", "韩语"),
    ("chinese_cht", "繁体中文"),
]

# 模式 → (OCR 版本, 模型档, 抽帧间隔秒)。间隔越小时间轴越准但越慢；server 模型更准更慢。
_PRESETS: dict[RecognizeMode, tuple[str, str, float]] = {
    RecognizeMode.FAST: ("PP-OCRv4", "mobile", 0.5),
    RecognizeMode.STANDARD: ("PP-OCRv4", "mobile", 0.3),
    RecognizeMode.ACCURATE: ("PP-OCRv5", "mobile", 0.2),
}


def mode_preset(mode: RecognizeMode) -> tuple[str, str, float]:
    """返回该模式的 (ocr_version, model_type, sample_interval)。"""
    return _PRESETS.get(mode, _PRESETS[RecognizeMode.STANDARD])


# ROI：原始分辨率像素 (x, y, w, h)
Roi = tuple[int, int, int, int]


@dataclass
class HardsubConfig:
    """一次硬字幕提取的完整参数。"""

    video_path: str
    # 字幕区域（原始分辨率像素）。None = 未指定，pipeline 会回退到底部默认带。
    roi: Optional[Roi] = None
    # ROI 是否由用户显式指定（GUI 手动框选/调整、CLI --roi）而非自动检测。手动指定时提取所见即所得，
    # 不套字号门/居中过滤（否则会挡掉用户特意框进来的小字）。
    roi_is_manual: bool = False
    lang: str = "ch"

    # 引擎 / 模型（由模式预设填充，也可单独覆盖）
    ocr_version: str = "PP-OCRv4"
    model_type: str = "mobile"
    threads: int = 0  # onnxruntime intra-op 线程数；0=自动

    # 抽帧
    sample_interval: float = 0.3  # 每隔多少秒抽一帧（时间分辨率）

    # 字幕区变化检测（只在变化点 OCR，是性能核心）
    similar_pixel_threshold: int = 25   # 像素亮度差 > 此值算「不同」
    change_area_ratio: float = 0.006    # ROI 中「不同像素」占比 ≥ 此值算「内容变了」
    blank_area_ratio: float = 0.0018    # 前景像素占比 < 此值算「无字幕」

    # 去重合并：同一显示块内多次识别合并成一条；紧邻出现高置信且相似度低于此值的文本才判硬切新句。
    text_sim_threshold: int = 70        # 低于此相似度 + 高置信 = 硬切新句
    conf_threshold: float = 0.6         # 低于此置信度的识别结果丢弃
    min_duration: float = 0.3           # 短于此时长的字幕视为噪声丢弃

    # 段水平中心偏移 ≤ 此比例才保留（0=正中，≥1=不过滤）。烧录字幕几乎总居中，两侧卡片/计数被滤。
    center_tolerance: float = 0.34

    # 自动区域检测采样
    region_sample_count: int = 20       # 检测字幕区时均匀抽多少帧（每帧一次 OCR，预处理耗时主体）
    # 主导字幕字号（原始分辨率像素），由 detect_subtitle_region 顺带学到回填供提取复用。
    # None = 未知（手动框选/默认带），提取时现学或不过滤。
    font_height: Optional[float] = None

    @property
    def merge_gap(self) -> float:
        """跨小间隙合并的时间窗：两个采样间隔。"""
        return self.sample_interval * 2.0

    @classmethod
    def from_mode(
        cls, video_path: str, mode: RecognizeMode = RecognizeMode.STANDARD, **kwargs
    ) -> "HardsubConfig":
        version, model_type, interval = mode_preset(mode)
        cfg = cls(
            video_path=video_path,
            ocr_version=version,
            model_type=model_type,
            sample_interval=interval,
        )
        return replace(cfg, **kwargs) if kwargs else cfg


@dataclass
class HardsubProgress:
    """提取进度快照（pipeline → UI）。"""

    current_time: float       # 已处理到的视频时刻（秒）
    duration: float           # 视频总时长（秒）
    cue_count: int            # 已产出字幕条数
    ocr_calls: int = field(default=0)  # 实际 OCR 次数（调试/优化用）

    @property
    def percent(self) -> int:
        if self.duration <= 0:
            return 0
        return max(0, min(100, int(self.current_time / self.duration * 100)))
