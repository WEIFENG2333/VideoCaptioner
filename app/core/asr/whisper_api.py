from typing import Any, Callable, List, Optional, Union

from openai import OpenAI

from app.core.llm.client import normalize_base_url

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("whisper_api")


class WhisperAPI(BaseASR):
    """OpenAI-compatible Whisper API implementation.

    Supports any OpenAI-compatible ASR API endpoint.
    """

    def __init__(
        self,
        audio_input: Union[str, bytes],
        whisper_model: str,
        need_word_time_stamp: bool = False,
        language: str = "zh",
        prompt: str = "",
        base_url: str = "",
        api_key: str = "",
        use_cache: bool = False,
    ):
        """Initialize Whisper API.

        Args:
            audio_input: Path to audio file or raw audio bytes
            whisper_model: Model name
            need_word_time_stamp: Return word-level timestamps
            language: Language code (default: zh)
            prompt: Initial prompt for model
            base_url: API base URL
            api_key: API key
            use_cache: Enable caching
        """
        super().__init__(audio_input, use_cache)

        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key.strip()

        if not self.base_url or not self.api_key:
            raise ValueError("Whisper BASE_URL and API_KEY must be set")

        self.model = whisper_model
        self.language = language
        self.prompt = prompt
        self.need_word_time_stamp = need_word_time_stamp

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        """Execute ASR via API."""
        return self._submit()

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        """Convert API response to segments."""
        if self.need_word_time_stamp and "words" in resp_data:
            return [
                ASRDataSeg(
                    text=word["word"],
                    start_time=int(float(word["start"]) * 1000),
                    end_time=int(float(word["end"]) * 1000),
                )
                for word in resp_data["words"]
            ]
        else:
            return [
                ASRDataSeg(
                    text=seg["text"].strip(),
                    start_time=int(float(seg["start"]) * 1000),
                    end_time=int(float(seg["end"]) * 1000),
                )
                for seg in resp_data["segments"]
            ]

    def _get_key(self) -> str:
        """Get cache key including model and language."""
        return f"{self.crc32_hex}-{self.model}-{self.language}-{self.prompt}"

    def _submit(self) -> dict:
        """Submit audio for transcription."""
        try:
            if self.language == "zh" and not self.prompt:
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子"

            if not self.base_url:
                raise ValueError("Whisper BASE_URL must be set")

            completion = self.client.audio.transcriptions.create(
                model=self.model,
                response_format="verbose_json",
                file=("audio.mp3", self.file_binary or b"", "audio/mp3"),
                prompt=self.prompt,
                language=self.language,
                timestamp_granularities=["word", "segment"],
            )
            if isinstance(completion, str):
                raise ValueError(
                    "WhisperAPI returned type error, please check your base URL."
                )
            return completion.to_dict()
        except Exception as e:
            logger.exception(f"WhisperAPI failed: {str(e)}")
            raise e
