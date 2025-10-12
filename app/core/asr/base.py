import os
import threading
import zlib
from typing import Callable, Optional, Union, cast

from app.core.utils.cache import get_asr_cache, is_cache_enabled
from app.core.utils.logger import setup_logger

from .asr_data import ASRData, ASRDataSeg

logger = setup_logger("asr")


class BaseASR:
    """Base class for ASR (Automatic Speech Recognition) implementations.

    Provides common functionality including:
    - Audio file loading and validation
    - CRC32-based file identification
    - Disk caching with automatic key generation
    - Template method pattern for subclass implementation
    """

    SUPPORTED_SOUND_FORMAT = ["flac", "m4a", "mp3", "wav"]
    _lock = threading.Lock()

    def __init__(
        self,
        audio_path: Optional[Union[str, bytes]] = None,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
    ):
        """Initialize ASR with audio data.

        Args:
            audio_path: Path to audio file or raw audio bytes
            use_cache: Whether to cache recognition results
            need_word_time_stamp: Whether to return word-level timestamps
        """
        self.audio_path = audio_path
        self.file_binary = None
        self.use_cache = use_cache
        self._set_data()
        self._cache = get_asr_cache()

    def _set_data(self):
        """Load audio data and compute CRC32 hash for cache key."""
        if isinstance(self.audio_path, bytes):
            self.file_binary = self.audio_path
        elif isinstance(self.audio_path, str):
            ext = self.audio_path.split(".")[-1].lower()
            assert (
                ext in self.SUPPORTED_SOUND_FORMAT
            ), f"Unsupported sound format: {ext}"
            assert os.path.exists(self.audio_path), f"File not found: {self.audio_path}"
            with open(self.audio_path, "rb") as f:
                self.file_binary = f.read()
        else:
            raise ValueError("audio_path must be provided as string or bytes")
        crc32_value = zlib.crc32(self.file_binary) & 0xFFFFFFFF
        self.crc32_hex = format(crc32_value, "08x")

    def run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs
    ) -> ASRData:
        """Run ASR with caching support.

        Args:
            callback: Optional progress callback(progress: int, message: str)
            **kwargs: Additional arguments passed to _run()

        Returns:
            ASRData: Recognition results with segments
        """
        cache_key = f"{self.__class__.__name__}:{self._get_key()}"

        # Try cache first
        if self.use_cache and is_cache_enabled():
            cached_result = cast(
                Optional[dict], self._cache.get(cache_key, default=None)
            )
            if cached_result is not None:
                logger.info("找到缓存，直接返回")
                segments = self._make_segments(cached_result)
                return ASRData(segments)

        # Run ASR
        resp_data = self._run(callback, **kwargs)

        # Cache result
        if self.use_cache and is_cache_enabled():
            self._cache.set(cache_key, resp_data)

        segments = self._make_segments(resp_data)
        return ASRData(segments)

    def _get_key(self) -> str:
        """Get cache key for this ASR request.

        Default implementation uses file CRC32.
        Subclasses can override to include additional parameters.

        Returns:
            Cache key string
        """
        return self.crc32_hex

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        """Convert ASR response to segment list.

        Args:
            resp_data: Raw response from ASR service

        Returns:
            List of ASRDataSeg objects
        """
        raise NotImplementedError(
            "_make_segments method must be implemented in subclass"
        )

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs
    ) -> dict:
        """Execute ASR service and return raw response.

        Args:
            callback: Progress callback(progress: int, message: str)
            **kwargs: Implementation-specific parameters

        Returns:
            Raw response data (dict or str depending on implementation)
        """
        raise NotImplementedError("_run method must be implemented in subclass")
