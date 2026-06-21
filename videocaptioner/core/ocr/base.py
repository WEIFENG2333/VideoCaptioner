"""OCR 引擎协议：硬字幕提取依赖的最小识别接口。

一条识别结果是 :class:`OcrLine`（文本 + 置信度 + 四点框）。引擎提供两档能力：``recognize``
（检测 + 识别，给字幕条出文本）与 ``detect``（仅检测，给区域自动检测用，省掉识别开销）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

# 四点多边形：((x,y), (x,y), (x,y), (x,y))，顺序为左上→右上→右下→左下
Polygon = tuple[tuple[float, float], ...]
# 轴对齐包围盒：(x0, y0, x1, y1)
BBox = tuple[float, float, float, float]


class OcrError(Exception):
    """OCR 引擎不可用（依赖缺失 / 模型下载失败 / 推理异常）。"""


@dataclass(frozen=True)
class OcrLine:
    """一行识别结果。box 为四点多边形（图像像素坐标），按需取轴对齐包围盒/中心。"""

    text: str
    score: float
    box: Polygon

    @property
    def bbox(self) -> BBox:
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def cy(self) -> float:
        ys = [p[1] for p in self.box]
        return (min(ys) + max(ys)) / 2.0

    @property
    def height(self) -> float:
        ys = [p[1] for p in self.box]
        return max(ys) - min(ys)


def bbox_of(box: Polygon) -> BBox:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return (min(xs), min(ys), max(xs), max(ys))


class OcrEngine(ABC):
    """图像 OCR 引擎。实现需线程安全到「同一实例可被一个工作线程串行复用」即可。

    图像约定为 HxWx3 的 numpy 数组（RGB 或 BGR 都接受——RapidOCR/OpenCV 对字幕这种
    高对比文本不敏感；调用方保持一致即可）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎短名（用于诊断/日志/配置回显）。"""

    @abstractmethod
    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        """检测 + 识别整张图，返回多行结果（无文本返回空列表）。失败抛 :class:`OcrError`。"""

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[BBox]:
        """仅做文本检测（不识别），返回文本框包围盒列表。区域自动检测用，比 recognize 快。"""

    def warmup(self) -> None:
        """可选：提前加载模型，避免首帧卡顿。默认 no-op。"""
