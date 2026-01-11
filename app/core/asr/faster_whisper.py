import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import GPUtil

from ..utils.logger import setup_logger
from ..utils.subprocess_helper import StreamReader
from .asr_data import ASRData, ASRDataSeg
from .base import BaseASR
from .status import ASRStatus

logger = setup_logger("faster_whisper")


class FasterWhisperASR(BaseASR):
    """Faster-Whisper local ASR implementation.

    Runs whisper model locally using faster-whisper/faster-whisper-xxl binary.
    Supports CPU/CUDA acceleration and various VAD methods.
    """

    def __init__(
        self,
        audio_input: Union[str, bytes],
        faster_whisper_program: str,
        whisper_model: str,
        model_dir: str,
        language: str = "zh",
        device: str = "cpu",
        output_dir: Optional[str] = None,
        output_format: str = "srt",
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        # VAD 相关参数
        vad_filter: bool = True,
        vad_threshold: float = 0.4,
        vad_method: str = "",  # https://github.com/Purfview/whisper-standalone-win/discussions/231
        # 音频处理
        ff_mdx_kim2: bool = False,
        # 文本处理参数
        one_word: int = 0,
        sentence: bool = False,
        max_line_width: int = 100,
        max_line_count: int = 1,
        max_comma: int = 20,
        max_comma_cent: int = 50,
        prompt: Optional[str] = None,
    ):
        super().__init__(audio_input, use_cache)

        # 基本参数
        self.model_path = whisper_model
        self.model_dir = model_dir
        self.faster_whisper_program = faster_whisper_program
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language
        self.device = device
        self.output_dir = output_dir
        self.output_format = output_format

        # VAD 参数
        self.vad_filter = vad_filter
        self.vad_threshold = vad_threshold
        self.vad_method = vad_method

        # 音频处理参数
        self.ff_mdx_kim2 = ff_mdx_kim2

        # 文本处理参数
        self.one_word = one_word
        self.sentence = sentence
        self.max_line_width = max_line_width
        self.max_line_count = max_line_count
        self.max_comma = max_comma
        self.max_comma_cent = max_comma_cent
        self.prompt = prompt

        self.process = None

        # 断句宽度
        if self.language in ["zh", "ja", "ko"]:
            self.max_line_width = 30
        else:
            self.max_line_width = 90

        # 断句选项
        if self.need_word_time_stamp:
            self.one_word = 1
        else:
            self.one_word = 0
            self.sentence = True

        # 根据设备选择程序
        if self.device == "cpu":
            if shutil.which("faster-whisper-xxl"):
                self.faster_whisper_program = "faster-whisper-xxl"
            else:
                if not shutil.which("faster-whisper"):
                    raise EnvironmentError("faster-whisper程序未找到，请确保已经下载。")
                self.faster_whisper_program = "faster-whisper"
                self.vad_method = ""
        elif self.device == "cuda":
            if not shutil.which("faster-whisper-xxl"):
                raise EnvironmentError(
                    "faster-whisper-xxl 程序未找到，请确保已经下载。"
                )
            self.faster_whisper_program = "faster-whisper-xxl"

    def _build_command(self, audio_input: str) -> List[str]:
        """Build command line arguments for faster-whisper."""

        cmd = [
            str(self.faster_whisper_program),
            "-m",
            str(self.model_path),
            # "--verbose", "true",
            "--print_progress",
        ]

        # 添加模型目录参数
        if self.model_dir:
            cmd.extend(["--model_dir", str(self.model_dir)])

        cmd.extend(
            [
                str(audio_input),
                "-l",
                self.language,
                "-d",
                self.device,
                "--output_format",
                self.output_format,
            ]
        )

        # 输出目录
        if self.output_dir:
            cmd.extend(["-o", str(self.output_dir)])
        else:
            cmd.extend(["-o", "source"])

        # VAD 相关参数
        if self.vad_filter:
            cmd.extend(
                [
                    "--vad_filter",
                    "true",
                    "--vad_threshold",
                    f"{self.vad_threshold:.2f}",
                ]
            )
            if self.vad_method:
                cmd.extend(["--vad_method", self.vad_method])
        else:
            cmd.extend(["--vad_filter", "false"])

        # 人声分离
        if self.ff_mdx_kim2 and self.faster_whisper_program.startswith(
            "faster-whisper-xxl"
        ):
            cmd.append("--ff_mdx_kim2")

        # 文本处理参数
        if self.one_word:
            self.one_word = 1
        else:
            self.one_word = 0
        if self.one_word in [0, 1, 2]:
            cmd.extend(["--one_word", str(self.one_word)])

        if self.sentence:
            cmd.extend(
                [
                    "--sentence",
                    "--max_line_width",
                    str(self.max_line_width),
                    "--max_line_count",
                    str(self.max_line_count),
                    "--max_comma",
                    str(self.max_comma),
                    "--max_comma_cent",
                    str(self.max_comma_cent),
                ]
            )

        # 提示词
        if self.prompt:
            cmd.extend(["--initial_prompt", self.prompt])

        # 完成的提示音
        cmd.extend(["--beep_off"])

        # 检测 50 系显卡，添加 compute_type 参数
        if is_rtx_50_series():
            cmd.extend(["--compute_type", "float16"])

        return cmd

    def _make_segments(self, resp_data: str) -> List[ASRDataSeg]:
        asr_data = ASRData.from_srt(resp_data)

        # 幻觉文本关键词列表
        hallucination_keywords = [
            "请不吝点赞 订阅 转发",
            "打赏支持明镜",
        ]
        # 过滤掉音乐标记和幻觉文本
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()

            # 跳过音乐标记
            if text.startswith(("【", "[", "(", "（")):
                continue

            # 跳过包含幻觉关键词的文本
            if any(keyword in text for keyword in hallucination_keywords):
                continue

            filtered_segments.append(seg)

        return filtered_segments

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> str:
        def _default_callback(x, y):
            pass

        if callback is None:
            callback = _default_callback

        with tempfile.TemporaryDirectory() as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = wav_path.with_suffix(".srt")

            if isinstance(self.audio_input, str):
                shutil.copy2(self.audio_input, wav_path)
            else:
                if self.file_binary:
                    wav_path.write_bytes(self.file_binary)
                else:
                    raise ValueError("No audio data available")

            cmd = self._build_command(str(wav_path))

            logger.info("Faster Whisper command: %s", " ".join(cmd))
            callback(*ASRStatus.TRANSCRIBING.with_progress(5))

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            # 使用 StreamReader 处理输出
            reader = StreamReader(self.process)
            reader.start_reading()

            is_finish = False
            error_msg = ""
            last_progress = 0

            # 实时处理输出
            while True:
                # 检查进程状态
                if self.process.poll() is not None:
                    # 进程已结束，读取剩余输出
                    for stream_name, line in reader.get_remaining_output():
                        line = line.strip()
                        if line:
                            if "error" in line:
                                error_msg += line
                            else:
                                logger.info(line)
                    break

                # 读取输出
                output = reader.get_output(timeout=0.1)
                if output:
                    stream_name, line = output
                    line = line.strip()
                    if line:
                        # 解析进度百分比
                        if match := re.search(r"(\d+)%", line):
                            progress = int(match.group(1))
                            if progress == 100:
                                is_finish = True
                            mapped_progress = int(5 + (progress * 0.9))
                            # 只允许进度单调递增
                            if mapped_progress > last_progress:
                                last_progress = mapped_progress
                                callback(mapped_progress, f"{mapped_progress}%")
                        if "Subtitles are written to" in line:
                            is_finish = True
                            callback(*ASRStatus.COMPLETED.callback_tuple())
                        if "error" in line or "Error" in line:
                            error_msg += line
                            logger.error(line)
                        else:
                            logger.info(line)

            if not is_finish:
                logger.error("Faster Whisper 错误: %s", error_msg)
                raise RuntimeError(error_msg)

            # 判断是否识别成功
            if not output_path.exists():
                logger.info("Faster Whisper 返回值: %s", self.process.returncode)
                raise RuntimeError(f"Faster Whisper 输出文件不存在: {output_path}")

            logger.info("Faster Whisper ASR completed")

            callback(*ASRStatus.COMPLETED.callback_tuple())

            return output_path.read_text(encoding="utf-8")

    def _get_key(self):
        """获取缓存key"""
        cmd = self._build_command("")
        cmd_hash = hashlib.md5(str(cmd).encode()).hexdigest()
        return f"{self.crc32_hex}-{cmd_hash}"


def is_rtx_50_series() -> bool:
    """检测是否为 RTX 50 系显卡"""
    if GPUtil is None:
        logger.debug("GPUtil 未安装，无法检测 GPU 型号")
        return False
    try:
        gpus = GPUtil.getGPUs()
        for gpu in gpus:
            gpu_name = gpu.name.lower()
            # 检测是否包含 50 系列标识，如 RTX 5090, RTX 5080 等
            if re.search(r"rtx\s*50\d{2}", gpu_name):
                logger.info(f"检测到 RTX 50 系显卡: {gpu.name}")
                return True
    except Exception as e:
        logger.debug(f"无法检测 GPU 型号: {e}")
    return False
