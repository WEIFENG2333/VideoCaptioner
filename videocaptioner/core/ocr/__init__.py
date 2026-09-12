"""OCR 引擎抽象与实现（无 PyQt）。

后端无关：硬字幕提取只依赖 :class:`OcrEngine` 协议，换引擎只需实现它。包 ``__init__`` 不
eager import 任何引擎实现，避免把 onnxruntime/rapidocr 拉进无关启动路径——按需 import 具体子模块。
"""

from videocaptioner.core.ocr.base import OcrEngine, OcrError, OcrLine

__all__ = ["OcrEngine", "OcrError", "OcrLine"]
