"""Unified LLM client for the application."""

import os
import threading
from typing import Any, List, Optional

from openai import OpenAI

from app.core.utils.cache import cached, get_llm_cache, validate_openai_response

_global_client: Optional[OpenAI] = None
_client_lock = threading.Lock()


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
                base_url = os.getenv("OPENAI_BASE_URL")
                api_key = os.getenv("OPENAI_API_KEY")

                if not base_url or not api_key:
                    raise ValueError(
                        "OPENAI_BASE_URL and OPENAI_API_KEY environment variables must be set"
                    )

                _global_client = OpenAI(base_url=base_url, api_key=api_key)

    return _global_client


@cached(cache_instance=get_llm_cache(), validate=validate_openai_response)
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
    """
    client = get_llm_client()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )

    return response
