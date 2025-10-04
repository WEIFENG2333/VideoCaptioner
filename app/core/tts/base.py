"""TTS 基类 - 提供缓存、批量处理等通用功能"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, List, Optional

from app.core.tts.status import TTSStatus
from app.core.tts.tts_data import TTSBatchResult, TTSConfig, TTSData
from app.core.utils.cache import get_tts_cache, is_cache_enabled
from app.core.utils.logger import setup_logger

logger = setup_logger("tts")


class BaseTTS(ABC):
    """TTS 基类

    提供通用功能：
    - 缓存机制（二进制数据缓存）
    - 批量处理
    - 配置管理
    """

    def __init__(self, config: TTSConfig):
        """初始化

        Args:
            config: TTS 配置
        """
        self.config = config
        self.cache = get_tts_cache()  # 总是初始化缓存实例

    def synthesize_batch(
        self,
        texts: List[str],
        output_dir: str,
        callback: Optional[Callable[[int, str], None]] = None,
    ) -> TTSBatchResult:
        """批量合成语音

        Args:
            texts: 文本列表
            output_dir: 输出目录
            callback: 进度回调函数 callback(progress: int, message: str)

        Returns:
            批量结果
        """

        def _default_callback(progress: int, message: str):
            pass

        if callback is None:
            callback = _default_callback

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        result = TTSBatchResult()
        total = len(texts)

        for idx, text in enumerate(texts):
            try:
                # 计算进度：基于已完成数量的百分比
                progress = int((idx / total) * 100)
                callback(progress, "synthesizing")

                # 生成音频文件名
                audio_filename = self._generate_filename(text, idx)
                audio_path = output_path / audio_filename

                # 合成单条语音（带缓存）
                tts_data = self.synthesize(text, str(audio_path))
                result.items.append(tts_data)

            except Exception as e:
                logger.error(f"TTS 失败 [{idx+1}/{total}]: {text[:50]}... - {str(e)}")
                # 失败时添加空数据（保持索引对齐）
                result.items.append(
                    TTSData(text=text, audio_path="", audio_duration=0.0)
                )

        callback(*TTSStatus.COMPLETED.callback_tuple())
        success_count = sum(1 for item in result.items if item.audio_path)
        logger.info(f"批量 TTS 完成: 成功 {success_count}/{total}")
        return result

    def synthesize(
        self, text: str, output_path: str, use_cache: bool = False
    ) -> TTSData:
        """合成单条语音

        Args:
            text: 输入文本
            output_path: 输出音频路径
            use_cache: 是否使用缓存（默认 False）

        Returns:
            TTS 数据
        """
        # 确定是否使用缓存
        should_use_cache = use_cache

        # 检查缓存（缓存二进制数据）
        if should_use_cache and is_cache_enabled():
            cache_key = self._generate_cache_key(text)
            cached_audio_data = self.cache.get(cache_key)

            if cached_audio_data:
                logger.info(f"使用缓存: {text[:50]}...")
                # 将缓存的二进制数据写入文件
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(cached_audio_data)

                return TTSData(
                    text=text,
                    audio_path=output_path,
                    model=self.config.model,
                    voice=self.config.voice,
                )

        # 调用子类实现的核心方法
        tts_data = self._synthesize(text, output_path)

        # 保存二进制数据到缓存
        if should_use_cache and is_cache_enabled():
            cache_key = self._generate_cache_key(text)
            try:
                with open(output_path, "rb") as f:
                    audio_data = f.read()
                self.cache.set(cache_key, audio_data, expire=self.config.cache_ttl)
            except Exception as e:
                logger.warning(f"缓存保存失败: {str(e)}")

        return tts_data

    @abstractmethod
    def _synthesize(self, text: str, output_path: str) -> TTSData:
        """合成语音的核心实现（子类必须实现）

        Args:
            text: 输入文本
            output_path: 输出音频路径

        Returns:
            TTS 数据
        """
        pass

    def _generate_cache_key(self, text: str) -> str:
        """生成缓存键"""
        content = f"{text}_{self.config.model}_{self.config.voice}_{self.config.speed}"
        return hashlib.md5(content.encode()).hexdigest()

    def _generate_filename(self, text: str, index: int) -> str:
        """生成音频文件名

        Args:
            text: 文本内容
            index: 索引

        Returns:
            文件名
        """
        # 使用索引和文本哈希生成文件名
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        ext = self.config.response_format
        return f"tts_{index:04d}_{text_hash}.{ext}"
