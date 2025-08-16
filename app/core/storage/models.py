# app/core/storage/models.py
from datetime import date, datetime

from sqlalchemy import JSON, Column, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ASRCache(Base):
    """语音识别缓存表"""

    __tablename__ = "asr_cache"

    id = Column(Integer, primary_key=True)
    crc32_hex = Column(String(8), nullable=False, index=True)
    asr_type = Column(String(50), nullable=False)  # ASR服务类型
    result_data = Column(JSON, nullable=False)  # ASR结果数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_asr_cache_unique", "crc32_hex", "asr_type", unique=True),
    )


class TranslationCache(Base):
    """翻译结果缓存表"""

    __tablename__ = "translation_cache"

    id = Column(Integer, primary_key=True)
    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    translator_type = Column(String(50), nullable=False)
    params = Column(JSON)
    content_hash = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_translation_lookup", content_hash, translator_type),)

    def __repr__(self):
        return f"<Translation(id={self.id}, translator={self.translator_type})>"


class LLMCache(Base):
    """LLM调用结果缓存表"""

    __tablename__ = "llm_cache"

    id = Column(Integer, primary_key=True)
    prompt = Column(Text, nullable=False)
    result = Column(Text, nullable=False)
    model_name = Column(String(100), nullable=False)
    params = Column(JSON)
    content_hash = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_llm_lookup", content_hash, model_name),)

    def __repr__(self):
        return f"<LlmResult(id={self.id}, model={self.model_name})>"


class UsageStatistics(Base):
    """使用统计表"""

    __tablename__ = "usage_statistics"

    id = Column(Integer, primary_key=True)
    operation_type = Column(String(50), nullable=False)
    service_name = Column(String(50), nullable=False)
    call_count = Column(Integer, default=0)
    token_count = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_usage_lookup", operation_type, service_name, unique=True),
    )

    def __repr__(self):
        return f"<UsageStatistics({self.operation_type}:{self.service_name})>"


class DailyServiceUsage(Base):
    """每日服务使用次数表"""

    __tablename__ = "daily_service_usage"

    id = Column(Integer, primary_key=True)
    service_name = Column(String(50), nullable=False)  # 服务名称
    usage_date = Column(Date, nullable=False)  # 使用日期，改用 Date 类型
    usage_count = Column(Integer, default=0)  # 使用次数
    daily_limit = Column(Integer, nullable=False)  # 每日限制次数
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_daily_usage_lookup", service_name, usage_date, unique=True),
    )

    def __repr__(self):
        return f"<DailyServiceUsage(service={self.service_name}, date={self.usage_date}, count={self.usage_count})>"

    def __init__(self, **kwargs):
        """初始化时去除时分秒，只保留日期"""
        if "usage_date" in kwargs:
            if isinstance(kwargs["usage_date"], datetime):
                kwargs["usage_date"] = kwargs["usage_date"].date()
            elif isinstance(kwargs["usage_date"], date):
                pass
        super().__init__(**kwargs)
