"""Google Translator integration tests."""

from typing import Dict, List

import pytest

from app.core.asr.asr_data import ASRData
from app.core.translate import SubtitleProcessData, TargetLanguage
from app.core.translate.google_translator import GoogleTranslator
from tests.conftest import assert_translation_quality


@pytest.mark.integration
class TestGoogleTranslator:
    """Test suite for GoogleTranslator using public API endpoints."""

    @pytest.fixture
    def google_translator(self, target_language: TargetLanguage) -> GoogleTranslator:
        """Create GoogleTranslator instance for testing."""
        return GoogleTranslator(
            thread_num=2,
            batch_num=5,
            target_language=target_language,
            timeout=20,
            update_callback=None,
        )

    @pytest.mark.parametrize(
        "target_language",
        [TargetLanguage.SIMPLIFIED_CHINESE, TargetLanguage.JAPANESE],
    )
    def test_translate_simple_text(
        self,
        google_translator: GoogleTranslator,
        sample_asr_data: ASRData,
        expected_translations: Dict[str, Dict[str, List[str]]],
        target_language: TargetLanguage,
    ) -> None:
        """Test translating simple ASR data with quality validation."""
        result = google_translator.translate_subtitle(sample_asr_data)

        print("\n" + "=" * 60)
        print(f"Google Translation Results (to {target_language.value}):")
        for i, seg in enumerate(result.segments, 1):
            print(f"  [{i}] {seg.text} → {seg.translated_text}")
        print("=" * 60)

        assert len(result.segments) == len(sample_asr_data.segments)

        # Get expected keywords for target language
        lang_expectations = expected_translations.get(target_language.value, {})

        # Validate translation quality
        for seg in result.segments:
            if seg.text in lang_expectations:
                assert_translation_quality(
                    seg.text, seg.translated_text, lang_expectations[seg.text]
                )
            else:
                assert seg.translated_text, f"Translation is empty for: {seg.text}"

    def test_translate_chunk(
        self,
        google_translator: GoogleTranslator,
        sample_translate_data: list[SubtitleProcessData],
        expected_translations: Dict[str, Dict[str, List[str]]],
        target_language: TargetLanguage,
    ) -> None:
        """Test translating a single chunk of data with quality validation."""
        result = google_translator._translate_chunk(sample_translate_data)

        print("\n" + "=" * 60)
        print(f"Google Chunk Translation Results (to {target_language.value}):")
        for data in result:
            print(f"  [{data.index}] {data.original_text} → {data.translated_text}")
        print("=" * 60)

        assert len(result) == len(sample_translate_data)

        # Get expected keywords for target language
        lang_expectations = expected_translations.get(target_language.value, {})

        # Validate translation quality
        for data in result:
            if data.original_text in lang_expectations:
                assert_translation_quality(
                    data.original_text,
                    data.translated_text,
                    lang_expectations[data.original_text],
                )
            else:
                assert (
                    data.translated_text
                ), f"Translation is empty for: {data.original_text}"
