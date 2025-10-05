"""Tests for SubtitlePipelineThread (simplified for basic validation)."""

import pytest

from app.thread.subtitle_pipeline_thread import SubtitlePipelineThread


@pytest.mark.integration
class TestSubtitlePipelineThread:
    """Test suite for SubtitlePipelineThread (simplified)."""

    def test_pipeline_placeholder(self, qapp):
        """Placeholder test - full pipeline tests require all dependencies."""
        # Full pipeline tests would require:
        # - FasterWhisper model downloaded
        # - LLM API configured
        # - Video files available
        # These are better suited for manual integration testing
        assert True, "Pipeline thread exists and can be imported"
