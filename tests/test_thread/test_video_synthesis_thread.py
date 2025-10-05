"""Tests for VideoSynthesisThread."""

import os
from pathlib import Path

import pytest

from app.core.entities import SynthesisConfig, SynthesisTask
from app.thread.video_synthesis_thread import VideoSynthesisThread
from tests.test_thread.conftest import run_thread_with_timeout


@pytest.mark.integration
class TestVideoSynthesisThread:
    """Test suite for VideoSynthesisThread."""

    @pytest.fixture
    def base_config(self) -> SynthesisConfig:
        """Create base synthesis configuration."""
        return SynthesisConfig(
            soft_subtitle=False,
            need_video=True,
        )

    def test_synthesize_skip_video(
        self,
        sample_video_path: str,
        sample_subtitle_path: str,
        output_dir: str,
        base_config: SynthesisConfig,
        qapp,
    ):
        """Test synthesis with need_video=False."""
        base_config.need_video = False
        output_path = os.path.join(output_dir, "output_skip.mp4")
        task = SynthesisTask(
            video_path=sample_video_path,
            subtitle_path=sample_subtitle_path,
            synthesis_config=base_config,
            output_path=output_path,
        )

        thread = VideoSynthesisThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is None, "Thread should not error when skipping video"
        assert results["finished"], "Thread should finish successfully"
        assert not Path(output_path).exists(), "Output file should not be created"

    def test_synthesize_missing_video(
        self,
        sample_subtitle_path: str,
        output_dir: str,
        base_config: SynthesisConfig,
        qapp,
    ):
        """Test synthesis with missing video file."""
        output_path = os.path.join(output_dir, "output.mp4")
        task = SynthesisTask(
            video_path="/nonexistent/video.mp4",
            subtitle_path=sample_subtitle_path,
            synthesis_config=base_config,
            output_path=output_path,
        )

        thread = VideoSynthesisThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is not None, "Expected error for missing video"

    def test_synthesize_empty_paths(
        self, output_dir: str, base_config: SynthesisConfig, qapp
    ):
        """Test synthesis with empty paths."""
        output_path = os.path.join(output_dir, "output.mp4")
        task = SynthesisTask(
            video_path="",
            subtitle_path="",
            synthesis_config=base_config,
            output_path=output_path,
        )

        thread = VideoSynthesisThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is not None, "Expected error for empty paths"
