"""OpenAI TTS 实现（支持 OpenAI 兼容接口）"""

from openai import OpenAI

from app.core.tts.base import BaseTTS
from app.core.tts.tts_data import TTSConfig, TTSDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("tts.openai")


class OpenAITTS(BaseTTS):
    """OpenAI TTS API 实现

    支持 OpenAI 及其兼容接口（如 SiliconFlow）
    """

    def __init__(self, config: TTSConfig):
        """初始化

        Args:
            config: TTS 配置
        """
        super().__init__(config)
        if not config.api_key:
            raise ValueError("API key is required for OpenAI TTS")

        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        """合成语音的核心实现

        Args:
            segment: TTS 数据段
            output_path: 输出音频路径
        """
        logger.info(f"调用 OpenAI TTS API: {segment.text[:50]}...")

        # 音色选择
        voice_to_use = segment.voice or self.config.voice or "alloy"

        # 调用 OpenAI TTS API（流式响应）
        with self.client.audio.speech.with_streaming_response.create(
            model=self.config.model,
            voice=voice_to_use,
            input=segment.text,
            response_format=self.config.response_format,
            speed=self.config.speed,
        ) as response:
            response.stream_to_file(output_path)

        logger.info(f"TTS 成功: {output_path}")

        # 更新 segment
        segment.audio_path = output_path
        segment.voice = voice_to_use
