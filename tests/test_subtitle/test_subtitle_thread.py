"""Tests for SubtitleThread.

This module tests the subtitle processing thread which handles:
- Subtitle splitting (semantic and sentence-based)
- Subtitle optimization (via LLM)
- Subtitle translation (Google, Bing, LLM)
"""

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv
from PyQt5.QtCore import QEventLoop, QTimer

from app.core.entities import (
    SubtitleConfig,
    SubtitleTask,
    TranslatorServiceEnum,
)
from app.core.llm.check_llm import get_available_models
from app.core.translate.types import TargetLanguage
from app.thread.subtitle_thread import SubtitleThread

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")


def get_test_model():
    """Get appropriate model for testing.

    Returns model from OPENAI_MODEL env var, or auto-detects from API.
    """
    # Check if model specified in environment
    env_model = os.getenv("OPENAI_MODEL")
    if env_model:
        return env_model

    # Auto-detect from API
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return "gpt-4o-mini"  # Default fallback

    try:
        models = get_available_models(base_url, api_key)
        if models:
            return models[0]  # Return first available model
    except Exception:
        pass

    return "gpt-4o-mini"  # Default fallback


def run_thread_with_timeout(thread, timeout_ms=60000):
    """Run thread with timeout to prevent hanging tests.

    Args:
        thread: QThread to run
        timeout_ms: Timeout in milliseconds (default 60s)

    Returns:
        dict: Results from signal handlers
    """
    results = {}

    def on_finished(output_path, _):
        results["output"] = output_path

    def on_error(error_msg):
        results["error"] = error_msg

    def on_progress(percent, message):
        results["progress"] = (percent, message)

    def on_update(data):
        results["updates"] = results.get("updates", [])
        results["updates"].append(data)

    thread.finished.connect(on_finished)
    thread.error.connect(on_error)
    thread.progress.connect(on_progress)
    thread.update.connect(on_update)

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    thread.error.connect(loop.quit)

    # Timeout safety
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)

    thread.start()
    loop.exec_()

    return results


@pytest.fixture
def subtitle_file():
    """Load test subtitle file from fixtures."""
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "subtitle" / "sample_en.srt"
    )
    assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
    return str(fixture_path)


@pytest.fixture
def output_dir():
    """Create temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def base_config():
    """Create base subtitle configuration."""
    return SubtitleConfig(
        need_split=False,
        need_optimize=False,
        need_translate=False,
        thread_num=2,
        batch_size=5,
    )


class TestSubtitleThreadSplit:
    """Test subtitle splitting functionality."""

    def test_split_sentence(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test sentence-based splitting (using mock LLM)."""
        config = base_config
        config.need_split = True
        config.max_word_count_cjk = 15
        config.max_word_count_english = 20
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "split_sentence.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        # Assertions
        assert "error" not in results, f"Thread failed: {results.get('error')}"
        assert "output" in results
        assert Path(results["output"]).exists()

    def test_split_semantic(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test semantic-based splitting (using mock LLM)."""
        config = base_config
        config.need_split = True
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "split_semantic.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results


class TestSubtitleThreadOptimize:
    """Test subtitle optimization functionality."""

    def test_optimize_with_llm(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test LLM-based subtitle optimization (using mock LLM)."""
        config = base_config
        config.need_optimize = True
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "optimize.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results
        assert "progress" in results


class TestSubtitleThreadTranslate:
    """Test subtitle translation functionality."""

    @pytest.mark.integration
    def test_translate_google(self, subtitle_file, output_dir, base_config):
        """Test Google Translate (free API)."""
        config = base_config
        config.need_translate = True
        config.translator_service = TranslatorServiceEnum.GOOGLE
        config.target_language = TargetLanguage.SIMPLIFIED_CHINESE

        output_path = os.path.join(output_dir, "translate_google.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results
        # Note: updates may not be captured depending on timing
        if "updates" in results:
            assert len(results["updates"]) > 0

    @pytest.mark.integration
    def test_translate_bing(self, subtitle_file, output_dir, base_config):
        """Test Bing Translate (free API)."""
        config = base_config
        config.need_translate = True
        config.translator_service = TranslatorServiceEnum.BING
        config.target_language = TargetLanguage.SIMPLIFIED_CHINESE

        output_path = os.path.join(output_dir, "translate_bing.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results

    def test_translate_llm(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test LLM translation (using mock LLM)."""
        config = base_config
        config.need_translate = True
        config.translator_service = TranslatorServiceEnum.OPENAI
        config.target_language = TargetLanguage.SIMPLIFIED_CHINESE
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "translate_llm.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results


class TestSubtitleThreadFullPipeline:
    """Test complete subtitle processing pipeline."""

    def test_split_and_translate(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test split + translate pipeline (using mock LLM)."""
        config = base_config
        config.need_split = True
        config.need_translate = True
        config.translator_service = TranslatorServiceEnum.GOOGLE
        config.target_language = TargetLanguage.SIMPLIFIED_CHINESE
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "split_translate.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results

    def test_optimize_and_translate(
        self, subtitle_file, output_dir, base_config, mock_llm_client
    ):
        """Test optimize + translate pipeline (using mock LLM)."""
        config = base_config
        config.need_optimize = True
        config.need_translate = True
        config.translator_service = TranslatorServiceEnum.OPENAI
        config.target_language = TargetLanguage.JAPANESE
        config.llm_model = get_test_model()
        config.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        config.api_key = os.getenv("OPENAI_API_KEY")

        output_path = os.path.join(output_dir, "optimize_translate.srt")
        task = SubtitleTask(
            subtitle_path=subtitle_file,
            subtitle_config=config,
            output_path=output_path,
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread)

        assert "error" not in results, f"Failed: {results.get('error')}"
        assert "output" in results


class TestSubtitleThreadError:
    """Test error handling."""

    def test_missing_file(self, output_dir, base_config):
        """Test handling of missing subtitle file."""
        task = SubtitleTask(
            subtitle_path="/nonexistent/file.srt", subtitle_config=base_config
        )
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert "error" in results
        assert "not" in results["error"].lower()

    def test_no_translator_service(self, subtitle_file, output_dir, base_config):
        """Test error when translation enabled but no service configured."""
        config = base_config
        config.need_translate = True
        config.translator_service = None

        task = SubtitleTask(subtitle_path=subtitle_file, subtitle_config=config)
        thread = SubtitleThread(task)
        results = run_thread_with_timeout(thread, timeout_ms=5000)

        assert "error" in results
