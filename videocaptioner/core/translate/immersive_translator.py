"""沉浸式翻译免费模型翻译器（公益，无需 API key）。无 PyQt。

复用沉浸式翻译的免费模型网关（OpenAI 兼容 chat completions），用户不用配 key：
- 每安装随机生成并持久化一个 deviceId（模仿浏览器扩展，按设备分摊免费额度，不共用一个）。
- 用 deviceId 换 30 分钟有效的 JWT（进程内缓存，过期或 401 自动续），再调 chat 端点。
- 批量 JSON（dict-in/dict-out）一次翻一组，键缺失重试、再不行退化为逐条，绝不丢段。

并发由工厂封顶到 MAX_CONCURRENCY。这是第三方免费额度，可能限流或随时变更，作为不配 key
的兜底翻译。最小请求：换 token 只需 query 的 deviceId；chat 只需 authorization: Bearer。
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from typing import Callable, Dict, List, Optional

import json_repair
import requests

from videocaptioner.config import APPDATA_PATH
from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.prompts import get_prompt
from videocaptioner.core.translate.base import BaseTranslator, logger
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.utils.cache import generate_cache_key

_TOKEN_URL = "https://api2.immersivetranslate.com/free-model/get-token"
_CHAT_URL = "https://aigw1.immersivetranslate.com/v1/free/chat/completions"
_MODEL = "THUDM/GLM-4-9B-0414"
_DEVICE_ID_FILE = APPDATA_PATH / "immersive_device_id"
_TOKEN_REFRESH_MARGIN = 120  # JWT 到期前 2 分钟主动续，避开临界并发

MAX_CONCURRENCY = 10  # 免费额度并发上限，工厂据此封顶 thread_num


def _new_device_id() -> str:
    """64 位 base62，形态对齐沉浸式扩展生成的 deviceId。"""
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


class _FreeTokenProvider:
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
            except OSError:  # 落盘失败用临时 id 继续，不挡翻译
                pass
        self._device_id = did
        return did

    def token(self, session: requests.Session, *, force: bool = False) -> str:
        with self._lock:
            now = time.time()
            if not force and self._token and now < self._expire_at:
                return self._token
            resp = session.get(
                _TOKEN_URL, params={"deviceId": self.device_id()}, timeout=15
            )
            resp.raise_for_status()
            token = str((resp.json() or {}).get("data") or "")
            if not token:
                raise RuntimeError("获取沉浸式免费翻译令牌失败")
            self._token = token
            exp = _jwt_exp(token)
            self._expire_at = (exp - _TOKEN_REFRESH_MARGIN) if exp else (now + 1500)
            return token


# deviceId/token 按进程共享（一台设备一份额度），所有翻译实例与线程复用。
_token_provider = _FreeTokenProvider()


class ImmersiveFreeTranslator(BaseTranslator):
    """沉浸式免费模型翻译器（OpenAI 兼容，批量 JSON）。"""

    MAX_STEPS = 3

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        custom_prompt: str = "",
        update_callback: Optional[Callable] = None,
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )
        self.custom_prompt = custom_prompt
        self.timeout = 60
        self.session = requests.Session()
        self._tokens = _token_provider

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        subtitle_dict = {str(d.index): d.original_text for d in subtitle_chunk}
        system_prompt = get_prompt(
            "translate/standard",
            target_language=self.target_language.value,
            custom_prompt=self.custom_prompt,
        )
        try:
            result = self._chat_dict(system_prompt, subtitle_dict)
        except Exception as e:
            # 整块失败（网络/限流/格式）：清空 result，逐条补译路径接管
            logger.warning(f"Immersive batch failed, retry per line: {e}")
            result = {}

        translated = 0
        for d in subtitle_chunk:
            text = result.get(str(d.index))
            if text not in (None, ""):
                d.translated_text = str(text).strip()
                translated += 1
            else:
                d.translated_text = ""  # 批量没覆盖到，待逐条补

        pending = [d for d in subtitle_chunk if not d.translated_text]
        if pending:
            translated += self._translate_single(pending)

        # 整块一条都没译出 = 硬失败（端点不可用/被限流/全程非法响应）：必须抛错，
        # 否则 BaseTranslator 的 ≥50% 失败保护永不触发，且会把「原文冒充译文」的结果
        # 缓存 7 天，重试一周内命中毒缓存无法恢复。免费端点 429 正是走这条路。
        if translated == 0:
            raise RuntimeError("沉浸式免费翻译整块失败（端点不可用或被限流）")

        # 仅零星条目仍未译出（局部失败）才回退原文，不影响整体，可缓存
        for d in subtitle_chunk:
            if not d.translated_text:
                d.translated_text = d.original_text
        return subtitle_chunk

    def _chat_dict(
        self, system_prompt: str, subtitle_dict: Dict[str, str]
    ) -> Dict[str, str]:
        """批量翻译：dict 进 dict 出，键缺失带反馈重试。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(subtitle_dict, ensure_ascii=False)},
        ]
        last: Dict[str, str] = {}
        for _ in range(self.MAX_STEPS):
            raw = self._post_chat(messages)
            parsed = json_repair.loads(raw)
            if isinstance(parsed, dict):
                last = {str(k): v for k, v in parsed.items()}
                missing = set(subtitle_dict) - set(last)
                if not missing:
                    return last
                messages.append(
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"缺少键 {sorted(missing)}，请只输出包含全部 "
                        f"{len(subtitle_dict)} 个键的 JSON 字典，值为译文。",
                    }
                )
            else:
                messages.append(
                    {"role": "user", "content": "请只输出 JSON 字典，键与输入完全一致。"}
                )
        return last

    def _post_chat(self, messages: List[dict]) -> str:
        body = {"model": _MODEL, "temperature": 0, "think": False, "messages": messages}
        token = self._tokens.token(self.session)
        resp = self.session.post(
            _CHAT_URL,
            headers={"authorization": f"Bearer {token}"},
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code in (401, 403):  # 令牌过期，强制续一次重试
            token = self._tokens.token(self.session, force=True)
            resp = self.session.post(
                _CHAT_URL,
                headers={"authorization": f"Bearer {token}"},
                json=body,
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:  # 429/错误体常是 200+无 choices，明确抛错而非 KeyError
            raise RuntimeError(f"沉浸式免费翻译返回无效响应: {str(data)[:200]}")
        content = choices[0].get("message", {}).get("content") or ""
        return content.strip()

    def _translate_single(self, subtitle_chunk: List[SubtitleProcessData]) -> int:
        """逐条翻译，返回成功译出的条数。失败条目 translated_text 留空，交调用方判定。"""
        single_prompt = get_prompt(
            "translate/single", target_language=self.target_language.value
        )
        translated = 0
        for d in subtitle_chunk:
            try:
                raw = self._post_chat(
                    [
                        {"role": "system", "content": single_prompt},
                        {"role": "user", "content": d.original_text},
                    ]
                )
                text = raw.strip()
                if text:
                    d.translated_text = text
                    translated += 1
            except Exception as e:
                logger.warning(f"Immersive single failed {d.index}: {e}")
        return translated

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        return (
            f"{self.__class__.__name__}:{generate_cache_key(chunk)}:"
            f"{self.target_language.value}:{_MODEL}"
        )
