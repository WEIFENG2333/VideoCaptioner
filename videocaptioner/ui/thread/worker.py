# -*- coding: utf-8 -*-
"""页面后台线程的统一基类。

约定：

- 子类实现 ``_work()``，正常返回即成功；抛异常会被捕获并发 ``error`` 信号。
- 取消是协作式的：``stop()`` 置取消标记并调用 ``_on_cancel()``（子类在这里
  停掉 core 层的 optimizer/translator 等），``_work()`` 在阶段边界调用
  ``checkpoint()`` 主动退出；只有等待超时才退化为 ``terminate()``。
- 被取消的运行静默结束：不发 ``error``，也不发结果信号。
- 面向用户的错误/状态文案用模块级 ``tr("t_xxx.key")``（已 i18n），不要用 Qt 的
  ``self.tr()``（基类是 QThread，语境不对）；纯日志/调试串不翻译。
"""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("ui_worker_thread")


class WorkerCancelled(Exception):
    """协作取消信号量：checkpoint() 在收到取消请求后抛出。"""


class WorkerThread(QThread):
    """progress(int, str) / error(str) + 协作式取消的 QThread 基类。"""

    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_requested = False

    # ----- 子类接口 -----

    def _work(self) -> None:
        raise NotImplementedError

    def _on_cancel(self) -> None:
        """收到取消请求时的钩子：停掉持有的 core 层执行器。"""

    # ----- 取消协议 -----

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested

    def checkpoint(self) -> None:
        """阶段边界调用；收到取消请求则中止本次运行。"""
        if self._cancel_requested:
            raise WorkerCancelled

    def request_cancel(self) -> None:
        """只置取消标记并触发钩子，不等待。

        批量并发取消时先对所有线程 ``request_cancel()`` 广播，再逐个 ``stop()``
        收割——这样 N 个线程并发退出，总等待 ≈ 单个最慢而非 N×wait_ms。
        """
        if not self.isRunning():
            return
        self._cancel_requested = True
        try:
            self._on_cancel()
        except Exception:
            logger.exception("取消钩子执行失败")

    def stop(self, wait_ms: int = 3000) -> None:
        """请求协作取消；超时未退出才强杀（最后手段）。"""
        if not self.isRunning():
            return
        self.request_cancel()
        if not self.wait(wait_ms):
            logger.warning("%s 未在 %dms 内退出，强制终止", type(self).__name__, wait_ms)
            self.terminate()
            self.wait(1000)

    # ----- 运行包装 -----

    def run(self):
        try:
            self._work()
        except WorkerCancelled:
            logger.info("%s 已取消", type(self).__name__)
        except Exception as exc:
            logger.exception("%s 失败: %s", type(self).__name__, exc)
            self.error.emit(str(exc))
