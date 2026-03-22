import io
import logging
import sys
from typing import Callable

from modelscope.hub.callback import ProgressCallback
from modelscope.hub.snapshot_download import snapshot_download
from PyQt5.QtCore import QThread, pyqtSignal


class SuppressOutput:
    """上下文管理器：抑制 stdout/stderr 和 modelscope 日志"""

    def __enter__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        self._loggers: dict[str, int] = {}
        for name in ["modelscope", "tqdm"]:
            logger = logging.getLogger(name)
            self._loggers[name] = logger.level
            logger.setLevel(logging.CRITICAL)
        return self

    def __exit__(self, *args):
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        for name, level in self._loggers.items():
            logging.getLogger(name).setLevel(level)


def create_progress_callback_class(
    progress_callback: Callable[[int, str], None],
) -> type[ProgressCallback]:
    """创建一个自定义的 ProgressCallback 类，用于接收下载进度"""

    class CustomProgressCallback(ProgressCallback):
        def __init__(self, filename: str, file_size: int):
            super().__init__(filename, file_size)
            self.downloaded = 0

        def update(self, size: int):
            self.downloaded += size
            if self.file_size > 0:
                percentage = min(int(self.downloaded * 100 / self.file_size), 99)
                progress_callback(percentage, f"{self.filename}: {percentage}%")

        def end(self):
            pass

    return CustomProgressCallback


class ModelscopeDownloadThread(QThread):
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, model_id: str, save_path: str):
        super().__init__()
        self.model_id = model_id
        self.save_path = save_path

    def run(self):
        try:
            self.progress.emit(0, self.tr("开始下载..."))

            callback_class = create_progress_callback_class(self.progress.emit)

            with SuppressOutput():
                snapshot_download(
                    self.model_id,
                    local_dir=self.save_path,
                    progress_callbacks=[callback_class],
                )

            self.progress.emit(100, self.tr("下载完成"))

        except Exception as e:
            self.error.emit(str(e))


if __name__ == "__main__":
    import sys

    from PyQt5.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    model_id = "pengzhendong/faster-whisper-tiny"
    save_path = r"models/faster-whisper-tiny"
    downloader = ModelscopeDownloadThread(model_id, save_path)

    def on_progress(percentage, message):
        print(f"进度: {message}")

    def on_error(error_msg):
        print(f"错误: {error_msg}")
        app.quit()

    def on_finished():
        print("下载完成！")
        app.quit()

    downloader.progress.connect(on_progress)
    downloader.error.connect(on_error)
    downloader.finished.connect(on_finished)

    print(f"开始下载模型 {model_id}")
    downloader.start()

    sys.exit(app.exec_())
