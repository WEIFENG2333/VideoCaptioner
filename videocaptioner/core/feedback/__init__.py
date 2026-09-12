"""用户反馈：组装报告 → multipart 提交后端（写入飞书多维表格）。无 PyQt 依赖。"""

from videocaptioner.core.feedback.client import (
    FeedbackClient,
    FeedbackResult,
)
from videocaptioner.core.feedback.diagnostics import (
    gather_diagnostics,
    get_or_create_client_id,
    platform_tag,
)
from videocaptioner.core.feedback.logs import collect_recent_logs, scrub_log_text
from videocaptioner.core.feedback.models import (
    ALLOWED_MIME,
    CATEGORIES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    MESSAGE_MAX,
    FeedbackAttachment,
    FeedbackReport,
    FeedbackValidationError,
)

__all__ = [
    "FeedbackClient",
    "FeedbackResult",
    "FeedbackReport",
    "FeedbackAttachment",
    "FeedbackValidationError",
    "gather_diagnostics",
    "get_or_create_client_id",
    "platform_tag",
    "collect_recent_logs",
    "scrub_log_text",
    "CATEGORIES",
    "ALLOWED_MIME",
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "MAX_TOTAL_BYTES",
    "MESSAGE_MAX",
]
