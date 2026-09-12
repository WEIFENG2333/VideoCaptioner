"""硬字幕提取业务逻辑（无 PyQt）。

从带烧录字幕的视频里识别字幕并生成可编辑字幕：抽帧 → 字幕区变化检测（只在变化点 OCR）
→ 识别 → 文本相似度去重合并 → 时间轴。识别引擎走 :mod:`videocaptioner.core.ocr` 抽象。
"""

from videocaptioner.core.hardsub.config import (
    LANGUAGES,
    HardsubConfig,
    RecognizeMode,
    mode_preset,
)

__all__ = ["HardsubConfig", "RecognizeMode", "LANGUAGES", "mode_preset"]
