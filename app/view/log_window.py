import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import FluentStyleSheet, PushButton, TextEdit, isDarkTheme

from app.config import LOG_PATH, RESOURCE_PATH


class LogWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("日志查看器")
        self.resize(800, 600)

        FluentStyleSheet.FLUENT_WINDOW.apply(self)

        theme = "dark" if isDarkTheme() else "light"
        with open(
            RESOURCE_PATH / "assets" / "qss" / theme / "demo.qss", encoding="utf-8"
        ) as f:
            self.setStyleSheet(f.read())

        # 设置为非模态对话框
        self.setWindowModality(Qt.NonModal)  # type: ignore
        # 设置窗口标志
        self.setWindowFlags(
            Qt.Window  # type: ignore  # 让窗口成为独立窗口
            | Qt.WindowCloseButtonHint  # type: ignore  # 添加关闭按钮
            | Qt.WindowMinMaxButtonsHint  # type: ignore  # 添加最小化最大化按钮
        )
        # 创建主布局
        layout = QVBoxLayout(self)

        # 创建顶部按钮布局
        top_layout = QHBoxLayout()
        self.open_folder_btn = PushButton("打开日志文件夹", self)
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        top_layout.addWidget(self.open_folder_btn)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # 创建文本编辑器用于显示日志
        self.log_text = TextEdit(self)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        # 设置定时器用于更新日志
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_log)
        self.timer.start(500)  # 每2秒更新一次

        # 获取日志文件路径并打开文件
        self.log_path = LOG_PATH / "app.log"
        try:
            self.log_file = open(self.log_path, "r", encoding="utf-8")
            self.load_last_lines(20480)
            self.log_text.moveCursor(QTextCursor.End)
            self.log_text.insertPlainText(f"\n{'=' * 25}以上是历史日志{'=' * 25}\n\n")
        except Exception as e:
            self.log_file = None
            self.log_text.setPlainText(f"打开日志文件失败: {str(e)}")

        # 添加文件大小跟踪
        self.last_position = self.log_file.tell()
        self.max_lines = 100  # 最多显示100行

        self.auto_scroll = True  # 添加自动滚动标志

        # 监听滚动条变化
        self.log_text.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

        # # 初始加载日志
        # self.update_log()

    def load_last_lines(self, read_size):
        """加载文件最后的内容
        Args:
            read_size: 要读取的字节数，比如102400表示读取最后100KB
        """
        try:
            # 移动到文件末尾
            self.log_file.seek(0, 2)
            file_size = self.log_file.tell()

            # 向前读取指定大小或整个文件
            read_size = min(read_size, file_size)

            # 从文件开头读取以确保不会破坏UTF-8编码
            self.log_file.seek(0)
            content = self.log_file.read()

            # 只保留最后一部分内容
            if len(content) > read_size:
                content = content[-read_size:]
                # 找到第一个完整的行
                newline_pos = content.find("\n")
                if newline_pos != -1:
                    content = content[newline_pos + 1 :]

            self.last_position = self.log_file.tell()
            self.log_text.moveCursor(QTextCursor.End)
            self.log_text.setPlainText(content)

            # 滚动到底部
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )

        except Exception as e:
            self.log_text.setPlainText(f"读取日志文件失败: {str(e)}")

    # def closeEvent(self, event):
    #     # 关闭窗口时同时关闭文件和定时器
    #     self.timer.stop()
    #     if self.log_file:
    #         self.log_file.close()
    #     event.accept()

    def on_scroll_changed(self, value):
        """监听滚动条变化"""
        scrollbar = self.log_text.verticalScrollBar()
        max_value = scrollbar.maximum()
        self.auto_scroll = value <= max_value and value >= max_value * 0.85

    def update_log(self):
        """更新日志内容"""
        if not self.log_file:
            return

        try:
            # 移动到上次读取的位置
            self.log_file.seek(self.last_position)
            new_content = self.log_file.read()

            if new_content:
                # 按行分割内容
                lines = new_content.splitlines(True)  # keepends=True 保留换行符
                for line in lines:
                    self.log_text.moveCursor(QTextCursor.End)
                    self.log_text.insertPlainText(line)
                    # time.sleep(0.02)
                    self.log_text.repaint()

                self.last_position = self.log_file.tell()

                if self.auto_scroll:
                    self.log_text.verticalScrollBar().setValue(
                        self.log_text.verticalScrollBar().maximum()
                    )

        except Exception as e:
            self.log_text.setPlainText(f"读取日志文件出错: {str(e)}")

    def open_log_folder(self):
        """打开日志文件所在文件夹"""
        import platform

        if platform.system() == "Windows":
            os.startfile(str(LOG_PATH))  # type: ignore
        elif platform.system() == "Darwin":  # macOS
            import subprocess

            subprocess.run(["open", str(LOG_PATH)])
        else:  # Linux
            import subprocess

            subprocess.run(["xdg-open", str(LOG_PATH)])
