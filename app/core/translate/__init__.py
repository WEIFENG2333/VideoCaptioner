"""
翻译模块

提供多种翻译服务：OpenAI LLM、Google、Bing、DeepLX
"""

from app.core.entities import SubtitleProcessData
from app.core.translate.base import BaseTranslator
from app.core.translate.bing_translator import BingTranslator
from app.core.translate.deeplx_translator import DeepLXTranslator
from app.core.translate.factory import TranslatorFactory
from app.core.translate.google_translator import GoogleTranslator
from app.core.translate.llm_translator import LLMTranslator
from app.core.translate.types import TargetLanguage, TranslatorType

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
