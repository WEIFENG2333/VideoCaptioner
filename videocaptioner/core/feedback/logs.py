"""采集随反馈上传的「最近日志」附件（默认开启）。无 PyQt。

取 app.log 尾部（~256KB），发送前脱敏。硬规则：logs 不得含 API key / base URL / token。
"""

from __future__ import annotations

import re

from videocaptioner.config import LOG_PATH
from videocaptioner.core.feedback.models import FeedbackAttachment

_LOG_FILE = LOG_PATH / "app.log"
_MAX_TAIL_BYTES = 256 * 1024  # 最近日志尾部上限

# 打码顺序固定。Bearer/Basic 单独成条保留 scheme 便于可读，故键值对列表不含
# authorization（否则会把 scheme 词二次吃成 ***）。base URL/endpoint 也算敏感，一并打码。
_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]+"), r"\1 ***"),
    (re.compile(r"\bsk-[A-Za-z0-9._\-]{6,}"), "sk-***"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "AIza***"),
    (
        re.compile(
            r"(?i)(\"?(?:api[_-]?key|apikey|api[_-]?secret|access[_-]?token|secret|password|token)\"?\s*[:=]\s*\"?)"
            r"([^\s\"',}]+)"
        ),
        r"\1***",
    ),
    # query string 凭据：以 ?/& 紧邻参数名锚定，避免误伤 keyboard/monkey 等普通词。
    (re.compile(r"(?i)([?&](?:api[_-]?key|key|token|access[_-]?token)=)([^&\s\"']+)"), r"\1***"),
    # base URL / endpoint 标记后的地址（含 deeplx endpoint）；值停在引号/逗号/花括号/空白。
    (
        re.compile(
            r"(?i)(\"?(?:api[ _]?base|base[ _]?url|endpoint|deeplx[ _]?endpoint)\"?\s*[:=]\s*\"?)"
            r"([^\s\"',}]+)"
        ),
        r"\1***",
    ),
    (re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+):([^/\s@]+)@"), r"\1:***@"),
)


def scrub_log_text(text: str) -> str:
    """把日志文本里疑似密钥/凭据打码（发送前必经）。"""
    for pattern, repl in _SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def collect_recent_logs() -> list[FeedbackAttachment]:
    """读取 app.log 尾部并脱敏，返回一个 recent.log 附件；无日志或读失败返回 []。"""
    try:
        size = _LOG_FILE.stat().st_size
        with _LOG_FILE.open("rb") as fh:
            if size > _MAX_TAIL_BYTES:
                fh.seek(size - _MAX_TAIL_BYTES)
                fh.readline()  # 丢弃截断处的半行，从完整行开始
            raw = fh.read()
    except OSError:
        return []
    text = scrub_log_text(raw.decode("utf-8", errors="replace"))
    data = text.encode("utf-8")
    if not data.strip():
        return []
    return [FeedbackAttachment(filename="recent.log", data=data, mime="text/plain")]
