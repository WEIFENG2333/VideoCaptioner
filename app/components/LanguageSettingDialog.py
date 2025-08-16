from PyQt5.QtWidgets import QVBoxLayout
from qfluentwidgets import (
    ComboBoxSettingCard,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    SettingCardGroup,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.core.entities import TranscribeLanguageEnum


class LanguageSettingDialog(MessageBoxBase):
    """语言设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(500)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI"""
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        # 主布局
        layout = QVBoxLayout()

        self.setting_group = SettingCardGroup(self.tr("语言设置"), self)

        # 语言选择卡片
        self.language_card = ComboBoxSettingCard(
            cfg.transcribe_language,
            FIF.LANGUAGE,
            self.tr("源语言"),
            self.tr("音频的源语言"),
            [lang.value for lang in TranscribeLanguageEnum],
        )
        self.language_card.comboBox.setMaxVisibleItems(6)

        self.setting_group.addSettingCard(self.language_card)
        layout.addWidget(self.setting_group)
        layout.addStretch(1)

        self.viewLayout.addLayout(layout)

    def _connect_signals(self):
        """连接信号"""
        self.yesButton.clicked.connect(self.__onYesButtonClicked)

    def __onYesButtonClicked(self):
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
