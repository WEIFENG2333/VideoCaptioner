from typing import Optional

from app.core.bk_asr.bcut import BcutASR
from app.core.bk_asr.jianying import JianYingASR
from app.core.bk_asr.kuaishou import KuaiShouASR
from app.core.bk_asr.whisper_api import WhisperAPI
from app.core.bk_asr.whisper_cpp import WhisperCppASR
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import TranscribeConfig, TranscribeModelEnum


def transcribe(audio_path: str, config: TranscribeConfig, callback=None) -> ASRData:
    """
    使用指定的转录配置对音频文件进行转录

    Args:
        audio_path: 音频文件路径
        config: 转录配置
        callback: 进度回调函数,接收两个参数(progress: int, message: str)

    Returns:
        ASRData: 转录结果数据
    """
    if callback is None:
        callback = lambda x, y: None

    # 获取ASR模型类
    ASR_MODELS = {
        TranscribeModelEnum.JIANYING: JianYingASR,
        # TranscribeModelEnum.KUAISHOU: KuaiShouASR,
        TranscribeModelEnum.BIJIAN: BcutASR,
        TranscribeModelEnum.WHISPER_CPP: WhisperCppASR,
        TranscribeModelEnum.WHISPER_API: WhisperAPI,
    }

    asr_class = ASR_MODELS.get(config.transcribe_model)
    if not asr_class:
        raise ValueError(f"无效的转录模型: {config.transcribe_model}")

    # 构建ASR参数
    asr_args = {
        "use_cache": config.use_asr_cache,
        "need_word_time_stamp": config.need_word_time_stamp,
    }

    # 根据不同模型添加特定参数
    if config.transcribe_model == TranscribeModelEnum.WHISPER_CPP:
        asr_args.update(
            {
                "language": config.transcribe_language,
                "whisper_model": config.whisper_model,
            }
        )
    elif config.transcribe_model == TranscribeModelEnum.WHISPER_API:
        asr_args.update(
            {
                "language": config.transcribe_language,
                "whisper_model": config.whisper_api_model,
                "api_key": config.whisper_api_key,
                "base_url": config.whisper_api_base,
                "prompt": config.whisper_api_prompt,
            }
        )

    # 创建ASR实例并运行
    asr = asr_class(audio_path, **asr_args)

    asr_data = asr.run(callback=callback)

    # 优化字幕显示时间 #161
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
