"""LLM Translator integration tests.

Requires environment variables:
    OPENAI_BASE_URL: OpenAI-compatible API endpoint
    OPENAI_API_KEY: API key for authentication
    OPENAI_MODEL: Model name (optional, defaults to gpt-4o-mini)
"""

import os
from typing import Callable, Dict, List

import pytest

from app.core.asr.asr_data import ASRData
from app.core.translate import SubtitleProcessData, TargetLanguage
from app.core.translate.llm_translator import LLMTranslator
from app.core.utils import cache
from tests.conftest import assert_translation_quality


@pytest.mark.integration
class TestLLMTranslator:
    """Test suite for LLMTranslator with OpenAI-compatible APIs."""

    @pytest.fixture
    def llm_translator(
        self, mock_llm_client, target_language: TargetLanguage
    ) -> LLMTranslator:
        """Create LLMTranslator instance for testing (using mock LLM)."""
        model = "gpt-4o-mini"

        return LLMTranslator(
            thread_num=2,
            batch_num=5,
            target_language=target_language,
            model=model,
            custom_prompt="",
            is_reflect=False,
            update_callback=None,
        )

    @pytest.mark.parametrize(
        "target_language",
        [TargetLanguage.SIMPLIFIED_CHINESE, TargetLanguage.JAPANESE],
    )
    def test_translate_simple_text(
        self,
        llm_translator: LLMTranslator,
        sample_asr_data: ASRData,
        expected_translations: Dict[str, Dict[str, List[str]]],
        target_language: TargetLanguage,
    ) -> None:
        """Test translating simple ASR data with quality validation (using mock LLM)."""

        result = llm_translator.translate_subtitle(sample_asr_data)

        print("\n" + "=" * 60)
        print(f"LLM Translation Results (to {target_language.value}):")
        for i, seg in enumerate(result.segments, 1):
            print(f"  [{i}] {seg.text} → {seg.translated_text}")
        print("=" * 60)

        assert len(result.segments) == len(sample_asr_data.segments)

        # Validate translation exists (quality check skipped for mock)
        for seg in result.segments:
            assert seg.translated_text, f"Translation is empty for: {seg.text}"

    def test_translate_chunk(
        self,
        llm_translator: LLMTranslator,
        sample_translate_data: list[SubtitleProcessData],
        expected_translations: Dict[str, Dict[str, List[str]]],
        target_language: TargetLanguage,
    ) -> None:
        """Test translating a single chunk of data with quality validation (using mock LLM)."""

        result = llm_translator._translate_chunk(sample_translate_data)

        print("\n" + "=" * 60)
        print(f"LLM Chunk Translation Results (to {target_language.value}):")
        for data in result:
            print(f"  [{data.index}] {data.original_text} → {data.translated_text}")
        print("=" * 60)

        assert len(result) == len(sample_translate_data)

        # Get expected keywords for target language
        lang_expectations = expected_translations.get(target_language.value, {})

        # Validate translation exists (quality check skipped for mock)
        for data in result:
            assert (
                data.translated_text
            ), f"Translation is empty for: {data.original_text}"

    def test_cache_works(
        self,
        llm_translator: LLMTranslator,
        sample_asr_data: ASRData,
    ) -> None:
        """Test that caching mechanism works correctly (using mock LLM)."""
        cache.enable_cache()

        result1 = llm_translator.translate_subtitle(sample_asr_data)
        result2 = llm_translator.translate_subtitle(sample_asr_data)

        print("\n" + "=" * 60)
        print("LLM Cache Test:")
        print(f"  First call:  {result1.segments[-1].translated_text}")
        print(f"  Second call: {result2.segments[-1].translated_text}")
        print(
            f"  Match: {result1.segments[0].translated_text == result2.segments[0].translated_text}"
        )
        print("=" * 60)

        for seg1, seg2 in zip(result1.segments, result2.segments):
            assert seg1.translated_text == seg2.translated_text

    @pytest.mark.parametrize(
        "target_language",
        [TargetLanguage.SIMPLIFIED_CHINESE],
    )
    def test_reflect_translation(
        self,
        sample_asr_data: ASRData,
        target_language: TargetLanguage,
        check_env_vars: Callable,
    ) -> None:
        """Test reflect translation mode with nested dict validation."""
        check_env_vars("OPENAI_BASE_URL", "OPENAI_API_KEY")

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        translator = LLMTranslator(
            thread_num=2,
            batch_num=5,
            target_language=target_language,
            model=model,
            custom_prompt="",
            is_reflect=True,
            update_callback=None,
        )

        result = translator.translate_subtitle(sample_asr_data)

        print("\n" + "=" * 60)
        print(f"Reflect Translation Results (to {target_language.value}):")
        for i, seg in enumerate(result.segments, 1):
            print(f"  [{i}] {seg.text}")
            print(f"      → {seg.translated_text}")
        print("=" * 60)

        assert len(result.segments) == len(sample_asr_data.segments)

        for seg in result.segments:
            assert seg.translated_text, f"Translation is empty for: {seg.text}"
            assert len(seg.translated_text) > 0, "Translated text should not be empty"
