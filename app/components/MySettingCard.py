# coding:utf-8
from typing import List, Union, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout
from qfluentwidgets import ColorDialog, ComboBox, CompactDoubleSpinBox, CompactSpinBox
from qfluentwidgets.common.config import isDarkTheme
from qfluentwidgets.common.icon import FluentIconBase, drawIcon
from qfluentwidgets.common.style_sheet import FluentStyleSheet
from qfluentwidgets.components.widgets.icon_widget import IconWidget


class SettingIconWidget(IconWidget):
    def paintEvent(self, e):
        painter = QPainter(self)

        if not self.isEnabled():
            painter.setOpacity(0.36)

        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        drawIcon(self._icon, painter, self.rect())


class SettingCard(QFrame):
    """Setting card"""

    def __init__(
        self, icon: Union[str, QIcon, FluentIconBase], title, content=None, parent=None
    ):
        """
        Parameters
        ----------
        icon: str | QIcon | FluentIconBase
            the icon to be drawn

        title: str
            the title of card

        content: str
            the content of card

        parent: QWidget
            parent widget
        """
        super().__init__(parent=parent)
        self.iconLabel = SettingIconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(content or "", self)
        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        if not content:
            self.contentLabel.hide()

        self.setFixedHeight(70 if content else 50)
        self.iconLabel.setFixedSize(16, 16)

        # initialize layout
        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setContentsMargins(16, 0, 0, 0)
        self.hBoxLayout.setAlignment(Qt.AlignVCenter)  # type: ignore
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)  # type: ignore

        self.hBoxLayout.addWidget(self.iconLabel, 0, Qt.AlignLeft)  # type: ignore
        self.hBoxLayout.addSpacing(16)

        self.hBoxLayout.addLayout(self.vBoxLayout)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignLeft)  # type: ignore
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignLeft)  # type: ignore

        self.hBoxLayout.addSpacing(16)
        self.hBoxLayout.addStretch(1)

        self.contentLabel.setObjectName("contentLabel")
        FluentStyleSheet.SETTING_CARD.apply(self)

    def setTitle(self, title: str):
        """set the title of card"""
        self.titleLabel.setText(title)

    def setContent(self, content: str):
        """set the content of card"""
        self.contentLabel.setText(content)
        self.contentLabel.setVisible(bool(content))

    def setValue(self, value):
        """set the value of config item"""
        pass

    def setIconSize(self, width: int, height: int):
        """set the icon fixed size"""
        self.iconLabel.setFixedSize(width, height)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        if isDarkTheme():
            painter.setBrush(QColor(255, 255, 255, 13))
            painter.setPen(QColor(0, 0, 0, 50))
        else:
            painter.setBrush(QColor(255, 255, 255, 170))
            painter.setPen(QColor(0, 0, 0, 19))

        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)


class DoubleSpinBoxSettingCard(SettingCard):
    """小数输入设置卡片"""

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        icon: Union[str, QIcon, FluentIconBase],
        title: str,
        content: Optional[str] = None,
        minimum: float = 0.0,
        maximum: float = 100.0,
        decimals: int = 1,
        parent=None,
    ):
        super().__init__(icon, title, content, parent)

        # 创建CompactDoubleSpinBox
        self.spinBox = CompactDoubleSpinBox(self)
        self.spinBox.setRange(minimum, maximum)
        self.spinBox.setDecimals(decimals)
        self.spinBox.setMinimumWidth(60)
        self.spinBox.setSingleStep(0.2)  # 设置步长为0.1

        # 添加到布局
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(8)

        # 设置初始值和连接信号
        self.spinBox.valueChanged.connect(self.__onValueChanged)

    def __onValueChanged(self, value: float):
        """数值改变时的槽函数"""
        self.setValue(value)
        self.valueChanged.emit(value)

    def setValue(self, value: float):
        """设置数值"""
        self.spinBox.setValue(value)


class SpinBoxSettingCard(SettingCard):
    """数值输入设置卡片"""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        icon: Union[str, QIcon],
        title: str,
        content: Optional[str] = None,
        minimum: int = 0,
        maximum: int = 100,
        parent=None,
    ):
        super().__init__(icon, title, content, parent)

        # 创建SpinBox
        self.spinBox = CompactSpinBox(self)
        self.spinBox.setRange(minimum, maximum)
        self.spinBox.setMinimumWidth(60)
        self.spinBox.setSingleStep(2)  # 设置步长为2

        # 添加到布局
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(8)

        # 设置初始值和连接信号
        self.spinBox.valueChanged.connect(self.__onValueChanged)

    def __onValueChanged(self, value: int):
        """数值改变时的槽函数"""
        self.setValue(value)
        self.valueChanged.emit(value)

    def setValue(self, value: int):
        """设置数值"""
        self.spinBox.setValue(value)


