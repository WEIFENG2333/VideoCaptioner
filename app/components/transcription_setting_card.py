from typing import Optional

from PyQt5.QtWidgets import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.entities import (
    TranscribeModelEnum,
)
from ..core.utils.platform_utils import is_macos
from .FasterWhisperSettingWidget import FasterWhisperSettingWidget
from .QwenASRSettingWidget import QwenASRSettingWidget
from .WhisperAPISettingWidget import WhisperAPISettingWidget
from .WhisperCppSettingWidget import WhisperCppSettingWidget


class TranscriptionSettingCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # 设置界面堆叠
        self.stacked_widget = QStackedWidget(self)

        # 添加各个设置界面
        self.empty_widget = QWidget(self)  # 添加空白页面作为默认显示
        self.whisper_cpp_widget = WhisperCppSettingWidget(self)
        self.whisper_api_widget = WhisperAPISettingWidget(self)
        self.qwen_asr_widget = QwenASRSettingWidget(self)

        # FasterWhisper 在 macOS 上不可用
        self.faster_whisper_widget: Optional[FasterWhisperSettingWidget] = None
        if not is_macos():
            self.faster_whisper_widget = FasterWhisperSettingWidget(self)

        self.stacked_widget.addWidget(self.empty_widget)  # 添加空白页面
        self.stacked_widget.addWidget(self.whisper_cpp_widget)
        self.stacked_widget.addWidget(self.whisper_api_widget)
        self.stacked_widget.addWidget(self.qwen_asr_widget)
        if self.faster_whisper_widget is not None:
            self.stacked_widget.addWidget(self.faster_whisper_widget)

        self.main_layout.addWidget(self.stacked_widget)

    def on_model_changed(self, value):
        # 切换对应的设置界面
        if value == TranscribeModelEnum.WHISPER_CPP.value:
            self.stacked_widget.setCurrentWidget(self.whisper_cpp_widget)
        elif value == TranscribeModelEnum.WHISPER_API.value:
            self.stacked_widget.setCurrentWidget(self.whisper_api_widget)
        elif value == TranscribeModelEnum.QWEN_ASR.value:
            self.stacked_widget.setCurrentWidget(self.qwen_asr_widget)
        elif value == TranscribeModelEnum.FASTER_WHISPER.value:
            self.stacked_widget.setCurrentWidget(self.faster_whisper_widget)
        else:
            self.stacked_widget.setCurrentWidget(self.empty_widget)
