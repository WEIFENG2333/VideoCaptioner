# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path
import subprocess
from ..common.config import cfg

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QApplication,
                             QFileDialog)
from qfluentwidgets import (CardWidget, LineEdit, BodyLabel,
                            InfoBar, InfoBarPosition, ProgressBar, PushButton)

from app.core.thread.create_task_thread import CreateTaskThread
from app.core.thread.video_synthesis_thread import VideoSynthesisThread
from ..core.entities import SupportedVideoFormats, SupportedSubtitleFormats
from ..core.entities import Task

current_dir = Path(__file__).parent.parent
SUBTITLE_STYLE_DIR = current_dir / "resource" / "subtitle_style"


class VideoSynthesisInterface(QWidget):
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoSynthesisInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)  # 启用拖放功能
        self.setup_ui()
        self.setup_style()
        self.set_value()
        self.setup_signals()
        self.task = None

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(20)

        # 配置卡片
        self.config_card = CardWidget(self)
        self.config_layout = QVBoxLayout(self.config_card)
        self.config_layout.setContentsMargins(20, 20, 20, 20)
        self.config_layout.setSpacing(20)

        # 字幕文件选择
        self.subtitle_layout = QHBoxLayout()
        self.subtitle_layout.setSpacing(15)
        self.subtitle_label = BodyLabel(self.tr("字幕文件"), self)
        self.subtitle_input = LineEdit(self)
        self.subtitle_input.setPlaceholderText(self.tr("选择或者拖拽字幕文件"))
        self.subtitle_input.setAcceptDrops(True)  # 启用拖放
        self.subtitle_button = PushButton(self.tr("浏览"))
        self.subtitle_layout.addWidget(self.subtitle_label)
        self.subtitle_layout.addWidget(self.subtitle_input)
        self.subtitle_layout.addWidget(self.subtitle_button)
        self.config_layout.addLayout(self.subtitle_layout)

        # 视频文件选择
        self.video_layout = QHBoxLayout()
        self.video_layout.setSpacing(15)
        self.video_label = BodyLabel(self.tr("视频文件"), self)
        self.video_input = LineEdit(self)
        self.video_input.setPlaceholderText(self.tr("选择或者拖拽视频文件"))
        self.video_input.setAcceptDrops(True)  # 启用拖放
        self.video_button = PushButton(self.tr("浏览"))
        self.video_layout.addWidget(self.video_label)
        self.video_layout.addWidget(self.video_input)
        self.video_layout.addWidget(self.video_button)
        self.config_layout.addLayout(self.video_layout)

        self.main_layout.addWidget(self.config_card)

        # 合成按钮和打开文件夹按钮
        self.button_layout = QHBoxLayout()
        self.synthesize_button = PushButton(self.tr("开始合成"), self)
        self.open_folder_button = PushButton(self.tr("打开视频文件夹"), self)
        self.button_layout.addWidget(self.synthesize_button)
        self.button_layout.addWidget(self.open_folder_button)
        self.main_layout.addLayout(self.button_layout)

        self.main_layout.addStretch(1)

        # 底部进度条和状态信息
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("就绪"), self)
        self.status_label.setMinimumWidth(100)  # 设置最小宽度
        self.status_label.setAlignment(Qt.AlignCenter)  # 设置文本居中对齐
        self.bottom_layout.addWidget(self.progress_bar, 1)  # 进度条使用剩余空间
        self.bottom_layout.addWidget(self.status_label)  # 状态标签使用固定宽度
        self.main_layout.addLayout(self.bottom_layout)

    def setup_style(self):
        self.subtitle_input.focusOutEvent = lambda e: super(LineEdit, self.subtitle_input).focusOutEvent(e)
        self.subtitle_input.paintEvent = lambda e: super(LineEdit, self.subtitle_input).paintEvent(e)
        self.subtitle_input.setStyleSheet(self.subtitle_input.styleSheet() + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """)

        self.video_input.focusOutEvent = lambda e: super(LineEdit, self.video_input).focusOutEvent(e)
        self.video_input.paintEvent = lambda e: super(LineEdit, self.video_input).paintEvent(e)
        self.video_input.setStyleSheet(self.video_input.styleSheet() + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """)

    def setup_signals(self):
        # 文件选择相关信号
        self.subtitle_button.clicked.connect(self.choose_subtitle_file)
        self.video_button.clicked.connect(self.choose_video_file)

        # 合成和文件夹相关信号
        self.synthesize_button.clicked.connect(self.process)
        self.open_folder_button.clicked.connect(self.open_video_folder)

    def set_value(self):
        pass

    def choose_subtitle_file(self):
        # 构建文件过滤器
        subtitle_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedSubtitleFormats)
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("选择字幕文件"), cfg.last_open_dir.value, filter_str)
        if file_path:
            self.subtitle_input.setText(file_path)
            # Save this file's directory for later use
            file_dir = str( Path(file_path).parent )
            if file_dir != cfg.last_open_dir.value:
                cfg.last_open_dir.value = file_dir


    def choose_video_file(self):
        # 构建文件过滤器
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        filter_str = f"{self.tr('视频文件')} ({video_formats})"

        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("选择视频文件"), cfg.last_open_dir.value, filter_str)
        if file_path:
            self.video_input.setText(file_path)
            # Save this file's directory for later use
            file_dir = str( Path(file_path).parent )
            if file_dir != cfg.last_open_dir.value:
                cfg.last_open_dir.value = file_dir

    def create_task(self):
        subtitle_file = self.subtitle_input.text()
        video_file = self.video_input.text()
        if not subtitle_file or not video_file:
            InfoBar.error(
                self.tr("错误"),
                self.tr("请选择字幕文件和视频文件"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )
            return None

        self.task = CreateTaskThread.create_video_synthesis_task(subtitle_file, video_file)
        return self.task

    def set_task(self, task: Task):
        self.task = task
        self.update_info()

    def update_info(self):
        if self.task:
            self.video_input.setText(self.task.file_path)
            self.subtitle_input.setText(self.task.result_subtitle_save_path)

    def process(self):
        self.synthesize_button.setEnabled(False)
        self.progress_bar.resume()
        
        if not self.task:
            self.task = None
            self.create_task()
        if self.task.file_path != self.video_input.text() or self.task.result_subtitle_save_path != self.subtitle_input.text():
            self.task = None
            self.create_task()

        if self.task:
            self.video_synthesis_thread = VideoSynthesisThread(self.task)
            self.video_synthesis_thread.finished.connect(self.on_video_synthesis_finished)
            self.video_synthesis_thread.progress.connect(self.on_video_synthesis_progress)
            self.video_synthesis_thread.error.connect(self.on_video_synthesis_error)
            self.video_synthesis_thread.start()
        else:
            InfoBar.error(
                self.tr("错误"),
                self.tr("无法创建任务"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )

    def on_video_synthesis_finished(self, task):
        self.synthesize_button.setEnabled(True)
        self.open_video_folder()
        InfoBar.success(
            self.tr("成功"),
            self.tr("视频合成已完成"),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )
        self.task.status = Task.Status.COMPLETED

    def on_video_synthesis_progress(self, progress, message):
        self.progress_bar.setValue(progress)
        self.status_label.setText(message)

    def on_video_synthesis_error(self, error):
        self.synthesize_button.setEnabled(True)
        self.progress_bar.error()
        InfoBar.error(
            self.tr("错误"),
            str(error),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def open_video_folder(self):
        video_folder= Path(self.video_input.text()).parent
        if video_folder.exists():
            # Cross-platform folder opening
            if sys.platform == "win32":
                os.startfile(str(video_folder))
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", str(video_folder)])
            else:  # Linux
                subprocess.run(["xdg-open", str(video_folder)])
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可用的视频文件夹"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )

    def dragEnterEvent(self, event):
        """拖拽进入事件处理"""
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent):
        """拖拽放下事件处理"""
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            if file_ext in {fmt.value for fmt in SupportedSubtitleFormats}:
                self.subtitle_input.setText(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("字幕文件已放入输入框"),
                    duration=2000,
                    parent=self
                )
                break
            elif file_ext in {fmt.value for fmt in SupportedVideoFormats}:
                self.video_input.setText(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("视频文件已输入框"),
                    duration=2000,
                    parent=self
                )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    self.tr("请拖入视频或者字幕文件"),
                    duration=3000,
                    parent=self
                )


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = VideoSynthesisInterface()
    window.resize(600, 400)  # 设置窗口大小
    window.show()
    sys.exit(app.exec_())
