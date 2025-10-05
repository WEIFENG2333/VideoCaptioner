"""Tests for VideoInfoThread."""

import pytest

from app.thread.video_info_thread import VideoInfoThread
from tests.test_thread.conftest import run_thread_with_timeout


@pytest.mark.integration
class TestVideoInfoThread:
    """Test suite for VideoInfoThread."""

    def test_get_video_info_missing_file(self, qapp):
        """Test getting info for missing video file."""
        thread = VideoInfoThread("/nonexistent/video.mp4")
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert results["error"] is not None, "Expected error for missing video"

    def test_get_video_info_invalid_file(self, tmp_path, qapp):
        """Test getting info for invalid video file."""
        invalid_file = tmp_path / "invalid.mp4"
        invalid_file.write_text("not a video file")

        thread = VideoInfoThread(str(invalid_file))
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        # May or may not error depending on ffmpeg behavior
        # Just ensure thread completes without hanging
        assert results["finished"] or results["error"] is not None
