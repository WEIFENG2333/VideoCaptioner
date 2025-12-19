"""Unified LLM client for the application."""

import os
import threading
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse

import openai
from openai import OpenAI
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.utils.cache import get_llm_cache, memoize
from app.core.utils.logger import setup_logger

_global_client: Optional[OpenAI] = None
_client_lock = threading.Lock()

logger = setup_logger("llm_client")


def normalize_base_url(base_url: str) -> str:
    """Normalize API base URL by ensuring /v1 suffix when needed.

    Handles various edge cases:
    - Removes leading/trailing whitespace
    - Only adds /v1 if domain has no path, or path is empty/root
    - Removes trailing slashes from /v1 (e.g., /v1/ -> /v1)
    - Preserves custom paths (e.g., /custom stays as /custom)

    Args:
        base_url: Raw base URL string

    Returns:
        Normalized base URL

    Examples:
        >>> normalize_base_url("https://api.openai.com")
        'https://api.openai.com/v1'
        >>> normalize_base_url("https://api.openai.com/v1/")
        'https://api.openai.com/v1'
        >>> normalize_base_url("https://api.openai.com/custom")
        'https://api.openai.com/custom'
        >>> normalize_base_url("  https://api.openai.com  ")
        'https://api.openai.com/v1'
    """
    url = base_url.strip()
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path:
        path = "/v1"

    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    return normalized


def get_llm_client() -> OpenAI:
    """Get global LLM client instance (thread-safe singleton).

    Returns:
        Global OpenAI client instance

    Raises:
        ValueError: If OPENAI_BASE_URL or OPENAI_API_KEY env vars not set
    """
    global _global_client

    if _global_client is None:
        with _client_lock:
            # Double-check locking pattern
            if _global_client is None:
                base_url = os.getenv("OPENAI_BASE_URL", "").strip()
                base_url = normalize_base_url(base_url)
                api_key = os.getenv("OPENAI_API_KEY", "").strip()

                if not base_url or not api_key:
                    raise ValueError(
                        "OPENAI_BASE_URL and OPENAI_API_KEY environment variables must be set"
                    )

                _global_client = OpenAI(base_url=base_url, api_key=api_key)

    return _global_client


def before_sleep_log(retry_state: RetryCallState) -> None:
    logger.warning(
        "Rate Limit Error, sleeping and retrying... Please lower your thread concurrency or use better OpenAI API."
    )


@memoize(get_llm_cache(), expire=3600, typed=True)
@retry(
    stop=stop_after_attempt(10),
    wait=wait_random_exponential(multiplier=1, min=5, max=60),
    retry=retry_if_exception_type(openai.RateLimitError),
    before_sleep=before_sleep_log,
)
def call_llm(
    messages: List[dict],
    model: str,
    temperature: float = 1,
    **kwargs: Any,
) -> Any:
    """Call LLM API with automatic caching.

    Uses global LLM client configured via environment variables.

    Args:
        messages: Chat messages list
        model: Model name
        temperature: Sampling temperature
        **kwargs: Additional parameters for API call

    Returns:
        API response object

    Raises:
        ValueError: If response is invalid (empty choices or content)
    """
    client = get_llm_client()

    response = client.chat.completions.create(
        model=model,
        messages=messages,  # pyright: ignore[reportArgumentType]
        temperature=temperature,
        **kwargs,
    )

    # Validate response (exceptions are not cached by diskcache)
    if not (
        response
        and hasattr(response, "choices")
        and response.choices
        and len(response.choices) > 0
        and hasattr(response.choices[0], "message")
        and response.choices[0].message.content
    ):
        raise ValueError("Invalid OpenAI API response: empty choices or content")

    return response
