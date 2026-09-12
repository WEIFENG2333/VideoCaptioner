# -*- coding: utf-8 -*-
"""转录服务的模型候选列表。

设置页与转录页共用，避免两处各写一份。
candidates 只是建议项：字段本身可编辑，用户配置了列表外的值时
界面会把当前值并入选项展示。
"""

from __future__ import annotations

FUN_ASR_MODEL_OPTIONS = [
    "fun-asr",
    "fun-asr-2025-11-07",
    "fun-asr-2025-08-25",
    "fun-asr-mtl",
    "fun-asr-mtl-2025-08-25",
]

WHISPER_API_MODEL_OPTIONS = [
    "whisper-1",
    "whisper-large-v3-turbo",
]
