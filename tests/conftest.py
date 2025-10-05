"""Root-level test configuration and shared fixtures.

This conftest.py provides shared fixtures and utilities for all tests.
Module-specific fixtures should be placed in their respective conftest.py files.
"""

import os
from typing import Dict, List

import pytest
from dotenv import load_dotenv
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# from phoenix.otel import register
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.translate import TargetLanguage, SubtitleProcessData
from app.core.utils import cache

# Load environment variables
load_dotenv()

# Register OpenAI OTel tracing
# tracer_provider = register(
#     project_name="default",
#     endpoint="http://localhost:6006/v1/traces",
#     auto_instrument=True,
# )
tracer_provider = trace_sdk.TracerProvider()
tracer_provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces"))
)
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)


# Disable cache for testing
cache.disable_cache()


# ============================================================================
# Shared Data Fixtures
# ============================================================================


@pytest.fixture
def sample_asr_data():
    """Create sample ASR data for translation testing.

    Returns:
        ASRData with 3 English segments
    """
    segments = [
        ASRDataSeg(
            start_time=0,
            end_time=1000,
            text="I am a student",
        ),
        ASRDataSeg(
            start_time=1000,
            end_time=2000,
            text="You are a teacher",
        ),
        ASRDataSeg(
            start_time=2000,
            end_time=3000,
            text="VideoCaptioner is a tool for captioning videos",
        ),
    ]
    return ASRData(segments)


@pytest.fixture
def sample_translate_data():
    """Create sample translation data for testing."""
    return [
        SubtitleProcessData(
            index=1, original_text="I am a student", translated_text=""
        ),
        SubtitleProcessData(
            index=2, original_text="You are a teacher", translated_text=""
        ),
        SubtitleProcessData(
            index=3,
            original_text="VideoCaptioner is a tool for captioning videos",
            translated_text="",
        ),
    ]


@pytest.fixture
def target_language():
    """Default target language for translation tests.

    Returns:
        Simplified Chinese as default target language
    """
    return TargetLanguage.SIMPLIFIED_CHINESE


# ============================================================================
# Shared Utility Fixtures
# ============================================================================


@pytest.fixture
def check_env_vars():
    """Check if required environment variables are set.

    Returns:
        Function that takes variable names and skips test if any are missing

    Example:
        def test_api(check_env_vars):
            check_env_vars("OPENAI_API_KEY", "OPENAI_BASE_URL")
            # Test continues only if both variables are set
    """

    def _check(*var_names):
        missing = [var for var in var_names if not os.getenv(var)]
        if missing:
            pytest.skip(f"Required environment variables not set: {', '.join(missing)}")

    return _check


# ============================================================================
# Translation Test Data
# ============================================================================


@pytest.fixture
def expected_translations() -> Dict[str, Dict[str, List[str]]]:
    """Expected translation keywords for quality validation.

    Returns:
        Dictionary mapping language -> original text -> expected keywords

    Example:
        {
            "简体中文": {
                "I am a student": ["学生"],
                "You are a teacher": ["老师", "教师"]
            }
        }
    """
    return {
        "简体中文": {
            "I am a student": ["学生"],
            "You are a teacher": ["老师", "教师"],
            "VideoCaptioner is a tool for captioning videos": ["工具"],
            "Hello world": ["你好", "世界"],
            "This is a test": ["测试"],
            "Machine learning": ["机器学习"],
        },
        "日本語": {
            "I am a student": ["学生"],
            "You are a teacher": ["先生", "教師"],
            "VideoCaptioner is a tool for captioning videos": [
                "VideoCaptioner",
                "ツール",
                "字幕",
            ],
            "Hello world": ["こんにちは", "世界"],
            "This is a test": ["テスト"],
            "Machine learning": ["機械学習"],
        },
        "English": {
            "我是学生": ["student"],
            "你是老师": ["teacher"],
            "这是一个测试": ["test"],
        },
    }


# ============================================================================
# Shared Assertion Utilities
# ============================================================================


def assert_translation_quality(
    original: str, translated: str, expected_keywords: List[str]
) -> None:
    """Validate translation contains expected keywords.

    Args:
        original: Original text
        translated: Translated text
        expected_keywords: List of keywords that should appear in translation

    Raises:
        AssertionError: If translation is empty or doesn't contain expected keywords
    """
    assert translated, f"Translation is empty for: {original}"

    found_keywords = [kw for kw in expected_keywords if kw in translated]

    assert found_keywords, (
        f"Translation quality issue:\n"
        f"  Original: {original}\n"
        f"  Translated: {translated}\n"
        f"  Expected keywords: {expected_keywords}\n"
        f"  Found: {found_keywords}"
    )
