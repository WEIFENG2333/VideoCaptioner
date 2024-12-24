import os
import re
import shutil
import subprocess
from pathlib import Path
import tempfile
from typing import Optional, List, Union

from .ASRData import ASRDataSeg, from_srt
from .BaseASR import BaseASR
from ..utils.logger import setup_logger
from ...config import MODEL_PATH, BIN_PATH


logger = setup_logger("faster_whisper")


class FasterWhisperASR(BaseASR):
    def __init__(self, 
                 audio_path: str,
                 faster_whisper_path: str,
                 whisper_model: str,
                 model_dir: str,
                 language: str = "zh",
                 device: str = "cpu",
                 output_dir: str = None,
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
                 translate_to_english: bool = False,
                 sentence: bool = False,
                 max_line_width: int = 100,
                 max_line_count: int = 1,
                 max_comma: int = 20,
                 max_comma_cent: int = 50,
                 prompt: str = None,
                 ):
        super().__init__(audio_path, False)
        
        # 基本参数
        self.model_path = whisper_model
        self.model_dir = model_dir
        self.faster_whisper_path = Path(faster_whisper_path)
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
        self.translate_to_english = translate_to_english
        self.prompt = prompt

        self.process = None

    def _build_command(self, audio_path: Path) -> List[str]:
        """构建命令行参数"""
        cmd = [
            str(self.faster_whisper_path),
            "-m", str(self.model_path),
            # "--verbose", "true",
            "--print_progress"
        ]
        
        # 添加模型目录参数
        if self.model_dir:
            cmd.extend(["--model_dir", str(self.model_dir)])
        
        # 基本参数
        cmd.extend([
            str(audio_path),
            "-l", self.language,
            "-d", self.device,
            "--output_format", self.output_format,
        ])
        
        # 输出目录
        if self.output_dir:
            cmd.extend(["-o", str(self.output_dir)])
        else:
            cmd.extend(["-o", "source"])

        # VAD 相关参数
        if self.vad_filter:
            cmd.extend([
                "--vad_filter", "true",
                "--vad_threshold", f"{self.vad_threshold:.2f}",
            ])
            if self.vad_method:
                cmd.extend(["--vad_method", self.vad_method])

        # 人声分离
        if self.ff_mdx_kim2 and self.faster_whisper_path.name.startswith("faster-whisper-xxl"):
            cmd.append("--ff_mdx_kim2")

        # 文本处理参数
        if self.one_word:
            self.one_word = 1
        else:
            self.one_word = 0
        if self.one_word in [0, 1, 2]:
            cmd.extend(["--one_word", str(self.one_word)])
        
        # 翻译成英语
        if self.translate_to_english:
            cmd.extend(["--task", "translate"])
        
        if self.sentence:
            cmd.extend([
                "--sentence",
                "--max_line_width", str(self.max_line_width),
                "--max_line_count", str(self.max_line_count),
                "--max_comma", str(self.max_comma),
                "--max_comma_cent", str(self.max_comma_cent)
            ])
        
        # 提示词
        if self.prompt:
            cmd.extend(["--prompt", self.prompt])

        return cmd

    def _make_segments(self, resp_data: str) -> list[ASRDataSeg]:
        asr_data = from_srt(resp_data)
        # 过滤掉纯音乐标记
        filtered_segments = []
        for seg in asr_data.segments:
            text = seg.text.strip()
            if not text.startswith(('【','[','(','（')):
                filtered_segments.append(seg)
        return filtered_segments

    def _run(self, callback=None) -> str:
        if callback is None:
            callback = lambda x, y: None

        temp_dir = Path(tempfile.gettempdir()) / "bk_asr"
        temp_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=temp_dir) as temp_path:
            temp_dir = Path(temp_path)
            wav_path = temp_dir / "audio.wav"
            output_path = wav_path.with_suffix(".srt")

            shutil.copy2(self.audio_path, wav_path)

            cmd = self._build_command(wav_path)

            logger.info("Faster Whisper 执行命令: %s", " ".join(cmd))
            callback(5, "Whisper识别")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            is_finish = False
            error_msg = ""

            # 实时打印日志和错误输出
            while self.process.poll() is None:
                output = self.process.stdout.readline()
                output = output.strip()
                if output:
                    # 解析进度百分比
                    if output.startswith("Operation finished"):
                        # Sometimes it's not showing 100% in output
                        is_finish = True
                    if match := re.search(r'(\d+)%', output):
                        progress = int(match.group(1))
                        if progress == 100:
                            is_finish = True
                        mapped_progress = int(5 + (progress * 0.9))
                        callback(mapped_progress, f"{mapped_progress} %")
                    if "error" in output:
                        error_msg += output
                        logger.error(output)
                    else:
                        logger.info(output)

            # 获取所有输出和错误信息
            self.process.communicate()

            logger.info("Faster Whisper 返回值: %s", self.process.returncode)
            if not is_finish:
                logger.error("Faster Whisper 错误: %s", error_msg)
                raise RuntimeError(error_msg)
            
            # 判断是否识别成功
            if not output_path.exists():
                raise RuntimeError(f"Faster Whisper 输出文件不存在: {output_path}")

            logger.info("Faster Whisper 识别完成")
    
            callback(100, "识别完成")

            return output_path.read_text(encoding='utf-8')

    def _get_key(self):
        return f"{self.__class__.__name__}-{self.crc32_hex}-{self.need_word_time_stamp}-{self.model_path}-{self.language}"
