"""Google 翻译器"""

import html
import re
from typing import Callable, List, Optional

import requests

from app.core.entities import SubtitleProcessData
from app.core.translate.base import BaseTranslator, logger
from app.core.translate.types import TargetLanguage, get_language_code
from app.core.utils.cache import generate_cache_key


class GoogleTranslator(BaseTranslator):
    """谷歌翻译器"""

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
        self.endpoint = "http://translate.google.com/m"
        self.headers = {
            "User-Agent": "Mozilla/4.0 (compatible;MSIE 6.0;Windows NT 5.1;SV1;.NET CLR 1.1.4322;.NET CLR 2.0.50727;.NET CLR 3.0.04506.30)"
        }

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """翻译字幕块"""
        target_lang = get_language_code(self.target_language, "google")

        for data in subtitle_chunk:
            try:
                text = data.original_text[:5000]  # google translate max length
                response = self.session.get(
                    self.endpoint,
                    params={"tl": target_lang, "sl": "auto", "q": text},
                    headers=self.headers,
                    timeout=self.timeout,
                )

                if response.status_code == 400:
                    logger.warning(f"Google翻译返回400错误 {data.index}")
                    continue

                response.raise_for_status()
                re_result = re.findall(
                    r'(?s)class="(?:t0|result-container)">(.*?)<', response.text
                )
                if re_result:
                    data.translated_text = html.unescape(re_result[0])
                    data.translated_text = data.translated_text
                else:
                    logger.warning(f"无法从Google翻译响应中提取翻译结果: {data.index}")
            except Exception as e:
                logger.error(f"Google翻译失败 {data.index}: {str(e)}")

        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
