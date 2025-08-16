# app/core/storage/constants.py
from datetime import timedelta
from enum import Enum


class TranslatorType(Enum):
    GOOGLE = "google"
    BING = "bing"
    LLM = "llm"
    DEEPLX = "deeplx"


class OperationType(Enum):
    TRANSLATION = "translation"
    LLM_CALL = "llm_call"


# 缓存配置
CACHE_CONFIG = {
    "max_age": timedelta(days=30),  # 缓存最大保存时间
    "db_filename": "cache.db",
    "cleanup_threshold": 10000,  # 触发清理的记录数阈值
}
