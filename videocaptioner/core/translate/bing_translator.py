"""Bing（必应）免费翻译器。

Bing 的免费翻译没有公开 API：早年的 `edge.microsoft.com/translate/auth` 取 token
方式已被微软下线（返回 404）。当前可用做法是抓取 `bing.com/translator` 页面里的会话凭证
（IG / IID / 防滥用的 key+token），再以表单 POST 到 `bing.com/ttranslatev3`。凭证有过期
时间，过期或被拒时自动重新抓取。

站点按区域不同：国际区走 `www.bing.com`，中国大陆区 `www.bing.com` 会返回空响应、需走
`cn.bing.com`。初始化时按候选站点各探一次，锁定第一个能返回有效结果的站点。该端点一次只翻
一条文本，批量并发交给基类的 chunk 线程池，chunk 内逐条翻译并复用同一会话。
"""

import json
import re
import threading
import time
from typing import Callable, List, Optional

import requests

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.base import BaseTranslator, logger
from videocaptioner.core.translate.types import TargetLanguage, get_language_code
from videocaptioner.core.utils.cache import generate_cache_key

_HOSTS = ("www.bing.com", "cn.bing.com")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
# 单条文本上限：ttranslatev3 免费端点约 1000 字符。
_MAX_TEXT_LEN = 1000

_IG_RE = re.compile(r'IG:"([^"]+)"')
_IID_RE = re.compile(r'data-iid="([^"]+)"')
_ABUSE_RE = re.compile(r"params_AbusePreventionHelper\s*=\s*(\[.*?\]);", re.DOTALL)


class _BingSession:
    """某个 Bing 站点的免费翻译会话（抓取并缓存凭证，过期自动刷新，线程安全）。"""

    def __init__(self, session: requests.Session, timeout: int, host: str):
        self.session = session
        self.timeout = timeout
        self.host = host
        self.page = f"https://{host}/translator"
        self.api = f"https://{host}/ttranslatev3?isVertical=1"
        self._lock = threading.Lock()
        self.ig = ""
        self.iid = ""
        self.key = ""
        self.token = ""
        self._expires_at = 0.0
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            # 双检：可能已被其他线程刷新
            if not force and time.time() < self._expires_at - 5:
                return
            resp = self.session.get(
                self.page, headers={"User-Agent": _USER_AGENT}, timeout=self.timeout
            )
            resp.raise_for_status()
            html = resp.text
            ig, iid, abuse = (
                _IG_RE.search(html),
                _IID_RE.search(html),
                _ABUSE_RE.search(html),
            )
            if not (ig and iid and abuse):
                raise RuntimeError(
                    "无法从 Bing 翻译页解析会话凭证（页面结构可能已变或被风控）"
                )
            key, token, expiry_ms = json.loads(abuse.group(1))[:3]
            self.ig, self.iid = ig.group(1), iid.group(1)
            self.key, self.token = str(key), str(token)
            self._expires_at = time.time() + int(expiry_ms) / 1000.0

    def translate_once(self, text: str, target_lang: str) -> Optional[str]:
        """翻译单条文本；被风控/凭证失效时返回 None（响应为空或非 list）。"""
        url = f"{self.api}&IG={self.ig}&IID={self.iid}"
        resp = self.session.post(
            url,
            data={
                "fromLang": "auto-detect",
                "to": target_lang,
                "text": text[:_MAX_TEXT_LEN],
                "token": self.token,
                "key": self.key,
            },
            headers={"User-Agent": _USER_AGENT, "Referer": self.page},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        if not resp.text.strip():
            return None
        payload = resp.json()
        if isinstance(payload, list) and payload:
            return payload[0]["translations"][0]["text"]
        return None

    def translate(self, text: str, target_lang: str) -> str:
        """翻译单条文本，token 过期或被拒时刷新一次后重试。"""
        for attempt in range(2):
            self._ensure_fresh()
            out = self.translate_once(text, target_lang)
            if out is not None:
                return out
            if attempt == 0:
                self.refresh(force=True)
        raise RuntimeError("Bing 返回空响应（可能被风控或凭证失效）")

    def _ensure_fresh(self) -> None:
        if time.time() >= self._expires_at - 5:
            self.refresh()


class BingTranslator(BaseTranslator):
    """必应免费翻译器。"""

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        update_callback: Optional[Callable],
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )
        self.timeout = 20
        self.session = requests.Session()
        self._init_session()

    def _init_session(self) -> None:
        """按候选站点各探一次，锁定第一个能返回有效结果的站点。"""
        target_lang = get_language_code(self.target_language, "bing")
        last_error: Optional[str] = None
        for host in _HOSTS:
            try:
                candidate = _BingSession(self.session, self.timeout, host)
                if candidate.translate_once("hello", target_lang):
                    self._bing = candidate
                    logger.debug(f"Bing translator using host: {host}")
                    return
                last_error = f"{host} 返回空响应"
            except Exception as e:
                last_error = f"{host}: {e}"
                logger.debug(f"Bing host {host} unavailable: {e}")
        raise RuntimeError(f"Failed to init Bing session: {last_error}")

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """逐条翻译一个批次（并发由基类在 chunk 层提供）。"""
        target_lang = get_language_code(self.target_language, "bing")
        for data in subtitle_chunk:
            try:
                data.translated_text = self._bing.translate(
                    data.original_text, target_lang
                )
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Bing translation failed: {str(e)}")
        return subtitle_chunk

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """生成缓存键"""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        return f"{class_name}:{chunk_key}:{lang}"
