"""SiliconFlow TTS 实现"""

import hashlib
from pathlib import Path

import requests

from app.core.tts.base import BaseTTS
from app.core.tts.tts_data import TTSConfig, TTSDataSeg
from app.core.utils.cache import get_tts_cache
from app.core.utils.logger import setup_logger

logger = setup_logger("tts.siliconflow")


class VoiceCloneManager:
    """声音克隆管理器 - 处理音频上传和 URI 缓存"""

    def __init__(self, api_key: str, base_url: str):
        """初始化

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.cache = get_tts_cache()

    def upload_voice(
        self,
        audio_path: str,
        text: str,
        model: str = "FunAudioLLM/CosyVoice2-0.5B",
    ) -> str:
        """上传音频并获取声音克隆 URI

        Args:
            audio_path: 音频文件路径
            text: 对应文本内容
            model: 模型名称

        Returns:
            voice_uri: 形如 speech:your-voice-name:xxx:xxx 的 URI

        Raises:
            FileNotFoundError: 音频文件不存在
            ValueError: API 返回错误
        """
        # 检查文件是否存在
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        # 检查缓存（避免重复上传）
        cache_key = self._generate_cache_key(audio_path, text, model)
        cached_uri = self.cache.get(cache_key)
        if cached_uri:
            logger.info(f"使用缓存的声音克隆 URI: {cached_uri}")
            return cached_uri

        logger.info(f"上传声音克隆音频: {audio_path}, 对应文本: {text[:50]}...")

        custom_name = "video_captioner"
        url = f"{self.base_url}/uploads/audio/voice"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        with open(audio_path, "rb") as f:
            files = {"file": (audio_file.name, f, "audio/mpeg")}
            data = {"model": model, "customName": custom_name, "text": text}

            try:
                response = requests.post(
                    url, headers=headers, files=files, data=data, timeout=60
                )
                response.raise_for_status()
            except requests.HTTPError as e:
                if e.response.status_code == 400:
                    raise ValueError(f"音频上传失败（参数错误）: {e.response.text}")
                elif e.response.status_code == 401:
                    raise ValueError("API Key 无效")
                else:
                    raise ValueError(f"音频上传失败: {e.response.text}")

        result = response.json()
        voice_uri = result.get("uri")
        if not voice_uri:
            raise ValueError(f"API 未返回 URI: {result}")

        logger.info(f"获得声音克隆 URI: {voice_uri}")

        # 缓存 URI
        self.cache.set(cache_key, voice_uri, expire=86400 * 2)

        return voice_uri

    def _generate_cache_key(self, audio_path: str, text: str, model: str) -> str:
        """生成缓存键（基于文件内容哈希）"""
        with open(audio_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        content = f"voice_clone_{file_hash}_{text}_{model}"
        return hashlib.md5(content.encode()).hexdigest()


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

        # 初始化声音克隆管理器
        self.voice_manager = VoiceCloneManager(config.api_key, config.base_url)

    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        """合成语音的核心实现

        Args:
            segment: TTS 数据段（需要填充 audio_path, voice, clone_voice_uri）
            output_path: 输出音频路径
        """
        url = f"{self.config.base_url}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        # 构建请求数据
        payload = {
            "model": self.config.model,
            "input": segment.text,
            "response_format": self.config.response_format,
            "sample_rate": self.config.sample_rate,
            "speed": self.config.speed,
            "gain": self.config.gain,
        }

        # 音色选择（优先级：声音克隆 > segment指定 > 全局配置）
        voice_to_use = None

        if segment.clone_audio_path and segment.clone_audio_text:
            # 使用声音克隆
            logger.info(f"上传声音克隆音频: {segment.clone_audio_path}")
            voice_uri = self.voice_manager.upload_voice(
                audio_path=segment.clone_audio_path,
                text=segment.clone_audio_text,
                model=self.config.model,
            )
            voice_to_use = voice_uri
            segment.clone_voice_uri = voice_uri
            logger.info(f"使用克隆音色: {voice_uri}")

        elif segment.voice:
            # segment 指定了音色
            voice_to_use = segment.voice

        elif self.config.voice:
            # 使用全局配置的音色
            voice_to_use = self.config.voice

        if voice_to_use:
            payload["voice"] = voice_to_use

        if self.config.stream:
            payload["stream"] = self.config.stream

        # 发送请求
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

        # 更新 segment
        segment.audio_path = output_path
        segment.voice = voice_to_use
        # TODO: 获取实际音频时长
        # segment.audio_duration = get_audio_duration(output_path)
