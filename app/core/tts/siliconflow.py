"""SiliconFlow TTS 实现"""

import requests

from app.core.tts.base import BaseTTS
from app.core.tts.tts_data import TTSConfig, TTSData
from app.core.utils.logger import setup_logger

logger = setup_logger("tts.siliconflow")


class SiliconFlowTTS(BaseTTS):
    """SiliconFlow TTS API 实现

    使用硅基流动的云端 TTS 服务
    """

    def __init__(self, config: TTSConfig):
        """初始化

        Args:
            config: TTS 配置
        """
        super().__init__(config)
        if not config.api_key:
            raise ValueError("API key is required for SiliconFlow TTS")

    def _synthesize(self, text: str, output_path: str) -> TTSData:
        """合成语音的核心实现

        Args:
            text: 输入文本
            output_path: 输出音频路径

        Returns:
            TTS 数据
        """
        url = f"{self.config.base_url}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        # 构建请求数据
        payload = {
            "model": self.config.model,
            "input": text,
            "response_format": self.config.response_format,
            "sample_rate": self.config.sample_rate,
            "speed": self.config.speed,
            "gain": self.config.gain,
        }

        # 可选参数
        if self.config.voice:
            payload["voice"] = self.config.voice
        if self.config.stream:
            payload["stream"] = self.config.stream

        # 发送请求
        logger.info(f"调用 SiliconFlow TTS API: {text[:50]}...")
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout,
        )
        response.raise_for_status()

        # 保存音频文件
        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"TTS 成功: {output_path}")

        # 返回 TTS 数据
        return TTSData(
            text=text,
            audio_path=output_path,
            model=self.config.model,
            voice=self.config.voice,
        )
