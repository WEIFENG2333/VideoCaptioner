"""公益大模型免费网关：OpenAI 兼容，无需 API key。无 PyQt。

网关在 Cloudflare managed challenge 后面，普通 headless 客户端（requests / httpx / OpenAI SDK）
高频请求会被 403「Just a moment」。统一用 curl_cffi（模拟浏览器 TLS 指纹）过 CF：换 token 用它，
LLM client 也借它的 httpx transport。每安装随机持久化一个 deviceId（按设备分摊免费额度），
用它换 30min JWT 当 api_key（过期 / 401 自动续）。
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time

import httpx
from curl_cffi import requests as cffi_requests

from videocaptioner.config import APPDATA_PATH
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("free_model")

# OpenAI client 以此为 base，自动拼 /chat/completions
BASE_URL = "https://aigw1.immersivetranslate.com/v1/free"
MODEL = "THUDM/GLM-4-9B-0414"
# 凭据解析阶段先填的占位 key（真实令牌在 get_llm_client 内实时取），非空以通过「已配置」校验
PLACEHOLDER_KEY = "free"
_TOKEN_URL = "https://api2.immersivetranslate.com/free-model/get-token"
_DEVICE_ID_FILE = APPDATA_PATH / "free_model_device_id"
_REFRESH_MARGIN = 120  # JWT 到期前 2 分钟主动续，避开临界并发
_IMPERSONATE = "chrome"  # curl_cffi 模拟的浏览器 TLS 指纹


def is_free_base(base_url: str) -> bool:
    return "aigw1.immersivetranslate.com" in (base_url or "")


def _new_device_id() -> str:
    """64 位 base62，形态对齐浏览器扩展生成的 deviceId。"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(64))


def _jwt_exp(token: str) -> float:
    """解析 JWT 的 exp（unix 秒）；解析失败返回 0。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return 0.0


class _TokenProvider:
    """进程级 deviceId + JWT 管理：多线程共享，加锁续期。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._device_id = ""
        self._token = ""
        self._expire_at = 0.0

    def device_id(self) -> str:
        if self._device_id:
            return self._device_id
        try:
            did = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            did = ""
        if len(did) < 32:
            did = _new_device_id()
            try:
                _DEVICE_ID_FILE.write_text(did, encoding="utf-8")
            except OSError:  # 落盘失败用临时 id 继续，不挡使用
                pass
        self._device_id = did
        return did

    def token(self, *, force: bool = False) -> str:
        with self._lock:
            now = time.time()
            if not force and self._token and now < self._expire_at:
                return self._token
            resp = cffi_requests.get(
                _TOKEN_URL,
                params={"deviceId": self.device_id()},
                impersonate=_IMPERSONATE,
                timeout=15,
            )
            resp.raise_for_status()
            token = str((resp.json() or {}).get("data") or "")
            if not token:
                raise RuntimeError("获取公益大模型令牌失败")
            self._token = token
            exp = _jwt_exp(token)
            self._expire_at = (exp - _REFRESH_MARGIN) if exp else (now + 1500)
            return token


_provider = _TokenProvider()


def token(*, force: bool = False) -> str:
    """当前有效令牌（缓存，过期或 force 时重取）。"""
    return _provider.token(force=force)


class _CurlCffiTransport(httpx.BaseTransport):
    """让 OpenAI SDK（httpx）借 curl_cffi 的浏览器 TLS 过 Cloudflare。

    call_llm 不走流式，只需整体请求/响应。curl_cffi 已解压响应体，故丢掉 content-encoding /
    content-length，避免 httpx 二次解压或长度不符。
    """

    def __init__(self) -> None:
        self._session = cffi_requests.Session()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # 只透传业务头：UA / accept-encoding / sec-ch-* 等指纹头交给 impersonate，
        # 否则 OpenAI SDK 的 user-agent 会覆盖浏览器画像、被 Cloudflare 识破 → 403
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in ("authorization", "content-type")
        }
        resp = self._session.request(
            method=request.method,  # type: ignore[arg-type]
            url=str(request.url),
            headers=headers,
            data=request.content or None,
            impersonate=_IMPERSONATE,
            timeout=300,
        )
        headers = [
            (k, v)
            for k, v in resp.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        ]
        return httpx.Response(
            status_code=resp.status_code,
            headers=headers,
            content=resp.content,
            request=request,
        )


def make_http_client() -> httpx.Client:
    """给 OpenAI SDK 的 http_client：经 curl_cffi transport 过 CF。"""
    return httpx.Client(transport=_CurlCffiTransport(), timeout=300)
