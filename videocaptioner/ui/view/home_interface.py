from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import SegmentedWidget

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.llm.context import generate_task_id
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.view.subtitle_interface import SubtitleInterface
from videocaptioner.ui.view.task_creation_interface import TaskCreationInterface
from videocaptioner.ui.view.transcription_interface import TranscriptionInterface
from videocaptioner.ui.view.video_synthesis_interface import VideoSynthesisInterface

logger = setup_logger("home_interface")


class HomeInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_task_id: Optional[str] = None  # 当前流程的任务 ID
        # 当前流程的任务目录：转录/字幕中间产物落盘处，链尾（合成页）负责清理
        self._current_task_dir: Optional[str] = None

        self.setObjectName("HomeInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]

        # 创建分段控件和堆叠控件
        self.pivot = SegmentedWidget(self)
        self.pivot.setObjectName("homePivot")
        self.pivot.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.stackedWidget = QStackedWidget(self)
        self.stackedWidget.setObjectName("homeStack")
        self.vBoxLayout = QVBoxLayout(self)

        # 添加子界面
        self.task_creation_interface = TaskCreationInterface(self)
        self.transcription_interface = TranscriptionInterface(self)
        self.subtitle_optimization_interface = SubtitleInterface(self)
        self.video_synthesis_interface = VideoSynthesisInterface(self)

        self.addSubInterface(
            self.task_creation_interface, "TaskCreationInterface", self.tr("任务创建")
        )
        self.addSubInterface(
            self.transcription_interface, "TranscriptionInterface", self.tr("语音转录")
        )
        self.addSubInterface(
            self.subtitle_optimization_interface,
            "SubtitleInterface",
            self.tr("字幕优化与翻译"),
        )
        self.addSubInterface(
            self.video_synthesis_interface,
            "VideoSynthesisInterface",
            self.tr("字幕视频合成"),
        )

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

        self.stackedWidget.currentChanged.connect(self.onCurrentIndexChanged)
        self.stackedWidget.setCurrentWidget(self.task_creation_interface)
        self.pivot.setCurrentItem("TaskCreationInterface")

        self.task_creation_interface.finished.connect(self.switch_to_transcription)
        self.transcription_interface.finished.connect(
            self.switch_to_subtitle_optimization
        )
        self.subtitle_optimization_interface.finished.connect(
            self.switch_to_video_synthesis
        )
        self._sync_style()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_style()

    def _sync_style(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QWidget#HomeInterface {{
                background: {palette.bg};
            }}
            /* 只作用于主页自己的页面栈：未限定的 QStackedWidget 规则会级联进
               子页面内部的栈，把面板中间“挖空”成页面底色。 */
            QStackedWidget#homeStack {{
                background: {palette.bg};
                border: none;
            }}
            SegmentedWidget#homePivot {{
                background: {palette.panel};
                border: 1px solid {palette.line_soft};
                border-radius: 8px;
            }}
            SegmentedWidget#homePivot QPushButton {{
                color: {palette.muted};
                background: transparent;
                border: none;
                min-height: 36px;
                font-weight: bold;
            }}
            SegmentedWidget#homePivot QPushButton:hover,
            SegmentedWidget#homePivot QPushButton:checked {{
                color: {palette.text};
                background: {palette.selected};
            }}
            SegmentedWidget#homePivot QLabel {{
                color: {palette.text};
                background: transparent;
            }}
            """
        )

    def switch_to_transcription(self, file_path, subtitle_path=None):
        # 流程开始，生成新的 task_id 与任务目录
        self._current_task_id = generate_task_id()
        self._current_task_dir = None

        # 下载时带回的字幕可直接用时跳过转录（路径由下载线程显式传递）
        if subtitle_path and self._subtitle_usable(str(subtitle_path)):
            self.switch_to_subtitle_optimization(str(subtitle_path), file_path)
            return

        self._current_task_dir = TaskFactory.new_task_dir(file_path, "transcribe")
        transcribe_task = TaskFactory.create_transcribe_task(
            file_path,
            need_next_task=True,
            task_id=self._current_task_id,
            task_dir=self._current_task_dir,
        )
        self.transcription_interface.set_task(transcribe_task)
        self.transcription_interface.process()
        self.stackedWidget.setCurrentWidget(self.transcription_interface)
        self.pivot.setCurrentItem("TranscriptionInterface")

    @staticmethod
    def _subtitle_usable(subtitle_path: str) -> bool:
        """下载字幕必须可解析且非空：站点可能返回弹幕 xml 或空文件。"""
        if not Path(subtitle_path).exists():
            return False
        try:
            segments = ASRData.from_subtitle_file(subtitle_path).segments
        except Exception:
            logger.warning("下载字幕无法解析，转为转录：%s", subtitle_path)
            return False
        if not segments:
            logger.warning("下载字幕为空，转为转录：%s", subtitle_path)
            return False
        return True

    def switch_to_subtitle_optimization(self, file_path, video_path):
        # 继续使用同一个 task_id / 任务目录（下载字幕跳转录时这里才建目录）
        if not self._current_task_dir:
            self._current_task_dir = TaskFactory.new_task_dir(video_path or file_path, "transcribe")
        subtitle_task = TaskFactory.create_subtitle_task(
            file_path,
            video_path,
            need_next_task=True,
            task_id=self._current_task_id,
            task_dir=self._current_task_dir,
        )
        self.subtitle_optimization_interface.set_task(subtitle_task)
        self.subtitle_optimization_interface.process()
        self.stackedWidget.setCurrentWidget(self.subtitle_optimization_interface)
        self.pivot.setCurrentItem("SubtitleInterface")

    def switch_to_video_synthesis(self, video_path, subtitle_path):
        # 继续使用同一个 task_id；任务目录交给合成页在收尾时清理
        synthesis_task = TaskFactory.create_synthesis_task(
            video_path,
            subtitle_path,
            need_next_task=True,
            task_id=self._current_task_id,
            task_dir=self._current_task_dir,
        )
        self._current_task_id = None  # 流程结束
        self._current_task_dir = None
        self.video_synthesis_interface.set_task(synthesis_task)
        self.video_synthesis_interface.process()
        self.stackedWidget.setCurrentWidget(self.video_synthesis_interface)
        self.pivot.setCurrentItem("VideoSynthesisInterface")

    def addSubInterface(self, widget, objectName, text):
        # 添加子界面到堆叠控件和分段控件
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(
            routeKey=objectName,
            text=text,
            onClick=lambda: self.stackedWidget.setCurrentWidget(widget),
        )

    def onCurrentIndexChanged(self, index):
        # 当堆叠控件的当前索引改变时，更新分段控件的当前项
        widget = self.stackedWidget.widget(index)
        if widget:
            self.pivot.setCurrentItem(widget.objectName())

    def closeEvent(self, event):
        # 关闭事件，关闭所有子界面
        self.task_creation_interface.close()
        self.transcription_interface.close()
        self.subtitle_optimization_interface.close()
        self.video_synthesis_interface.close()
        super().closeEvent(event)
