# -*- coding: utf-8 -*-
import os
import sys
from urllib.parse import urlparse

from PyQt5.QtCore import QStandardPaths, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    HyperlinkButton,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ProgressBar,
    ToolButton,
)

from app.common.config import cfg
from app.components.DonateDialog import DonateDialog
from app.components.LanguageSettingDialog import LanguageSettingDialog
from app.config import APPDATA_PATH, ASSETS_PATH, VERSION
from app.core.entities import (
    LLMServiceEnum,
    SupportedAudioFormats,
    SupportedVideoFormats,
    TranscribeModelEnum,
)
from app.thread.video_download_thread import VideoDownloadThread
from app.view.log_window import LogWindow

LOGO_PATH = ASSETS_PATH / "logo.png"


class TaskCreationInterface(QWidget):
    """
    任务创建界面类，用于创建和配置任务。
    """

    finished = pyqtSignal(str)  # 该信号用于在任务创建完成后通知主窗口

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.log_window = None

        self.setObjectName("TaskCreationInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore
        self.setAcceptDrops(True)

        self.setup_ui()
        self.setup_values()
        self.setup_signals()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(50)
        self.main_layout.addSpacing(120)
        self.setup_logo()
        self.setup_search_layout()
        self.setup_status_layout()
        self.setup_info_label()

    def setup_logo(self):
        self.logo_label = QLabel(self)
        self.logo_pixmap = QPixmap(str(LOGO_PATH))
        self.logo_pixmap = self.logo_pixmap.scaled(
            150,
            150,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.SmoothTransformation,  # type: ignore
        )

        self.logo_label.setPixmap(self.logo_pixmap)
        self.logo_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self.main_layout.addWidget(self.logo_label)
        self.main_layout.addSpacing(10)

    def setup_search_layout(self):
        self.search_layout = QHBoxLayout()
        self.search_layout.setContentsMargins(80, 0, 80, 0)
        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText(self.tr("请拖拽文件或输入视频URL"))
        self.search_input.setFixedHeight(40)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.focusOutEvent = lambda e: super(
            LineEdit, self.search_input
        ).focusOutEvent(e)
        self.search_input.paintEvent = lambda e: super(
            LineEdit, self.search_input
        ).paintEvent(e)
        self.search_input.setStyleSheet(
            self.search_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 18px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
            
        """
        )
        self.start_button = ToolButton(FluentIcon.FOLDER, self)
        self.start_button.setFixedSize(40, 40)
        self.start_button.setStyleSheet(
            self.start_button.styleSheet()
            + """
            QToolButton {
                border-radius: 20px;
                background-color: #2F8D63;
            }
            QToolButton:hover {
                background-color: #2E805C;
            }
            QToolButton:pressed {
                background-color: #2E905C;
            }
        """
        )
        self.search_layout.addWidget(self.search_input)
        self.search_layout.addWidget(self.start_button)
        self.search_layout.setSpacing(10)
        self.main_layout.addLayout(self.search_layout)
        self.main_layout.addSpacing(100)

    def setup_status_layout(self):
        self.status_layout = QVBoxLayout()
        self.status_layout.setContentsMargins(50, 0, 30, 5)
        self.status_layout.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)  # type: ignore
        self.status_label = BodyLabel(self.tr("准备就绪"), self)
        self.status_label.setStyleSheet("font-size: 14px; color: #888888;")
        self.status_layout.addWidget(self.status_label, 0, Qt.AlignCenter)  # type: ignore
        self.progress_bar = ProgressBar(self)
        self.status_label.hide()
        self.progress_bar.hide()
        self.progress_bar.setFixedWidth(300)
        self.status_layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)  # type: ignore

        self.main_layout.addStretch(1)
        self.main_layout.addLayout(self.status_layout)

    def setup_info_label(self):
        # 创建底部容器
        bottom_container = QWidget()
        bottom_layout = QHBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # 创建日志按钮
        self.log_button = HyperlinkButton(url="", text=self.tr("查看日志"), parent=self)
        self.log_button.setStyleSheet(
            self.log_button.styleSheet()
            + """
            QPushButton {
                font-size: 12px;
                color: #2F8D63;
                text-decoration: underline;
            }
        """
        )

        # 创建捐助按钮
        self.donate_button = HyperlinkButton(url="", text=self.tr("捐助"), parent=self)
        self.donate_button.setStyleSheet(
            self.donate_button.styleSheet()
            + """
            QPushButton {
                font-size: 12px;
                color: #2F8D63;
                text-decoration: underline;
            }
        """
        )

        # 添加版权信息标签
        self.info_label = BodyLabel(
            self.tr(f"©VideoCaptioner {VERSION} • By Weifeng"), self
        )
        self.info_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self.info_label.setStyleSheet("font-size: 12px; color: #888888;")

        # 将组件添加到底部布局
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.info_label)
        bottom_layout.addWidget(self.log_button)
        bottom_layout.addWidget(self.donate_button)
        bottom_layout.addStretch()

        self.main_layout.addStretch()
        self.main_layout.addWidget(bottom_container)

    def setup_signals(self):
        self.start_button.clicked.connect(self.on_start_clicked)
        self.search_input.textChanged.connect(self.on_search_input_changed)
        self.log_button.clicked.connect(self.show_log_window)
        self.donate_button.clicked.connect(self.show_donate_dialog)

    def setup_values(self):
        self.search_input.setText("")
        # 根据当前选择的LLM服务获取对应的配置
        current_service = cfg.llm_service.value
        if current_service == LLMServiceEnum.PUBLIC:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("为确保字幕修正的准确性，建议到设置中配置自己的API"),
                duration=6000,
                parent=self,
                position=InfoBarPosition.BOTTOM_RIGHT,
            )

    def on_start_clicked(self):
        if self.start_button._icon == FluentIcon.FOLDER:
            desktop_path = QStandardPaths.writableLocation(
                QStandardPaths.DesktopLocation
            )
            file_dialog = QFileDialog()

            # 构建文件过滤器
            video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
            audio_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedAudioFormats)
            filter_str = f"{self.tr('媒体文件')} ({video_formats} {audio_formats});;{self.tr('视频文件')} ({video_formats});;{self.tr('音频文件')} ({audio_formats})"

            file_path, _ = file_dialog.getOpenFileName(
                self, self.tr("选择媒体文件"), desktop_path, filter_str
            )
            if file_path:
                self.search_input.setText(file_path)
            return

        self.process()

    def on_search_input_changed(self):
        if self.search_input.text():
            self.start_button.setIcon(FluentIcon.PLAY)
        else:
            self.start_button.setIcon(FluentIcon.FOLDER)

    def dragEnterEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedVideoFormats} | {
                fmt.value for fmt in SupportedAudioFormats
            }
            is_supported = file_ext in supported_formats

            if is_supported:
                self.search_input.setText(file_path)
                self.status_label.setText(self.tr("导入成功"))
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("导入媒体文件成功"),
                    duration=1500,
                    parent=self,
                )
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext,
                    self.tr("不支持该文件格式"),
                    duration=3000,
                    parent=self,
                )

    def create_task(self):
        search_input = self.search_input.text()
        if os.path.isfile(search_input):
            self._process_file(search_input)
        elif self._is_valid_url(search_input):
            self._process_url(search_input)
        else:
            InfoBar.error(
                self.tr("错误"),
                self.tr("请输入有效的文件路径或视频URL"),
                duration=3000,
                parent=self,
            )

    def _is_valid_url(self, url):
        try:
            result = urlparse(url)
            return result.scheme in ("http", "https") and bool(result.netloc)
        except ValueError:
            return False

    def _process_file(self, file_path):
        self.finished.emit(file_path)

    def _process_url(self, url):
        # 检测 cookies.txt 文件
        cookiefile_path = APPDATA_PATH / "cookies.txt"
        if not cookiefile_path.exists():
            InfoBar.warning(
                self.tr("警告"),
                self.tr("建议根据文档配置cookies.txt文件，以可以下载高清视频"),
                duration=5000,
                parent=self,
            )

        # 创建视频下载线程
        self.video_download_thread = VideoDownloadThread(url, str(cfg.work_dir.value))
        self.video_download_thread.finished.connect(self.on_video_download_finished)
        self.video_download_thread.progress.connect(self.on_create_task_progress)
        self.video_download_thread.error.connect(self.on_create_task_error)
        self.video_download_thread.start()

        InfoBar.info(
            self.tr("开始下载"), self.tr("开始下载视频..."), duration=3000, parent=self
        )

    def on_video_download_finished(self, video_file_path):
        """视频下载完成的回调函数"""
        if video_file_path:
            self.finished.emit(video_file_path)
            InfoBar.success(
                self.tr("下载成功"),
                self.tr("视频下载完成，开始自动处理..."),
                duration=2000,
                position=InfoBarPosition.BOTTOM,
                parent=self.parent(),
            )
        else:
            InfoBar.error(
                self.tr("错误"), self.tr("视频下载失败"), duration=3000, parent=self
            )

    def on_create_task_progress(self, value, status):
        self.progress_bar.show()
        self.status_label.show()
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def on_create_task_error(self, error):
        InfoBar.error(self.tr("错误"), self.tr(error), duration=5000, parent=self)

    def set_task(self, task):
        self.task = task
        self.update_info()

    def update_info(self):
        if self.task:
            self.search_input.setText(self.task.file_path)

    def process(self):
        search_input = self.search_input.text()

        # 检查是否需要显示语言设置对话框
        need_language_settings = cfg.transcribe_model.value in [
            TranscribeModelEnum.WHISPER_CPP,
            TranscribeModelEnum.WHISPER_API,
            TranscribeModelEnum.FASTER_WHISPER,
        ]
        if need_language_settings and not self.show_language_settings():
            return

        if os.path.isfile(search_input):
            self._process_file(search_input)
        elif self._is_valid_url(search_input):
            self._process_url(search_input)
        else:
            InfoBar.error(
                self.tr("错误"),
                self.tr("请输入音视频文件路径或URL"),
                duration=3000,
                parent=self,
            )

    def show_language_settings(self):
        """显示语言设置对话框"""
        dialog = LanguageSettingDialog(self.window())
        if dialog.exec_():
            return True
        return False

    def show_log_window(self):
        """显示日志窗口"""
        if self.log_window is None:
            self.log_window = LogWindow()
        if self.log_window.isHidden():
            self.log_window.show()
        else:
            self.log_window.activateWindow()

    def show_donate_dialog(self):
        """显示捐助窗口"""
        donate_dialog = DonateDialog(self)
        donate_dialog.exec_()


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)  # type: ignore
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)  # type: ignore

    app = QApplication(sys.argv)
    window = TaskCreationInterface()
    window.show()
    sys.exit(app.exec_())
