import os
import re
import shutil
import subprocess
from pathlib import Path
import time
import tempfile

from .ASRData import ASRDataSeg, from_srt
from .BaseASR import BaseASR
from ..utils.logger import setup_logger
from ...config import MODEL_PATH

logger = setup_logger("whisper_asr")


class WhisperASR(BaseASR):
    def __init__(self, audio_path, language="en", whisper_cpp_path="whisper-cpp", whisper_model=None,
                 use_cache: bool = False, need_word_time_stamp: bool = False):
        super().__init__(audio_path, False)
        # 如果指定了 whisper_model，则在 models 目录下查找对应模型
        if whisper_model:
            models_dir = Path(MODEL_PATH)
            model_files = list(models_dir.glob(f"*ggml*{whisper_model}*.bin"))
            if not model_files:
                raise ValueError(f"在 {models_dir} 目录下未找到包含 '{whisper_model}' 的模型文件")
            model_path = str(model_files[0])
            logger.info(f"找到模型文件: {model_path}")
        else:
            raise ValueError("whisper_model 不能为空")

        self.model_path = model_path
        self.whisper_cpp_path = Path(whisper_cpp_path)
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language
        self.process = None

        # 注册退出处理
        import atexit
        atexit.register(self.stop)

    def _make_segments(self, resp_data: str) -> list[ASRDataSeg]:
        asr_data = from_srt(resp_data)
        # 过滤掉纯音乐标记
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()
            # 保留不以【、[、(、（开头的文本
            if not (text.startswith('【') or 
                   text.startswith('[') or 
                   text.startswith('(') or 
                   text.startswith('（')):
                filtered_segments.append(seg)
        return filtered_segments

    def _run(self, callback=None) -> str:
        if callback is None:
            callback = lambda x, y: None

        temp_dir = Path(tempfile.gettempdir()) / "bk_asr"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用 with 语句管理临时文件的生命周期
        with tempfile.TemporaryDirectory(dir=temp_dir) as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = temp_dir / "output.srt"

            try:
                # 转换音频为 WAV 格式（Whisper-CPP 主要支持 WAV 格式的音频输入）
                ffmpeg_cmd = f'ffmpeg -i "{self.audio_path}" -ar 16000 -ac 1 -c:a pcm_s16le "{wav_path}"'
                subprocess.run(ffmpeg_cmd, shell=True, check=True)
                logger.info(f"音频转换完成: {wav_path}")

                # 构建基础命令
                base_cmd = {
                    'whisper_path': str(self.whisper_cpp_path),
                    'model': str(self.model_path),
                    'input': str(wav_path),
                    'language': self.language,
                    'output': str(output_path.with_suffix("")),
                }

                cmd_str = (
                    f'"{base_cmd["whisper_path"]}" '
                    f'-m "{base_cmd["model"]}" '
                    f'-f "{base_cmd["input"]}" '
                    f'-l {base_cmd["language"]} '
                    f'--output-srt '
                    f'--output-file "{base_cmd["output"]}" '
                    f'--no-gpu'
                )

                if self.language == "zh":
                    cmd_str += ' --prompt "你好，我们需要使用简体中文，以下是普通话的句子。"'

                logger.info("完整命令行: %s", cmd_str)

                self.process = subprocess.Popen(
                    cmd_str,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    shell=True
                )

                # 获取音频时长
                total_duration = self.get_audio_duration(self.audio_path) or 600
                logger.info("音频总时长: %d 秒", total_duration)

                # 处理输出和进度
                full_output = []
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    full_output.append(line)
                    
                    # 简化的进度处理
                    if ' --> ' in line and '[' in line:
                        try:
                            time_str = line.split('[')[1].split(' -->')[0].strip()
                            current_time = sum(float(x) * y for x, y in 
                                zip(reversed(time_str.split(':')), [1, 60, 3600]))
                            progress = int(min(current_time / total_duration * 100, 98))
                            callback(progress, f"{progress}% 正在转换")
                        except (ValueError, IndexError):
                            continue

                # 等待进程完成
                stdout, stderr = self.process.communicate()
                if self.process.returncode != 0:
                    raise RuntimeError(f"WhisperCPP 执行失败: {stderr}")

                callback(100, "转换完成")
                
                # 读取结果文件
                srt_path = output_path.with_suffix('.srt')
                if not srt_path.exists():
                    raise RuntimeError(f"输出文件未生成: {srt_path}")
                    
                return srt_path.read_text(encoding='utf-8')

            except Exception as e:
                logger.exception("处理失败")
                raise RuntimeError(f"生成 SRT 文件失败: {str(e)}")

    def _get_key(self):
        return f"{self.__class__.__name__}-{self.crc32_hex}-{self.need_word_time_stamp}-{self.model_path}-{self.language}"

    def get_audio_duration(self, filepath: str) -> int:
        try:
            cmd = ["ffmpeg", "-i", filepath]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', shell=True)
            info = result.stderr
            # 提取时长
            if duration_match := re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', info):
                hours, minutes, seconds = map(float, duration_match.groups())
                duration_seconds = hours * 3600 + minutes * 60 + seconds
                return int(duration_seconds)
            return 600  # 如果无法获取时长，返回默认值
        except Exception as e:
            logger.exception("获取音频时长时出错: %s", str(e))
            return 600  # 发生异常时返回默认值

    def stop(self):
        """停止 ASR 语音识别处理
        - 终止进程及其子进程
        """
        if self.process:
            logger.info("终止 Whisper ASR 进程")
            if os.name == 'nt':  # Windows系统
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.process.pid)], 
                             capture_output=True)
            else:  # Linux/Mac系统
                import signal
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            self.process = None


if __name__ == '__main__':
    # 简短示例
    asr = WhisperASR(
        audio_path="audio.mp3",
        model_path="models/ggml-tiny.bin",
        whisper_cpp_path="bin/whisper-cpp.exe",
        language="en",
        need_word_time_stamp=True
    )
    asr_data = asr._run(callback=print)
