from typing import Optional, Callable, Any, List

from openai import OpenAI

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("whisper_api")


class WhisperAPI(BaseASR):
    def __init__(
        self,
        audio_path: str,
        whisper_model: str,
        need_word_time_stamp: bool = False,
        language: str = "zh",
        prompt: str = "",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        use_cache: bool = False,
    ):
        """
        初始化 Whisper API

        Args:
            audio_path: 音频文件路径
            model: 模型名称
            language: 语言代码,默认中文
            prompt: 提示词
            base_url: API基础URL,可选
            api_key: API密钥,可选
            use_cache: 是否使用缓存
        """
        super().__init__(audio_path, use_cache)

        # 优先使用传入的参数,否则使用环境变量
        self.base_url = base_url
        self.api_key = api_key

        if not self.base_url or not self.api_key:
            raise ValueError("必须设置 OPENAI_BASE_URL 和 OPENAI_API_KEY")

        self.model = whisper_model
        self.language = language
        self.prompt = prompt
        self.need_word_time_stamp = need_word_time_stamp

        logger.info(
            f"初始化 WhisperCppASR: model={whisper_model}, language={language}, prompt={prompt}"
        )
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        """执行语音识别"""
        return self._submit()

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        """从响应数据构建语音片段"""
        segments = []
        for seg in resp_data["segments"]:
            segments.append(
                ASRDataSeg(
                    text=seg["text"].strip(),
                    start_time=int(float(seg["start"]) * 1000),
                    end_time=int(float(seg["end"]) * 1000),
                )
            )
        return segments

    def _get_key(self) -> str:
        """获取缓存键值"""
        return f"{self.crc32_hex}-{self.model}-{self.language}-{self.prompt}"

    def _submit(self) -> dict:
        """提交音频进行识别"""
        try:
            if self.language == "zh" and not self.prompt:
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子。"
            args = {}
            if (
                self.need_word_time_stamp
                and self.base_url
                and "groq" not in self.base_url
            ):
                args["timestamp_granularities"] = ["word", "segment"]
            logger.info("开始识别音频...")
            # Remove language parameter to avoid type issues - OpenAI will auto-detect
            create_args = {
                "model": self.model,
                "temperature": 0,
                "response_format": "verbose_json",
                "file": ("audio.mp3", self.file_binary or b"", "audio/mp3"),
                "prompt": self.prompt,
                **args,
            }
            # Only add language if it's a valid string
            if self.language and isinstance(self.language, str):
                create_args["language"] = self.language

            completion = self.client.audio.transcriptions.create(**create_args)
            logger.info("音频识别完成")
            return completion.to_dict()
        except Exception as e:
            logger.exception(f"音频识别失败: {str(e)}")
            raise e
