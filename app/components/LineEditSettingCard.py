from typing import Optional
from PyQt5.QtCore import Qt, pyqtSignal
from qfluentwidgets import LineEdit, SettingCard
from qfluentwidgets.common.config import ConfigItem, qconfig


class LineEditSettingCard(SettingCard):
    """行输入卡片"""

    textChanged = pyqtSignal(str)

    def __init__(
        self,
        configItem: ConfigItem,
        icon,
        title: str,
        content: Optional[str] = None,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(icon, title, content, parent)

        self.configItem = configItem

        self.lineEdit = LineEdit(self)
        self.lineEdit.setPlaceholderText(placeholder)
        self.hBoxLayout.addWidget(self.lineEdit, 1, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(16)

        self.lineEdit.setMinimumWidth(280)

        self.setValue(qconfig.get(configItem))

        self.lineEdit.textChanged.connect(self.__onTextChanged)
        configItem.valueChanged.connect(self.setValue)

    def __onTextChanged(self, text: str):
        self.setValue(text)
        self.textChanged.emit(text)

    def setValue(self, value: str):
        qconfig.set(self.configItem, value)
        self.lineEdit.setText(value)
