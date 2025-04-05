from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, ComboBoxSettingCard
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    HyperlinkCard,
    RangeSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
    SwitchSettingCard,
)

from app.components.SpinBoxSettingCard import DoubleSpinBoxSettingCard

from ..common.config import cfg
from ..core.entities import (
    FasterWhisperModelEnum,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    VadMethodEnum,
    WhisperModelEnum,
)
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .FasterWhisperSettingWidget import FasterWhisperSettingWidget
from .LineEditSettingCard import LineEditSettingCard
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
        self.faster_whisper_widget = FasterWhisperSettingWidget(self)

        self.stacked_widget.addWidget(self.empty_widget)  # 添加空白页面
        self.stacked_widget.addWidget(self.whisper_cpp_widget)
        self.stacked_widget.addWidget(self.whisper_api_widget)
        self.stacked_widget.addWidget(self.faster_whisper_widget)

        self.main_layout.addWidget(self.stacked_widget)

    def on_model_changed(self, value):
        # 切换对应的设置界面
        if value == str(TranscribeModelEnum.WHISPER_CPP):
            self.stacked_widget.setCurrentWidget(self.whisper_cpp_widget)
        elif value == str(TranscribeModelEnum.WHISPER_API):
            self.stacked_widget.setCurrentWidget(self.whisper_api_widget)
        elif value == str(TranscribeModelEnum.FASTER_WHISPER):
            self.stacked_widget.setCurrentWidget(self.faster_whisper_widget)
        else:
            self.stacked_widget.setCurrentWidget(self.empty_widget)
