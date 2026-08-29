import os
import subprocess
import tempfile
from typing import Any, Callable, List, Optional, Union

from openai import OpenAI

from videocaptioner.core.llm.client import normalize_base_url

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("whisper_api")
MAX_UPLOAD_BYTES = 24 * 1024 * 1024


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
        temp_path = None
        try:
            if self.language == "zh" and not self.prompt:
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子"

            if not self.base_url:
                raise ValueError("Whisper BASE_URL must be set")

            audio_binary = self.file_binary or b""
            if len(audio_binary) > MAX_UPLOAD_BYTES:
                logger.info(
                    "音频过大 (%d 字节)，使用 ffmpeg 压缩后上传...", len(audio_binary)
                )
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", prefix="VideoCaptioner_whisper_", delete=False
                ) as temp_file:
                    temp_path = temp_file.name

                cmd = ["ffmpeg", "-y"]
                input_data = None
                if isinstance(self.audio_input, str):
                    cmd.extend(["-i", self.audio_input])
                else:
                    # Raw bytes do not carry a filename, so let ffmpeg probe stdin.
                    cmd.extend(["-i", "pipe:0"])
                    input_data = audio_binary
                cmd.extend(
                    [
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-b:a",
                        "32k",
                        "-f",
                        "mp3",
                        temp_path,
                    ]
                )

                result = subprocess.run(
                    cmd,
                    input=input_data,
                    capture_output=True,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )
                if (
                    result.returncode != 0
                    or not os.path.isfile(temp_path)
                    or os.path.getsize(temp_path) == 0
                ):
                    raw_stderr = result.stderr or b""
                    stderr = (
                        raw_stderr.decode(errors="replace")
                        if isinstance(raw_stderr, bytes)
                        else str(raw_stderr)
                    )
                    raise RuntimeError(f"ffmpeg 压缩音频失败: {stderr}")

                with open(temp_path, "rb") as compressed_file:
                    audio_binary = compressed_file.read()
                logger.info("压缩后音频大小: %d 字节", len(audio_binary))

            api_kwargs: dict[str, Any] = {
                "model": self.model,
                "response_format": "verbose_json",
                "file": ("audio.mp3", audio_binary, "audio/mp3"),
                "prompt": self.prompt,
                "timestamp_granularities": ["word", "segment"],
            }
            # 空字符串表示自动检测，不传 language 参数让 API 自行判断
            if self.language:
                api_kwargs["language"] = self.language

            completion = self.client.audio.transcriptions.create(**api_kwargs)
            if isinstance(completion, str):
                raise ValueError(
                    "WhisperAPI returned type error, please check your base URL."
                )
            return completion.to_dict()
        except Exception:
            logger.exception("WhisperAPI failed")
            raise
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning("无法删除 WhisperAPI 临时音频: %s", temp_path)
