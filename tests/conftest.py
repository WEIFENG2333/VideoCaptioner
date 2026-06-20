"""Root-level test configuration and shared fixtures."""

import json
import os
import re
from typing import Dict, List

import json_repair
import pytest

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.translate import SubtitleProcessData, TargetLanguage
from videocaptioner.core.utils import cache
from videocaptioner.core.utils.text_utils import count_words, is_mainly_cjk

# Disable cache for testing
cache.disable_cache()


@pytest.fixture(autouse=True)
def isolate_cache_state():
    """Keep tests from leaking the process-wide cache switch into each other."""
    cache.disable_cache()
    yield
    cache.disable_cache()


class _FakeLLMMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeLLMChoice:
    def __init__(self, content: str):
        self.message = _FakeLLMMessage(content)


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.choices = [_FakeLLMChoice(content)]


def _split_mock_text(text: str) -> List[str]:
    """Produce deterministic mock LLM sentence splits without changing content."""
    if not text.strip():
        return [text]

    if is_mainly_cjk(text) or re.search(r"[\u4e00-\u9fff]", text):
        limit = 12
        segments: List[str] = []
        current = ""
        for char in text:
            current += char
            should_break = char in "。！？；" or count_words(current) >= limit
            if should_break and current.strip():
                segments.append(current)
                current = ""
        if current:
            segments.append(current)
        return segments

    words = text.split()
    if len(words) <= 10:
        return [text]
    return [" ".join(words[i : i + 10]) for i in range(0, len(words), 10)]


def _extract_json_dict(text: str) -> Dict[str, str]:
    match = re.search(r"<input_subtitle>(.*?)</input_subtitle>", text, re.S)
    payload = match.group(1) if match else text
    parsed = json_repair.loads(payload)
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items()}
    return {}


@pytest.fixture
def mock_llm_client(monkeypatch):
    """Patch all direct LLM call sites with a deterministic OpenAI-like response."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.local/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    def fake_call_llm(messages, model, **kwargs):
        system_prompt = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        user_prompt = next(
            (
                str(message.get("content", ""))
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )

        if "Please use multiple <br> tags" in user_prompt:
            text = user_prompt.split("\n", 1)[-1]
            return _FakeLLMResponse("<br>".join(_split_mock_text(text)))

        if "<input_subtitle>" in user_prompt or "Correct the following subtitles" in user_prompt:
            subtitle_dict = _extract_json_dict(user_prompt)
            return _FakeLLMResponse(json.dumps(subtitle_dict, ensure_ascii=False))

        try:
            subtitle_dict = _extract_json_dict(user_prompt)
        except Exception:
            subtitle_dict = {}

        if subtitle_dict:
            if "native_translation" in system_prompt or "reflect" in system_prompt.lower():
                payload = {
                    key: {"native_translation": f"{value} 译文"}
                    for key, value in subtitle_dict.items()
                }
            else:
                payload = {key: f"{value} 译文" for key, value in subtitle_dict.items()}
            return _FakeLLMResponse(json.dumps(payload, ensure_ascii=False))

        return _FakeLLMResponse('{"1": "mock"}')

    monkeypatch.setattr("videocaptioner.core.llm.client.call_llm", fake_call_llm)
    monkeypatch.setattr("videocaptioner.core.llm.call_llm", fake_call_llm)
    monkeypatch.setattr("videocaptioner.core.translate.llm_translator.call_llm", fake_call_llm)
    monkeypatch.setattr("videocaptioner.core.optimize.optimize.call_llm", fake_call_llm)
    monkeypatch.setattr("videocaptioner.core.split.split_by_llm.call_llm", fake_call_llm)
    monkeypatch.setattr(
        "videocaptioner.ui.thread.subtitle_thread.check_llm_connection",
        lambda *args, **kwargs: (True, "mock"),
    )
    return fake_call_llm


@pytest.fixture
def sample_asr_data():
    """Create sample ASR data for translation testing."""
    segments = [
        ASRDataSeg(start_time=0, end_time=1000, text="I am a student"),
        ASRDataSeg(start_time=1000, end_time=2000, text="You are a teacher"),
        ASRDataSeg(start_time=2000, end_time=3000, text="VideoCaptioner is a tool for captioning videos"),
    ]
    return ASRData(segments)


@pytest.fixture
def sample_translate_data():
    """Create sample translation data for testing."""
    return [
        SubtitleProcessData(index=1, original_text="I am a student", translated_text=""),
        SubtitleProcessData(index=2, original_text="You are a teacher", translated_text=""),
        SubtitleProcessData(index=3, original_text="VideoCaptioner is a tool for captioning videos", translated_text=""),
    ]


@pytest.fixture
def target_language():
    """Default target language for translation tests."""
    return TargetLanguage.SIMPLIFIED_CHINESE


@pytest.fixture
def check_env_vars():
    """Check if required environment variables are set."""
    def _check(*var_names):
        missing = [var for var in var_names if not os.getenv(var)]
        if missing:
            pytest.skip(f"Required environment variables not set: {', '.join(missing)}")
    return _check


@pytest.fixture
def expected_translations() -> Dict[str, Dict[str, List[str]]]:
    """Expected translation keywords for quality validation."""
    return {
        "简体中文": {
            "I am a student": ["学生"],
            "You are a teacher": ["老师", "教师"],
            "VideoCaptioner is a tool for captioning videos": ["工具"],
        },
        "日本語": {
            "I am a student": ["学生"],
            "You are a teacher": ["先生", "教師"],
        },
        "English": {
            "我是学生": ["student"],
            "你是老师": ["teacher"],
        },
    }


def assert_translation_quality(original: str, translated: str, expected_keywords: List[str]) -> None:
    """Validate translation contains expected keywords."""
    assert translated, f"Translation is empty for: {original}"
    found_keywords = [kw for kw in expected_keywords if kw in translated]
    assert found_keywords, (
        f"Translation quality issue:\n"
        f"  Original: {original}\n"
        f"  Translated: {translated}\n"
        f"  Expected keywords: {expected_keywords}"
    )
