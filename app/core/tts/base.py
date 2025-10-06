"""TTS 基类 - 提供缓存、批量处理等通用功能"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional, cast

from app.core.tts.status import TTSStatus
from app.core.tts.tts_data import TTSConfig, TTSData, TTSDataSeg
from app.core.utils.cache import get_tts_cache, is_cache_enabled
from app.core.utils.logger import setup_logger

logger = setup_logger("tts")


class BaseTTS(ABC):
    """TTS 基类

    提供通用功能：
    - 缓存机制（二进制数据缓存）
    - 批量处理（统一接口）
    - 配置管理
    """

    def __init__(self, config: TTSConfig):
        """初始化

        Args:
            config: TTS 配置
        """
        self.config = config
        self.cache = get_tts_cache()  # 总是初始化缓存实例

    def synthesize(
        self,
        tts_data: TTSData,
        output_dir: str,
        callback: Optional[Callable[[int, str], None]] = None,
    ) -> TTSData:
        """合成语音（统一批量处理接口）

        Args:
            tts_data: TTS 数据（包含多个待合成的文本段）
            output_dir: 输出目录
            callback: 进度回调函数 callback(progress: int, message: str)

        Returns:
            TTS 数据（segments 已填充 audio_path 等信息）
        """

        def _default_callback(progress: int, message: str):
            pass

        if callback is None:
            callback = _default_callback

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        total = len(tts_data.segments)
        if total == 0:
            logger.warning("TTS 数据为空，无需合成")
            return tts_data

        logger.info(f"开始批量合成 {total} 条语音")

        for idx, segment in enumerate(tts_data.segments):
            try:
                # 计算进度
                progress = int((idx / total) * 100)
                callback(progress, "synthesizing")

                # 生成音频文件名
                audio_filename = self._generate_filename(segment.text, idx)
                audio_path = output_path / audio_filename

                # 合成单条语音（带缓存）
                self._synthesize_segment(segment, str(audio_path))

            except Exception as e:
                logger.error(
                    f"TTS 失败 [{idx+1}/{total}]: {segment.text[:50]}... - {str(e)}"
                )
                # 失败时保持 segment，但不设置 audio_path

        callback(*TTSStatus.COMPLETED.callback_tuple())
        success_count = sum(1 for seg in tts_data.segments if seg.audio_path)
        logger.info(f"批量 TTS 完成: 成功 {success_count}/{total}")
        return tts_data

    def _synthesize_segment(self, segment: TTSDataSeg, output_path: str) -> None:
        """合成单个片段的语音（带缓存）

        Args:
            segment: TTS 数据段（会被修改，填充 audio_path 等）
            output_path: 输出音频路径
        """
        # 生成缓存键（考虑声音克隆）
        cache_key = self._generate_cache_key_for_segment(segment)

        # 检查缓存
        if self.config.use_cache and is_cache_enabled():
            cached_audio_data = cast(Optional[bytes], self.cache.get(cache_key))

            if cached_audio_data:
                logger.info(f"使用缓存: {segment.text[:50]}...")
                # 将缓存的二进制数据写入文件
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(cached_audio_data)

                # 更新 segment
                segment.audio_path = output_path
                # TODO: 从缓存元数据中获取 audio_duration
                return

        # 调用子类实现的核心方法
        self._synthesize(segment, output_path)

        # 保存二进制数据到缓存
        if self.config.use_cache and is_cache_enabled():
            try:
                with open(output_path, "rb") as f:
                    audio_data = f.read()
                self.cache.set(cache_key, audio_data, expire=self.config.cache_ttl)
            except Exception as e:
                logger.warning(f"缓存保存失败: {str(e)}")

    @abstractmethod
    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        """合成语音的核心实现（子类必须实现）

        Args:
            segment: TTS 数据段（需要填充 audio_path, voice, clone_voice_uri 等字段）
            output_path: 输出音频路径
        """
        pass

    def _generate_cache_key_for_segment(self, segment: TTSDataSeg) -> str:
        """为 segment 生成缓存键（考虑声音克隆）"""
        content_parts = [
            segment.text,
            self.config.model,
            str(self.config.speed),
            str(self.config.gain),
        ]

        # 音色信息
        if segment.clone_audio_path and segment.clone_audio_text:
            # 声音克隆：使用参考音频的哈希
            try:
                with open(segment.clone_audio_path, "rb") as f:
                    audio_hash = hashlib.md5(f.read()).hexdigest()[:12]
                content_parts.append(f"clone_{audio_hash}")
            except Exception:
                content_parts.append(f"clone_{segment.clone_audio_path}")
        elif segment.voice:
            # 指定音色
            content_parts.append(f"voice_{segment.voice}")
        elif self.config.voice:
            # 默认音色
            content_parts.append(f"voice_{self.config.voice}")

        content = "_".join(content_parts)
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
