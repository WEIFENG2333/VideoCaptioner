"""Disk cache utility for API responses and computation results.

This module provides a simple interface for caching using diskcache.
Can be used by translation, ASR, and other modules that need caching.
"""

import functools
import hashlib
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, Optional

from diskcache import Cache

from app.config import CACHE_PATH

logger = logging.getLogger("cache")

# Global cache switch
_cache_enabled = True


def enable_cache() -> None:
    """Enable caching globally."""
    global _cache_enabled
    _cache_enabled = True


def disable_cache() -> None:
    """Disable caching globally."""
    global _cache_enabled
    _cache_enabled = False


def is_cache_enabled() -> bool:
    """Check if caching is enabled."""
    return _cache_enabled


class DiskCache:
    """Disk-based cache with TTL support."""

    # Sentinel value to distinguish "not in cache" from "cached None"
    _MISSING = object()

    def __init__(self, cache_name: str):
        """Initialize cache.

        Args:
            cache_name: Name of the cache subdirectory (e.g., 'llm', 'asr')
        """
        self.cache_dir = CACHE_PATH / cache_name
        self._cache = Cache(str(self.cache_dir))

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Get value from cache.

        Args:
            key: Cache key
            default: Value to return if key not found (defaults to sentinel)

        Returns:
            Cached value, or default if not found/expired
        """
        if not _cache_enabled:
            return default
        return self._cache.get(key, default=default)

    def set(self, key: str, value: Any, expire: Optional[int] = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            expire: TTL in seconds (None = never expires)
        """
        self._cache.set(key, value, expire=expire)

    def delete(self, key: str) -> None:
        """Delete value from cache.

        Args:
            key: Cache key
        """
        self._cache.delete(key)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def close(self) -> None:
        """Close cache connection."""
        self._cache.close()

    @staticmethod
    def _serialize_for_key(obj: Any) -> Any:
        """递归序列化对象为可 JSON 序列化的格式

        Args:
            obj: 要序列化的对象

        Returns:
            可 JSON 序列化的对象
        """
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)  # type: ignore
        elif isinstance(obj, list):
            return [DiskCache._serialize_for_key(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: DiskCache._serialize_for_key(v) for k, v in obj.items()}
        else:
            return obj

    @staticmethod
    def generate_key(data: Any) -> str:
        """Generate cache key from data dictionary.

        Args:
            data: Dictionary to generate key from (supports dataclasses)

        Returns:
            SHA256 hash of the data
        """
        # 序列化 dataclass 为字典
        serialized_data = DiskCache._serialize_for_key(data)
        data_str = json.dumps(serialized_data, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()


# Predefined cache instances for common use cases
_llm_cache = DiskCache("llm_translation")
_asr_cache = DiskCache("asr_results")
_tts_cache = DiskCache("tts_audio")
_translate_cache = DiskCache("translate_results")


def get_llm_cache() -> DiskCache:
    """Get LLM translation cache instance."""
    return _llm_cache


def get_asr_cache() -> DiskCache:
    """Get ASR results cache instance."""
    return _asr_cache


def get_translate_cache() -> DiskCache:
    """Get translate cache instance."""
    return _translate_cache


def get_tts_cache() -> DiskCache:
    """Get TTS audio cache instance."""
    return _tts_cache


# Predefined validators for common use cases
def validate_not_none(result: Any) -> bool:
    """Validate that result is not None.

    Args:
        result: Function result to validate

    Returns:
        True if result is not None
    """
    return result is not None


def validate_not_empty(result: Any) -> bool:
    """Validate that result is not empty.

    Works with strings, lists, dicts, etc.

    Args:
        result: Function result to validate

    Returns:
        True if result is truthy (not None, not empty, not False)
    """
    return bool(result)


def validate_openai_response(response: Any) -> bool:
    """Validate OpenAI ChatCompletion API response.

    Checks that the response has choices with non-empty content.

    Args:
        response: OpenAI ChatCompletion API response object

    Returns:
        True if response is valid and has non-empty content
    """
    try:
        return bool(
            response
            and hasattr(response, "choices")
            and response.choices
            and len(response.choices) > 0
            and hasattr(response.choices[0], "message")
            and response.choices[0].message.content
        )
    except (IndexError, AttributeError):
        return False


def validate_has_segments(result: dict) -> bool:
    """Validate that ASR result has segments.

    Args:
        result: ASR result dictionary

    Returns:
        True if result has non-empty segments list
    """
    return bool(result and result.get("segments"))


def cached(
    cache_instance: DiskCache,
    ttl: Optional[int] = None,
    validate: Optional[Callable[[Any], bool]] = None,
) -> Callable:
    """Decorator to cache function results with validation.

    Exceptions are never cached and will propagate normally.
    Results are only cached if the validate function returns True (or if no validate function is provided).

    Args:
        cache_instance: DiskCache instance to use
        ttl: Cache TTL in seconds (None = never expires)
        validate: Optional validation function. Takes the result as input and returns True if it should be cached.
                 If None, all non-exception results are cached.

    Returns:
        Decorated function

    Examples:
        # Cache all results
        @cached(get_llm_cache(), ttl=3600)
        def translate(self, text: str) -> str:
            return call_api(text)

        # Only cache valid responses
        @cached(
            get_llm_cache(),
            ttl=3600,
            validate=lambda r: r and hasattr(r, 'choices') and r.choices
        )
        def call_api(self, prompt: str):
            return self.client.chat.completions.create(...)
    """

    def decorator(func: Callable) -> Callable:
        import inspect

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Skip cache if disabled
            if not is_cache_enabled():
                return func(*args, **kwargs)

            # Get function signature and bind arguments
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Convert to dict, excluding 'self'
            key_data = {k: v for k, v in bound_args.arguments.items() if k != "self"}
            key_data["func"] = func.__name__

            cache_key = cache_instance.generate_key(key_data)

            # Check cache (use sentinel to distinguish None from missing)
            cached_result = cache_instance.get(cache_key)
            is_cache_hit = cached_result is not DiskCache._MISSING
            if is_cache_hit:
                logger.debug(f"Cache hit for {func.__name__}: {cache_key[:16]}...")
                return cached_result

            # Call function (exceptions will propagate and not be cached)
            result = func(*args, **kwargs)

            # Validate result before caching
            should_cache = True
            if validate is not None:
                try:
                    should_cache = validate(result)
                except Exception as e:
                    logger.warning(
                        f"Validation function failed for {func.__name__}: {e}"
                    )
                    should_cache = False

            # Cache only if validation passed
            if should_cache:
                cache_instance.set(cache_key, result, expire=ttl)
                logger.debug(f"Cached result for {func.__name__}: {cache_key[:16]}...")
            else:
                logger.debug(
                    f"Result not cached (validation failed) for {func.__name__}"
                )

            return result

        return wrapper

    return decorator
