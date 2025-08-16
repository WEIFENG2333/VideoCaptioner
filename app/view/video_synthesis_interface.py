# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CommandBar,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ToolTipFilter,
    ToolTipPosition,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.core.entities import (
    SupportedSubtitleFormats,
    SupportedVideoFormats,
    SynthesisTask,
)
from app.core.task_factory import TaskFactory
from app.core.utils.platform_utils import open_folder
from app.thread.video_synthesis_thread import VideoSynthesisThread

current_dir = Path(__file__).parent.parent
SUBTITLE_STYLE_DIR = current_dir / "resource" / "subtitle_style"


class VideoSynthesisInterface(QWidget):
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoSynthesisInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore
        self.setAcceptDrops(True)  # 启用拖放功能
        self.setup_ui()
        self.setup_style()
        self.set_value()
        self.setup_signals()
        self.task = None

        self.installEventFilter(ToolTipFilter(self, 100, ToolTipPosition.BOTTOM))

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(20)

        # 创建顶部布局
        top_layout = QHBoxLayout()

        # 添加顶部命令栏
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)  # type: ignore
        top_layout.addWidget(self.command_bar, 1)  # 设置stretch为1，使其尽可能占用空间

        # 设置命令栏
        self._setup_command_bar()

        # 添加开始合成按钮到水平布局
        self.synthesize_button = PrimaryPushButton(
            self.tr("开始合成"), self, icon=FIF.PLAY
        )
        self.synthesize_button.setFixedHeight(34)
        top_layout.addWidget(self.synthesize_button)

        self.main_layout.addLayout(top_layout)

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

        self.main_layout.addStretch(1)

        # 底部进度条和状态信息
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("就绪"), self)
        self.status_label.setMinimumWidth(100)  # 设置最小宽度
        self.status_label.setAlignment(Qt.AlignCenter)  # type: ignore  # 设置文本居中对齐
        self.bottom_layout.addWidget(self.progress_bar, 1)  # 进度条使用剩余空间
        self.bottom_layout.addWidget(self.status_label)  # 状态标签使用固定宽度
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_command_bar(self):
        """设置顶部命令栏"""
        # 添加软字幕选项
        self.soft_subtitle_action = Action(
            FIF.FONT,
            self.tr("软字幕"),
            triggered=self.on_soft_subtitle_changed,
            checkable=True,
        )
        self.soft_subtitle_action.setToolTip(self.tr("使用软字幕嵌入视频"))
        self.command_bar.addAction(self.soft_subtitle_action)

        # 添加分隔符
        self.command_bar.addSeparator()

        # 添加是否合成视频选项
        self.need_video_action = Action(
            FIF.VIDEO,
            self.tr("合成视频"),
            triggered=self.on_need_video_changed,
            checkable=True,
        )
        self.need_video_action.setToolTip(self.tr("是否生成新的视频文件"))
        self.command_bar.addAction(self.need_video_action)

        self.command_bar.addSeparator()

        # 添加打开文件夹按钮
        folder_action = Action(FIF.FOLDER, "", triggered=self.open_video_folder)
        folder_action.setToolTip(self.tr("打开输出文件夹"))
        self.command_bar.addAction(folder_action)

        # 添加文件选择按钮
        file_action = Action(FIF.FOLDER_ADD, "", triggered=self.choose_video_file)
        file_action.setToolTip(self.tr("选择视频文件"))
        self.command_bar.addAction(file_action)

    def setup_style(self):
        self.subtitle_input.focusOutEvent = lambda e: super(
            LineEdit, self.subtitle_input
        ).focusOutEvent(e)
        self.subtitle_input.paintEvent = lambda e: super(
            LineEdit, self.subtitle_input
        ).paintEvent(e)
        self.subtitle_input.setStyleSheet(
            self.subtitle_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """
        )

        self.video_input.focusOutEvent = lambda e: super(
            LineEdit, self.video_input
        ).focusOutEvent(e)
        self.video_input.paintEvent = lambda e: super(
            LineEdit, self.video_input
        ).paintEvent(e)
        self.video_input.setStyleSheet(
            self.video_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """
        )

    def setup_signals(self):
        # 文件选择相关信号
        self.subtitle_button.clicked.connect(self.choose_subtitle_file)
        self.video_button.clicked.connect(self.choose_video_file)

        # 合成和文件夹相关信号
        self.synthesize_button.clicked.connect(
            lambda: self.start_video_synthesis(need_create_task=True)
        )

        # 全局 signalBus
        signalBus.soft_subtitle_changed.connect(self.on_soft_subtitle_changed)
        signalBus.need_video_changed.connect(self.on_need_video_changed)

    def set_value(self):
        """设置初始值"""
        self.soft_subtitle_action.setChecked(cfg.soft_subtitle.value)
        self.need_video_action.setChecked(cfg.need_video.value)

    def on_soft_subtitle_changed(self, checked: bool):
        """处理软字幕选项变更"""
        cfg.set(cfg.soft_subtitle, checked)
        self.soft_subtitle_action.setChecked(checked)

    def on_need_video_changed(self, checked: bool):
        """处理视频合成选项变更"""
        cfg.set(cfg.need_video, checked)
        self.need_video_action.setChecked(checked)

    def choose_subtitle_file(self):
        # 构建文件过滤器
        subtitle_formats = " ".join(
            f"*.{fmt.value}" for fmt in SupportedSubtitleFormats
        )
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", filter_str
        )
        if file_path:
            self.subtitle_input.setText(file_path)

    def choose_video_file(self):
        # 构建文件过滤器
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        filter_str = f"{self.tr('视频文件')} ({video_formats})"

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择视频文件"), "", filter_str
        )
        if file_path:
            self.video_input.setText(file_path)

    def create_task(self):
        subtitle_file = self.subtitle_input.text()
        video_file = self.video_input.text()
        if not subtitle_file or not video_file:
            InfoBar.error(
                self.tr("错误"),
                self.tr("请选择字幕文件和视频文件"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        return TaskFactory.create_synthesis_task(video_file, subtitle_file)

    def set_task(self, task: SynthesisTask):
        self.task = task
        self.update_info()

    def update_info(self):
        if self.task:
            self.video_input.setText(self.task.video_path)
            self.subtitle_input.setText(self.task.subtitle_path)

    def start_video_synthesis(self, need_create_task=True):
        self.synthesize_button.setEnabled(False)
        self.progress_bar.resume()
        if need_create_task:
            self.task = self.create_task()

        if self.task:
            self.video_synthesis_thread = VideoSynthesisThread(self.task)
            self.video_synthesis_thread.finished.connect(
                self.on_video_synthesis_finished
            )
            self.video_synthesis_thread.progress.connect(
                self.on_video_synthesis_progress
            )
            self.video_synthesis_thread.error.connect(self.on_video_synthesis_error)
            self.video_synthesis_thread.start()
        else:
            self.synthesize_button.setEnabled(True)

    def process(self):
        self.start_video_synthesis(need_create_task=False)

    def on_video_synthesis_finished(self, task):
        self.synthesize_button.setEnabled(True)
        self.open_video_folder()
        InfoBar.success(
            self.tr("成功"),
            self.tr("视频合成已完成"),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

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
            parent=self,
        )

    def open_video_folder(self):
        if self.task and self.task.output_path:
            file_path = Path(self.task.output_path)
            target_dir = str(
                file_path.parent
                if file_path.exists()
                else (
                    Path(str(self.task.video_path)).parent
                    if self.task.video_path
                    else file_path.parent
                )
            )
            # Cross-platform folder opening
            open_folder(target_dir)
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可用的视频文件夹"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
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
                    parent=self,
                )
                break
            elif file_ext in {fmt.value for fmt in SupportedVideoFormats}:
                self.video_input.setText(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("视频文件已输入框"),
                    duration=2000,
                    parent=self,
                )
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext,
                    self.tr("请拖入视频或者字幕文件"),
                    duration=3000,
                    parent=self,
                )


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)  # type: ignore
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)  # type: ignore

    app = QApplication(sys.argv)
    window = VideoSynthesisInterface()
    window.resize(600, 400)  # 设置窗口大小
    window.show()
    sys.exit(app.exec_())
