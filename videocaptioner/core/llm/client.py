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

from videocaptioner.core.utils.cache import get_llm_cache, memoize
from videocaptioner.core.utils.logger import setup_logger

from . import free_model
from .request_logger import create_logging_http_client, log_llm_response

_global_client: Optional[OpenAI] = None
_client_fingerprint: Optional[tuple] = None  # 构建当前 client 所用的 (base_url, api_key)
_client_lock = threading.Lock()

logger = setup_logger("llm_client")


def normalize_base_url(base_url: str) -> str:
    """Normalize API base URL by ensuring /v1 suffix when needed."""
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
    """Get the LLM client, rebuilt when the active provider (base/key) changes.

    base/key 来自 OPENAI_BASE_URL/OPENAI_API_KEY 环境变量（各功能在调用前写入自己选的 provider
    凭证）。早期是「首次构建后永久缓存」的纯单例，会导致同进程内功能间串台：例如先跑字幕 LLM 翻译
    建好 client 后，再开实时字幕选另一个 provider，env 虽改了却仍复用旧 base/key，译文静默走错端点。
    这里按 (base, key) 指纹缓存：指纹不变直接复用，变了就重建——既保留单例复用，又能正确切换。"""
    global _global_client, _client_fingerprint

    base_url = normalize_base_url(os.getenv("OPENAI_BASE_URL", "").strip())
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    # 公益大模型网关无需用户 key：忽略占位 key，实时取令牌（指纹含令牌，过期换发后自动重建）
    if free_model.is_free_base(base_url):
        api_key = free_model.token()
    if not base_url or not api_key:
        raise ValueError(
            "OPENAI_BASE_URL and OPENAI_API_KEY environment variables must be set"
        )
    fingerprint = (base_url, api_key)

    if _global_client is None or _client_fingerprint != fingerprint:
        with _client_lock:
            if _global_client is None or _client_fingerprint != fingerprint:
                # 公益网关在 Cloudflare 后，httpx 默认指纹会被 403：改走 curl_cffi transport
                http_client = (
                    free_model.make_http_client()
                    if free_model.is_free_base(base_url)
                    else create_logging_http_client()
                )
                _global_client = OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    http_client=http_client,
                )
                _client_fingerprint = fingerprint

    return _global_client


def before_sleep_log(retry_state: RetryCallState) -> None:
    logger.warning(
        "Rate Limit Error, sleeping and retrying... Please lower your thread concurrency or use better OpenAI API."
    )


# 记住「不支持 enable_thinking 的 (端点, 模型)」（如 OpenAI 官方、或腾讯 Hunyuan-MT 这类非推理模型会
# 400）：之后直接不带该参数，免得每次先失败一次。按 (base, model) 记——同一端点下有的模型支持、有的
# 不支持（如 SiliconFlow 同时有 DeepSeek 思考模型和 Hunyuan-MT），不能按端点一刀切。
_thinking_unsupported: set = set()


def _is_bad_request(exc: Exception) -> bool:
    return (getattr(exc, "status_code", None) == 400
            or type(exc).__name__ == "BadRequestError"
            or "rror code: 400" in str(exc))


def _strip_thinking(kwargs: dict) -> dict:
    """去掉 extra_body 里的 enable_thinking（其余原样保留）。"""
    extra = {k: v for k, v in (kwargs.get("extra_body") or {}).items() if k != "enable_thinking"}
    out = dict(kwargs)
    if extra:
        out["extra_body"] = extra
    else:
        out.pop("extra_body", None)
    return out


@retry(
    stop=stop_after_attempt(10),
    wait=wait_random_exponential(multiplier=1, min=5, max=60),
    retry=retry_if_exception_type(openai.RateLimitError),
    before_sleep=before_sleep_log,
)
def _call_llm_api(
    messages: List[dict],
    model: str,
    **kwargs: Any,
) -> Any:
    """实际调用 LLM API（带重试）。不设 temperature：用各模型自身默认值。

    若带了 enable_thinking（关思考求快）而端点不支持（如 OpenAI 官方报 400 unknown parameter），
    自动去掉该参数重试一次、并记住该端点之后不再带——这样无论 provider 认不认都不会因此报错。"""
    client = get_llm_client()
    key = (os.getenv("OPENAI_BASE_URL", ""), model)
    if "enable_thinking" in (kwargs.get("extra_body") or {}) and key in _thinking_unsupported:
        kwargs = _strip_thinking(kwargs)  # 已知该模型不支持 → 提前去掉

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,  # pyright: ignore[reportArgumentType]
            **kwargs,
        )
    except openai.AuthenticationError:
        # 公益大模型 JWT 过期：换发后重建 client 重试一次（其它端点的 401 仍照常抛出）
        if not free_model.is_free_base(os.getenv("OPENAI_BASE_URL", "")):
            raise
        logger.info("公益大模型令牌过期，刷新后重试")
        free_model.token(force=True)
        client = get_llm_client()
        response = client.chat.completions.create(
            model=model,
            messages=messages,  # pyright: ignore[reportArgumentType]
            **kwargs,
        )
    except Exception as exc:
        if "enable_thinking" in (kwargs.get("extra_body") or {}) and _is_bad_request(exc):
            logger.info("LLM 模型不支持 enable_thinking，去掉该参数重试：%s", model)
            _thinking_unsupported.add(key)
            response = client.chat.completions.create(
                model=model,
                messages=messages,  # pyright: ignore[reportArgumentType]
                **_strip_thinking(kwargs),
            )
        else:
            raise

    # 记录响应内容
    log_llm_response(response)

    return response


@memoize(get_llm_cache(), expire=3600, typed=True)
def call_llm(
    messages: List[dict],
    model: str,
    **kwargs: Any,
) -> Any:
    """Call LLM API with automatic caching."""
    response = _call_llm_api(messages, model, **kwargs)

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
