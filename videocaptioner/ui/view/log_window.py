from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import TextEdit

from videocaptioner.config import LOG_PATH
from videocaptioner.core.utils.platform_utils import reveal_in_explorer
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.workbench import WorkbenchButton, apply_font
from videocaptioner.ui.i18n import tr


class LogWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("logwin.title"))
        self.resize(800, 600)

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
        self.open_folder_btn = WorkbenchButton(
            tr("logwin.btn.open_folder"), AppIcon.FOLDER, parent=self
        )
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        top_layout.addWidget(self.open_folder_btn)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # 创建文本编辑器用于显示日志
        self.log_text = TextEdit(self)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        self._sync_style()

        # 设置定时器用于更新日志
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_log)
        self.timer.start(500)  # 每2秒更新一次

        # 获取日志文件路径并打开文件
        self.log_path = LOG_PATH / "app.log"
        try:
            self.log_file = open(self.log_path, "rb")
            self.load_last_lines(20480)
            self.log_text.moveCursor(QTextCursor.End)
            self.log_text.insertPlainText(
                f"\n{'=' * 25}{tr('logwin.history_divider')}{'=' * 25}\n\n"
            )
        except Exception as e:
            self.log_file = None
            self.log_text.setPlainText(tr("logwin.error.open_failed", error=str(e)))

        self.last_position = self.log_file.tell() if self.log_file else 0
        self.auto_scroll = True

        # 监听滚动条变化
        self.log_text.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)


    def load_last_lines(self, read_size):
        """加载文件最后的内容
        Args:
            read_size: 要读取的字节数，比如102400表示读取最后100KB
        """
        try:
            # 只读末尾一段：全量读取在无轮转的大日志上会卡住打开
            self.log_file.seek(0, 2)
            file_size = self.log_file.tell()
            start = max(0, file_size - read_size)
            self.log_file.seek(start)
            content = self.log_file.read().decode("utf-8", errors="replace")
            if start > 0:
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
            self.log_text.setPlainText(tr("logwin.error.read_failed", error=str(e)))

    def _sync_style(self):
        palette = app_palette()
        self.setStyleSheet(f"QWidget {{ background: {palette.bg}; }}")
        apply_font(self.log_text, 13, 500)
        self.log_text.setStyleSheet(
            f"""
            TextEdit {{
                background: {palette.field};
                color: {palette.text};
                border: 1px solid {palette.line};
                border-radius: 10px;
                padding: 10px;
            }}
            """
        )

    def closeEvent(self, event):
        # 关闭时停定时器并关文件，避免后台 timer 持续触发 + 文件句柄泄漏。
        self.timer.stop()
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        super().closeEvent(event)

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
            new_content = self.log_file.read().decode("utf-8", errors="replace")

            if new_content:
                self.log_text.moveCursor(QTextCursor.End)
                self.log_text.insertPlainText(new_content)
                self.last_position = self.log_file.tell()

                if self.auto_scroll:
                    self.log_text.verticalScrollBar().setValue(
                        self.log_text.verticalScrollBar().maximum()
                    )

        except Exception as e:
            self.log_text.setPlainText(tr("logwin.error.update_failed", error=str(e)))

    def open_log_folder(self):
        """打开日志文件所在文件夹"""
        reveal_in_explorer(str(self.log_path))
