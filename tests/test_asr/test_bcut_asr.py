"""BcutASR integration tests."""

from pathlib import Path

import pytest

from app.core.asr import BcutASR
from app.core.asr.asr_data import ASRData
from tests.test_asr.conftest import assert_asr_result_valid


@pytest.mark.integration
@pytest.mark.slow
class TestBcutASR:
    """Test suite for BcutASR using public Bilibili API.

    Note: This service has rate limits and should be used sparingly.
    Tests are marked as 'slow' to avoid running in normal CI.
    """

    @pytest.fixture
    def bcut_asr_sentence(self, test_audio_path: Path) -> BcutASR:
        """Create BcutASR instance with sentence-level timestamps.

        Args:
            test_audio_path: Path to test audio file

        Returns:
            BcutASR instance configured for sentence-level timestamps
        """
        return BcutASR(
            audio_input=str(test_audio_path),
            need_word_time_stamp=False,
        )

    @pytest.fixture
    def bcut_asr_word(self, test_audio_path: Path) -> BcutASR:
        """Create BcutASR instance with word-level timestamps.

        Args:
            test_audio_path: Path to test audio file

        Returns:
            BcutASR instance configured for word-level timestamps
        """
        return BcutASR(
            audio_input=str(test_audio_path),
            need_word_time_stamp=True,
        )

    # def test_transcribe_sentence_level(self, bcut_asr_sentence: BcutASR) -> None:
    #     """Test sentence-level transcription (need_word_time_stamp=False).

    #     Args:
    #         bcut_asr_sentence: BcutASR instance with sentence-level timestamps
    #     """
    #     result: ASRData = bcut_asr_sentence.run()

    #     print("\n" + "=" * 60)
    #     print("BcutASR Sentence-Level Transcription Results:")
    #     print(f"  Total segments: {len(result.segments)}")
    #     print(f"  Is word timestamp: {result.is_word_timestamp()}")
    #     for i, seg in enumerate(result.segments[:3], 1):
    #         print(f"  [{i}] {seg.text} ({seg.start_time}-{seg.end_time}ms)")
    #     print("=" * 60)

    #     assert_asr_result_valid(result, min_segments=0)
    #     assert (
    #         not result.is_word_timestamp()
    #     ), "Result should be sentence-level, not word-level"

    # def test_transcribe_word_level(self, bcut_asr_word: BcutASR) -> None:
    #     """Test word-level transcription (need_word_time_stamp=True).

    #     Args:
    #         bcut_asr_word: BcutASR instance with word-level timestamps
    #     """
    #     result: ASRData = bcut_asr_word.run()

    #     print("\n" + "=" * 60)
    #     print("BcutASR Word-Level Transcription Results:")
    #     print(f"  Total segments: {len(result.segments)}")
    #     print(f"  Is word timestamp: {result.is_word_timestamp()}")
    #     for i, seg in enumerate(result.segments[:5], 1):
    #         print(f"  [{i}] {seg.text} ({seg.start_time}-{seg.end_time}ms)")
    #     print("=" * 60)

    #     assert_asr_result_valid(result, min_segments=0)

    #     if len(result.segments) > 0:
    #         assert (
    #             result.is_word_timestamp()
    #         ), "Result should be word-level when need_word_time_stamp=True"

    @pytest.mark.parametrize(
        "need_word_ts,audio_fixture",
        [
            (False, "test_audio_path_zh"),
            (True, "test_audio_path_zh"),
            (False, "test_audio_path_en"),
            (True, "test_audio_path_en"),
        ],
    )
    def test_transcribe_parametrized(
        self, need_word_ts: bool, audio_fixture: str, request
    ) -> None:
        """Test transcription with different configurations and languages.

        Args:
            need_word_ts: Whether to use word-level timestamps
            audio_fixture: Name of the audio fixture to use
            request: Pytest request object for fixture access
        """
        audio_path: Path = request.getfixturevalue(audio_fixture)
        lang = "Chinese" if "zh" in audio_fixture else "English"
        level = "word" if need_word_ts else "sentence"

        asr = BcutASR(
            audio_input=str(audio_path),
            need_word_time_stamp=need_word_ts,
        )

        result: ASRData = asr.run()

        print("\n" + "=" * 60)
        print(f"BcutASR - {lang.upper()} - {level.title()}-Level Results:")
        print(f"  Total Segments: {len(result.segments)}")
        print(f"  Is Word Timestamp: {result.is_word_timestamp()}")
        for i, seg in enumerate(result.segments[:50], 1):
            print(
                f"    [{i:2d}] {seg.text:<30} ({seg.start_time:6d} - {seg.end_time:6d} ms)"
            )
        print("=" * 60)

        assert_asr_result_valid(result, min_segments=0)

        if not need_word_ts and len(result.segments) > 0:
            assert not result.is_word_timestamp()
