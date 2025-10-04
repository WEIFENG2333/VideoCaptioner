from typing import Any, Dict, Optional

from app.core.asr.asr_data import ASRData
from app.core.asr.base import BaseASR
from app.core.asr.bcut import BcutASR
from app.core.asr.faster_whisper import FasterWhisperASR
from app.core.asr.jianying import JianYingASR
from app.core.asr.whisper_api import WhisperAPI
from app.core.asr.whisper_cpp import WhisperCppASR
from app.core.entities import TranscribeConfig, TranscribeModelEnum


def transcribe(audio_path: str, config: TranscribeConfig, callback=None) -> ASRData:
    """Transcribe audio file using specified configuration.

    Args:
        audio_path: Path to audio file
        config: Transcription configuration
        callback: Progress callback function(progress: int, message: str)

    Returns:
        ASRData: Transcription result data
    """

    def _default_callback(x, y):
        pass

    if callback is None:
        callback = _default_callback

    # Get ASR model class
    ASR_MODELS = {
        TranscribeModelEnum.JIANYING: JianYingASR,
        TranscribeModelEnum.BIJIAN: BcutASR,
        TranscribeModelEnum.WHISPER_CPP: WhisperCppASR,
        TranscribeModelEnum.WHISPER_API: WhisperAPI,
        TranscribeModelEnum.FASTER_WHISPER: FasterWhisperASR,
    }

    if config.transcribe_model is None:
        raise ValueError("Transcription model not set")
    asr_class = ASR_MODELS.get(config.transcribe_model)
    if not asr_class:
        raise ValueError(f"Invalid transcription model: {config.transcribe_model}")

    # Build ASR arguments
    asr_args: Dict[str, Any] = {
        "use_cache": config.use_asr_cache,
        "need_word_time_stamp": config.need_word_time_stamp,
    }

    # Add model-specific parameters
    if config.transcribe_model == TranscribeModelEnum.WHISPER_CPP:
        asr_args["language"] = config.transcribe_language
        asr_args["whisper_model"] = (
            config.whisper_model.value if config.whisper_model else None
        )
    elif config.transcribe_model == TranscribeModelEnum.WHISPER_API:
        asr_args["language"] = config.transcribe_language
        asr_args["whisper_model"] = config.whisper_api_model
        asr_args["api_key"] = config.whisper_api_key
        asr_args["base_url"] = config.whisper_api_base
        asr_args["prompt"] = config.whisper_api_prompt
    elif config.transcribe_model == TranscribeModelEnum.FASTER_WHISPER:
        asr_args["faster_whisper_program"] = config.faster_whisper_program
        asr_args["language"] = config.transcribe_language
        asr_args["whisper_model"] = (
            config.faster_whisper_model.value if config.faster_whisper_model else None
        )
        asr_args["model_dir"] = config.faster_whisper_model_dir
        asr_args["device"] = config.faster_whisper_device
        asr_args["vad_filter"] = config.faster_whisper_vad_filter
        asr_args["vad_threshold"] = config.faster_whisper_vad_threshold
        asr_args["vad_method"] = (
            config.faster_whisper_vad_method.value
            if config.faster_whisper_vad_method
            else None
        )
        asr_args["ff_mdx_kim2"] = config.faster_whisper_ff_mdx_kim2
        asr_args["one_word"] = config.faster_whisper_one_word
        asr_args["prompt"] = config.faster_whisper_prompt

    # Create ASR instance and run
    asr = asr_class(audio_path, **asr_args)

    asr_data = asr.run(callback=callback)

    # Optimize subtitle timing if not using word timestamps
    if not config.need_word_time_stamp:
        asr_data.optimize_timing()

    return asr_data


if __name__ == "__main__":
    # 示例用法
    from app.core.entities import WhisperModelEnum

    # 创建配置
    config = TranscribeConfig(
        transcribe_model=TranscribeModelEnum.WHISPER_CPP,
        transcribe_language="zh",
        whisper_model=WhisperModelEnum.MEDIUM,
        use_asr_cache=True,
    )

    # 转录音频
    audio_file = "test.wav"

    def progress_callback(progress: int, message: str):
        print(f"Progress: {progress}%, Message: {message}")

    result = transcribe(audio_file, config, callback=progress_callback)
    print(result)
