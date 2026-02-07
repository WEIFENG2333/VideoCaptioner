from PyQt5.QtWidgets import QVBoxLayout
from qfluentwidgets import (
    ComboBox,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    SettingCard,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.core.entities import (
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    get_asr_language_capability,
)


class LanguageSettingDialog(MessageBoxBase):
    """语言设置对话框"""

    def __init__(self, model: TranscribeModelEnum, parent=None):
        self.model = model
        super().__init__(parent)
        self.widget.setMinimumWidth(500)
        self._setup_ui()
        self._connect_signals()

    def _get_available_languages(self) -> list[str]:
        """获取当前模型支持的语言列表"""
        capability = get_asr_language_capability(self.model)
        languages = [lang.value for lang in capability.supported_languages]
        if capability.supports_auto:
            languages.insert(0, TranscribeLanguageEnum.AUTO.value)
        return languages

    def _setup_ui(self):
        """设置UI"""
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        # 主布局
        layout = QVBoxLayout()

        # 使用自定义 SettingCard 代替 ComboBoxSettingCard（因为需要动态选项）
        self.language_card = SettingCard(
            FIF.LANGUAGE,
            self.tr("源语言"),
            self.tr("自动检测会根据前30秒音频识别语言，也可手动指定"),
            self,
        )

        # 创建 ComboBox
        self.language_combo = ComboBox(self)
        available_languages = self._get_available_languages()
        self.language_combo.addItems(available_languages)
        self.language_combo.setMaxVisibleItems(6)
        self.language_combo.setMinimumWidth(160)

        # 设置当前值
        current_lang = cfg.transcribe_language.value
        if current_lang.value in available_languages:
            self.language_combo.setCurrentText(current_lang.value)
        elif available_languages:
            # 当前选择的语言不在可选列表中，选择第一个
            self.language_combo.setCurrentIndex(0)

        # 添加 ComboBox 到卡片
        self.language_card.hBoxLayout.addWidget(self.language_combo)
        self.language_card.hBoxLayout.addSpacing(16)

        layout.addWidget(self.language_card)
        layout.addStretch(1)

        self.viewLayout.addLayout(layout)

    def _connect_signals(self):
        """连接信号"""
        self.yesButton.clicked.connect(self.__onYesButtonClicked)

    def __onYesButtonClicked(self):
        # 保存选中的语言到配置
        selected_text = self.language_combo.currentText()
        for lang in TranscribeLanguageEnum:
            if lang.value == selected_text:
                cfg.set(cfg.transcribe_language, lang)
                break

        self.accept()
        InfoBar.success(
            self.tr("设置已保存"),
            self.tr("语言设置已更新"),
            duration=3000,
            parent=self.window(),
            position=InfoBarPosition.BOTTOM,
        )
        if cfg.transcribe_language.value == TranscribeLanguageEnum.JAPANESE:
            InfoBar.warning(
                self.tr("请注意身体！！"),
                self.tr("小心肝儿,注意身体哦~"),
                duration=2000,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
