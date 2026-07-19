"""Real translation-service check shared by GUI and future diagnostics callers."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import SubtitleConfig, TranslatorServiceEnum
from videocaptioner.core.llm import free_model
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.types import TargetLanguage, TranslatorType

_SERVICE_TO_TYPE = {
    TranslatorServiceEnum.OPENAI: TranslatorType.OPENAI,
    TranslatorServiceEnum.GOOGLE: TranslatorType.GOOGLE,
    TranslatorServiceEnum.BING: TranslatorType.BING,
    TranslatorServiceEnum.DEEPLX: TranslatorType.DEEPLX,
}


@dataclass(frozen=True)
class TranslationCheckResult:
    success: bool
    detail: str
    translated_text: str = ""


def _source_text(target: TargetLanguage) -> str:
    """Choose a source language different from the selected target language."""
    if target in {
        TargetLanguage.ENGLISH,
        TargetLanguage.ENGLISH_US,
        TargetLanguage.ENGLISH_UK,
    }:
        return "你好，这是一次翻译服务测试。"
    return "Hello, this is a translation service test."


def check_translation(config: SubtitleConfig) -> TranslationCheckResult:
    """Translate one uncached short sentence through the production provider path."""
    service = config.translator_service
    translator_type = _SERVICE_TO_TYPE.get(service)
    if translator_type is None:
        return TranslationCheckResult(False, f"不支持的翻译服务: {service}")

    if service == TranslatorServiceEnum.DEEPLX:
        endpoint = str(config.deeplx_endpoint or "").strip()
        if not endpoint:
            return TranslationCheckResult(False, "请先填写 DeepLX 接口地址")
        os.environ["DEEPLX_ENDPOINT"] = endpoint
    elif service == TranslatorServiceEnum.OPENAI:
        api_base = str(config.base_url or "").strip()
        api_key = str(config.api_key or "").strip()
        model = str(config.llm_model or "").strip()
        if not (api_base and model) or (not api_key and not free_model.is_free_base(api_base)):
            return TranslationCheckResult(False, "请先完成 LLM 地址、密钥和模型配置")
        os.environ["OPENAI_BASE_URL"] = api_base
        os.environ["OPENAI_API_KEY"] = api_key or "free-model"

    target_language = config.target_language or TargetLanguage.SIMPLIFIED_CHINESE
    translator = None
    try:
        translator = TranslatorFactory.create_translator(
            translator_type=translator_type,
            thread_num=1,
            batch_num=1,
            target_language=target_language,
            model=config.llm_model or "",
            custom_prompt="",
            is_reflect=False,
            disable_thinking=True,
        )
        # A timestamp prevents the normal seven-day translation cache from
        # turning a connectivity check into a local cache hit.
        source = f"{_source_text(target_language)} [{time.time_ns()}]"
        result = translator.translate_subtitle(
            ASRData([ASRDataSeg(text=source, start_time=0, end_time=1000)])
        )
        translated = str(result.segments[0].translated_text or "").strip()
        if not translated:
            detail = str(getattr(translator, "last_error", "") or "").strip()
            return TranslationCheckResult(False, detail or "服务返回了空翻译")
        return TranslationCheckResult(True, "翻译服务可用", translated)
    except Exception as exc:
        return TranslationCheckResult(False, str(exc))
    finally:
        if translator is not None:
            translator.stop()
