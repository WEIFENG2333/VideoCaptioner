"""Convert merged CLI/shared TOML configuration dictionaries into AppConfig."""

from __future__ import annotations

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.application.app_config import (
    AppConfig,
    DubbingSettings,
    LLMSettings,
    SubtitleSettings,
    SynthesisSettings,
    TranscribeSettings,
    enum_by_value,
    layout_from_cli,
    quality_from_cli,
    render_mode_from_cli,
    target_language_from_code,
    transcribe_model_from_cli,
    transcribe_output_format_from_cli,
    translator_from_cli,
)
from videocaptioner.core.application.config_store import get
from videocaptioner.core.entities import FasterWhisperModelEnum, VadMethodEnum, WhisperModelEnum
from videocaptioner.core.llm import free_model
from videocaptioner.core.subtitle.style_manager import normalize_style_id


def app_config_from_cli(config: dict) -> AppConfig:
    asr = str(get(config, "transcribe.asr", "bijian"))
    language = str(get(config, "transcribe.language", "auto"))
    vad_method = str(get(config, "transcribe.faster_whisper.vad_method", "silero_v4"))

    subtitle_mode = str(get(config, "synthesize.subtitle_mode", "hard"))
    llm_service = str(get(config, "llm.service", "openai"))
    llm_provider = get(config, f"llm.providers.{llm_service}", {}) or {}
    if llm_service == "immersive":
        # 公益大模型：无需用户配置，base/model 固定，真实令牌在 LLM client 内实时取
        llm_key, llm_base, llm_model = (
            free_model.PLACEHOLDER_KEY, free_model.BASE_URL, free_model.MODEL,
        )
    else:
        llm_key = str(llm_provider.get("api_key") or get(config, "llm.api_key", "") or "")
        llm_base = str(
            llm_provider.get("api_base")
            or get(config, "llm.api_base", "https://api.openai.com/v1")
            or ""
        )
        llm_model = str(llm_provider.get("model") or get(config, "llm.model", "gpt-4o-mini") or "")
    return AppConfig(
        work_dir=str(get(config, "app.work_dir", "") or ""),
        cache_enabled=bool(
            get(config, "app.cache_enabled", get(config, "dubbing.use_cache", True))
        ),
        llm=LLMSettings(
            service=_llm_service_from_key(llm_service),
            api_key=llm_key,
            api_base=llm_base,
            model=llm_model,
        ),
        transcribe=TranscribeSettings(
            model=transcribe_model_from_cli(asr),
            language="" if language == "auto" else language,
            language_label="Auto" if language == "auto" else language,
            output_format=transcribe_output_format_from_cli(
                get(config, "transcribe.output_format", get(config, "output.format", "srt"))
            ),
            whisper_model=enum_by_value(
                WhisperModelEnum,
                get(config, "transcribe.whisper_cpp.model", "tiny"),
                WhisperModelEnum.TINY,
            ),
            whisper_api_key=str(get(config, "whisper_api.api_key", "") or ""),
            whisper_api_base=str(get(config, "whisper_api.api_base", "") or ""),
            whisper_api_model=str(get(config, "whisper_api.model", "whisper-1") or ""),
            whisper_api_prompt=str(get(config, "whisper_api.prompt", "") or ""),
            fun_asr_api_key=str(get(config, "fun_asr.api_key", "") or ""),
            fun_asr_api_base=str(
                get(config, "fun_asr.api_base", "https://dashscope.aliyuncs.com") or ""
            ),
            fun_asr_model=str(get(config, "fun_asr.model", "fun-asr") or ""),
            faster_whisper_model=enum_by_value(
                FasterWhisperModelEnum,
                get(config, "transcribe.faster_whisper.model", "tiny"),
                FasterWhisperModelEnum.TINY,
            ),
            faster_whisper_program=str(
                get(config, "transcribe.faster_whisper.program", "faster-whisper-xxl.exe")
                or "faster-whisper-xxl.exe"
            ),
            faster_whisper_model_dir=str(
                get(config, "transcribe.faster_whisper.model_dir", "") or MODEL_PATH
            ),
            faster_whisper_device=str(
                get(config, "transcribe.faster_whisper.device", "auto") or "auto"
            ),
            faster_whisper_vad_filter=bool(
                get(config, "transcribe.faster_whisper.vad_filter", True)
            ),
            faster_whisper_vad_threshold=float(
                get(config, "transcribe.faster_whisper.vad_threshold", 0.4)
            ),
            faster_whisper_vad_method=enum_by_value(
                VadMethodEnum, vad_method, VadMethodEnum.SILERO_V4
            ),
            faster_whisper_ff_mdx_kim2=bool(
                get(config, "transcribe.faster_whisper.voice_extraction", False)
            ),
            faster_whisper_one_word=bool(
                get(config, "transcribe.faster_whisper.one_word", True)
            ),
            faster_whisper_prompt=str(get(config, "transcribe.faster_whisper.prompt", "") or ""),
        ),
        subtitle=SubtitleSettings(
            translator_service=translator_from_cli(get(config, "translate.service", "bing")),
            need_reflect=bool(get(config, "translate.reflect", False)),
            deeplx_endpoint=str(get(config, "translate.deeplx_endpoint", "") or ""),
            thread_num=int(get(config, "subtitle.thread_num", 10)),
            batch_size=int(get(config, "subtitle.batch_size", 10)),
            need_optimize=bool(get(config, "subtitle.optimize", False)),
            need_translate=bool(get(config, "subtitle.translate", False)),
            need_split=bool(get(config, "subtitle.split", False)),
            target_language=target_language_from_code(
                get(config, "translate.target_language", "zh-Hans")
            ),
            max_word_count_cjk=int(get(config, "subtitle.max_word_count_cjk", 28)),
            max_word_count_english=int(get(config, "subtitle.max_word_count_english", 20)),
            custom_prompt_text=str(
                get(config, "subtitle.custom_prompt", get(config, "subtitle.prompt", "")) or ""
            ),
            layout=layout_from_cli(get(config, "synthesize.layout", "target-above")),
            style_name=str(get(config, "synthesize.style", "default") or "default"),
        ),
        synthesis=SynthesisSettings(
            need_video=bool(get(config, "synthesize.need_video", True)),
            soft_subtitle=bool(get(config, "synthesize.soft_subtitle", subtitle_mode != "hard")),
            video_quality=quality_from_cli(get(config, "synthesize.quality", "medium")),
            render_mode=render_mode_from_cli(get(config, "synthesize.render_mode", "rounded")),
            style_id=normalize_style_id(
                get(config, "synthesize.style", "default"),
                get(config, "synthesize.render_mode", "rounded"),
            ),
        ),
        dubbing=DubbingSettings(
            enabled=bool(get(config, "dubbing.enabled", False)),
            provider=str(get(config, "dubbing.provider", "edge") or "edge"),
            preset=str(get(config, "dubbing.preset", "edge-cn-female") or ""),
            voice=str(get(config, "dubbing.voice", "zh-CN-XiaoxiaoNeural") or ""),
            text_track=str(get(config, "dubbing.text_track", "auto") or "auto"),
            timing=str(get(config, "dubbing.timing", "balanced") or "balanced"),
            audio_mode=str(get(config, "dubbing.audio_mode", "replace") or "replace"),
            api_key=str(get(config, "dubbing.api_key", "") or ""),
            api_base=str(get(config, "dubbing.api_base", "") or ""),
            model=str(get(config, "dubbing.model", "") or ""),
            tts_workers=int(get(config, "dubbing.tts_workers", 5)),
            clone_audio_path=str(get(config, "dubbing.clone_audio", "") or ""),
            clone_audio_text=str(get(config, "dubbing.clone_text", "") or ""),
        ),
    )


def _llm_service_from_key(value: str):
    from videocaptioner.core.entities import LLMServiceEnum

    return {
        "openai": LLMServiceEnum.OPENAI,
        "official": LLMServiceEnum.OFFICIAL,
        "silicon_cloud": LLMServiceEnum.SILICON_CLOUD,
        "siliconcloud": LLMServiceEnum.SILICON_CLOUD,
        "deepseek": LLMServiceEnum.DEEPSEEK,
        "ollama": LLMServiceEnum.OLLAMA,
        "lm_studio": LLMServiceEnum.LM_STUDIO,
        "lmstudio": LLMServiceEnum.LM_STUDIO,
        "gemini": LLMServiceEnum.GEMINI,
        "chatglm": LLMServiceEnum.CHATGLM,
    }.get(str(value or "openai").lower(), LLMServiceEnum.OPENAI)