class ComboBoxSettingCard(SettingCard):
    """下拉框设置卡片"""

    currentTextChanged = pyqtSignal(str)
    currentIndexChanged = pyqtSignal(int)

    def __init__(
        self,
        icon: Union[str, QIcon],
        title: str,
        content: Optional[str] = None,
        texts: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(icon, title, content, parent)

        # 创建ComboBox
        self.comboBox = ComboBox(self)
        self.hBoxLayout.addWidget(self.comboBox, 0, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(16)

        # 添加选项
        if texts:
            for text in texts:
                self.comboBox.addItem(text)

        # 连接信号
        self.comboBox.currentTextChanged.connect(self.__onCurrentTextChanged)
        self.comboBox.currentIndexChanged.connect(self.__onCurrentIndexChanged)

    def __onCurrentTextChanged(self, text: str):
        """当前文本改变时的槽函数"""
        self.currentTextChanged.emit(text)

    def __onCurrentIndexChanged(self, index: int):
        """当前索引改变时的槽函数"""
        self.currentIndexChanged.emit(index)

    def setCurrentText(self, text: str):
        """设置当前文本"""
        self.comboBox.setCurrentText(text)

    def setCurrentIndex(self, index: int):
        """设置当前索引"""
        self.comboBox.setCurrentIndex(index)

    def addItem(self, text: str):
        """添加选项"""
        self.comboBox.addItem(text)

    def addItems(self, texts: List[str]):
        """添加多个选项"""
        self.comboBox.addItems(texts)

    def clear(self):
        """清空所有选项"""
        self.comboBox.clear()


class ColorSettingCard(SettingCard):
    """带颜色选择器的设置卡片"""

    colorChanged = pyqtSignal(QColor)

    def __init__(
        self,
        color: QColor,
        icon: Union[str, QIcon, FluentIconBase],
        title: str,
        content: Optional[str] = None,
        parent=None,
        enableAlpha=False,
    ):
        """
        参数
        ----------
        color: QColor
            初始颜色

        icon: str | QIcon | FluentIconBase
            要绘制的图标

        title: str
            卡片标题

        content: str
            卡片内容

        parent: QWidget
            父组件

        enableAlpha: bool
            是否启用透明通道
        """
        super().__init__(icon, title, content, parent)
        self.colorPicker = ColorPickerButton(color, title, self, enableAlpha)
        self.colorPicker.setFixedWidth(60)
        self.hBoxLayout.addWidget(self.colorPicker, 0, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(16)
        self.colorPicker.colorChanged.connect(self.__onColorChanged)

    def __onColorChanged(self, color: QColor):
        """颜色改变时的槽函数"""
        self.colorChanged.emit(color)

    def setColor(self, color: QColor):
        """设置颜色"""
        self.colorPicker.setColor(color)


class ColorPickerButton(QToolButton):
    """Color picker button"""

    colorChanged = pyqtSignal(QColor)

    def __init__(self, color: QColor, title: str, parent=None, enableAlpha=False):
        super().__init__(parent=parent)
        self.title = title
        self.enableAlpha = enableAlpha
        self.setFixedSize(96, 32)
        self.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore

        self.setColor(color)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore
        self.clicked.connect(self.__showColorDialog)

    def __showColorDialog(self):
        """show color dialog"""
        w = ColorDialog(
            self.color, self.tr("Choose ") + self.title, self.window(), self.enableAlpha
        )
        w.colorChanged.connect(self.__onColorChanged)
        w.exec()

    def __onColorChanged(self, color):
        """color changed slot"""
        self.setColor(color)
        self.colorChanged.emit(color)

    def setColor(self, color):
        """set color"""
        self.color = QColor(color)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        pc = QColor(255, 255, 255, 10) if isDarkTheme() else QColor(234, 234, 234)
        painter.setPen(pc)

        color = QColor(self.color)
        if not self.enableAlpha:
            color.setAlpha(255)

        painter.setBrush(color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)
