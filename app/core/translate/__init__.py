"""
翻译模块

提供多种翻译服务：OpenAI LLM、Google、Bing、DeepLX
"""

from app.core.translate.base import BaseTranslator, TranslateData
from app.core.translate.factory import TranslatorFactory
from app.core.translate.types import TargetLanguage, TranslatorType

__all__ = [
    "BaseTranslator",
    "TranslateData",
    "TranslatorFactory",
    "TranslatorType",
    "TargetLanguage",
]
