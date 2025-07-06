import os
import threading
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable, List

from ...config import MODEL_PATH
from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg, ASRData
from .base import BaseASR

logger = setup_logger("whisper_asr")


class WhisperCppASR(BaseASR):
    DEFAULT_DURATION = 600

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
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()
            if not re.match(r'[【\[(（]', text):
                filtered_segments.append(seg)
        return filtered_segments

    def _build_command(
        self, wav_path, output_path, is_const_me_version: bool
    ) -> List[str]:
        """构建 whisper-cpp 命令行参数"""
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

        if not is_const_me_version:
            whisper_params.extend(["--output-file", str(output_path.with_suffix(""))])

        if self.language == "zh":
            whisper_params.extend([
                "--prompt",
                "我需要简体中文的结果，下面是简体中文的句子，请忠实地转录内容"
            ])

        return whisper_params

    def _run(self, callback: Optional[Callable[[int, str], None]] = None) -> str:
        if callback is None:
            callback = lambda x, y: None

        temp_dir = Path(tempfile.gettempdir()) / "bk_asr"
        temp_dir.mkdir(parents=True, exist_ok=True)

        is_const_me_version = (os.name == "nt")

        with tempfile.TemporaryDirectory(dir=temp_dir) as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = wav_path.with_suffix(".srt")

            try:
                shutil.copy2(self.audio_path, wav_path)

                whisper_params = self._build_command(wav_path, output_path, is_const_me_version)
                logger.info("完整命令行参数: %s", " ".join(whisper_params))

                total_duration = self.get_audio_duration(self.audio_path) or self.DEFAULT_DURATION
                logger.info("音频总时长: %d 秒", total_duration)

                # 启动子进程
                self.process = subprocess.Popen(
                    whisper_params,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )

                # 单独开线程读取 stderr，防止缓冲区满导致卡死
                def read_stderr():
                    for line in iter(self.process.stderr.readline, ''):
                        logger.debug("STDERR: %s", line.strip())

                threading.Thread(target=read_stderr, daemon=True).start()

                # 实时更新进度条（每秒一次）
                start_time = time.time()
                while self.process.poll() is None:
                    elapsed = time.time() - start_time
                    progress = int(min(elapsed / total_duration * 95, 95))
                    callback(progress, f"{progress}% 正在识别...")
                    time.sleep(1)

                # 等待完成
                stdout, stderr = self.process.communicate(timeout=60)

                if self.process.returncode != 0:
                    raise RuntimeError(f"WhisperCPP 执行失败: {stderr}")

                callback(100, "转换完成")

                # 读取结果文件
                srt_path = output_path
                if not srt_path.exists():
                    raise RuntimeError(f"输出文件未生成: {srt_path}")

                return srt_path.read_text(encoding="utf-8")

            except Exception as e:
                logger.exception("处理失败")
                raise RuntimeError(f"生成 SRT 文件失败: {str(e)}")

    def _get_key(self):
        return f"{self.crc32_hex}-{self.need_word_time_stamp}-{self.model_path}-{self.language}"

    def get_audio_duration(self, filepath: str) -> Optional[int]:
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
                return int(hours * 3600 + minutes * 60 + seconds)
            return self.DEFAULT_DURATION
        except Exception as e:
            logger.warning("获取音频时长失败: %s", str(e))
            return self.DEFAULT_DURATION


if __name__ == "__main__":
    # 示例调用
    def test_callback(progress, message):
        print(f"[回调] 进度: {progress}% - {message}")

    asr = WhisperCppASR(
        audio_path="audio.wav",
        whisper_cpp_path="/opt/homebrew/bin/whisper-cpp",
        whisper_model="large-v2",
        language="zh",
        need_word_time_stamp=False,
    )
    result = asr._run(callback=test_callback)
    print("识别结果：")
    print(result)