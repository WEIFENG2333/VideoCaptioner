"""反馈提交的 Qt 线程薄壳；业务在 core/feedback，UI 只消费信号。"""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.feedback import FeedbackClient, FeedbackReport
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("feedback_thread")


class FeedbackSubmitThread(QThread):
    """后台 multipart 提交反馈。结果回 Qt 信号（队列到 GUI 线程）。"""

    succeeded = pyqtSignal(str)  # feedback id
    failed = pyqtSignal(str, str)  # (code, error)

    def __init__(self, report: FeedbackReport, parent=None):
        super().__init__(parent)
        self._report = report

    def run(self) -> None:
        try:
            result = FeedbackClient().submit(self._report)
        except Exception as exc:  # noqa: BLE001 — 提交失败不该崩，回失败信号
            logger.warning("feedback submit error: %s", exc)
            self.failed.emit("server_error", str(exc))
            return
        if result.ok:
            self.succeeded.emit(result.id)
        else:
            self.failed.emit(result.code, result.error)
