from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBoxSettingCard,
    InfoBar,
    InfoBarPosition,
    PushSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import cfg
from ..core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from ..core.entities import TranscribeLanguageEnum
from ..core.llm import check_whisper_connection
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

        # 添加测试连接按钮
        self.check_connection_card = PushSettingCard(
            self.tr("测试连接"),
            FIF.CONNECT,
            self.tr("测试 Whisper API 连接"),
            self.tr("点击测试 API 连接是否正常"),
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
        self.setting_group.addSettingCard(self.check_connection_card)

        # 连接测试按钮信号
        self.check_connection_card.clicked.connect(self.on_check_connection)

        # 将设置组添加到容器布局
        self.containerLayout.addWidget(self.setting_group)
        self.containerLayout.addStretch(1)

        # 设置滚动区域
        self.scrollArea.setWidget(self.container)
        self.scrollArea.setWidgetResizable(True)

        # 将滚动区域添加到主布局
        self.main_layout.addWidget(self.scrollArea)

    def on_check_connection(self):
        """测试 Whisper API 连接"""
        # 获取配置
        base_url = self.base_url_card.lineEdit.text().strip()
        api_key = self.api_key_card.lineEdit.text().strip()
        model = self.model_card.comboBox.currentText().strip()

        # 验证必填字段
        if not base_url or not api_key or not model:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请输入 API Base URL、API Key 和 model"),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
            return

        # 禁用按钮，显示加载状态
        self.check_connection_card.button.setEnabled(False)
        self.check_connection_card.button.setText(self.tr("正在测试..."))

        # 创建并启动测试线程
        self.connection_thread = WhisperConnectionThread(base_url, api_key, model)
        self.connection_thread.finished.connect(self.on_connection_check_finished)
        self.connection_thread.error.connect(self.on_connection_check_error)
        self.connection_thread.start()

    def on_connection_check_finished(self, success, result):
        """处理连接检查完成事件"""
        # 恢复按钮状态
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))

        if success:
            InfoBar.success(
                self.tr("连接成功"),
                self.tr("Whisper API 连接成功！") + "\n" + result,
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
        else:
            InfoBar.error(
                self.tr("连接失败"),
                self.tr(f"Whisper API 连接失败！\n{result}"),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )

    def on_connection_check_error(self, message):
        """处理连接检查错误事件"""
        # 恢复按钮状态
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))
        InfoBar.error(
            self.tr("测试错误"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.BOTTOM,
            parent=self.window(),
        )


class WhisperConnectionThread(QThread):
    """Whisper API 连接测试线程"""

    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, base_url, api_key, model):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self):
        """执行连接测试"""
        try:
            success, result = check_whisper_connection(
                self.base_url, self.api_key, self.model
            )
            self.finished.emit(success, result)
        except Exception as e:
            self.error.emit(str(e))
