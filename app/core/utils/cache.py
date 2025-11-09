"""Disk cache utility for API responses and computation results.

This module provides a simple interface for caching using diskcache.
Can be used by translation, ASR, and other modules that need caching.
"""

import functools
import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from diskcache import Cache

from app.config import CACHE_PATH

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


# Predefined cache instances for common use cases
_llm_cache = Cache(str(CACHE_PATH / "llm_translation"))
_asr_cache = Cache(str(CACHE_PATH / "asr_results"), tag_index=True)
_tts_cache = Cache(str(CACHE_PATH / "tts_audio"))
_translate_cache = Cache(str(CACHE_PATH / "translate_results"))
_version_state_cache = Cache(str(CACHE_PATH / "version_state"))


def get_llm_cache() -> Cache:
    """Get LLM translation cache instance."""
    return _llm_cache


def get_asr_cache() -> Cache:
    """Get ASR results cache instance."""
    return _asr_cache


def get_translate_cache() -> Cache:
    """Get translate cache instance."""
    return _translate_cache


def get_tts_cache() -> Cache:
    """Get TTS audio cache instance."""
    return _tts_cache


def get_version_state_cache() -> Cache:
    """Get version check state cache instance."""
    return _version_state_cache


def memoize(cache_instance: Cache, **kwargs):
    """Decorator to cache function results with global switch support.

    This is a thin wrapper around diskcache.Cache.memoize() that respects
    the global cache enable/disable setting.

    Args:
        cache_instance: Cache instance to use (from get_llm_cache(), etc.)
        **kwargs: Arguments passed to cache.memoize() (expire, typed, etc.)

    Returns:
        Decorated function

    Examples:
        @memoize(get_llm_cache(), expire=3600, typed=True)
        def call_api(prompt: str):
            response = client.chat.completions.create(...)
            if not response.choices:
                raise ValueError("Invalid response")  # Exceptions are not cached
            return response
    """

    def decorator(func):
        memoized_func = cache_instance.memoize(**kwargs)(func)

        @functools.wraps(func)
        def wrapper(*args, **kw):
            if _cache_enabled:
                return memoized_func(*args, **kw)
            return func(*args, **kw)

        return wrapper

    return decorator


def generate_cache_key(data: Any) -> str:
    """Generate cache key from data (supports dataclasses, dicts, lists).

    Args:
        data: Data to generate key from

    Returns:
        SHA256 hash of the data
    """

    def _serialize(obj: Any) -> Any:
        """Recursively serialize object to JSON-serializable format"""
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)  # type: ignore
        elif isinstance(obj, list):
            return [_serialize(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: _serialize(v) for k, v in obj.items()}
        else:
            return obj

    serialized_data = _serialize(data)
    data_str = json.dumps(serialized_data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data_str.encode()).hexdigest()
