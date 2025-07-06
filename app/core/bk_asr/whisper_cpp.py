import os
import threading
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable, List

from app.config import MODEL_PATH
from app.common.config import cfg
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

        # 解析模型名称并查找模型文件
        self.whisper_model = self._resolve_model_name(whisper_model)
        self.model_path = self._find_model_file(self.whisper_model)

        self.whisper_cpp_path = Path(whisper_cpp_path)
        self.need_word_time_stamp = need_word_time_stamp
        self.language = language
        self.process = None

    def _resolve_model_name(self, whisper_model: Optional[str]) -> str:
        """解析模型名称"""
        if whisper_model is not None:
            return whisper_model

        # 使用配置中的模型
        try:
            model_value = cfg.whisper_model.value
            
            if hasattr(model_value, 'value'):
                # 如果是枚举类型，获取其值
                return model_value.value
            else:
                # 如果是字符串类型，直接使用
                return model_value
        except Exception as e:
            raise ValueError(f"无法获取用户选择的模型配置: {e}")

    def _find_model_file(self, model_name: str) -> str:
        """查找模型文件，支持多种命名格式"""
        models_dir = Path(MODEL_PATH)
        if not models_dir.exists():
            raise ValueError(f"模型目录不存在: {models_dir}")

        # 支持多种可能的文件名格式
        possible_patterns = [
            f"ggml-{model_name}.bin",      # 标准格式
            f"ggml-{model_name}-*.bin",    # 带版本号
            f"{model_name}.bin",           # 简化格式
            f"{model_name}-*.bin",         # 带版本号的简化格式
            f"*{model_name}*.bin",         # 包含模型名的任意格式
        ]

        for pattern in possible_patterns:
            model_files = list(models_dir.glob(pattern))
            if model_files:
                # 如果找到多个文件，选择第一个并记录
                selected_file = str(model_files[0])
                if len(model_files) > 1:
                    logger.warning(f"找到多个匹配的模型文件: {[str(f) for f in model_files]}")
                    logger.warning(f"选择第一个: {selected_file}")
                else:
                    logger.info(f"找到模型文件: {selected_file}")
                return selected_file

        # 如果没有找到指定模型，给出清晰的错误信息和解决方案
        available_models = list(models_dir.glob("*.bin"))
        available_model_names = [f.stem for f in available_models]
        
        error_message = f"模型 '{model_name}' 未下载。\n\n"
        
        if available_model_names:
            error_message += f"已下载的模型: {available_model_names}\n\n"
        else:
            error_message += "没有任何已下载的模型。\n\n"
        
        error_message += f"解决方案:\n"
        error_message += f"1. 在设置界面中点击 '模型管理' 下载 {model_name} 模型\n"
        error_message += f"2. 或者选择其他已下载的模型\n"
        error_message += f"3. 模型文件应保存在: {models_dir}"

        raise ValueError(error_message)

    def update_model(self, new_model_name: str) -> None:
        """更新模型，允许运行时动态切换模型"""
        try:
            old_model = self.whisper_model
            self.whisper_model = new_model_name
            self.model_path = self._find_model_file(new_model_name)
            logger.info(f"模型已更新: {old_model} -> {new_model_name}")
        except Exception as e:
            logger.error(f"更新模型失败: {e}")
            raise

    def get_available_models(self) -> List[str]:
        """获取所有可用的模型名称"""
        return self._get_available_models()
    
    def _get_available_models(self) -> List[str]:
        """内部方法：获取所有可用的模型名称"""
        models_dir = Path(MODEL_PATH)
        if not models_dir.exists():
            return []

        model_files = list(models_dir.glob("*.bin"))
        # 提取模型名称，去掉 ggml- 前缀和 .bin 后缀
        model_names = []
        for file in model_files:
            name = file.stem
            if name.startswith("ggml-"):
                name = name[5:]  # 去掉 "ggml-" 前缀
            model_names.append(name)

        return sorted(set(model_names))  # 去重并排序

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
                logger.info("使用模型: %s (路径: %s)", self.whisper_model, self.model_path)

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

    # 获取可用模型
    available_models = asr.get_available_models()
    print(f"可用模型: {available_models}")

    # 动态切换模型
    try:
        asr.update_model("base")
        print("模型切换成功")
    except Exception as e:
        print(f"模型切换失败: {e}")

    result = asr._run(callback=test_callback)
    print("识别结果：")
    print(result)
