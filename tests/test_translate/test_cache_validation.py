"""Tests for cache validation functionality."""

from typing import Any

import pytest
from diskcache import Cache

from app.core.utils.cache import (
    disable_cache,
    enable_cache,
    memoize,
)


@pytest.fixture(autouse=True)
def ensure_cache_enabled():
    """Ensure cache is enabled before each test."""
    enable_cache()
    yield
    enable_cache()  # Re-enable after test


@pytest.fixture
def test_cache(tmp_path) -> Cache:
    """Create a temporary cache instance for testing."""
    cache = Cache(str(tmp_path / "test_cache"))
    yield cache
    cache.close()


class TestCacheValidation:
    """Test suite for cache validation features."""

    def test_exception_not_cached(self, test_cache: Cache) -> None:
        """Test that exceptions are never cached."""
        call_count = 0

        @memoize(test_cache)
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

    def test_validate_none_not_cached(self, test_cache: Cache) -> None:
        """Test that None results are not cached when validation raises exception."""
        call_count = 0

        @memoize(test_cache)
        def returns_none_then_raises() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Invalid None result")
            return None

        # First call - raises exception (not cached)
        with pytest.raises(ValueError, match="Invalid None result"):
            returns_none_then_raises()

        # Second call - should execute again and return None
        result = returns_none_then_raises()
        assert result is None

        # Both calls should have executed
        assert call_count == 2

    def test_validate_empty_not_cached(self, test_cache: Cache) -> None:
        """Test that empty results raise exception and are not cached."""
        call_count = 0

        @memoize(test_cache)
        def returns_empty_then_success() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Empty result not allowed")
            return "success"

        # First call - raises exception (not cached)
        with pytest.raises(ValueError, match="Empty result not allowed"):
            returns_empty_then_success()

        # Second call - should execute again and return success
        result = returns_empty_then_success()
        assert result == "success"

        # Both calls should have executed
        assert call_count == 2

    def test_custom_validator(self, test_cache: Cache) -> None:
        """Test custom validation with exception for invalid results."""
        call_count = 0

        @memoize(test_cache)
        def get_number() -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Negative number not allowed")
            return 42

        # First call - raises exception (not cached)
        with pytest.raises(ValueError, match="Negative number not allowed"):
            get_number()

        # Second call - should execute again and return valid result
        result2 = get_number()
        assert result2 == 42

        # Third call - should use cache
        result3 = get_number()
        assert result3 == 42

        # Should have called function twice (third time used cache)
        assert call_count == 2

    def test_valid_result_cached(self, test_cache: Cache) -> None:
        """Test that valid results are cached."""
        call_count = 0

        @memoize(test_cache)
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

    def test_no_validator_caches_all(self, test_cache: Cache) -> None:
        """Test that all non-exception results are cached, including None."""
        call_count = 0

        @memoize(test_cache)
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

    def test_cache_disabled_bypasses_cache(self, test_cache: Cache) -> None:
        """Test that cache is bypassed when globally disabled."""
        call_count = 0

        @memoize(test_cache)
        def returns_value() -> str:
            nonlocal call_count
            call_count += 1
            return "value"

        # Disable cache
        disable_cache()

        # First call
        result1 = returns_value()
        assert result1 == "value"

        # Second call - should execute again (cache disabled)
        result2 = returns_value()
        assert result2 == "value"

        # Both calls should have executed
        assert call_count == 2

        # Re-enable cache
        enable_cache()
