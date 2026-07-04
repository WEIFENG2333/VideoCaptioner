"""Convert desktop UI settings state into AppConfig.

Execution code consumes AppConfig, not UI widgets or UI setting fields.
"""

from __future__ import annotations

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.application.app_config import (
    AppConfig,
    DubbingSettings,
    LLMSettings,
    SubtitleSettings,
    SynthesisSettings,
    TranscribeSettings,
)
from videocaptioner.core.entities import LANGUAGES, LLMServiceEnum
from videocaptioner.core.llm import free_model


def app_config_from_ui(cfg) -> AppConfig:
    llm = _llm_from_ui(cfg)
    language_label = cfg.transcribe_language.value.value
    faster_model_dir = str(cfg.faster_whisper_model_dir.value or MODEL_PATH)
    return AppConfig(
        work_dir=str(cfg.work_dir.value),
        cache_enabled=bool(cfg.cache_enabled.value),
        llm=llm,
        transcribe=TranscribeSettings(
            model=cfg.transcribe_model.value,
            language=LANGUAGES[language_label],
            language_label=language_label,
            output_format=cfg.transcribe_output_format.value,
            whisper_model=cfg.whisper_model.value,
            whisper_api_key=str(cfg.whisper_api_key.value or ""),
            whisper_api_base=str(cfg.whisper_api_base.value or ""),
            whisper_api_model=str(cfg.whisper_api_model.value or ""),
            whisper_api_prompt=str(cfg.whisper_api_prompt.value or ""),
            fun_asr_api_key=str(cfg.fun_asr_api_key.value or ""),
            fun_asr_api_base=str(cfg.fun_asr_api_base.value or ""),
            fun_asr_model=str(cfg.fun_asr_model.value or ""),
            faster_whisper_program=str(cfg.faster_whisper_program.value or ""),
            faster_whisper_model=cfg.faster_whisper_model.value,
            faster_whisper_model_dir=faster_model_dir,
            faster_whisper_device=str(cfg.faster_whisper_device.value or "cuda"),
            faster_whisper_vad_filter=bool(cfg.faster_whisper_vad_filter.value),
            faster_whisper_vad_threshold=float(cfg.faster_whisper_vad_threshold.value),
            faster_whisper_vad_method=cfg.faster_whisper_vad_method.value,
            faster_whisper_ff_mdx_kim2=bool(cfg.faster_whisper_ff_mdx_kim2.value),
            faster_whisper_one_word=bool(cfg.faster_whisper_one_word.value),
            faster_whisper_prompt=str(cfg.faster_whisper_prompt.value or ""),
        ),
        subtitle=SubtitleSettings(
            translator_service=cfg.translator_service.value,
            need_reflect=bool(cfg.need_reflect_translate.value),
            deeplx_endpoint=str(cfg.deeplx_endpoint.value or ""),
            thread_num=int(cfg.thread_num.value),
            batch_size=int(cfg.batch_size.value),
            need_optimize=bool(cfg.need_optimize.value),
            need_translate=bool(cfg.need_translate.value),
            need_split=bool(cfg.need_split.value),
            target_language=cfg.target_language.value,
            max_word_count_cjk=int(cfg.max_word_count_cjk.value),
            max_word_count_english=int(cfg.max_word_count_english.value),
            custom_prompt_text=str(cfg.custom_prompt_text.value or ""),
            layout=cfg.subtitle_layout.value,
            style_name=str(cfg.subtitle_style_name.value or "default"),
        ),
        synthesis=SynthesisSettings(
            need_video=bool(cfg.need_video.value),
            soft_subtitle=bool(cfg.soft_subtitle.value),
            video_quality=cfg.video_quality.value,
            render_mode=cfg.subtitle_render_mode.value,
            style_id=str(cfg.subtitle_style_name.value or "rounded/default"),
        ),
        dubbing=DubbingSettings(
            enabled=bool(cfg.dubbing_enabled.value),
            provider=str(cfg.dubbing_provider.value or "edge"),
            preset=str(cfg.dubbing_preset.value or ""),
            voice=str(cfg.dubbing_voice.value or ""),
            text_track=str(cfg.dubbing_text_track.value or "auto"),
            timing=str(cfg.dubbing_timing.value or "balanced"),
            audio_mode=str(cfg.dubbing_audio_mode.value or "replace"),
            api_key=str(cfg.dubbing_api_key.value or "").strip(),
            api_base=str(cfg.dubbing_api_base.value or "").strip(),
            model=str(cfg.dubbing_model.value or "").strip(),
            tts_workers=int(cfg.dubbing_tts_workers.value),
            clone_audio_path=str(cfg.dubbing_clone_audio.value or "").strip(),
            clone_audio_text=str(cfg.dubbing_clone_text.value or "").strip(),
        ),
    )


def _llm_from_ui(cfg) -> LLMSettings:
    service = cfg.llm_service.value
    if service == LLMServiceEnum.IMMERSIVE:
        # 公益大模型：无需用户配置，base/model 固定，真实令牌在 LLM client 内实时取
        return LLMSettings(
            service=service,
            api_key=free_model.PLACEHOLDER_KEY,
            api_base=free_model.BASE_URL,
            model=free_model.MODEL,
        )
    items = {
        LLMServiceEnum.OPENAI: (
            cfg.openai_api_key,
            cfg.openai_api_base,
            cfg.openai_model,
        ),
        LLMServiceEnum.SILICON_CLOUD: (
            cfg.silicon_cloud_api_key,
            cfg.silicon_cloud_api_base,
            cfg.silicon_cloud_model,
        ),
        LLMServiceEnum.DEEPSEEK: (
            cfg.deepseek_api_key,
            cfg.deepseek_api_base,
            cfg.deepseek_model,
        ),
        LLMServiceEnum.OLLAMA: (
            cfg.ollama_api_key,
            cfg.ollama_api_base,
            cfg.ollama_model,
        ),
        LLMServiceEnum.LM_STUDIO: (
            cfg.lm_studio_api_key,
            cfg.lm_studio_api_base,
            cfg.lm_studio_model,
        ),
        LLMServiceEnum.GEMINI: (
            cfg.gemini_api_key,
            cfg.gemini_api_base,
            cfg.gemini_model,
        ),
        LLMServiceEnum.CHATGLM: (
            cfg.chatglm_api_key,
            cfg.chatglm_api_base,
            cfg.chatglm_model,
        ),
    }
    api_key, api_base, model = items.get(service, items[LLMServiceEnum.OPENAI])
    return LLMSettings(
        service=service,
        api_key=str(api_key.value or ""),
        api_base=str(api_base.value or ""),
        model=str(model.value or ""),
    )
