"""Tests for TranscriptThread."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.core.entities import TranscribeConfig, TranscribeModelEnum, TranscribeTask
from app.thread.transcript_thread import TranscriptThread
from tests.test_thread.conftest import run_thread_with_timeout

load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.integration
class TestTranscriptThread:
    """Test suite for TranscriptThread."""

    @pytest.fixture
    def base_config(self) -> TranscribeConfig:
        """Create base transcription configuration."""
        return TranscribeConfig(
            transcribe_model=TranscribeModelEnum.FASTER_WHISPER,
            transcribe_language="zh",
            need_word_time_stamp=True,
        )

    @pytest.mark.skipif(
        not Path("resource/bin/faster-whisper-xxl").exists()
        and not Path("resource/bin/faster-whisper-xxl.exe").exists(),
        reason="FasterWhisper executable not found - 需要本地 FasterWhisper 可执行文件",
    )
    def test_transcribe_audio_with_faster_whisper(
        self,
        sample_audio_path: str,
        output_dir: str,
        base_config: TranscribeConfig,
        qapp,
    ):
        """Test transcription using FasterWhisper model with audio file."""
        output_path = os.path.join(output_dir, "transcript_audio.srt")
        task = TranscribeTask(
            file_path=sample_audio_path,
            transcribe_config=base_config,
            output_path=output_path,
        )

        thread = TranscriptThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=60000)

        assert results["error"] is None, f"Thread failed: {results.get('error')}"
        assert results["finished"], "Thread did not finish"
        assert Path(output_path).exists(), f"Output file not created: {output_path}"

    @pytest.mark.skipif(
        not Path("resource/bin/faster-whisper-xxl").exists()
        and not Path("resource/bin/faster-whisper-xxl.exe").exists(),
        reason="FasterWhisper executable not found - 需要本地 FasterWhisper 可执行文件",
    )
    def test_transcribe_video_with_faster_whisper(
        self,
        sample_video_path: str,
        output_dir: str,
        base_config: TranscribeConfig,
        qapp,
    ):
        """Test transcription using FasterWhisper model with video file."""
        output_path = os.path.join(output_dir, "transcript_video.srt")
        task = TranscribeTask(
            file_path=sample_video_path,
            transcribe_config=base_config,
            output_path=output_path,
        )

        thread = TranscriptThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=60000)

        assert results["error"] is None, f"Thread failed: {results.get('error')}"
        assert results["finished"], "Thread did not finish"
        assert Path(output_path).exists(), f"Output file not created: {output_path}"

    def test_transcribe_missing_video(
        self, output_dir: str, base_config: TranscribeConfig, qapp
    ):
        """Test transcription with missing video file."""
        output_path = os.path.join(output_dir, "transcript.srt")
        task = TranscribeTask(
            file_path="/nonexistent/video.mp4",
            transcribe_config=base_config,
            output_path=output_path,
        )

        thread = TranscriptThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is not None, "Expected error for missing video"
        assert not results["finished"], "Thread should not finish successfully"

    def test_transcribe_empty_path(
        self, output_dir: str, base_config: TranscribeConfig, qapp
    ):
        """Test transcription with empty file path."""
        output_path = os.path.join(output_dir, "transcript.srt")
        task = TranscribeTask(
            file_path="",
            transcribe_config=base_config,
            output_path=output_path,
        )

        thread = TranscriptThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is not None, "Expected error for empty path"
