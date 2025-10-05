"""Thread module test fixtures and utilities."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def sample_audio_path() -> str:
    """Return path to sample audio file in fixtures."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    audio_file = fixtures_dir / "audio" / "zh.mp3"
    if not audio_file.exists():
        pytest.skip(f"Sample audio not found: {audio_file}")
    return str(audio_file)


@pytest.fixture
def sample_video_path(tmp_path: Path, sample_audio_path: str) -> str:
    """Create a simple test video from audio file using ffmpeg."""
    output_video = tmp_path / "test_video.mp4"

    # Create a simple video with a solid color and the audio
    cmd = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=1280x720:d=5",
        "-i",
        sample_audio_path,
        "-shortest",
        "-y",
        str(output_video),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(output_video)
    except subprocess.CalledProcessError:
        pytest.skip("Failed to create test video with ffmpeg")


@pytest.fixture
def sample_subtitle_path(tmp_path: Path) -> str:
    """Return path to sample subtitle file in fixtures."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    subtitle_file = fixtures_dir / "subtitle" / "sample_en.srt"
    if not subtitle_file.exists():
        pytest.skip(f"Sample subtitle not found: {subtitle_file}")
    return str(subtitle_file)


@pytest.fixture
def output_dir(tmp_path: Path) -> Generator[str, None, None]:
    """Create and cleanup temporary output directory."""
    output_path = tmp_path / "output"
    output_path.mkdir(exist_ok=True)
    yield str(output_path)


def run_thread_with_timeout(thread, timeout_ms: int = 30000) -> dict:
    """Run QThread with timeout and collect results.

    Args:
        thread: QThread instance to run
        timeout_ms: Timeout in milliseconds (default 30s)

    Returns:
        dict with keys: 'finished', 'error', 'output' (if available)
    """
    result = {"finished": False, "error": None, "output": None}
    loop = QEventLoop()

    def on_finished(task=None):
        result["finished"] = True
        if task:
            result["output"] = getattr(task, "output_path", None)
        loop.quit()

    def on_error(error_msg):
        result["error"] = error_msg
        loop.quit()

    def on_timeout():
        result["error"] = "Thread execution timed out"
        thread.terminate()
        loop.quit()

    thread.finished.connect(on_finished)
    thread.error.connect(on_error)

    timer = QTimer()
    timer.timeout.connect(on_timeout)
    timer.setSingleShot(True)
    timer.start(timeout_ms)

    thread.start()
    loop.exec_()
    timer.stop()

    return result
