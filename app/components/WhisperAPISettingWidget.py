from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBoxSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import cfg
from ..core.entities import TranscribeLanguageEnum
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .LineEditSettingCard import LineEditSettingCard


class WhisperAPISettingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        # 创建单向滚动区域和容器
        self.scrollArea = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)  # type: ignore
        self.scrollArea.setStyleSheet(
            "QScrollArea{background: transparent; border: none}"
        )

        self.container = QWidget(self)
        self.container.setStyleSheet("QWidget{background: transparent}")
        self.containerLayout = QVBoxLayout(self.container)

        self.setting_group = SettingCardGroup(self.tr("Whisper API 设置"), self)

        # API Base URL
        self.base_url_card = LineEditSettingCard(
            cfg.whisper_api_base,
            FIF.LINK,
            self.tr("API Base URL"),
            self.tr("输入 Whisper API Base URL"),
            "https://api.openai.com/v1",
            self.setting_group,
        )

        # API Key
        self.api_key_card = LineEditSettingCard(
            cfg.whisper_api_key,
            FIF.FINGERPRINT,
            self.tr("API Key"),
            self.tr("输入 Whisper API Key"),
            "sk-",
            self.setting_group,
        )

        # Model
        self.model_card = EditComboBoxSettingCard(
            cfg.whisper_api_model,
            FIF.ROBOT,  # type: ignore
            self.tr("Whisper 模型"),
            self.tr("选择 Whisper 模型"),
            ["whisper-large-v3", "whisper-large-v3-turbo", "whisper-1"],
            self.setting_group,
        )

        # 添加 Language 选择
        self.language_card = ComboBoxSettingCard(
            cfg.transcribe_language,
            FIF.LANGUAGE,
            self.tr("原语言"),
            self.tr("音频的原语言"),
            [lang.value for lang in TranscribeLanguageEnum],
            self.setting_group,
        )

        # 添加 Prompt
        self.prompt_card = LineEditSettingCard(
            cfg.whisper_api_prompt,
            FIF.CHAT,
            self.tr("提示词"),
            self.tr("可选的提示词,默认空"),
            "",
            self.setting_group,
        )

        # 设置最小宽度
        self.base_url_card.lineEdit.setMinimumWidth(200)
        self.api_key_card.lineEdit.setMinimumWidth(200)
        self.model_card.comboBox.setMinimumWidth(200)
        self.language_card.comboBox.setMinimumWidth(200)
        self.prompt_card.lineEdit.setMinimumWidth(200)

        # 使用 addSettingCard 添加所有卡片到组
        self.setting_group.addSettingCard(self.base_url_card)
        self.setting_group.addSettingCard(self.api_key_card)
        self.setting_group.addSettingCard(self.model_card)
        self.setting_group.addSettingCard(self.language_card)
        self.setting_group.addSettingCard(self.prompt_card)

        # 将设置组添加到容器布局
        self.containerLayout.addWidget(self.setting_group)
        self.containerLayout.addStretch(1)

        # 设置滚动区域
        self.scrollArea.setWidget(self.container)
        self.scrollArea.setWidgetResizable(True)

        # 将滚动区域添加到主布局
        self.main_layout.addWidget(self.scrollArea)
