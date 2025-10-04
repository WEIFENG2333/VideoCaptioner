"""ASR-specific fixtures and utilities for integration tests.

This conftest.py provides ASR-specific fixtures that are only needed for ASR tests.
General fixtures are available from the root-level tests/conftest.py.
"""

from pathlib import Path

import pytest

# ============================================================================
# ASR-Specific Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def test_audio_path() -> Path:
    """Get path to Chinese test audio file for ASR tests (default).

    Uses the Chinese speech audio file: tests/fixtures/audio/zh.mp3
    Session-scoped to avoid repeated file system checks.

    Returns:
        Path to the Chinese test audio file

    Raises:
        FileNotFoundError: If zh.mp3 doesn't exist
    """
    audio_path = Path(__file__).parent.parent / "fixtures" / "audio" / "zh.mp3"

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Test audio file not found: {audio_path}\n"
            "Please ensure zh.mp3 exists in tests/fixtures/audio/ directory"
        )

    return audio_path


@pytest.fixture(scope="session")
def test_audio_path_zh() -> Path:
    """Get path to Chinese test audio file for ASR tests.

    Uses: tests/fixtures/audio/zh.mp3
    Session-scoped to avoid repeated file system checks.

    Returns:
        Path to the Chinese test audio file

    Raises:
        FileNotFoundError: If zh.mp3 doesn't exist
    """
    audio_path = Path(__file__).parent.parent / "fixtures" / "audio" / "zh.mp3"

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Test audio file not found: {audio_path}\n"
            "Please ensure zh.mp3 exists in tests/fixtures/audio/ directory"
        )

    return audio_path


@pytest.fixture(scope="session")
def test_audio_path_en() -> Path:
    """Get path to English test audio file for ASR tests.

    Uses: tests/fixtures/audio/en.mp3
    Session-scoped to avoid repeated file system checks.

    Returns:
        Path to the English test audio file

    Raises:
        FileNotFoundError: If en.mp3 doesn't exist
    """
    audio_path = Path(__file__).parent.parent / "fixtures" / "audio" / "en.mp3"

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Test audio file not found: {audio_path}\n"
            "Please ensure en.mp3 exists in tests/fixtures/audio/ directory"
        )

    return audio_path


def assert_asr_result_valid(result, min_segments: int = 0) -> None:
    """Validate ASR result structure and content.

    Checks that:
    - Result is not None
    - Has minimum number of segments
    - All segments have non-empty text
    - All segments have valid timestamps (start >= 0, end > start)

    Args:
        result: ASRData object returned from ASR service
        min_segments: Minimum number of segments expected (default 0)

    Raises:
        AssertionError: If validation fails
    """
    assert result is not None, "ASR result should not be None"
    assert (
        len(result.segments) >= min_segments
    ), f"Expected at least {min_segments} segments, got {len(result.segments)}"

    for i, seg in enumerate(result.segments):
        assert seg.text, f"Segment {i} should have non-empty text"
        assert seg.start_time >= 0, f"Segment {i} start_time should be non-negative"
        assert (
            seg.end_time > seg.start_time
        ), f"Segment {i} end_time should be greater than start_time"
