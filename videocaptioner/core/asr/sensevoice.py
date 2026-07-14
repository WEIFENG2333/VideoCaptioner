import importlib
import re
import threading
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, ClassVar, Optional, Union

from pydub import AudioSegment

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("sensevoice")


class SenseVoiceASR(BaseASR):
    """Local SenseVoice inference through the optional FunASR runtime."""

    DEFAULT_MODEL = "iic/SenseVoiceSmall"
    SENTENCE_ENDINGS = frozenset(".!?。！？")
    MAX_SENTENCE_DURATION_MS = 10_000
    SILENCE_SPLIT_MS = 1_200
    _RICH_TAG_PATTERN = re.compile(r"<\|[^|]*\|>")
    _NO_SPACE_BEFORE = frozenset(".,!?;:%)]}，。！？；：、…'’")
    _NO_SPACE_AFTER = frozenset("([{'‘“")

    _model_cache: ClassVar[dict[tuple[str, str], Any]] = {}
    _model_cache_lock: ClassVar[threading.Lock] = threading.Lock()
    _inference_locks: ClassVar[dict[tuple[str, str], threading.Lock]] = {}

    def __init__(
        self,
        audio_input: Union[str, bytes],
        model: str = DEFAULT_MODEL,
        device: str = "auto",
        language: str = "auto",
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
    ):
        super().__init__(audio_input, use_cache, need_word_time_stamp)
        self.model_name = model or self.DEFAULT_MODEL
        self.device = device or "auto"
        self.language = language or "auto"
        self.need_word_time_stamp = need_word_time_stamp

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device

        try:
            torch = importlib.import_module("torch")
        except ImportError:
            return "cpu"

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _create_model(self, device: str):
        try:
            AutoModel = importlib.import_module("funasr").AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "SenseVoice requires the optional FunASR runtime. "
                "Install it with: pip install 'videocaptioner[sensevoice]'"
            ) from exc

        return AutoModel(
            model=self.model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30_000},
            device=device,
            disable_update=True,
            disable_pbar=True,
        )

    def _get_model(self):
        device = self._resolve_device(self.device)
        cache_key = (self.model_name, device)
        with self._model_cache_lock:
            if cache_key not in self._model_cache:
                logger.info("Loading SenseVoice model %s on %s", self.model_name, device)
                self._model_cache[cache_key] = self._create_model(device)
            self._inference_locks.setdefault(cache_key, threading.Lock())
            return self._model_cache[cache_key]

    @classmethod
    def _get_inference_lock(cls, model: str, device: str) -> threading.Lock:
        cache_key = (model, device)
        with cls._model_cache_lock:
            return cls._inference_locks.setdefault(cache_key, threading.Lock())

    def _run(self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any) -> dict:
        def default_callback(_progress: int, _message: str) -> None:
            pass

        progress_handler = callback or default_callback

        progress_handler(5, "Loading SenseVoice model")
        device = self._resolve_device(self.device)
        model = self._get_model()

        def progress_callback(current: int, total: int) -> None:
            if total > 0:
                progress = min(95, 5 + int(current / total * 90))
                progress_handler(progress, "Transcribing with SenseVoice")

        def generate(audio_input: str) -> list[dict]:
            with self._get_inference_lock(self.model_name, device):
                return model.generate(
                    input=audio_input,
                    cache={},
                    language=self.language,
                    use_itn=True,
                    batch_size_s=60,
                    merge_vad=True,
                    merge_length_s=15,
                    output_timestamp=True,
                    return_time_stamps=True,
                    progress_callback=progress_callback,
                )

        if isinstance(self.audio_input, bytes):
            with TemporaryDirectory() as temp_dir:
                wav_path = Path(temp_dir) / "sensevoice_input.wav"
                audio = AudioSegment.from_file(BytesIO(self.audio_input))
                audio.set_channels(1).set_frame_rate(16_000).export(wav_path, format="wav")
                results = generate(str(wav_path))
        elif isinstance(self.audio_input, str):
            results = generate(self.audio_input)
        else:
            raise ValueError("audio_input must be provided as string or bytes")

        progress_handler(100, "SenseVoice transcription completed")
        return {"results": results or []}

    @classmethod
    def _clean_text(cls, text: str) -> str:
        try:
            postprocess = importlib.import_module("funasr.utils.postprocess_utils")
        except ImportError:
            return cls._RICH_TAG_PATTERN.sub("", text or "").strip()
        return postprocess.rich_transcription_postprocess(text or "").strip()

    @staticmethod
    def _timestamp_pair_ms(timestamp: Any) -> Optional[tuple[int, int]]:
        if isinstance(timestamp, dict):
            start = timestamp.get("start_time", timestamp.get("start"))
            end = timestamp.get("end_time", timestamp.get("end"))
            if start is None or end is None:
                return None
            start_ms = int(float(start) * 1000)
            end_ms = int(float(end) * 1000)
        elif isinstance(timestamp, (list, tuple)) and len(timestamp) >= 2:
            start_ms = int(timestamp[0])
            end_ms = int(timestamp[1])
        else:
            return None

        if start_ms < 0 or end_ms <= start_ms:
            return None
        return start_ms, end_ms

    @classmethod
    def _aligned_words(cls, result: dict) -> list[tuple[str, int, int]]:
        words = result.get("words") or []
        timestamps = result.get("timestamp") or result.get("timestamps") or []
        if len(words) != len(timestamps):
            return []

        aligned = []
        for word, timestamp in zip(words, timestamps):
            pair = cls._timestamp_pair_ms(timestamp)
            text = cls._RICH_TAG_PATTERN.sub("", str(word)).strip()
            if pair is None or not text:
                continue
            aligned.append((text, pair[0], pair[1]))
        return aligned if len(aligned) == len(words) else []

    @staticmethod
    def _is_cjk(char: str) -> bool:
        return any(
            start <= ord(char) <= end
            for start, end in (
                (0x3040, 0x30FF),
                (0x3400, 0x4DBF),
                (0x4E00, 0x9FFF),
                (0xAC00, 0xD7AF),
            )
        )

    @classmethod
    def _join_words(cls, words: list[str]) -> str:
        text = ""
        for word in words:
            if not text:
                text = word
            elif (
                word[0] in cls._NO_SPACE_BEFORE
                or text[-1] in cls._NO_SPACE_AFTER
                or (cls._is_cjk(text[-1]) and cls._is_cjk(word[0]))
            ):
                text += word
            else:
                text += f" {word}"
        return text.strip()

    @classmethod
    def _group_words(cls, words: list[tuple[str, int, int]]) -> list[ASRDataSeg]:
        segments = []
        current: list[tuple[str, int, int]] = []

        def flush() -> None:
            if not current:
                return
            segments.append(
                ASRDataSeg(
                    text=cls._join_words([word for word, _, _ in current]),
                    start_time=current[0][1],
                    end_time=current[-1][2],
                )
            )
            current.clear()

        for word in words:
            if current and word[1] - current[-1][2] >= cls.SILENCE_SPLIT_MS:
                flush()

            current.append(word)
            duration = current[-1][2] - current[0][1]
            if word[0][-1] in cls.SENTENCE_ENDINGS or duration >= cls.MAX_SENTENCE_DURATION_MS:
                flush()

        flush()
        return segments

    @classmethod
    def _timestamp_bounds_ms(cls, result: dict) -> Optional[tuple[int, int]]:
        timestamps = result.get("timestamp") or result.get("timestamps") or []
        pairs = [cls._timestamp_pair_ms(timestamp) for timestamp in timestamps]
        valid_pairs = [pair for pair in pairs if pair is not None]
        if not valid_pairs:
            return None
        return min(pair[0] for pair in valid_pairs), max(pair[1] for pair in valid_pairs)

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        segments = []
        for result in resp_data.get("results", []):
            aligned_words = self._aligned_words(result)
            if aligned_words:
                if self.need_word_time_stamp:
                    segments.extend(
                        ASRDataSeg(text=word, start_time=start, end_time=end)
                        for word, start, end in aligned_words
                    )
                else:
                    segments.extend(self._group_words(aligned_words))
                continue

            sentence_info = result.get("sentence_info") or []
            sentence_start = len(segments)
            for sentence in sentence_info:
                text = self._clean_text(sentence.get("sentence") or sentence.get("text", ""))
                start = int(sentence.get("start", 0) or 0)
                end = int(sentence.get("end", 0) or 0)
                if text and end > start:
                    segments.append(ASRDataSeg(text=text, start_time=start, end_time=end))

            if len(segments) > sentence_start:
                continue

            text = self._clean_text(result.get("text", ""))
            if not text:
                continue
            start, end = self._timestamp_bounds_ms(result) or (
                0,
                max(1, int(self.audio_duration * 1000)),
            )
            segments.append(ASRDataSeg(text=text, start_time=start, end_time=end))

        return segments

    def _get_key(self) -> str:
        return (
            f"{self.crc32_hex}-{self.model_name}-{self.device}-{self.language}-"
            f"{self.need_word_time_stamp}"
        )
