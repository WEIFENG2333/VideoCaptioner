"""TTS 数据结构定义"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TTSConfig:
    """TTS 配置"""

    # 基础配置
    model: str = "FunAudioLLM/CosyVoice2-0.5B"
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1"

    # 音频参数
    voice: Optional[str] = None  # 音色选择
    response_format: str = "mp3"  # mp3, opus, wav, pcm
    sample_rate: int = 32000  # 采样率
    speed: float = 1.0  # 语速 0.25-4.0
    gain: int = 0  # 音量增益 -10 到 10

    # 处理参数
    stream: bool = False  # 是否流式传输
    cache_ttl: int = 86400 * 2  # 缓存过期时间（秒），默认2天
    timeout: int = 60  # 超时时间（秒）


@dataclass
class TTSData:
    """TTS 数据 - 单条文本转音频的结果"""

    text: str  # 原始文本
    audio_path: str  # 生成的音频文件路径
    start_time: float = 0.0  # 开始时间（秒，用于字幕时间轴对齐）
    end_time: float = 0.0  # 结束时间（秒，用于字幕时间轴对齐）
    audio_duration: float = 0.0  # 实际音频时长（秒）
    model: str = ""  # 使用的模型
    voice: Optional[str] = None  # 使用的音色

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "text": self.text,
            "audio_path": self.audio_path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "audio_duration": self.audio_duration,
            "model": self.model,
            "voice": self.voice,
        }


@dataclass
class TTSBatchResult:
    """批量 TTS 结果"""

    items: List[TTSData] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {"items": [item.to_dict() for item in self.items]}
