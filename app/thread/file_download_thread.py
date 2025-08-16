import os
import shutil
import subprocess

from PyQt5.QtCore import QThread, pyqtSignal

from app.config import CACHE_PATH
from app.core.utils.logger import setup_logger
from app.core.utils.platform_utils import get_subprocess_kwargs

logger = setup_logger("download_thread")


class FileDownloadThread(QThread):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.process = None

    def run(self):
        try:
            # 创建缓存下载目录
            temp_dir = CACHE_PATH / "aria2c_download_cache"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / os.path.basename(self.save_path)

            # 检查是否存在未完成的下载文件
            if temp_file.exists():
                logger.info(f"发现未完成的下载文件: {temp_file}")
            self.progress.emit(0, self.tr("正在连接..."))
            cmd = [
                "aria2c",
                "--show-console-readout=false",
                "--summary-interval=1",
                "-x2",
                "-s2",
                "--connect-timeout=10",  # 连接超时时间10秒
                "--timeout=10",  # 数据传输超时时间10秒
                "--max-tries=2",  # 最大重试次数2次
                "--retry-wait=1",  # 重试等待时间1秒
                "--continue=true",  # 开启断点续传
                "--auto-file-renaming=false",
                "--allow-overwrite=true",
                "--check-certificate=false",
                f"--dir={temp_dir}",
                f"--out={temp_file.name}",
                self.url,
            ]

            # 根据操作系统设置不同的 subprocess 参数
            subprocess_args = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "universal_newlines": True,
                "encoding": "utf-8",
            }

            # 获取跨平台的subprocess参数
            subprocess_args.update(get_subprocess_kwargs())

            logger.info("运行下载命令: %s", " ".join(cmd))

            self.process = subprocess.Popen(cmd, **subprocess_args)

            while True:
                if self.process.poll() is not None:
                    break

                line = self.process.stdout.readline()

                if "[#" in line and "]" in line:
                    try:
                        # 解析类似 "[#40ca1b 2.4MiB/74MiB(3%) CN:2 DL:3.9MiB ETA:18s]" 的格式
                        progress_part = line.split("(")[1].split(")")[0]
                        percent = float(progress_part.strip("%"))

                        # 提取下载速度和剩余时间
                        speed = "0"
                        eta = ""
                        if "DL:" in line:
                            speed = line.split("DL:")[1].split()[0]
                        if "ETA:" in line:
                            eta = line.split("ETA:")[1].split("]")[0]
                        status_msg = f"{self.tr('速度')}: {speed}/s, {self.tr('剩余时间')}: {eta}"
                        self.progress.emit(percent, status_msg)
                    except Exception:
                        pass

            if self.process.returncode == 0:
                # 下载完成后移动文件到目标位置
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                shutil.move(str(temp_file), self.save_path)
                self.finished.emit()
            else:
                error = self.process.stderr.read()
                logger.error("下载失败: %s", error)
                self.error.emit(f"{self.tr('下载失败')}: {error}")

        except Exception as e:
            logger.error("下载异常: %s", str(e))
            self.error.emit(str(e))

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
