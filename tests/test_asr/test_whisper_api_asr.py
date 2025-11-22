"""WhisperAPI integration tests."""

import os
from pathlib import Path

import pytest

from app.core.asr import WhisperAPI
from app.core.asr.asr_data import ASRData
from tests.test_asr.conftest import assert_asr_result_valid


@pytest.mark.integration
class TestWhisperAPI:
    """Test suite for WhisperAPI using OpenAI-compatible API endpoints."""

    @pytest.fixture(autouse=True)
    def skip_if_no_env(self, check_env_vars) -> None:
        """Skip tests if required environment variables are not set.

        Args:
            check_env_vars: Fixture from root conftest.py
        """
        check_env_vars("WHISPER_BASE_URL", "WHISPER_API_KEY")

    def test_chinese_word_timestamp(self, test_audio_path_zh: Path) -> None:
        """Test Chinese word-level timestamp functionality.

        Args:
            test_audio_path_zh: Path to Chinese test audio file
        """
        whisper_api = WhisperAPI(
            audio_input=str(test_audio_path_zh),
            whisper_model=os.getenv("WHISPER_MODEL", "whisper-1"),
            language="zh",
            prompt="",
            base_url=os.getenv("WHISPER_BASE_URL"),
            api_key=os.getenv("WHISPER_API_KEY"),
            need_word_time_stamp=True,
        )

        result: ASRData = whisper_api.run()

        print("\n" + "=" * 60)
        print("WhisperAPI - Chinese Word Timestamp Test:")
        print(f"  Total Segments: {len(result.segments)}")
        print(f"  Is Word Timestamp: {result.is_word_timestamp()}")
        for i, seg in enumerate(result.segments, 1):
            print(
                f"    [{i:3d}] {seg.text:<20} ({seg.start_time:6d} - {seg.end_time:6d} ms)"
            )
        print("=" * 60)

        assert_asr_result_valid(result, min_segments=0)

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
        language_code = "zh" if "zh" in audio_fixture else "en"

        whisper_api = WhisperAPI(
            audio_input=str(audio_path),
            whisper_model=os.getenv("WHISPER_MODEL", "whisper-1"),
            language=language_code,
            prompt="",
            base_url=os.getenv("WHISPER_BASE_URL"),
            api_key=os.getenv("WHISPER_API_KEY"),
            need_word_time_stamp=need_word_ts,
        )

        result: ASRData = whisper_api.run()

        print("\n" + "=" * 60)
        print(f"WhisperAPI - {lang.upper()} - {level.title()}-Level Results:")
        print(f"  Total Segments: {len(result.segments)}")
        print(f"  Is Word Timestamp: {result.is_word_timestamp()}")
        for i, seg in enumerate(result.segments[:50], 1):
            print(
                f"    [{i:2d}] {seg.text:<30} ({seg.start_time:6d} - {seg.end_time:6d} ms)"
            )
        print("=" * 60)

        assert_asr_result_valid(result, min_segments=0)
