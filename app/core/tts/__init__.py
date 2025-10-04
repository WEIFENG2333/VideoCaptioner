"""TTS (Text-To-Speech) 模块

提供多种 TTS 服务的统一接口
"""

from .base import BaseTTS
from .openai_fm import OpenAIFmTTS
from .openai_tts import OpenAITTS
from .siliconflow import SiliconFlowTTS
from .status import TTSStatus
from .tts_data import TTSBatchResult, TTSConfig, TTSData

__all__ = [
    "BaseTTS",
    "OpenAITTS",
    "OpenAIFmTTS",
    "SiliconFlowTTS",
    "TTSStatus",
    "TTSConfig",
    "TTSData",
    "TTSBatchResult",
]
