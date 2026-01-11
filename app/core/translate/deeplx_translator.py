"""DeepLX 翻译器"""

import os
from typing import Callable, List, Optional

import requests

from app.core.translate.base import BaseTranslator, SubtitleProcessData, logger
from app.core.translate.types import TargetLanguage, get_language_code
from app.core.utils.cache import generate_cache_key


class DeepLXTranslator(BaseTranslator):
    """DeepLX翻译器"""

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        timeout: int,
        update_callback: Optional[Callable],
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )
        self.timeout = timeout
        self.session = requests.Session()
        self.endpoint = os.getenv("DEEPLX_ENDPOINT", "https://api.deeplx.org/translate")

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块"""
        target_lang = get_language_code(self.target_language, "deeplx")

        for data in subtitle_chunk:
            try:
                response = self.session.post(
                    self.endpoint,
                    json={
                        "text": data.original_text,
                        "source_lang": "auto",
                        "target_lang": target_lang,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data.translated_text = response.json()["data"]
            except Exception as e:
                logger.error(f"DeepLX翻译失败 {data.index}: {str(e)}")

        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
