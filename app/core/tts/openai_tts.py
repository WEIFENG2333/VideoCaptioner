"""OpenAI TTS 实现（支持 OpenAI 兼容接口）"""

from openai import OpenAI

from app.core.tts.base import BaseTTS
from app.core.tts.tts_data import TTSConfig, TTSData
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

    def _synthesize(self, text: str, output_path: str) -> TTSData:
        """合成语音的核心实现

        Args:
            text: 输入文本
            output_path: 输出音频路径

        Returns:
            TTS 数据
        """
        logger.info(f"调用 OpenAI TTS API: {text[:50]}...")

        # 调用 OpenAI TTS API（流式响应）
        with self.client.audio.speech.with_streaming_response.create(
            model=self.config.model,
            voice=self.config.voice or "alloy",  # 默认音色
            input=text,
            response_format=self.config.response_format,
            speed=self.config.speed,
        ) as response:
            response.stream_to_file(output_path)

        logger.info(f"TTS 成功: {output_path}")

        # 返回 TTS 数据
        return TTSData(
            text=text,
            audio_path=output_path,
            model=self.config.model,
            voice=self.config.voice,
        )
