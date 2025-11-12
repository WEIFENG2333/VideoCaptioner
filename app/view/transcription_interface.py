# -*- coding: utf-8 -*-

import datetime
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QStandardPaths, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CommandBar,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    PrimaryPushButton,
    ProgressRing,
    PushButton,
    RoundMenu,
    TransparentDropDownPushButton,
    setFont,
)

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.components.LanguageSettingDialog import LanguageSettingDialog
from app.components.transcription_setting_card import TranscriptionSettingCard
from app.components.TranscriptionSettingDialog import TranscriptionSettingDialog
from app.config import RESOURCE_PATH
from app.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from app.core.entities import (
    SupportedAudioFormats,
    SupportedVideoFormats,
    TranscribeModelEnum,
    TranscribeTask,
    VideoInfo,
)
from app.core.task_factory import TaskFactory
from app.core.utils.platform_utils import get_available_transcribe_models, open_folder
from app.thread.transcript_thread import TranscriptThread
from app.thread.video_info_thread import VideoInfoThread

DEFAULT_THUMBNAIL_PATH = RESOURCE_PATH / "assets" / "default_thumbnail.jpg"


class VideoInfoCard(CardWidget):
    finished = pyqtSignal(TranscribeTask)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setup_ui()
        self.setup_signals()
        self.task: Optional[TranscribeTask] = None
        self.video_info: Optional[VideoInfo] = None
        self.transcription_interface = parent
        self.selected_audio_track_index = 0  # 默认选择第一条音轨

    def setup_ui(self) -> None:
        self.setFixedHeight(150)
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(20, 15, 20, 15)
        self.main_layout.setSpacing(20)

        self.setup_thumbnail()
        self.setup_info_layout()
        self.setup_button_layout()

    def setup_thumbnail(self) -> None:
        default_thumbnail_path = os.path.join(DEFAULT_THUMBNAIL_PATH)

        self.video_thumbnail = QLabel(self)
        self.video_thumbnail.setFixedSize(208, 117)
        self.video_thumbnail.setStyleSheet("background-color: #1E1F22;")
        self.video_thumbnail.setAlignment(Qt.AlignCenter)  # type: ignore
        pixmap = QPixmap(default_thumbnail_path).scaled(
            self.video_thumbnail.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.SmoothTransformation,  # type: ignore
        )
        self.video_thumbnail.setPixmap(pixmap)
        self.main_layout.addWidget(self.video_thumbnail, 0, Qt.AlignLeft)  # type: ignore

    def setup_info_layout(self) -> None:
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(3, 8, 3, 8)
        self.info_layout.setSpacing(10)

        self.video_title = BodyLabel(self.tr("请拖入音频或视频文件"), self)
        self.video_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self.video_title.setWordWrap(True)
        self.info_layout.addWidget(self.video_title, alignment=Qt.AlignTop)  # type: ignore

        self.details_layout = QHBoxLayout()
        self.details_layout.setSpacing(15)

        self.resolution_info = self.create_pill_button(self.tr("画质"), 110)
        self.file_size_info = self.create_pill_button(self.tr("文件大小"), 110)
        self.duration_info = self.create_pill_button(self.tr("时长"), 100)
        self.audio_track_button = self.create_pill_button(self.tr("音轨"), 100)
        self.audio_track_button.hide()  # 默认隐藏，只在多音轨时显示

        self.progress_ring = ProgressRing(self)
        self.progress_ring.setFixedSize(20, 20)
        self.progress_ring.setStrokeWidth(4)
        self.progress_ring.hide()

        self.details_layout.addWidget(self.resolution_info)
        self.details_layout.addWidget(self.file_size_info)
        self.details_layout.addWidget(self.duration_info)
        self.details_layout.addWidget(self.audio_track_button)
        self.details_layout.addWidget(self.progress_ring)
        self.details_layout.addStretch(1)
        self.info_layout.addLayout(self.details_layout)
        self.main_layout.addLayout(self.info_layout)  # type: ignore

    def create_pill_button(self, text: str, width: int) -> PillPushButton:
        button = PillPushButton(text, self)
        button.setCheckable(False)
        setFont(button, 11)
        # button.setFixedWidth(width)
        button.setMinimumWidth(50)
        return button

    def setup_button_layout(self) -> None:
        self.button_layout = QVBoxLayout()
        self.open_folder_button = PushButton(self.tr("打开文件夹"), self)
        self.start_button = PrimaryPushButton(self.tr("开始转录"), self)
        self.button_layout.addWidget(self.open_folder_button)
        self.button_layout.addWidget(self.start_button)

        self.start_button.setDisabled(True)

        button_widget = QWidget()
        button_widget.setLayout(self.button_layout)
        button_widget.setFixedWidth(130)
        self.main_layout.addWidget(button_widget)  # type: ignore

    def update_info(self, video_info: VideoInfo) -> None:
        """更新视频信息显示"""
        self.reset_ui()
        self.video_info = video_info

        self.video_title.setText(video_info.file_name.rsplit(".", 1)[0])
        self.resolution_info.setText(
            self.tr("画质: ") + f"{video_info.width}x{video_info.height}"
        )
        file_size_mb = os.path.getsize(video_info.file_path) / 1024 / 1024
        self.file_size_info.setText(self.tr("大小: ") + f"{file_size_mb:.1f} MB")
        duration = datetime.timedelta(seconds=int(video_info.duration_seconds))
        self.duration_info.setText(self.tr("时长: ") + f"{duration}")

        # 更新音轨选择按钮
        self.update_audio_tracks(video_info)

        if self.transcription_interface and self.transcription_interface.is_processing:  # type: ignore
            self.start_button.setEnabled(False)
        else:
            self.start_button.setEnabled(True)
        self.update_thumbnail(video_info.thumbnail_path)

    def update_audio_tracks(self, video_info: VideoInfo) -> None:
        """更新音轨选择按钮"""
        audio_streams = video_info.audio_streams

        if len(audio_streams) > 1:
            # 多音轨，显示选择按钮，默认选择第一条音轨（数组索引0）
            self.selected_audio_track_index = 0
            self.update_audio_track_button_text(audio_streams, 0)

            # 创建下拉菜单
            menu = RoundMenu(parent=self)
            for i, stream in enumerate(audio_streams):
                lang = stream.language

                # 构建菜单项文本（使用序号 i+1）
                text = self.tr("音轨") + str(i + 1)
                if lang:
                    text += f" ({lang})"

                action = Action(text)
                action.triggered.connect(
                    lambda checked, array_idx=i, streams=audio_streams: self.on_audio_track_selected(
                        array_idx, streams
                    )
                )
                menu.addAction(action)

            # 绑定菜单到按钮
            self.audio_track_button.clicked.connect(
                lambda: menu.exec(
                    self.audio_track_button.mapToGlobal(
                        self.audio_track_button.rect().bottomLeft()
                    )
                )
            )
            self.audio_track_button.show()
        else:
            self.audio_track_button.hide()
            self.selected_audio_track_index = 0

    def update_audio_track_button_text(
        self, audio_streams: list, array_index: int
    ) -> None:
        """更新音轨按钮显示文本

        Args:
            audio_streams: 音轨列表
            array_index: 数组索引（0, 1, 2...）
        """
        if array_index < len(audio_streams):
            stream = audio_streams[array_index]
            lang = stream.language
            text = f"{self.tr('音轨')} {array_index + 1}"
            if lang:
                text += f" ({lang})"
            self.audio_track_button.setText(text)

    def on_audio_track_selected(self, array_index: int, audio_streams: list) -> None:
        """音轨选择事件处理

        Args:
            array_index: 数组索引（0, 1, 2...），用于 UI 显示和 ffmpeg -map 0:a:N
            audio_streams: 音轨列表
        """
        self.selected_audio_track_index = array_index  # 保存数组索引，传给 ffmpeg
        self.update_audio_track_button_text(audio_streams, array_index)

    def update_thumbnail(self, thumbnail_path):
        """更新视频缩略图"""
        if not Path(thumbnail_path).exists():
            thumbnail_path = RESOURCE_PATH / "assets" / "audio-thumbnail.png"

        pixmap = QPixmap(str(thumbnail_path)).scaled(
            self.video_thumbnail.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.SmoothTransformation,  # type: ignore
        )
        self.video_thumbnail.setPixmap(pixmap)

    def setup_signals(self) -> None:
        self.start_button.clicked.connect(self.on_start_button_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)

    def show_language_settings(self):
        """显示语言设置对话框"""
        dialog = LanguageSettingDialog(self.window())
        if dialog.exec_():
            return True
        return False

    def on_start_button_clicked(self):
        """开始转录按钮点击事件"""
        if self.task and not self.task.need_next_task:
            need_language_settings = cfg.transcribe_model.value in [
                TranscribeModelEnum.WHISPER_CPP,
                TranscribeModelEnum.WHISPER_API,
                TranscribeModelEnum.FASTER_WHISPER,
            ]
            if need_language_settings and not self.show_language_settings():
                return
        self.progress_ring.setValue(0)
        self.progress_ring.show()
        self.start_button.setDisabled(True)
        self.start_transcription()

    def on_open_folder_clicked(self):
        """打开文件夹按钮点击事件"""
        if self.task and self.task.output_path:
            original_subtitle_save_path = Path(str(self.task.output_path))
            target_dir = str(
                original_subtitle_save_path.parent
                if original_subtitle_save_path.exists()
                else Path(str(self.task.file_path)).parent
            )
            open_folder(target_dir)
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可用的字幕文件夹"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self,
            )

    def start_transcription(self, need_create_task=True):
        """开始转录过程"""
        self.transcription_interface.is_processing = True  # type: ignore
        self.start_button.setEnabled(False)

        if need_create_task:
            self.task = TaskFactory.create_transcribe_task(self.video_info.file_path)

        if not self.task:
            return

        # 将选中的音轨索引作为临时属性传递给 task
        self.task.selected_audio_track_index = self.selected_audio_track_index  # type: ignore

        self.transcript_thread = TranscriptThread(self.task)
        self.transcript_thread.finished.connect(self.on_transcript_finished)
        self.transcript_thread.progress.connect(self.on_transcript_progress)
        self.transcript_thread.error.connect(self.on_transcript_error)
        self.transcript_thread.start()

    def on_transcript_progress(self, value, message):
        """更新转录进度"""
        self.start_button.setText(message)
        self.progress_ring.setValue(value)

    def on_transcript_error(self, error):
        """处理转录错误"""
        self.transcription_interface.is_processing = False  # type: ignore
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("重新转录"))
        self.progress_ring.hide()
        InfoBar.error(
            self.tr("转录失败"),
            self.tr(error),
            duration=INFOBAR_DURATION_ERROR,
            parent=self.parent().parent(),
        )

    def on_transcript_finished(self, task):
        """转录完成处理"""
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("转录完成"))
        self.progress_ring.hide()
        self.finished.emit(task)

    def reset_ui(self):
        """重置UI状态"""
        self.start_button.setDisabled(False)
        self.start_button.setText(self.tr("开始转录"))
        self.progress_ring.setValue(0)
        self.progress_ring.hide()

    def set_task(self, task):
        """设置任务并更新UI"""
        self.task = task
        self.reset_ui()

    def stop(self):
        if hasattr(self, "transcript_thread"):
            self.transcript_thread.terminate()


