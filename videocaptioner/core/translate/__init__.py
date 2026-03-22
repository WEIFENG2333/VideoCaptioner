"""
翻译模块

提供多种翻译服务：OpenAI LLM、Google、Bing、DeepLX
"""

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.base import BaseTranslator
from videocaptioner.core.translate.bing_translator import BingTranslator
from videocaptioner.core.translate.deeplx_translator import DeepLXTranslator
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.google_translator import GoogleTranslator
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage, TranslatorType

__all__ = [
    "BaseTranslator",
    "SubtitleProcessData",
    "TranslatorFactory",
    "TranslatorType",
    "TargetLanguage",
    "BingTranslator",
    "DeepLXTranslator",
    "GoogleTranslator",
    "LLMTranslator",
]
