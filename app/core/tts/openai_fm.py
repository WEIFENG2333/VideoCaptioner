"""OpenAI.fm TTS 实现

OpenAI.fm 是一个免费的 TTS 服务，提供多种音色和语音风格。
API 文档: https://www.openai.fm/
"""

from urllib.parse import quote

import requests

from app.core.tts.base import BaseTTS
from app.core.tts.tts_data import TTSConfig, TTSDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("tts.openai_fm")


class OpenAIFmTTS(BaseTTS):
    """OpenAI.fm TTS API 实现

    免费的云端 TTS 服务，支持多种音色和语音风格。
    """

    # 预定义音色
    VOICES = {
        "alloy": "alloy",
        "echo": "echo",
        "fable": "fable",
        "onyx": "onyx",
        "nova": "nova",
        "shimmer": "shimmer",
    }

    # 预定义提示词模板
    PROMPT_TEMPLATES = {
        "natural": "Natural and conversational voice with clear pronunciation.",
        "professional": "Professional and formal tone, suitable for business presentations.",
        "friendly": "Warm and friendly tone, like talking to a friend.",
        "storyteller": "Expressive and engaging, perfect for storytelling.",
        "news": "Clear and authoritative, like a news anchor.",
        "casual": "Relaxed and informal, everyday conversation style.",
    }

    # API 端点（固定，不可配置）
    API_URL = "https://www.openai.fm/api/generate"

    def __init__(self, config: TTSConfig):
        """初始化

        Args:
            config: TTS 配置
                - voice: 音色选择 (alloy, echo, fable, onyx, nova, shimmer)
                - 不需要 api_key 和 base_url
        """
        super().__init__(config)

        # 默认音色
        if not config.voice:
            config.voice = "fable"

    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        """合成语音的核心实现

        Args:
            segment: TTS 数据段
            output_path: 输出音频路径
        """
        # 构建提示词
        prompt = self._build_prompt()

        # 音色选择
        voice_to_use = segment.voice or self.config.voice or "fable"

        # 构建请求参数
        params = {
            "input": segment.text,
            "prompt": prompt,
            "voice": voice_to_use,
        }

        logger.info(
            f"调用 OpenAI.fm TTS API: {segment.text[:50]}... (voice={voice_to_use})"
        )

        # 发送请求（使用固定 API URL）
        response = requests.get(
            self.API_URL,
            params=params,
            timeout=self.config.timeout,
        )
        response.raise_for_status()

        # 保存音频文件
        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"TTS 成功: {output_path}")

        # 更新 segment
        segment.audio_path = output_path
        segment.voice = voice_to_use

    def _build_prompt(self) -> str:
        """构建提示词

        Returns:
            提示词字符串
        """
        # 如果配置中有自定义提示词，直接使用
        if self.config.custom_prompt:
            return self.config.custom_prompt

        # 使用默认提示词
        return self.PROMPT_TEMPLATES["natural"]

    @staticmethod
    def get_available_voices():
        """获取可用音色列表

        Returns:
            音色列表
        """
        return list(OpenAIFmTTS.VOICES.keys())

    @staticmethod
    def get_prompt_templates():
        """获取预定义提示词模板

        Returns:
            提示词模板字典
        """
        return OpenAIFmTTS.PROMPT_TEMPLATES.copy()
