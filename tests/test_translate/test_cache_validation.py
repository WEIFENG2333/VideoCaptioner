"""Tests for cache validation functionality."""

from typing import Any

import pytest

from app.core.utils.cache import (
    DiskCache,
    cached,
    disable_cache,
    enable_cache,
    validate_not_empty,
    validate_not_none,
    validate_openai_response,
)


@pytest.fixture(autouse=True)
def ensure_cache_enabled():
    """Ensure cache is enabled before each test."""
    enable_cache()
    yield
    enable_cache()  # Re-enable after test


@pytest.fixture
def test_cache(tmp_path) -> DiskCache:
    """Create a temporary cache instance for testing."""
    cache = DiskCache(str(tmp_path / "test_cache"))
    yield cache
    cache.close()


class TestCacheValidation:
    """Test suite for cache validation features."""

    def test_exception_not_cached(self, test_cache: DiskCache) -> None:
        """Test that exceptions are never cached."""
        call_count = 0

        @cached(cache_instance=test_cache)
        def failing_function() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        # First call - should raise exception
        with pytest.raises(ValueError, match="Test error"):
            failing_function()

        # Second call - should raise exception again (not cached)
        with pytest.raises(ValueError, match="Test error"):
            failing_function()

        # Both calls should have executed the function
        assert call_count == 2

    def test_validate_none_not_cached(self, test_cache: DiskCache) -> None:
        """Test that None results are not cached with validate_not_none."""
        call_count = 0

        @cached(cache_instance=test_cache, validate=validate_not_none)
        def returns_none() -> None:
            nonlocal call_count
            call_count += 1
            return None

        # First call
        result1 = returns_none()
        assert result1 is None

        # Second call - should execute again (not cached)
        result2 = returns_none()
        assert result2 is None

        # Both calls should have executed
        assert call_count == 2

    def test_validate_empty_not_cached(self, test_cache: DiskCache) -> None:
        """Test that empty results are not cached with validate_not_empty."""
        call_count = 0

        @cached(cache_instance=test_cache, validate=validate_not_empty)
        def returns_empty() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""
            return "success"

        # First call - returns empty string
        result1 = returns_empty()
        assert result1 == ""

        # Second call - should execute again and return success
        result2 = returns_empty()
        assert result2 == "success"

        # Both calls should have executed
        assert call_count == 2

    def test_custom_validator(self, test_cache: DiskCache) -> None:
        """Test custom validation function."""
        call_count = 0

        def validate_positive(result: int) -> bool:
            return result > 0

        @cached(cache_instance=test_cache, validate=validate_positive)
        def get_number() -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return -1  # Invalid
            return 42  # Valid

        # First call - returns negative (not cached)
        result1 = get_number()
        assert result1 == -1

        # Second call - should execute again
        result2 = get_number()
        assert result2 == 42

        # Third call - should use cache
        result3 = get_number()
        assert result3 == 42

        # Should have called function twice (third time used cache)
        assert call_count == 2

    def test_valid_result_cached(self, test_cache: DiskCache) -> None:
        """Test that valid results are cached."""
        call_count = 0

        @cached(cache_instance=test_cache, validate=validate_not_empty)
        def returns_valid() -> str:
            nonlocal call_count
            call_count += 1
            return "valid result"

        # First call
        result1 = returns_valid()
        assert result1 == "valid result"

        # Second call - should use cache
        result2 = returns_valid()
        assert result2 == "valid result"

        # Function should only be called once
        assert call_count == 1

    def test_no_validator_caches_all(self, test_cache: DiskCache) -> None:
        """Test that without validator, all non-exception results are cached."""
        call_count = 0

        @cached(cache_instance=test_cache)
        def returns_none_or_value() -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return "value"

        # First call - returns None
        result1 = returns_none_or_value()
        assert result1 is None

        # Second call - should use cached None
        result2 = returns_none_or_value()
        assert result2 is None

        # Function should only be called once (None was cached)
        assert call_count == 1

    def test_validate_openai_response(self) -> None:
        """Test OpenAI response validator."""

        # Mock valid response
        class MockChoice:
            def __init__(self, content: str):
                self.message = type("Message", (), {"content": content})()

        class MockResponse:
            def __init__(self, content: str):
                self.choices = [MockChoice(content)]

        # Valid response
        valid_response = MockResponse("translated text")
        assert validate_openai_response(valid_response) is True

        # Invalid responses
        assert validate_openai_response(None) is False
        assert validate_openai_response({}) is False

        empty_response = MockResponse("")
        assert validate_openai_response(empty_response) is False

        no_choices = type("Response", (), {"choices": []})()
        assert validate_openai_response(no_choices) is False

    def test_cache_disabled_ignores_validation(self, test_cache: DiskCache) -> None:
        """Test that validation is bypassed when cache is disabled."""
        call_count = 0

        @cached(cache_instance=test_cache, validate=validate_not_none)
        def returns_none() -> None:
            nonlocal call_count
            call_count += 1
            return None

        # Disable cache
        disable_cache()

        # First call
        result1 = returns_none()
        assert result1 is None

        # Second call - should execute again (cache disabled)
        result2 = returns_none()
        assert result2 is None

        # Both calls should have executed
        assert call_count == 2

        # Re-enable cache
        enable_cache()

    def test_validator_exception_prevents_caching(self, test_cache: DiskCache) -> None:
        """Test that validator exceptions prevent caching."""
        call_count = 0

        def failing_validator(result: Any) -> bool:
            raise RuntimeError("Validator error")

        @cached(cache_instance=test_cache, validate=failing_validator)
        def get_value() -> str:
            nonlocal call_count
            call_count += 1
            return "value"

        # First call
        result1 = get_value()
        assert result1 == "value"

        # Second call - should execute again (validation failed)
        result2 = get_value()
        assert result2 == "value"

        # Both calls should have executed
        assert call_count == 2
