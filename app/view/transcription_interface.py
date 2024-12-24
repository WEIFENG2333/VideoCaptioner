# -*- coding: utf-8 -*-

import datetime
import os
import sys
import subprocess
from pathlib import Path

from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QLabel, QFileDialog
from qfluentwidgets import CardWidget, PrimaryPushButton, PushButton, InfoBar, BodyLabel, PillPushButton, setFont, \
    ProgressRing, InfoBarPosition

from ..components.FasterWhisperSettingDialog import FasterWhisperSettingDialog
from ..components.WhisperSettingDialog import WhisperSettingDialog
from ..components.WhisperAPISettingDialog import WhisperAPISettingDialog
from ..config import RESOURCE_PATH
from ..core.thread.create_task_thread import CreateTaskThread
from ..common.config import cfg
from ..core.entities import LANGUAGES, Task, VideoInfo
from ..core.entities import SupportedVideoFormats, SupportedAudioFormats
from ..core.thread.transcript_thread import TranscriptThread
from ..core.entities import TranscribeModelEnum

DEFAULT_THUMBNAIL_PATH = RESOURCE_PATH / "assets" / "default_thumbnail.jpg"


class VideoInfoCard(CardWidget):
    finished = pyqtSignal(Task)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.setup_ui()
        self.setup_signals()

    def setup_ui(self):
        self.setFixedHeight(150)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 15, 20, 15)
        self.layout.setSpacing(20)

        self.setup_thumbnail()
        self.setup_info_layout()
        self.setup_button_layout()

    def setup_thumbnail(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_thumbnail_path = os.path.join(DEFAULT_THUMBNAIL_PATH)

        self.video_thumbnail = QLabel(self)
        self.video_thumbnail.setFixedSize(208, 117)
        self.video_thumbnail.setStyleSheet("background-color: #1E1F22;")
        self.video_thumbnail.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(default_thumbnail_path).scaled(
            self.video_thumbnail.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.video_thumbnail.setPixmap(pixmap)
        self.layout.addWidget(self.video_thumbnail, 0, Qt.AlignLeft)

    def setup_info_layout(self):
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(3, 8, 3, 8)
        self.info_layout.setSpacing(10)

        self.video_title = BodyLabel(self.tr("请拖入音频或视频文件"), self)
        self.video_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self.video_title.setWordWrap(True)
        self.info_layout.addWidget(self.video_title, alignment=Qt.AlignTop)

        self.details_layout = QHBoxLayout()
        self.details_layout.setSpacing(15)

        self.resolution_info = self.create_pill_button(self.tr("画质"), 110)
        self.file_size_info = self.create_pill_button(self.tr("文件大小"), 110)
        self.duration_info = self.create_pill_button(self.tr("时长"), 100)

        self.progress_ring = ProgressRing(self)
        self.progress_ring.setFixedSize(20, 20)
        self.progress_ring.setStrokeWidth(4)
        self.progress_ring.hide()

        self.details_layout.addWidget(self.resolution_info)
        self.details_layout.addWidget(self.file_size_info)
        self.details_layout.addWidget(self.duration_info)
        self.details_layout.addWidget(self.progress_ring)
        self.details_layout.addStretch(1)
        self.info_layout.addLayout(self.details_layout)
        self.layout.addLayout(self.info_layout)

    def create_pill_button(self, text, width):
        button = PillPushButton(text, self)
        button.setCheckable(False)
        setFont(button, 11)
        button.setFixedWidth(width)
        return button

    def setup_button_layout(self):
        self.button_layout = QVBoxLayout()
        self.open_folder_button = PushButton(self.tr("打开文件夹"), self)
        self.start_button = PrimaryPushButton(self.tr("开始转录"), self)
        self.button_layout.addWidget(self.open_folder_button)
        self.button_layout.addWidget(self.start_button)

        self.start_button.setDisabled(True)

        button_widget = QWidget()
        button_widget.setLayout(self.button_layout)
        button_widget.setFixedWidth(130)
        self.layout.addWidget(button_widget)

    def update_info(self, video_info: VideoInfo):
        """更新视频信息显示"""
        self.video_title.setText(video_info.file_name.rsplit('.', 1)[0])
        self.resolution_info.setText(self.tr("画质: ") + f"{video_info.width}x{video_info.height}")
        file_size_mb = os.path.getsize(self.task.file_path) / 1024 / 1024
        self.file_size_info.setText(self.tr("大小: ") + f"{file_size_mb:.1f} MB")
        duration = datetime.timedelta(seconds=int(video_info.duration_seconds))
        self.duration_info.setText(self.tr("时长: ") + f"{duration}")
        self.start_button.setDisabled(False)
        self.update_thumbnail(video_info.thumbnail_path)

    def update_thumbnail(self, thumbnail_path):
        """更新视频缩略图"""
        if not Path(thumbnail_path).exists():
            thumbnail_path = RESOURCE_PATH / "assets" / "audio-thumbnail.png"

        pixmap = QPixmap(str(thumbnail_path)).scaled(
            self.video_thumbnail.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.video_thumbnail.setPixmap(pixmap)

    def setup_signals(self):
        self.start_button.clicked.connect(self.on_start_button_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)

    def show_whisper_settings(self):
        """显示Whisper设置对话框"""
        if cfg.transcribe_model.value == TranscribeModelEnum.WHISPER:
            dialog = WhisperSettingDialog(self.window())
            if dialog.exec_():
                return True
        elif cfg.transcribe_model.value == TranscribeModelEnum.WHISPER_API:
            dialog = WhisperAPISettingDialog(self.window())
            if dialog.exec_():
                return True
        elif cfg.transcribe_model.value == TranscribeModelEnum.FASTER_WHISPER:
            dialog = FasterWhisperSettingDialog(self.window())
            if dialog.exec_():
                return True
        return False

    def on_start_button_clicked(self):
        """开始转录按钮点击事件"""
        if self.task.status == Task.Status.TRANSCRIBING:
            need_whisper_settings = cfg.transcribe_model.value in [TranscribeModelEnum.WHISPER, TranscribeModelEnum.WHISPER_API, TranscribeModelEnum.FASTER_WHISPER]
            if need_whisper_settings and not self.show_whisper_settings():
                return
        self.progress_ring.show()
        self.progress_ring.setValue(100)
        self.start_button.setDisabled(True)
        self.start_transcription()

    def on_open_folder_clicked(self):
        """打开文件夹按钮点击事件"""
        if self.task and self.task.work_dir:
            original_subtitle_save_path = Path(self.task.original_subtitle_save_path)
            target_path = str(original_subtitle_save_path.parent if original_subtitle_save_path.exists() else Path(self.task.work_dir))
            if sys.platform == "win32":
                os.startfile(target_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", target_path])
            else:  # Linux
                subprocess.run(["xdg-open", target_path])
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可用的字幕文件夹"),
                duration=2000,
                parent=self
            )

    def start_transcription(self):
        """开始转录过程"""
        self.start_button.setEnabled(False)
        self._update_task_config()
        self.transcript_thread = TranscriptThread(self.task)
        self.transcript_thread.finished.connect(self.on_transcript_finished)
        self.transcript_thread.progress.connect(self.on_transcript_progress)
        self.transcript_thread.error.connect(self.on_transcript_error)
        self.transcript_thread.start()

    def _update_task_config(self):
        self.task.target_language = cfg.target_language.value.value
        self.task.transcribe_language = LANGUAGES[cfg.transcribe_language.value.value]
        self.task.transcribe_model = cfg.transcribe_model.value
        self.task.whisper_model = cfg.whisper_model.value.value
        self.task.whisper_api_key = cfg.whisper_api_key.value
        self.task.whisper_api_base = cfg.whisper_api_base.value
        self.task.whisper_api_model = cfg.whisper_api_model.value
        self.task.whisper_api_prompt = cfg.whisper_api_prompt.value
        self.task.faster_whisper_model = cfg.faster_whisper_model.value
        self.task.faster_whisper_model_dir = cfg.faster_whisper_model_dir.value
        self.task.faster_whisper_device = cfg.faster_whisper_device.value
        self.task.faster_whisper_vad_filter = cfg.faster_whisper_vad_filter.value
        self.task.faster_whisper_vad_threshold = cfg.faster_whisper_vad_threshold.value
        self.task.faster_whisper_vad_method = cfg.faster_whisper_vad_method.value
        self.task.faster_whisper_ff_mdx_kim2 = cfg.faster_whisper_ff_mdx_kim2.value
        self.task.faster_whisper_one_word = cfg.faster_whisper_one_word.value
        self.task.faster_whisper_prompt = cfg.faster_whisper_prompt.value
        self.task.max_word_count_cjk = cfg.max_word_count_cjk.value
        self.task.max_word_count_english = cfg.max_word_count_english.value

    def on_transcript_progress(self, value, message):
        """更新转录进度"""
        self.start_button.setText(message)
        self.progress_ring.setValue(value)


    def on_transcript_error(self, error):
        """处理转录错误"""
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("重新转录"))
        self.start_button.setEnabled(True)
        InfoBar.error(
            self.tr("转录失败"),
            self.tr(error),
            duration=3000,
            parent=self.parent().parent()
        )

    def on_transcript_finished(self, task):
        """转录完成处理"""
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("转录完成"))
        if self.task.status == Task.Status.PENDING:
            self.finished.emit(task)

    def reset_ui(self):
        """重置UI状态"""
        self.start_button.setDisabled(False)
        self.start_button.setText(self.tr("开始转录"))
        self.progress_ring.setValue(100)

    def set_task(self, task):
        """设置任务并更新UI"""
        self.task = task
        self.update_info(self.task.video_info)
        self.reset_ui()
    
    def stop(self):
        if hasattr(self, 'transcript_thread'):
            self.transcript_thread.terminate()



class TranscriptionInterface(QWidget):
    """转录界面类,用于显示视频信息和转录进度"""
    finished = pyqtSignal(Task)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.task = None

        self._init_ui()
        self._setup_signals()

    def _init_ui(self):
        """初始化UI"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self.video_info_card = VideoInfoCard(self)
        self.main_layout.addWidget(self.video_info_card)

        self.file_select_button = PushButton(self.tr("选择视频文件"), self)
        self.main_layout.addWidget(self.file_select_button, alignment=Qt.AlignCenter)

    def _setup_signals(self):
        """设置信号连接"""
        self.file_select_button.clicked.connect(self._on_file_select)
        self.video_info_card.finished.connect(self._on_transcript_finished)

    def _on_transcript_finished(self, task):
        """转录完成处理"""
        self.finished.emit(task)
        InfoBar.success(
            self.tr("转录完成"),
            self.tr("开始字幕优化..."),
            duration=3000,
            position=InfoBarPosition.BOTTOM,
            parent=self.parent()
        )

    def _on_file_select(self):
        """文件选择处理"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

        # 构建文件过滤器
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        audio_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedAudioFormats)
        filter_str = f"{self.tr('媒体文件')} ({video_formats} {audio_formats});;{self.tr('视频文件')} ({video_formats});;{self.tr('音频文件')} ({audio_formats})"

        if cfg.last_open_dir.value != "":
            open_path = cfg.last_open_dir.value
        else:
            open_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            
        file_path, _ = file_dialog.getOpenFileName(self, self.tr("选择媒体文件"), open_path, filter_str)
        if file_path:
            # Save this file's directory for later use
            file_dir = str( Path(file_path).parent )
            if file_dir != cfg.last_open_dir.value:
                cfg.last_open_dir.value = file_dir

            self.create_task(file_path)

    def create_task(self, file_path):
        """创建任务"""
        self.create_task_thread = CreateTaskThread(file_path, Task.Type.TRANSCRIBE)
        self.create_task_thread.finished.connect(self.set_task)
        self.create_task_thread.start()

    def set_task(self, task: Task):
        """设置任务并更新UI"""
        self.task = task
        self.update_info()

    def update_info(self):
        """更新页面信息"""
        self.video_info_card.set_task(self.task)

    def process(self):
        """主处理函数"""
        self.video_info_card.start_transcription()

    def dragEnterEvent(self, event):
        """拖拽进入事件处理"""
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        """拖拽放下事件处理"""
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedVideoFormats} | {fmt.value for fmt in
                                                                                SupportedAudioFormats}
            is_supported = file_ext in supported_formats

            if is_supported:
                self.create_task(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("开始语音转文字"),
                    duration=3000,
                    parent=self
                )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    self.tr(f"请拖入音频或视频文件"),
                    duration=3000,
                    parent=self
                )

    def closeEvent(self, event):
        self.video_info_card.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = TranscriptionInterface()
    window.show()
    sys.exit(app.exec_())
