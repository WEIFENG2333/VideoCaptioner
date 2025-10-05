"""TTS 数据结构定义"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TTSConfig:
    """TTS 配置"""

    # 基础配置
    model: str = "FunAudioLLM/CosyVoice2-0.5B"
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1"

    # 音频参数
    voice: Optional[str] = None  # 默认音色选择
    custom_prompt: Optional[str] = None  # 自定义提示词（用于 OpenAI.fm 等）
    response_format: str = "mp3"  # mp3, opus, wav, pcm
    sample_rate: int = 32000  # 采样率
    speed: float = 1.0  # 语速 0.25-4.0
    gain: int = 0  # 音量增益 -10 到 10

    # 处理参数
    stream: bool = False  # 是否流式传输
    cache_ttl: int = 86400 * 2  # 缓存过期时间（秒），默认2天
    timeout: int = 60  # 超时时间（秒）
    use_cache: bool = True  # 是否使用缓存


@dataclass
class TTSDataSeg:
    """TTS 数据段 - 单条文本转音频的片段"""

    text: str  # 要合成的文本
    start_time: float = 0.0  # 开始时间（秒）
    end_time: float = 0.0  # 结束时间（秒）
    audio_path: str = ""  # 生成的音频文件路径
    audio_duration: float = 0.0  # 实际音频时长（秒）
    voice: Optional[str] = None  # 使用的音色

    # 声音克隆相关
    clone_audio_path: Optional[str] = None  # 参考音频文件路径
    clone_audio_text: Optional[str] = None  # 参考音频对应的文本
    clone_voice_uri: Optional[str] = None  # 上传后获得的 URI

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "audio_path": self.audio_path,
            "audio_duration": self.audio_duration,
            "voice": self.voice,
            "clone_audio_path": self.clone_audio_path,
            "clone_audio_text": self.clone_audio_text,
            "clone_voice_uri": self.clone_voice_uri,
        }

    def __str__(self) -> str:
        return f"TTSDataSeg(text={self.text[:20]}..., audio_path={self.audio_path})"


class TTSData:
    """TTS 数据 - 包含多个 TTS 片段的容器（参考 ASRData 设计）"""

    def __init__(self, segments: Optional[List[TTSDataSeg]] = None):
        """初始化 TTS 数据

        Args:
            segments: TTS 数据段列表
        """
        if segments is None:
            segments = []
        # 过滤空文本，按时间排序
        filtered_segments = [seg for seg in segments if seg.text and seg.text.strip()]
        filtered_segments.sort(key=lambda x: x.start_time)
        self.segments = filtered_segments

    def __iter__(self):
        """迭代器"""
        return iter(self.segments)

    def __len__(self) -> int:
        """返回段落数量"""
        return len(self.segments)

    def has_data(self) -> bool:
        """检查是否有数据"""
        return len(self.segments) > 0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {"segments": [seg.to_dict() for seg in self.segments]}

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        clone_audio_path: Optional[str] = None,
        clone_audio_text: Optional[str] = None,
    ) -> "TTSData":
        """从文本列表创建 TTSData

        Args:
            texts: 文本列表
            clone_audio_path: 统一的参考音频路径（可选）
            clone_audio_text: 统一的参考音频文本（可选）

        Returns:
            TTSData 实例
        """
        segments = [
            TTSDataSeg(
                text=text,
                clone_audio_path=clone_audio_path,
                clone_audio_text=clone_audio_text,
            )
            for text in texts
        ]
        return cls(segments)
