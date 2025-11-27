"""Gemini LLM client using google-genai."""

import os
import re
import threading
from typing import Any, List, Optional

from google import genai
from google.genai import types
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.utils.cache import get_llm_cache, memoize
from app.core.utils.logger import setup_logger

_global_api_key: Optional[str] = None
_client_lock = threading.Lock()

logger = setup_logger("gemini_client")


def configure_gemini(api_key: Optional[str] = None) -> str:
    """Configure Gemini API key (thread-safe).

    Args:
        api_key: API key string, if None will read from Gemini_API_Key env var

    Returns:
        The API key being used

    Raises:
        ValueError: If API key not provided and Gemini_API_Key env var not set
    """
    global _global_api_key

    if _global_api_key is None:
        with _client_lock:
            if _global_api_key is None:
                if api_key is None:
                    api_key = os.getenv("GEMINI_API_KEY", "").strip()

                if not api_key:
                    raise ValueError(
                        "Gemini_API_Key environment variable must be set"
                    )

                # Store the API key for later use
                _global_api_key = api_key

    return _global_api_key


def before_sleep_log(retry_state: RetryCallState) -> None:
    logger.warning(
        "Rate Limit Error, sleeping and retrying... Please lower your thread concurrency or use better Gemini API."
    )


@memoize(get_llm_cache(), expire=3600, typed=True)
@retry(
    stop=stop_after_attempt(10),
    wait=wait_random_exponential(multiplier=1, min=5, max=60),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log,
)
def call_gemini(
    messages: List[dict],
    model: str,
    temperature: float = 0.7,
    system_instruction: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Call Gemini API with automatic caching and multi-turn conversation support.

    Configured via GOOGLE_API_KEY environment variable.

    Args:
        messages: Chat messages list with role and content
                 (roles: "user" and "model")
        model: Model name (e.g., "gemini-2.0-flash", "gemini-1.5-pro")
        temperature: Sampling temperature (0.0 to 2.0)
        system_instruction: System instruction for the model
        **kwargs: Additional parameters for API call

    Returns:
        Response object with .text attribute

    Raises:
        ValueError: If response is invalid or messages are malformed
    """
    # Ensure API key is configured
    api_key = configure_gemini()

    # Validate messages format
    if not messages:
        raise ValueError("Messages list cannot be empty")

    # Extract system instruction from messages if present
    actual_system_instruction = system_instruction
    message_list = list(messages)

    # Check if first message is system instruction in old format
    if (
        message_list
        and message_list[0].get("role") == "system"
        and not system_instruction
    ):
        actual_system_instruction = message_list[0].get("content")
        message_list = message_list[1:]

    # Create client with API key
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=60 * 1000,
            retry_options=types.HttpRetryOptions(
                attempts=5,
                initial_delay=30,
                max_delay=30
            )
        )
    )

    # Get the final message content
    if message_list:
        final_content = message_list[-1].get("content", "")
    else:
        raise ValueError("No messages provided")

    # Use generate_content with just the string content
    model_name = re.sub(r"models/", "", model, 0, re.MULTILINE)
    thinking_budget = -1 if model_name == "gemini-2.5-pro" else 0
    response = client.models.generate_content(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY", threshold="BLOCK_NONE"),
            ],
            # Turn off thinking:
            # thinking_config=types.ThinkingConfig(thinking_budget=0)
            # Turn on dynamic thinking:
            # thinking_config=types.ThinkingConfig(thinking_budget=-1)
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget)
        ),
        contents=final_content,
    )

    # Validate response
    if not response or not hasattr(response, "text") or not response.text:
        raise ValueError("Invalid Gemini API response: empty text content")

    return response
