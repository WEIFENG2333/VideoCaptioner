"""工件下载线程：模型（多文件）与运行程序（单文件）共用一个线程类。

线程只负责把 core 下载器跑在后台并翻译进度为
``progress(percent, message)``；message 形如 ``model.bin · 760.4 MB / 1.6 GB``，
与模型管理弹窗下载行的副文案约定一致。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.download import (
    DownloadCancelled,
    ModelFile,
    ModelSpec,
    download_file,
    download_model,
)
from videocaptioner.core.download.dependencies import DependencySpec, install_dependency
from videocaptioner.ui.thread.worker import WorkerCancelled, WorkerThread

# job(progress_cb, cancel_cb) -> 落盘路径
_Job = Callable[[Callable[[int, str], None], Callable[[], bool]], str]


class ArtifactDownloadThread(WorkerThread):
    """completed(str) 为落盘路径；取消静默结束（.part 保留续传）。"""

    completed = pyqtSignal(str)

    def __init__(self, job: _Job, parent=None):
        super().__init__(parent)
        self._job = job

    def _work(self) -> None:
        try:
            result = self._job(self.progress.emit, self.is_cancel_requested)
        except DownloadCancelled as exc:
            raise WorkerCancelled from exc
        self.checkpoint()
        self.completed.emit(str(result))


def model_download_thread(
    spec: ModelSpec, models_dir: Path, parent=None
) -> ArtifactDownloadThread:
    def job(report, should_cancel) -> str:
        def on_progress(event):
            if event.total_bytes:
                percent = int(event.total_received * 100 / event.total_bytes)
                position = f"{_size_text(event.total_received)} / {_size_text(event.total_bytes)}"
            elif event.file.total:
                percent = int(event.file.received * 100 / event.file.total)
                position = f"{_size_text(event.file.received)} / {_size_text(event.file.total)}"
            else:
                percent = -1
                position = _size_text(event.file.received)
            report(percent, f"{event.file.file_name} · {position}")

        return str(
            download_model(
                spec, models_dir, on_progress=on_progress, should_cancel=should_cancel
            )
        )

    return ArtifactDownloadThread(job, parent)


def program_download_thread(
    file: ModelFile, bin_dir: Path, parent=None
) -> ArtifactDownloadThread:
    def job(report, should_cancel) -> str:
        dest = Path(bin_dir) / file.name

        def on_progress(progress):
            total = progress.total or file.size_bytes
            if total:
                percent = int(progress.received * 100 / total)
                position = f"{_size_text(progress.received)} / {_size_text(total)}"
            else:
                percent = -1
                position = _size_text(progress.received)
            report(percent, f"{progress.file_name} · {position}")

        download_file(
            file.urls,
            dest,
            sha1=file.sha1,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        return str(dest)

    return ArtifactDownloadThread(job, parent)


def asset_install_thread(asset, display_name: str, parent=None) -> ArtifactDownloadThread:
    """下载并安装一个具体资产（压缩包解压 / 单文件落地）到应用 bin 目录。"""
    from videocaptioner.core.download.dependencies import install_asset

    def job(report, should_cancel) -> str:
        def on_progress(progress):
            total = progress.total or getattr(asset, "size_bytes", None)
            if total:
                percent = int(progress.received * 100 / total)
                position = f"{_size_text(progress.received)} / {_size_text(total)}"
            else:
                percent = -1
                position = _size_text(progress.received)
            report(percent, f"{progress.file_name} · {position}")

        def on_phase(message: str):
            report(-1, message)

        path = install_asset(
            asset,
            display_name,
            on_progress=on_progress,
            on_phase=on_phase,
            should_cancel=should_cancel,
        )
        return str(path)

    return ArtifactDownloadThread(job, parent)


def dependency_download_thread(
    spec: DependencySpec, parent=None
) -> ArtifactDownloadThread:
    """下载并安装一个运行依赖（ffmpeg / voxgate）：下载→解压→落 BIN_PATH。"""

    def job(report, should_cancel) -> str:
        def on_progress(progress):
            total = progress.total
            if total:
                percent = int(progress.received * 100 / total)
                position = f"{_size_text(progress.received)} / {_size_text(total)}"
            else:
                percent = -1
                position = _size_text(progress.received)
            report(percent, f"{progress.file_name} · {position}")

        def on_phase(message: str):
            report(-1, message)  # 解压等无字节进度的阶段，只刷文案

        path = install_dependency(
            spec,
            on_progress=on_progress,
            on_phase=on_phase,
            should_cancel=should_cancel,
        )
        return str(path)

    return ArtifactDownloadThread(job, parent)


def _size_text(num_bytes: int) -> str:
    if num_bytes >= 1_000_000_000:
        return f"{num_bytes / 1_000_000_000:.1f} GB"
    return f"{num_bytes / 1_000_000:.1f} MB"
