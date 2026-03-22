"""翻译器工厂"""

from typing import Callable, Optional

from videocaptioner.core.translate.base import BaseTranslator
from videocaptioner.core.translate.bing_translator import BingTranslator
from videocaptioner.core.translate.deeplx_translator import DeepLXTranslator
from videocaptioner.core.translate.google_translator import GoogleTranslator
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage, TranslatorType
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("translator_factory")


class TranslatorFactory:
    """翻译器工厂类"""

    @staticmethod
    def create_translator(
        translator_type: TranslatorType,
        thread_num: int = 5,
        batch_num: int = 10,
        target_language: Optional[TargetLanguage] = None,
        model: str = "gpt-4o-mini",
        custom_prompt: str = "",
        is_reflect: bool = False,
        update_callback: Optional[Callable] = None,
    ) -> BaseTranslator:
        """创建翻译器实例"""
        try:
            # 如果没有指定目标语言，使用默认值
            if target_language is None:
                target_language = TargetLanguage.SIMPLIFIED_CHINESE

            if translator_type == TranslatorType.OPENAI:
                return LLMTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    model=model,
                    custom_prompt=custom_prompt,
                    is_reflect=is_reflect,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.GOOGLE:
                batch_num = 5
                return GoogleTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    timeout=20,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.BING:
                batch_num = 10
                return BingTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    update_callback=update_callback,
                )
            elif translator_type == TranslatorType.DEEPLX:
                batch_num = 5
                return DeepLXTranslator(
                    thread_num=thread_num,
                    batch_num=batch_num,
                    target_language=target_language,
                    timeout=20,
                    update_callback=update_callback,
                )
        except Exception as e:
            logger.error(f"创建翻译器失败：{str(e)}")
            raise
