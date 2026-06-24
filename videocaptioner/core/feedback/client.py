"""提交反馈到后端（multipart/form-data）。无 PyQt。

复用 net.system_proxy（GUI 进程拿不到 shell 的 HTTP_PROXY，必须主动取系统代理）。
端点写死在 config.FEEDBACK_API_URL，不走环境变量/配置文件。本期后端无幂等，但客户端仍每次
带新 request_id 仅供排查。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

from videocaptioner.config import APP_NAME, FEEDBACK_API_URL, VERSION
from videocaptioner.core.download.net import system_proxy
from videocaptioner.core.feedback.diagnostics import get_or_create_client_id, platform_tag
from videocaptioner.core.feedback.models import FeedbackReport
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("feedback_client")


@dataclass(frozen=True)
class FeedbackResult:
    ok: bool
    id: str = ""
    code: str = ""
    error: str = ""


class FeedbackClient:
    def __init__(self, endpoint: str = "", *, session: Optional[requests.Session] = None, timeout: int = 30):
        self._endpoint = endpoint or FEEDBACK_API_URL
        self._session = session
        self._timeout = timeout

    def submit(self, report: FeedbackReport) -> FeedbackResult:
        """校验 → multipart POST → 解析 {ok,id} / {ok,code,error}。网络/服务端失败返回 ok=False。"""
        report.validate()  # 本地预校验，失败抛 FeedbackValidationError（调用方先处理）
        http = self._session or requests.Session()
        plat = platform_tag()
        headers = {
            "X-App-Version": VERSION,
            "X-App-Platform": plat,
            "User-Agent": f"{APP_NAME}/{VERSION} ({plat})",
        }
        fields = {
            "category": report.category,
            "message": report.message.strip(),
            "client_id": get_or_create_client_id(),
            "request_id": str(uuid.uuid4()),
        }
        if report.contact.strip():
            fields["contact"] = report.contact.strip()
        if report.diagnostics:
            fields["diagnostics"] = json.dumps(report.diagnostics, ensure_ascii=False)
        # 后端强制 multipart/form-data。文本字段也作为 multipart part（filename=None）发送，
        # 否则无截图时 requests 会退化成 application/x-www-form-urlencoded 被后端拒绝。
        parts = [(key, (None, value)) for key, value in fields.items()]
        parts += [("files", (att.filename, att.data, att.mime)) for att in report.attachments]

        proxy = system_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = http.post(
                self._endpoint,
                headers=headers,
                files=parts,
                proxies=proxies,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("feedback submit failed: %s", exc)
            return FeedbackResult(ok=False, code="network", error=str(exc))
        return _parse_response(resp)


def _parse_response(resp: requests.Response) -> FeedbackResult:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code == 200 and isinstance(body, dict) and body.get("ok"):
        return FeedbackResult(ok=True, id=str(body.get("id", "")))
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    error = str(body.get("error", "")) if isinstance(body, dict) else ""
    if not code:
        code = {400: "invalid_request", 401: "unauthorized", 413: "too_large"}.get(
            resp.status_code, "server_error"
        )
    return FeedbackResult(ok=False, code=code, error=error or f"HTTP {resp.status_code}")
