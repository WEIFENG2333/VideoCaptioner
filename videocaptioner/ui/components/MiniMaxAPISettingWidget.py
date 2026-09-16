from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    InfoBar,
    InfoBarPosition,
    PushSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
)
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.core.asr.minimax_api import check_minimax_connection
from videocaptioner.core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from videocaptioner.core.entities import (
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    get_asr_language_capability,
)

from ..common.config import cfg
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .LineEditSettingCard import LineEditSettingCard

_minimax_capability = get_asr_language_capability(TranscribeModelEnum.MINIMAX_API)
_MINIMAX_LANGUAGE_LABELS = (
    [TranscribeLanguageEnum.AUTO] if _minimax_capability.supports_auto else []
) + _minimax_capability.supported_languages


class MiniMaxConnectionThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, api_key: str, base_url: str, model: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        ok, message = check_minimax_connection(self.api_key, self.base_url, self.model)
        self.finished.emit(ok, message)


class MiniMaxAPISettingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)  # type: ignore
        self.scroll_area.setStyleSheet("QScrollArea{background: transparent; border: none}")
        self.container = QWidget(self)
        self.container.setStyleSheet("QWidget{background: transparent}")
        self.container_layout = QVBoxLayout(self.container)
        self.setting_group = SettingCardGroup(self.tr("MiniMax ASR 设置"), self)

        self.base_url_card = LineEditSettingCard(
            cfg.minimax_api_base,
            FIF.LINK,
            self.tr("API Base URL"),
            self.tr("MiniMax Speech-to-Text API 地址"),
            "https://api.minimaxi.com/v1",
            self.setting_group,
        )
        self.api_key_card = LineEditSettingCard(
            cfg.minimax_api_key,
            FIF.FINGERPRINT,
            self.tr("API Key"),
            self.tr("输入 MiniMax API Key"),
            "",
            self.setting_group,
        )
        self.model_card = EditComboBoxSettingCard(
            cfg.minimax_api_model,
            FIF.ROBOT,  # type: ignore
            self.tr("MiniMax ASR 模型"),
            self.tr("当前官方 Speech-to-Text 模型"),
            ["asr-1.0"],
            self.setting_group,
        )
        self.language_card = ComboBoxSettingCard(
            cfg.transcribe_language,
            FIF.LANGUAGE,
            self.tr("源语言"),
            self.tr("支持自动检测；显式指定时仅显示 MiniMax 官方支持语言"),
            [lang.value for lang in _MINIMAX_LANGUAGE_LABELS],
            self.setting_group,
        )
        self.check_connection_card = PushSettingCard(
            self.tr("测试连接"),
            FIF.CONNECT,
            self.tr("测试 MiniMax ASR 连接"),
            self.tr("发送一段极短静音 WAV 验证鉴权与服务可用性"),
            self.setting_group,
        )

        for card in (
            self.base_url_card,
            self.api_key_card,
            self.model_card,
            self.language_card,
            self.check_connection_card,
        ):
            self.setting_group.addSettingCard(card)

        self.check_connection_card.clicked.connect(self.on_check_connection)
        self.container_layout.addWidget(self.setting_group)
        self.container_layout.addStretch(1)
        self.scroll_area.setWidget(self.container)
        self.scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll_area)

    def on_check_connection(self):
        base_url = self.base_url_card.lineEdit.text().strip()
        api_key = self.api_key_card.lineEdit.text().strip()
        model = self.model_card.comboBox.currentText().strip()
        if not api_key or not base_url or not model:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请输入 MiniMax API Key、Base URL 和模型"),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
            return

        self.check_connection_card.button.setEnabled(False)
        self.check_connection_card.button.setText(self.tr("正在测试..."))
        self.connection_thread = MiniMaxConnectionThread(api_key, base_url, model, self)
        self.connection_thread.finished.connect(self.on_connection_finished)
        self.connection_thread.start()

    def on_connection_finished(self, ok: bool, message: str):
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))
        if ok:
            InfoBar.success(
                self.tr("连接成功"),
                self.tr(message),
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
        else:
            InfoBar.error(
                self.tr("连接失败"),
                self.tr(message),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
