import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from app.config import CACHE_PATH
from app.core.utils.logger import setup_logger
from app.core.utils.platform_utils import get_subprocess_kwargs

logger = setup_logger("download_thread")


class BaseDownloader(ABC):
    """下载器基类"""

    def __init__(self, url: str, save_path: Path, progress_callback):
        self.url = url
        self.save_path = save_path
        self.progress_callback = progress_callback
        self._cancelled = False

    @abstractmethod
    def download(self) -> bool:
        """执行下载，返回是否成功"""
        pass

    def cancel(self):
        """取消下载"""
        self._cancelled = True


class Aria2Downloader(BaseDownloader):
    """aria2c 多线程下载器"""

    def __init__(self, url: str, save_path: Path, progress_callback):
        super().__init__(url, save_path, progress_callback)
        self.process = None

    @staticmethod
    def is_available() -> bool:
        """检查 aria2c 是否可用"""
        return shutil.which("aria2c") is not None

    def download(self) -> bool:
        temp_dir = CACHE_PATH / "download_cache"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / self.save_path.name

        cmd = [
            "aria2c",
            "--no-conf",
            "--show-console-readout=false",
            "--summary-interval=1",
            "--max-connection-per-server=2",
            "--split=2",
            "--connect-timeout=10",
            "--timeout=10",
            "--max-tries=2",
            "--retry-wait=1",
            "--continue=true",
            "--auto-file-renaming=false",
            "--allow-overwrite=true",
            "--check-certificate=false",
            f"--dir={temp_dir}",
            f"--out={temp_file.name}",
            self.url,
        ]

        subprocess_args = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "universal_newlines": True,
            "encoding": "utf-8",
            **get_subprocess_kwargs(),
        }

        logger.info(f"使用 aria2c 下载: {self.url}")
        self.process = subprocess.Popen(cmd, **subprocess_args)

        while True:
            if self._cancelled:
                self.process.terminate()
                return False

            if self.process.poll() is not None:
                break

            line = self.process.stdout.readline()
            self._parse_progress(line)

        if self.process.returncode == 0:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_file), self.save_path)
            return True
        else:
            error = self.process.stderr.read()
            logger.error(f"aria2c 下载失败: {error}")
            return False

    def _parse_progress(self, line: str):
        """解析 aria2c 输出格式: [#40ca1b 2.4MiB/74MiB(3%) CN:2 DL:3.9MiB ETA:18s]"""
        if "[#" not in line or "]" not in line:
            return

        try:
            progress_part = line.split("(")[1].split(")")[0]
            percent = float(progress_part.strip("%"))

            speed = "0"
            eta = ""
            if "DL:" in line:
                speed = line.split("DL:")[1].split()[0]
            if "ETA:" in line:
                eta = line.split("ETA:")[1].split("]")[0]

            status = f"速度: {speed}/s, 剩余: {eta}"
            self.progress_callback(percent, status)
        except Exception:
            pass

    def cancel(self):
        super().cancel()
        if self.process:
            self.process.terminate()
            self.process.wait()


class RequestsDownloader(BaseDownloader):
    """Python requests 下载器（回退方案）"""

    CHUNK_SIZE = 8192

    def download(self) -> bool:
        logger.info(f"使用 requests 下载: {self.url}")
        self.progress_callback(0, "正在连接...")

        try:
            response = requests.get(self.url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.save_path.with_suffix(".tmp")

            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self._cancelled:
                        temp_file.unlink(missing_ok=True)
                        return False

                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        speed = self._format_size(downloaded)
                        status = f"已下载: {speed} / {self._format_size(total_size)}"
                        self.progress_callback(percent, status)

            # 下载完成后重命名
            shutil.move(str(temp_file), self.save_path)
            return True

        except requests.RequestException as e:
            logger.error(f"requests 下载失败: {e}")
            return False

    @staticmethod
    def _format_size(bytes_size: int) -> str:
        """格式化文件大小"""
        size = float(bytes_size)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"


class FileDownloadThread(QThread):
    """文件下载线程"""

    progress = pyqtSignal(float, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url: str, save_path: str):
        super().__init__()
        self.url = url
        self.save_path = Path(save_path)
        self.downloader: BaseDownloader | None = None

    def run(self):
        try:
            self.progress.emit(0, self.tr("正在连接..."))

            # 选择下载器：优先 aria2c，否则回退到 requests
            if Aria2Downloader.is_available():
                self.downloader = Aria2Downloader(
                    self.url, self.save_path, self._on_progress
                )
            else:
                logger.info("aria2c 不可用，使用 requests 下载")
                self.downloader = RequestsDownloader(
                    self.url, self.save_path, self._on_progress
                )

            success = self.downloader.download()

            if success:
                self.finished.emit()
            else:
                self.error.emit(self.tr("下载失败"))

        except Exception as e:
            logger.exception("下载异常")
            self.error.emit(str(e))

    def _on_progress(self, percent: float, status: str):
        """进度回调"""
        self.progress.emit(percent, status)

    def stop(self):
        """停止下载"""
        if self.downloader:
            self.downloader.cancel()
