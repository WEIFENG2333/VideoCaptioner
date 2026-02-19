import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

from ...config import MODEL_PATH
from ..utils.logger import setup_logger
from ..utils.subprocess_helper import StreamReader
from .asr_data import ASRData, ASRDataSeg
from .base import BaseASR
from .status import ASRStatus

logger = setup_logger("whisper_asr")


class WhisperCppASR(BaseASR):
    """Whisper.cpp local ASR implementation.

    Runs whisper.cpp binary for local ASR processing.
    """

    def __init__(
        self,
        audio_input: Union[str, bytes],
        language="en",
        whisper_cpp_path=None,
        whisper_model=None,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        enable_vad: bool = False,
        vad_model: Optional[str] = None,
        vad_threshold: float = 0.3,
        vad_min_speech_duration_ms: int = 150,
        vad_min_silence_duration_ms: int = 200,
        vad_max_speech_duration_s: int = 30,
        vad_speech_pad_ms: int = 50,
    ):
        super().__init__(audio_input, use_cache)

        if isinstance(audio_input, str):
            assert os.path.exists(audio_input), f"Audio file not found: {audio_input}"
            assert audio_input.endswith(
                ".wav"
            ), f"Audio must be WAV format: {audio_input}"

        # Auto-detect whisper executable if not provided
        if whisper_cpp_path is None:
            whisper_cpp_path = detect_whisper_executable()

        # Find model file in models directory
        models_dir = Path(MODEL_PATH)
        if whisper_model:
            model_files = list(models_dir.glob(f"*ggml*{whisper_model}*.bin"))
            if not model_files:
                raise ValueError(
                    f"Model file not found in {models_dir} for: {whisper_model}"
                )
            model_path = str(model_files[0])
            logger.info(f"Model found: {model_path}")
        else:
            raise ValueError("whisper_model cannot be empty")

        self.model_path = model_path
        self.whisper_cpp_path = Path(whisper_cpp_path)
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language
        self.enable_vad = enable_vad
        self.vad_model_path = None
        self.vad_threshold = vad_threshold
        self.vad_min_speech_duration_ms = vad_min_speech_duration_ms
        self.vad_min_silence_duration_ms = vad_min_silence_duration_ms
        self.vad_max_speech_duration_s = vad_max_speech_duration_s
        self.vad_speech_pad_ms = vad_speech_pad_ms

        if self.enable_vad:
            if vad_model:
                vad_model_files = list(models_dir.glob(f"*{vad_model}*.bin"))
                if vad_model_files:
                    self.vad_model_path = str(vad_model_files[0])
                    logger.info(f"VAD Model found: {self.vad_model_path}")
                elif os.path.exists(vad_model):
                    self.vad_model_path = vad_model
                    logger.info(f"VAD Model found at path: {self.vad_model_path}")
                else:
                     logger.warning(f"VAD Model not found: {vad_model}, VAD will be disabled")
                     self.enable_vad = False
            else:
                 logger.warning("VAD enabled but no model provided. VAD will be disabled unless a default is found (not implemented).")
                 self.enable_vad = False

        self.process = None

    def _make_segments(self, resp_data: str) -> List[ASRDataSeg]:
        asr_data = ASRData.from_srt(resp_data)
        # 过滤掉纯音乐标记
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()
            # 保留不以【、[、(、（开头的文本
            if not (
                text.startswith("【")
                or text.startswith("[")
                or text.startswith("(")
                or text.startswith("（")
            ):
                filtered_segments.append(seg)
        return filtered_segments

    def _build_command(
        self, wav_path, output_path, is_const_me_version: bool
    ) -> list[str]:
        """Build whisper-cpp command line arguments."""
        whisper_params = [
            str(self.whisper_cpp_path),
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "-l",
            self.language or "auto",
            "--output-srt",
        ]

        if not is_const_me_version:
            if sys.platform != "darwin":
                whisper_params.append("--no-gpu")

            whisper_params.extend(
                ["--output-file", str(output_path.with_suffix(""))]
            )

        if self.language == "zh":
            whisper_params.extend(
                ["--prompt", "你好，我们需要使用简体中文，以下是普通话的句子。"]
            )

        if self.enable_vad and self.vad_model_path:
            whisper_params.append("--vad")
            whisper_params.extend(["-vm", str(self.vad_model_path)])
            whisper_params.extend(["-vt", str(self.vad_threshold)])
            whisper_params.extend(["-vspd", str(self.vad_min_speech_duration_ms)])
            whisper_params.extend(["-vsd", str(self.vad_min_silence_duration_ms)])
            whisper_params.extend(["-vmsd", str(self.vad_max_speech_duration_s)])
            whisper_params.extend(["-vp", str(self.vad_speech_pad_ms)])

        return whisper_params

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> str:
        def _default_callback(_progress: int, _message: str) -> None:
            pass

        if callback is None:
            callback = _default_callback

        is_const_me_version = True if os.name == "nt" else False

        with tempfile.TemporaryDirectory() as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "whisper_cpp_audio.wav"
            output_path = wav_path.with_suffix(".srt")

            try:
                # 复制音频文件
                if isinstance(self.audio_input, str):
                    shutil.copy2(self.audio_input, wav_path)
                else:
                    if self.file_binary:
                        wav_path.write_bytes(self.file_binary)
                    else:
                        raise ValueError("No audio data available")

                # Build command
                whisper_params = self._build_command(
                    wav_path, output_path, is_const_me_version
                )
                logger.info("Whisper.cpp command: %s", " ".join(whisper_params))

                # Get audio duration
                total_duration = self.audio_duration
                logger.info("Audio duration: %d seconds", total_duration)

                # Start process
                self.process = subprocess.Popen(
                    whisper_params,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )

                logger.info(f"Whisper.cpp process started, PID: {self.process.pid}")

                # Process output with StreamReader
                reader = StreamReader(self.process)
                reader.start_reading()

                last_progress = 0

                while True:
                    # Check process status
                    if self.process.poll() is not None:
                        time.sleep(0.2)
                        for stream_name, line in reader.get_remaining_output():
                            if stream_name == "stderr":
                                logger.debug(f"[stderr] {line.strip()}")
                        break

                    # Non-blocking output reading
                    output = reader.get_output(timeout=0.1)
                    if output:
                        stream_name, line = output

                        if stream_name == "stdout":
                            logger.debug(f"[stdout] {line.strip()}")

                            # Parse progress
                            if " --> " in line and "[" in line:
                                try:
                                    time_str = (
                                        line.split("[")[1].split(" -->")[0].strip()
                                    )
                                    parts = time_str.split(":")
                                    current_time = sum(
                                        float(x) * y
                                        for x, y in zip(reversed(parts), [1, 60, 3600])
                                    )
                                    progress = int(
                                        min(current_time / total_duration * 100, 98)
                                    )

                                    if progress > last_progress:
                                        last_progress = progress
                                        callback(progress, f"{progress}%")
                                except (ValueError, IndexError) as e:
                                    logger.debug(f"Progress parse failed: {e}")
                        else:
                            logger.debug(f"[stderr] {line.strip()}")

                # Check return code
                if self.process.returncode != 0:
                    raise RuntimeError(
                        f"Whisper.cpp failed with code: {self.process.returncode}"
                    )

                callback(*ASRStatus.COMPLETED.callback_tuple())
                logger.info("Whisper.cpp ASR completed")

                # Read result file
                srt_path = output_path
                if not srt_path.exists():
                    time.sleep(5)
                    if not srt_path.exists():
                        raise RuntimeError(f"Output file not generated: {srt_path}")

                return srt_path.read_text(encoding="utf-8")

            except Exception as e:
                logger.exception("ASR processing failed")
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                raise RuntimeError(f"SRT generation failed: {str(e)}")

    def _get_key(self):
        return f"{self.crc32_hex}-{self.need_word_time_stamp}-{self.model_path}-{self.language}-{self.enable_vad}-{self.vad_model_path}-{self.vad_threshold}-{self.vad_min_speech_duration_ms}-{self.vad_min_silence_duration_ms}-{self.vad_max_speech_duration_s}-{self.vad_speech_pad_ms}"

    def get_audio_duration(self, filepath: str) -> int:
        """Get audio file duration in seconds using ffmpeg."""
        try:
            cmd = ["ffmpeg", "-i", filepath]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            info = result.stderr
            if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
                hours, minutes, seconds = map(float, duration_match.groups())
                duration_seconds = hours * 3600 + minutes * 60 + seconds
                return int(duration_seconds)
            return 600
        except Exception as e:
            logger.exception("Failed to get audio duration: %s", str(e))
            return 600


def detect_whisper_executable() -> str:
    """Detect available whisper-cpp executable name."""
    # Try new version first (whisper-cli)
    if shutil.which("whisper-cli"):
        return "whisper-cli"

    # Fall back to old version (whisper-cpp)
    if shutil.which("whisper-cpp"):
        return "whisper-cpp"

    # Neither found
    raise RuntimeError("Neither 'whisper-cli' nor 'whisper-cpp' found in PATH. ")


if __name__ == "__main__":
    # 简短示例
    asr = WhisperCppASR(
        audio_input="audio.mp3",
        whisper_model="tiny",
        whisper_cpp_path="bin/whisper-cpp.exe",
        language="en",
        need_word_time_stamp=True,
    )
    asr_data = asr._run(callback=print)