class TranscriptionInterface(QWidget):
    """转录界面类,用于显示视频信息和转录进度"""

    finished = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore
        self.setAcceptDrops(True)
        self.task: Optional[TranscribeTask] = None
        self.is_processing: bool = False

        self._init_ui()
        self._setup_signals()
        self._set_value()

    def _init_ui(self) -> None:
        """初始化UI"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        # 添加命令栏
        self._setup_command_bar()

        self.video_info_card = VideoInfoCard(self)
        self.main_layout.addWidget(self.video_info_card)

        # 添加转录设置卡片
        self.transcription_setting_card = TranscriptionSettingCard(self)
        self.main_layout.addWidget(self.transcription_setting_card)

    def _setup_command_bar(self):
        """设置命令栏"""
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)  # type: ignore
        self.command_bar.setFixedHeight(40)

        # 添加打开文件按钮
        self.open_file_action = Action(FluentIcon.FOLDER, self.tr("打开文件"))
        self.open_file_action.triggered.connect(self._on_file_select)
        self.command_bar.addAction(self.open_file_action)

        self.command_bar.addSeparator()

        # 添加转录模型选择按钮
        self.model_button = TransparentDropDownPushButton(
            self.tr("转录模型"), self, FluentIcon.MICROPHONE
        )
        self.model_button.setFixedHeight(34)
        self.model_button.setMinimumWidth(180)

        self.model_menu = RoundMenu(parent=self)
        # 只显示当前平台可用的模型（macOS 上不显示 FasterWhisper）
        available_models = get_available_transcribe_models()
        for model in available_models:
            if (
                model == TranscribeModelEnum.WHISPER_API
                or model == TranscribeModelEnum.BIJIAN
                or model == TranscribeModelEnum.JIANYING
            ):
                self.model_menu.addActions(
                    [
                        Action(FluentIcon.GLOBE, model.value),
                    ]
                )
            else:
                self.model_menu.addActions(
                    [
                        Action(FluentIcon.ROBOT, model.value),
                    ]
                )
        self.model_button.setMenu(self.model_menu)
        self.command_bar.addWidget(self.model_button)

        self.command_bar.addSeparator()

        # 添加输出设置按钮
        self.command_bar.addAction(
            Action(FluentIcon.SETTING, "", triggered=self._show_output_settings)
        )

        self.main_layout.addWidget(self.command_bar)

    def _setup_signals(self) -> None:
        """设置信号连接"""
        self.video_info_card.finished.connect(self._on_transcript_finished)

        # 设置模型选择菜单的信号连接
        for action in self.model_menu.actions():
            action.triggered.connect(
                lambda checked, text=action.text(): self.on_transcription_model_changed(
                    text
                )
            )

        # 全局信号连接
        signalBus.transcription_model_changed.connect(
            self.on_transcription_model_changed
        )

    def _show_output_settings(self):
        """显示转录设置对话框"""
        dialog = TranscriptionSettingDialog(self.window())
        dialog.exec_()

    def _set_value(self) -> None:
        """设置转录模型"""
        model_name = cfg.get(cfg.transcribe_model).value
        # self.model_button.setText(self.tr(model_name))
        self.on_transcription_model_changed(model_name)

    def on_transcription_model_changed(self, model_name: str):
        """处理转录模型改变"""
        self.model_button.setText(self.tr(model_name))
        self.transcription_setting_card.on_model_changed(model_name)
        for model in TranscribeModelEnum:
            if model.value == model_name:
                cfg.set(cfg.transcribe_model, model)
                break

    def _on_transcript_finished(self, task: TranscribeTask):
        """转录完成处理"""
        self.is_processing = False
        if task.need_next_task:
            self.finished.emit(task.output_path, task.file_path)

            InfoBar.success(
                self.tr("转录完成"),
                self.tr("开始字幕优化..."),
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM,
                parent=self.parent(),
            )

    def _on_file_select(self):
        """文件选择处理"""
        desktop_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        file_dialog = QFileDialog()

        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        audio_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedAudioFormats)
        filter_str = f"{self.tr('媒体文件')} ({video_formats} {audio_formats});;{self.tr('视频文件')} ({video_formats});;{self.tr('音频文件')} ({audio_formats})"

        file_path, _ = file_dialog.getOpenFileName(
            self, self.tr("选择媒体文件"), desktop_path, filter_str
        )
        if file_path:
            self.update_info(file_path)

    def update_info(self, file_path):
        """设置UI"""
        self.video_info_thread = VideoInfoThread(file_path)
        self.video_info_thread.finished.connect(self.video_info_card.update_info)
        self.video_info_thread.error.connect(self._on_video_info_error)
        self.video_info_thread.start()

    def _on_video_info_error(self, error_msg):
        """处理视频信息提取错误"""
        self.is_processing = False
        InfoBar.error(
            self.tr("错误"),
            self.tr(error_msg),
            duration=INFOBAR_DURATION_ERROR,
            parent=self,
        )

    def set_task(self, task: TranscribeTask) -> None:
        """设置任务并更新UI"""
        self.task = task
        self.video_info_card.set_task(self.task)
        self.update_info(self.task.file_path)

    def process(self):
        """主处理函数"""
        self.is_processing = True
        self.video_info_card.start_transcription(need_create_task=False)

    def dragEnterEvent(self, event):
        """拖拽进入事件处理"""
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        """拖拽放下事件处理"""
        if self.is_processing:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("正在处理中，请等待当前任务完成"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self,
            )
            return

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
                self.update_info(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("开始语音转文字"),
                    duration=INFOBAR_DURATION_SUCCESS,
                    parent=self,
                )
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext,
                    self.tr("请拖入音频或视频文件"),
                    duration=INFOBAR_DURATION_ERROR,
                    parent=self,
                )

    def closeEvent(self, event):
        self.video_info_card.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)  # type: ignore
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)  # type: ignore

    app = QApplication(sys.argv)
    window = TranscriptionInterface()
    window.show()
    sys.exit(app.exec_())
