"""Root-level test configuration and shared fixtures.

This conftest.py provides shared fixtures and utilities for all tests.
Module-specific fixtures should be placed in their respective conftest.py files.
"""

import os
from pathlib import Path
from typing import Dict, List

import pytest
from dotenv import load_dotenv
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# from phoenix.otel import register
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.translate import SubtitleProcessData, TargetLanguage
from app.core.utils import cache

# Load environment variables from tests/.env
load_dotenv(Path(__file__).parent / ".env")

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
# LLM Mocking Utilities
# ============================================================================


@pytest.fixture
def mock_llm_client(monkeypatch):
    """Mock LLM client for testing without external API calls.

    Provides reasonable default responses for common LLM operations.
    Tests can use this fixture to avoid real API calls.

    Example:
        def test_split(mock_llm_client):
            # LLM calls will be mocked automatically
            result = split_by_llm("你好世界")
    """
    from unittest.mock import MagicMock

    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice

    def mock_create(**kwargs):
        """Mock OpenAI chat completion create method."""
        messages = kwargs.get("messages", [])
        model = kwargs.get("model", "gpt-4o-mini")

        # Extract system and user messages
        system_content = ""
        user_content = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            elif msg.get("role") == "user":
                user_content = msg.get("content", "")

        # Generate mock response based on request
        if "<br>" in user_content or "separate" in user_content.lower():
            # Split request - return text with <br> tags
            text_to_split = user_content.split("sentence:\n")[-1].strip()

            # Extract max length from system prompt
            import re

            max_cjk = 18  # default
            max_eng = 12  # default
            if "max" in system_content.lower():
                cjk_match = re.search(r"中文.*?(\d+)", system_content)
                if cjk_match:
                    max_cjk = int(cjk_match.group(1))
                eng_match = re.search(r"英文.*?(\d+)", system_content)
                if eng_match:
                    max_eng = int(eng_match.group(1))

            # Split by punctuation first
            sentences = re.split(r"([。！？\.!?])", text_to_split)
            initial_parts = []
            for i in range(0, len(sentences) - 1, 2):
                if i + 1 < len(sentences):
                    initial_parts.append(sentences[i] + sentences[i + 1])
            if len(sentences) % 2 == 1 and sentences[-1].strip():
                initial_parts.append(sentences[-1])

            # Further split long segments
            from app.core.utils.text_utils import count_words, is_mainly_cjk

            result_parts = []
            for part in initial_parts:
                part = part.strip()
                if not part:
                    continue

                word_count = count_words(part)
                max_limit = max_cjk if is_mainly_cjk(part) else max_eng

                if word_count <= max_limit:
                    result_parts.append(part)
                else:
                    # Split long part into smaller chunks
                    words = list(part) if is_mainly_cjk(part) else part.split()
                    chunk = []
                    for word in words:
                        chunk.append(word)
                        if (
                            count_words(
                                "".join(chunk)
                                if is_mainly_cjk(part)
                                else " ".join(chunk)
                            )
                            >= max_limit
                        ):
                            result_parts.append(
                                "".join(chunk)
                                if is_mainly_cjk(part)
                                else " ".join(chunk)
                            )
                            chunk = []
                    if chunk:
                        result_parts.append(
                            "".join(chunk) if is_mainly_cjk(part) else " ".join(chunk)
                        )

            response_text = "<br>".join(p for p in result_parts if p)
        elif "translate" in system_content.lower() or "翻译" in system_content.lower():
            # Translation request - parse JSON input and return translated JSON
            import json

            import json_repair

            try:
                # Try to parse JSON from user content
                input_dict = json_repair.loads(user_content)

                # Create mock translations
                translated_dict = {}
                for key, value in input_dict.items():
                    # Simple mock translation: add "[译]" prefix
                    if (
                        "简体中文" in system_content
                        or "Simplified Chinese" in system_content
                    ):
                        translated_dict[key] = f"[中文]{value}"
                    elif "日本語" in system_content or "Japanese" in system_content:
                        translated_dict[key] = f"[日]{value}"
                    else:
                        translated_dict[key] = f"[译]{value}"

                response_text = json.dumps(translated_dict, ensure_ascii=False)
            except Exception:
                # Fallback to simple response
                response_text = '{"1": "Mocked translation"}'
        elif "correct" in system_content.lower() or "优化" in system_content.lower():
            # Optimization request - parse JSON input and return optimized JSON
            import json

            import json_repair

            try:
                # Extract input from user content
                if "<input_subtitle>" in user_content:
                    # Extract dict from <input_subtitle> tags
                    import re

                    match = re.search(
                        r"<input_subtitle>({[^}]+})</input_subtitle>", user_content
                    )
                    if match:
                        input_dict = json_repair.loads(match.group(1))
                    else:
                        # Try to find dict in content
                        match = re.search(r"{[^}]+}", user_content)
                        if match:
                            input_dict = json_repair.loads(match.group(0))
                        else:
                            input_dict = {}
                else:
                    # Try to parse entire user content as JSON
                    input_dict = json_repair.loads(user_content)

                # Return the same text (mock optimization = no change)
                response_text = json.dumps(input_dict, ensure_ascii=False)
            except Exception:
                # Fallback to simple response
                response_text = '{"1": "Mocked optimization"}'
        else:
            # Default response
            response_text = "Mocked LLM response"

        # Create mock response object
        mock_response = MagicMock(spec=ChatCompletion)
        mock_message = MagicMock(spec=ChatCompletionMessage)
        mock_message.content = response_text
        mock_message.role = "assistant"

        mock_choice = MagicMock(spec=Choice)
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"
        mock_choice.index = 0

        mock_response.choices = [mock_choice]
        mock_response.model = model
        mock_response.id = "mock-id"

        return mock_response

    # Patch the LLM client
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    def mock_get_client():
        return mock_client

    monkeypatch.setattr("app.core.llm.client.get_llm_client", mock_get_client)

    # Mock check_llm_connection to prevent real API calls
    def mock_check_llm_connection(base_url, api_key, model):
        """Mock LLM connection check - always returns success."""
        return True, None

    monkeypatch.setattr(
        "app.thread.subtitle_thread.check_llm_connection", mock_check_llm_connection
    )

    return mock_client


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
