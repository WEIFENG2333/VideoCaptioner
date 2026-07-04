"""反馈数据模型 + 本地预校验（无 PyQt）。限制对齐后端契约 docs/dev/feedback-api 与 vc-backend。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

CATEGORIES = ("bug", "feature", "question", "other")
MESSAGE_MIN = 1
MESSAGE_MAX = 5000
CONTACT_MAX_BYTES = 200
MAX_FILES = 3
MAX_LOG_FILES = 3
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024  # 后端按整条请求体（截图 + 日志 + 文本字段）卡 12 MB
# 本地 total 也计入文本字段与框架开销，成为后端上限的真超集，避免本地放行后被后端 413。
_FRAMING_RESERVE_BYTES = 2048
ALLOWED_MIME = ("image/png", "image/jpeg")


class FeedbackValidationError(ValueError):
    """提交前本地校验失败。``code`` 供 UI 映射到本地化提示（core 不做 i18n）。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class FeedbackAttachment:
    """一张用户截图：内存字节，不落临时文件。"""

    filename: str
    data: bytes
    mime: str  # image/png | image/jpeg

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class FeedbackReport:
    category: str
    message: str
    contact: str = ""
    attachments: list[FeedbackAttachment] = field(default_factory=list)
    logs: list[FeedbackAttachment] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.category not in CATEGORIES:
            raise FeedbackValidationError("category_invalid", f"未知反馈类型：{self.category}")
        msg = self.message.strip()
        if len(msg) < MESSAGE_MIN:
            raise FeedbackValidationError("message_required", "请填写问题描述")
        if len(msg) > MESSAGE_MAX:
            raise FeedbackValidationError("message_too_long", f"问题描述需 ≤ {MESSAGE_MAX} 字")
        if len(self.contact.encode("utf-8")) > CONTACT_MAX_BYTES:
            raise FeedbackValidationError("contact_too_long", "联系方式过长")
        if len(self.attachments) > MAX_FILES:
            raise FeedbackValidationError("too_many_files", f"最多 {MAX_FILES} 张截图")
        if len(self.logs) > MAX_LOG_FILES:
            raise FeedbackValidationError("too_many_logs", f"最多 {MAX_LOG_FILES} 个日志文件")
        total = len(msg.encode("utf-8")) + len(self.contact.strip().encode("utf-8"))
        if self.diagnostics:
            total += len(json.dumps(self.diagnostics, ensure_ascii=False).encode("utf-8"))
        total += _FRAMING_RESERVE_BYTES
        for att in self.attachments:
            if att.mime not in ALLOWED_MIME:
                raise FeedbackValidationError("file_type", "仅支持 PNG / JPEG 截图")
            if att.size > MAX_FILE_BYTES:
                raise FeedbackValidationError("file_too_large", "单张截图需 ≤ 5 MB")
            total += att.size
        for log in self.logs:
            if log.size > MAX_FILE_BYTES:
                raise FeedbackValidationError("log_too_large", "单个日志需 ≤ 5 MB")
            total += log.size
        if total > MAX_TOTAL_BYTES:
            raise FeedbackValidationError("total_too_large", "截图与日志总大小需 ≤ 12 MB")
