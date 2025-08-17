import os
import re
import shutil
import time
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Callable, Any

from ...config import MODEL_PATH
from ..utils.logger import setup_logger
from ..utils.subprocess_helper import StreamReader
from .asr_data import ASRData, ASRDataSeg
from .base import BaseASR

logger = setup_logger("whisper_asr")


class WhisperCppASR(BaseASR):
    def __init__(
        self,
        audio_path,
        language="en",
        whisper_cpp_path="whisper-cpp",
        whisper_model=None,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
    ):
        super().__init__(audio_path, False)
        assert os.path.exists(audio_path), f"音频文件 {audio_path} 不存在"
        assert audio_path.endswith(".wav"), f"音频文件 {audio_path} 必须是WAV格式"

        # 如果指定了 whisper_model，则在 models 目录下查找对应模型
        if whisper_model:
            models_dir = Path(MODEL_PATH)
            model_files = list(models_dir.glob(f"*ggml*{whisper_model}*.bin"))
            if not model_files:
                raise ValueError(
                    f"在 {models_dir} 目录下未找到包含 '{whisper_model}' 的模型文件"
                )
            model_path = str(model_files[0])
            logger.info(f"找到模型文件: {model_path}")
        else:
            raise ValueError("whisper_model 不能为空")

        self.model_path = model_path
        self.whisper_cpp_path = Path(whisper_cpp_path)
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language

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
        """构建 whisper-cpp 命令行参数

        Args:
            wav_path: 输入的WAV文件路径
            output_path: 输出文件路径
            is_const_me_version: 是否为 const_me 版本

        Returns:
            list[str]: 命令行参数列表
        """
        # 构建基础命令参数列表
        whisper_params = [
            str(self.whisper_cpp_path),
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "-l",
            self.language,
            "--output-srt",
        ]

        # 根据版本添加额外参数
        if not is_const_me_version:
            whisper_params.extend(
                ["--no-gpu", "--output-file", str(output_path.with_suffix(""))]
            )

        # 中文模式下添加提示语
        if self.language == "zh":
            whisper_params.extend(
                ["--prompt", "你好，我们需要使用简体中文，以下是普通话的句子。"]
            )

        return whisper_params

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> str:
        def _default_callback(x, y):
            pass

        if callback is None:
            callback = _default_callback

        is_const_me_version = True if os.name == "nt" else False

        with tempfile.TemporaryDirectory() as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = wav_path.with_suffix(".srt")

            try:
                # 复制音频文件
                if isinstance(self.audio_path, str):
                    shutil.copy2(self.audio_path, wav_path)
                else:
                    if self.file_binary:
                        wav_path.write_bytes(self.file_binary)
                    else:
                        raise ValueError("No audio data available")

                # 构建命令
                whisper_params = self._build_command(
                    wav_path, output_path, is_const_me_version
                )
                logger.info("完整命令行参数: %s", " ".join(whisper_params))

                # 获取音频时长
                if isinstance(self.audio_path, str):
                    total_duration = self.get_audio_duration(self.audio_path)
                else:
                    total_duration = 600
                logger.info("音频总时长: %d 秒", total_duration)

                # 启动进程
                self.process = subprocess.Popen(
                    whisper_params,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,  # 行缓冲
                )

                logger.info(f"whisper-cpp 进程已启动，PID: {self.process.pid}")

                # 使用 StreamReader 处理输出流
                reader = StreamReader(self.process)
                reader.start_reading()

                # 处理输出
                last_progress = 0

                while True:
                    # 检查进程状态
                    if self.process.poll() is not None:
                        # 进程已结束，读取剩余输出
                        time.sleep(0.2)
                        for stream_name, line in reader.get_remaining_output():
                            if stream_name == "stderr":
                                logger.debug(f"[stderr] {line.strip()}")
                        break

                    # 非阻塞读取输出
                    output = reader.get_output(timeout=0.1)
                    if output:
                        stream_name, line = output

                        if stream_name == "stdout":
                            logger.debug(f"[stdout] {line.strip()}")

                            # 解析进度
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
                                    logger.debug(f"解析进度失败: {e}")
                        else:
                            logger.debug(f"[stderr] {line.strip()}")

                # 检查返回码
                if self.process.returncode != 0:
                    raise RuntimeError(
                        f"WhisperCPP 执行失败，返回码: {self.process.returncode}"
                    )

                callback(100, "转换完成")
                logger.info("whisper-cpp 处理完成")

                # 读取结果文件
                srt_path = output_path
                if not srt_path.exists():
                    time.sleep(5)
                    if not srt_path.exists():
                        raise RuntimeError(f"输出文件未生成: {srt_path}")

                return srt_path.read_text(encoding="utf-8")

            except Exception as e:
                logger.exception("处理失败")
                # 确保进程被终止
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                raise RuntimeError(f"生成 SRT 文件失败: {str(e)}")

    def _get_key(self):
        return f"{self.crc32_hex}-{self.need_word_time_stamp}-{self.model_path}-{self.language}"

    def get_audio_duration(self, filepath: str) -> int:
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
            # 提取时长
            if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
                hours, minutes, seconds = map(float, duration_match.groups())
                duration_seconds = hours * 3600 + minutes * 60 + seconds
                return int(duration_seconds)
            return 600
        except Exception as e:
            logger.exception("获取音频时长时出错: %s", str(e))
            return 600


if __name__ == "__main__":
    # 简短示例
    asr = WhisperCppASR(
        audio_path="audio.mp3",
        whisper_model="tiny",
        whisper_cpp_path="bin/whisper-cpp.exe",
        language="en",
        need_word_time_stamp=True,
    )
    asr_data = asr._run(callback=print)
