import re
import sys

from modelscope.hub.snapshot_download import snapshot_download
from PyQt5.QtCore import QThread, pyqtSignal


class ModelscopeDownloadThread(QThread):
    progress = pyqtSignal(int, str)  # 进度值和状态消息
    error = pyqtSignal(str)  # 错误信息

    def __init__(self, model_id, save_path):
        super().__init__()
        self.model_id = model_id
        self.save_path = save_path
        self._original_stdout = None
        self._original_stderr = None

    def custom_write(self, text):
        # 解析进度信息
        if "%|" in text:
            try:
                # 提取百分比
                match = re.search(r"(\d+)%", text)
                if match:
                    percentage = int(match.group(1))
                    # 提取文件名
                    file_match = re.search(r"\[(.*?)\]:", text)
                    if file_match:
                        filename = file_match.group(1)
                        self.progress.emit(
                            percentage, f"正在下载 {filename}: {percentage}%"
                        )
            except Exception:
                pass
        # 写入原始stdout
        self._original_stdout.write(text)
        self._original_stdout.flush()

    def run(self):
        try:
            # 发送开始下载信号
            self.progress.emit(0, "开始下载...")

            # 保存原始stdout
            self._original_stdout = sys.stdout
            self._original_stderr = sys.stderr

            # 创建自定义输出对象
            class CustomOutput:
                def __init__(self, callback):
                    self.callback = callback

                def write(self, text):
                    self.callback(text)

                def flush(self):
                    pass

            # 重定向输出
            sys.stdout = CustomOutput(self.custom_write)
            sys.stderr = CustomOutput(self.custom_write)

            try:
                # 下载模型
                snapshot_download(self.model_id, local_dir=self.save_path)
            finally:
                # 恢复原始输出
                sys.stdout = self._original_stdout
                sys.stderr = self._original_stderr

            # 发送完成信号
            self.progress.emit(100, "下载完成")

        except Exception as e:
            self.error.emit(str(e))


if __name__ == "__main__":
    import sys

    from PyQt5.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    model_id = "pengzhendong/faster-whisper-tiny"
    save_path = r"models\faster-whisper-tiny"  # 保存到当前目录下的models文件夹
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

    # 开始下载
    print(f"开始下载模型 {model_id}")
    downloader.start()

    # 运行事件循环
    sys.exit(app.exec_())
