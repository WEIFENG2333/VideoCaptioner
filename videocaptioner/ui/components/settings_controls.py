from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    EditableComboBox,
    ScrollArea,
    SwitchButton,
)

from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.settings_state import SettingField
from videocaptioner.ui.common.theme_tokens import app_palette, is_dark_theme, rgba
from videocaptioner.ui.components.workbench import AppLineEdit, WorkbenchButton, apply_font

CONTROL_WIDTH = 246
CONTROL_HEIGHT = 42
SHORT_CONTROL_WIDTH = 112
SLIDER_WIDTH = 190
ROW_MIN_HEIGHT = 68
ROW_VERTICAL_PADDING = 11


def _bind_config_value(widget: QWidget, config_item: SettingField, handler: Callable[[Any], None]) -> None:
    config_item.valueChanged.connect(handler)

    def disconnect_handler(*_args) -> None:
        try:
            config_item.valueChanged.disconnect(handler)
        except (RuntimeError, TypeError):
            pass

    widget.destroyed.connect(disconnect_handler)


@dataclass(frozen=True)
class Option:
    value: Any
    text: str


def option_text(value: Any) -> str:
    text = str(getattr(value, "value", value))
    return text.replace(" ✨", "").strip()


def options_from(values: Iterable[Any], text: Callable[[Any], str] | None = None) -> list[Option]:
    display = text or option_text
    return [Option(value, display(value)) for value in values]


class SettingsShell(QWidget):
    pageChanged = pyqtSignal(str)
    backRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsShell")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self._pages: dict[str, SettingsPage] = {}
        self._nav_buttons: dict[str, QPushButton] = {}

        self.rootLayout = QHBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)

        self.sidebar = QFrame(self)
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.sidebarLayout = QVBoxLayout(self.sidebar)
        self.sidebarLayout.setContentsMargins(12, 18, 12, 18)
        self.sidebarLayout.setSpacing(12)

        # 弹窗里不再用左侧「返回应用」——关闭统一走右上角 X / Esc / 点遮罩
        self.navTitle = QLabel(self.tr("设置"), self.sidebar)
        self.navTitle.setObjectName("settingsNavTitle")
        apply_font(self.navTitle, 13, 820)

        self.navLayout = QVBoxLayout()
        self.navLayout.setContentsMargins(0, 0, 0, 0)
        self.navLayout.setSpacing(5)

        self.sidebarLayout.addWidget(self.navTitle)
        self.sidebarLayout.addLayout(self.navLayout)
        self.sidebarLayout.addStretch(1)

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("settingsStack")

        self.rootLayout.addWidget(self.sidebar)
        self.rootLayout.addWidget(self.stack, 1)
        self.syncStyle()

    def addPage(self, key: str, title: str) -> "SettingsPage":  # noqa: N802
        page = SettingsPage(title, self.stack)
        self._pages[key] = page
        self.stack.addWidget(page)

        button = QPushButton(title, self.sidebar)
        button.setObjectName("settingsNavButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        button.clicked.connect(lambda _checked=False, page_key=key: self.setCurrentPage(page_key))
        self._nav_buttons[key] = button
        self.navLayout.addWidget(button)
        return page

    def setCurrentPage(self, key: str) -> bool:
        page = self._pages.get(key)
        if page is None:
            return False
        self.stack.setCurrentWidget(page)
        for page_key, button in self._nav_buttons.items():
            button.setChecked(page_key == key)
        self.pageChanged.emit(key)
        return True

    def currentPageKey(self) -> str:
        current = self.stack.currentWidget()
        for key, page in self._pages.items():
            if page is current:
                return key
        return ""

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        width = max(188, min(210, int(self.width() * 0.16)))
        self.sidebar.setFixedWidth(width)

    def syncStyle(self) -> None:
        palette = app_palette()
        # 侧栏与全局面板同色，不再用独立硬编码色
        sidebar_bg = palette.panel
        sidebar_hover = rgba(palette.accent, 0.13 if is_dark_theme() else 0.10)
        sidebar_checked = rgba(palette.accent, 0.18 if is_dark_theme() else 0.14)
        self.setStyleSheet(
            f"""
            QWidget#settingsShell {{
                background: {palette.bg};
                color: {palette.text};
            }}
            QFrame#settingsSidebar {{
                background: {sidebar_bg};
                border: none;
            }}
            QLabel#settingsNavTitle {{
                color: {palette.subtle};
                background: transparent;
                margin-left: 10px;
                margin-top: 2px;
                margin-bottom: 2px;
            }}
            QPushButton#settingsNavButton {{
                min-height: 42px;
                border: none;
                border-radius: 10px;
                padding: 0 14px;
                text-align: left;
                color: {palette.muted};
                background: transparent;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton#settingsNavButton:hover {{
                color: {palette.text};
                background: {sidebar_hover};
            }}
            QPushButton#settingsNavButton:checked {{
                color: {palette.text};
                background: {sidebar_checked};
            }}
            QStackedWidget#settingsStack {{
                background: {palette.bg};
                border: none;
            }}
            """
        )
        for page in self._pages.values():
            page.syncStyle()


class SettingsPage(ScrollArea):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._groups: list[SettingsGroup] = []
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self.setWidgetResizable(True)

        self.container = QWidget(self)
        self.container.setObjectName("settingsPageContainer")
        self.container.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(52, 42, 52, 40)
        self.layout.setSpacing(0)

        self.titleLabel = QLabel(title, self.container)
        self.titleLabel.setObjectName("settingsPageTitle")
        self.titleLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.titleLabel, 30, 860)
        self.layout.addWidget(self.titleLabel, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        self.layout.addSpacing(28)
        self.layout.addStretch(1)
        self.setWidget(self.container)
        self.syncStyle()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._sync_group_widths()

    def addGroup(self, group: "SettingsGroup") -> None:  # noqa: N802
        stretch = self.layout.takeAt(self.layout.count() - 1)
        self._groups.append(group)
        self._sync_group_width(group)
        self.layout.addWidget(group, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        self.layout.addSpacing(28)
        if stretch is not None:
            self.layout.addItem(stretch)

    def _sync_group_width(self, group: "SettingsGroup") -> None:
        # 关键：组宽绝不能超过可视宽度，否则内容横向溢出、整页能被左右拖动。
        # 理想 640–940，但窄视口下以「可视宽-边距」为准（宁可窄也不溢出）。
        avail = self.viewport().width() - 104
        width = min(940, avail) if avail > 0 else self.viewport().width()
        group.setFixedWidth(max(1, width))

    def _sync_group_widths(self) -> None:
        for group in self._groups:
            self._sync_group_width(group)

    def syncStyle(self) -> None:
        palette = app_palette()
        self.setAutoFillBackground(True)
        self.viewport().setAutoFillBackground(True)
        self.viewport().setStyleSheet(f"background: {palette.bg}; border: none;")
        self.container.setStyleSheet(f"background: {palette.bg};")
        self.titleLabel.setStyleSheet(f"color: {palette.text}; background: transparent;")
        self.setStyleSheet(
            f"""
            QScrollArea#settingsPage {{
                background: {palette.bg};
                border: none;
            }}
            QWidget#settingsPageContainer {{
                background: {palette.bg};
            }}
            QLabel#settingsPageTitle {{
                color: {palette.text};
                background: transparent;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: {palette.line};
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            """
        )
        for group in self._groups:
            group.syncStyle()


class SettingsGroup(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("settingsGroup")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._rows: list[SettingRow] = []
        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)
        if title:
            self.titleLabel = QLabel(title, self)
            self.titleLabel.setObjectName("settingsSectionTitle")
            apply_font(self.titleLabel, 17, 840)
            self.rootLayout.addWidget(self.titleLabel)
            self.rootLayout.addSpacing(14)
        else:
            self.titleLabel = None
        self.box = QFrame(self)
        self.box.setObjectName("settingsBox")
        self.boxLayout = QVBoxLayout(self.box)
        self.boxLayout.setContentsMargins(0, 0, 0, 0)
        self.boxLayout.setSpacing(0)
        self.rootLayout.addWidget(self.box)
        self.syncStyle()

    def addRow(self, row: "SettingRow") -> "SettingRow":  # noqa: N802
        if self._rows:
            self._rows[-1].setLast(False)
        self._rows.append(row)
        row.setLast(True)
        row.installEventFilter(self)
        self.boxLayout.addWidget(row)
        self._refresh_row_edges()
        return row

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in {QEvent.Show, QEvent.Hide}:
            self._refresh_row_edges()
        return super().eventFilter(watched, event)

    def _refresh_row_edges(self) -> None:
        visible_rows = [row for row in self._rows if row.isVisible()]
        last_visible = visible_rows[-1] if visible_rows else None
        for row in self._rows:
            row.setLast(row is last_visible)

    def syncStyle(self) -> None:
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QLabel#settingsSectionTitle {{
                color: {palette.text};
                background: transparent;
            }}
            QFrame#settingsBox {{
                background: {palette.panel};
                border: 1px solid {palette.line};
                border-radius: 14px;
            }}
            """
        )
        for row in self._rows:
            row.syncStyle()


class SettingRow(QFrame):
    def __init__(self, title: str, description: str = "", control: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.setMinimumHeight(ROW_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)  # 高度随描述换行增长，不裁字
        self._is_last = False
        self.rootLayout = QHBoxLayout(self)
        self.rootLayout.setContentsMargins(18, ROW_VERTICAL_PADDING, 18, ROW_VERTICAL_PADDING)
        self.rootLayout.setSpacing(24)

        textBox = QWidget(self)
        textBox.setObjectName("settingRowTextBox")
        textBox.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        textLayout = QVBoxLayout(textBox)
        textLayout.setContentsMargins(0, 0, 0, 0)
        textLayout.setSpacing(6)
        self.titleLabel = QLabel(title, textBox)
        self.titleLabel.setObjectName("settingRowTitle")
        self.descLabel = QLabel(description, textBox)
        self.descLabel.setObjectName("settingRowDescription")
        self.descLabel.setWordWrap(True)  # 描述自动换行，不再被右侧控件挤出容器/截断
        self.titleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.descLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        apply_font(self.titleLabel, 15, 820)
        apply_font(self.descLabel, 13, 500)
        textLayout.addWidget(self.titleLabel)
        if description:
            textLayout.addWidget(self.descLabel)
        else:
            self.descLabel.hide()

        self.controlSlot = QWidget(self)
        self.controlSlot.setObjectName("settingRowControlSlot")
        self.controlSlot.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.controlLayout = QHBoxLayout(self.controlSlot)
        self.controlLayout.setContentsMargins(0, 0, 0, 0)
        self.controlLayout.setSpacing(8)
        self.controlLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]

        self.rootLayout.addWidget(textBox, 1)
        self.rootLayout.addWidget(self.controlSlot, 0)
        if control is not None:
            self.setControl(control)
        self.syncStyle()

    def setControl(self, control: QWidget) -> None:  # noqa: N802
        while self.controlLayout.count():
            item = self.controlLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.controlLayout.addWidget(control)
        self._sync_control_styles()

    def setLast(self, is_last: bool) -> None:  # noqa: N802
        self._is_last = is_last
        self.syncStyle()

    def syncStyle(self) -> None:
        palette = app_palette()
        border = "none" if self._is_last else f"1px solid {palette.line_soft}"
        self.setStyleSheet(
            f"""
            QFrame#settingRow {{
                min-height: {ROW_MIN_HEIGHT}px;
                background: transparent;
                border: none;
                border-bottom: {border};
            }}
            QLabel#settingRowTitle {{
                color: {palette.text};
                background: transparent;
            }}
            QLabel#settingRowDescription {{
                color: {palette.muted};
                background: transparent;
            }}
            QWidget#settingRowControlSlot,
            QWidget#settingRowTextBox {{
                background: transparent;
            }}
            """
        )
        self._sync_control_styles()

    def _sync_control_styles(self) -> None:
        for widget in self.controlSlot.findChildren(QWidget):
            sync_style = getattr(widget, "syncStyle", None)
            if callable(sync_style):
                sync_style()
            if widget.objectName() == "settingsButton":
                _apply_button_style(widget, bool(widget.property("settingsPrimary")))
            elif widget.objectName() == "settingsValueLabel" and not widget.property("settingsCustomStyle"):
                _apply_value_label_style(widget)


class BoundComboBox(ComboBox):
    currentValueChanged = pyqtSignal(object)

    def __init__(self, config_item: SettingField, options: Iterable[Option], parent=None):
        super().__init__(parent)
        self.config_item = config_item
        self.options: list[Option] = list(options)
        self.setObjectName("settingsControl")
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setFixedWidth(CONTROL_WIDTH)
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._populate()
        self.currentTextChanged.connect(self._on_text_changed)
        _bind_config_value(self, config_item, self.setValue)
        self.syncStyle()

    def _populate(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItems([option.text for option in self.options])
        self.setValue(self.config_item.value)
        self.blockSignals(False)

    def setOptions(self, options: Iterable[Option], keep_value: Any | None = None) -> None:  # noqa: N802
        self.options = list(options)
        if keep_value is not None:
            cfg.set(self.config_item, keep_value)
        self._populate()

    def value(self) -> Any:
        text = self.currentText()
        for option in self.options:
            if option.text == text:
                return option.value
        return text

    def setValue(self, value: Any) -> None:  # noqa: N802
        text = option_text(value)
        for option in self.options:
            if option.value == value:
                text = option.text
                break
        self.blockSignals(True)
        if text and self.findText(text) < 0:
            self.addItem(text)
        self.setCurrentText(text)
        self.blockSignals(False)

    def _on_text_changed(self, _text: str) -> None:
        value = self.value()
        cfg.set(self.config_item, value)
        self.currentValueChanged.emit(value)

    def syncStyle(self) -> None:
        _apply_control_style(self)


class BoundEditableComboBox(EditableComboBox):
    currentValueChanged = pyqtSignal(str)

    def paintEvent(self, e):  # noqa: N802
        # 跳过 qfluent 聚焦底部下划线：聚焦态已有边框，双重指示很乱
        QLineEdit.paintEvent(self, e)

    def __init__(self, config_item: SettingField, items: Iterable[str] = (), parent=None):
        super().__init__(parent)
        self.config_item = config_item
        self.setObjectName("settingsControl")
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setFixedWidth(CONTROL_WIDTH)
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setItems(list(items))
        self.setValue(str(config_item.value or ""))
        self.currentTextChanged.connect(self._on_text_changed)
        _bind_config_value(self, config_item, self._set_config_value)
        self.syncStyle()

    def setItems(self, items: Iterable[str]) -> None:  # noqa: N802
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(list(items))
        if current:
            if self.findText(current) < 0:
                self.addItem(current)
            self.setText(current)
        self.blockSignals(False)

    def setValue(self, value: str) -> None:  # noqa: N802
        self.blockSignals(True)
        if value and self.findText(value) < 0:
            self.addItem(value)
        self.setText(value)
        self.blockSignals(False)

    def _set_config_value(self, value: Any) -> None:
        self.setValue(str(value or ""))

    def _on_text_changed(self, text: str) -> None:
        if "key" in self.config_item.name.lower():
            text = text.strip()
        cfg.set(self.config_item, text)
        self.currentValueChanged.emit(text)

    def syncStyle(self) -> None:
        _apply_control_style(self)


class BoundLineEdit(AppLineEdit):
    """设置页文本输入：复用第一方 AppLineEdit（自绘圆角、聚焦主题色描边、

    失焦自动清除、无 qfluent 下划线），并绑定到配置项。"""

    def __init__(self, config_item: SettingField, placeholder: str = "", parent=None, password: bool = False):
        super().__init__(parent=parent, height=CONTROL_HEIGHT)
        self.config_item = config_item
        self.setFixedWidth(CONTROL_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setPlaceholderText(placeholder)
        if password:
            self.setEchoMode(QLineEdit.Password)
        self.setText(str(config_item.value or ""))
        self.textChanged.connect(self._on_text_changed)
        _bind_config_value(self, config_item, self.setValue)

    def setValue(self, value: Any) -> None:  # noqa: N802
        self.blockSignals(True)
        self.setText(str(value or ""))
        self.blockSignals(False)

    def _on_text_changed(self, text: str) -> None:
        if "key" in self.config_item.name.lower():
            text = text.strip()
            if text != self.text():
                self.blockSignals(True)
                self.setText(text)
                self.blockSignals(False)
        cfg.set(self.config_item, text)


class BoundSwitch(SwitchButton):
    def __init__(self, config_item: SettingField, parent=None):
        super().__init__(parent)
        self.config_item = config_item
        self.setOnText("")
        self.setOffText("")
        self.setChecked(bool(config_item.value))
        self.checkedChanged.connect(self._on_checked_changed)
        _bind_config_value(self, config_item, self.setChecked)

    def _on_checked_changed(self, checked: bool) -> None:
        cfg.set(self.config_item, checked)


class BoundSlider(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, config_item: SettingField, parent=None):
        super().__init__(parent)
        self.config_item = config_item
        self.setObjectName("settingsSliderControl")
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        minimum, maximum = getattr(config_item, "range", (0, 100))
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)
        self.label = QLabel(str(config_item.value), self)
        self.label.setObjectName("settingsSliderLabel")
        self.label.setFixedWidth(38)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setObjectName("settingsSlider")
        self.slider.setRange(int(minimum), int(maximum))
        self.slider.setFixedWidth(SLIDER_WIDTH)
        self.slider.setValue(int(config_item.value))
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._on_value_changed)
        _bind_config_value(self, config_item, self.setValue)
        self.syncStyle()

    def setValue(self, value: Any) -> None:  # noqa: N802
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self.label.setText(str(value))

    def _on_value_changed(self, value: int) -> None:
        cfg.set(self.config_item, value)
        self.label.setText(str(value))
        self.valueChanged.emit(value)

    def syncStyle(self) -> None:
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QWidget#settingsSliderControl,
            QSlider#settingsSlider {{
                background: transparent;
            }}
            QLabel#settingsSliderLabel {{
                color: {palette.text};
                background: transparent;
                min-width: 34px;
            }}
            QSlider#settingsSlider::groove:horizontal {{
                height: 4px;
                border-radius: 2px;
                background: {palette.line_soft};
            }}
            QSlider#settingsSlider::sub-page:horizontal {{
                height: 4px;
                border-radius: 2px;
                background: {palette.accent};
            }}
            QSlider#settingsSlider::add-page:horizontal {{
                height: 4px;
                border-radius: 2px;
                background: {palette.line_soft};
            }}
            QSlider#settingsSlider::handle:horizontal {{
                width: 18px;
                height: 18px;
                margin: -7px 0;
                border-radius: 9px;
                background: {palette.accent};
                border: 1px solid {palette.control_border};
            }}
            """
        )


class BoundFloatSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, config_item: SettingField, decimals: int = 2, parent=None):
        super().__init__(parent)
        self.config_item = config_item
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.decimals = decimals
        self.scale = 10 ** decimals
        minimum, maximum = getattr(config_item, "range", (0, 1))
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)
        self.label = QLabel(self._format(float(config_item.value)), self)
        self.label.setObjectName("settingsSliderLabel")
        self.label.setFixedWidth(48)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(int(float(minimum) * self.scale), int(float(maximum) * self.scale))
        self.slider.setFixedWidth(SLIDER_WIDTH)
        self.slider.setValue(int(float(config_item.value) * self.scale))
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._on_value_changed)
        _bind_config_value(self, config_item, self.setValue)
        self.syncStyle()

    def _format(self, value: float) -> str:
        return f"{value:.{self.decimals}f}"

    def setValue(self, value: Any) -> None:  # noqa: N802
        numeric = float(value)
        self.slider.blockSignals(True)
        self.slider.setValue(int(numeric * self.scale))
        self.slider.blockSignals(False)
        self.label.setText(self._format(numeric))

    def _on_value_changed(self, slider_value: int) -> None:
        value = slider_value / self.scale
        cfg.set(self.config_item, value)
        self.label.setText(self._format(value))
        self.valueChanged.emit(value)

    def syncStyle(self) -> None:
        BoundSlider.syncStyle(self)  # type: ignore[misc]


def make_button(text: str, primary: bool = False, parent=None) -> WorkbenchButton:
    """设置页操作按钮：统一用第一方 WorkbenchButton（弃 qfluent PushButton），与全站按钮一致。"""
    button = WorkbenchButton(text, None, primary=primary, height=CONTROL_HEIGHT, parent=parent)
    button.setMinimumWidth(SHORT_CONTROL_WIDTH)
    return button


class _ElidedPathLabel(QLabel):
    """只读路径展示：家目录缩写成 ~，超宽时中段省略，完整路径走 tooltip。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsValueLabel")
        self.setProperty("settingsCustomStyle", False)
        self.setFixedWidth(CONTROL_WIDTH)
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)  # type: ignore[arg-type]
        _apply_value_label_style(self)
        self._display = ""

    def setPath(self, path: str, placeholder: str) -> None:
        if path:
            from pathlib import Path

            home = str(Path.home())
            self._display = "~" + path[len(home):] if path.startswith(home) else path
            self.setToolTip(path)
        else:
            self._display = placeholder
            self.setToolTip("")
        self._refresh_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elide()

    def _refresh_elide(self) -> None:
        # 路径首尾都有信息量（盘符/盘点 + 末级目录名），中段省略最可读。
        width = self.width() - 28  # 与 value label 的左右内边距对齐
        self.setText(self.fontMetrics().elidedText(self._display, Qt.ElideMiddle, width))  # type: ignore[arg-type]


class FolderPickerControl(QWidget):
    """目录设置控件：只读路径 + 「打开」 + 「更改」。

    目录路径是配置值，不该被当文本手敲——只读展示防误改；「打开」
    满足最常见的"看看里面有什么"诉求；选目录统一走系统对话框
    （changeRequested 由所属页面接管，便于定制对话框标题与落库）。
    """

    changeRequested = pyqtSignal()

    def __init__(self, parent=None, *, placeholder: str = ""):
        super().__init__(parent)
        self._path = ""
        self._placeholder = placeholder
        self.setObjectName("settingsControlPair")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setStyleSheet("QWidget#settingsControlPair { background: transparent; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.pathLabel = _ElidedPathLabel(self)
        self.openButton = make_button(self.tr("打开"), parent=self)
        self.changeButton = make_button(self.tr("更改"), parent=self)
        layout.addWidget(self.pathLabel)
        layout.addWidget(self.openButton)
        layout.addWidget(self.changeButton)

        self.openButton.clicked.connect(self._open)
        self.changeButton.clicked.connect(self.changeRequested)

    def path(self) -> str:
        return self._path

    def setPath(self, path: str) -> None:
        self._path = str(path or "")
        self.pathLabel.setPath(self._path, self._placeholder)
        self.openButton.setEnabled(bool(self._path))

    def _open(self) -> None:
        from videocaptioner.core.utils.platform_utils import open_folder

        if self._path:
            open_folder(self._path)


class ColorSwatchButton(QPushButton):
    colorChanged = pyqtSignal(QColor)

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsColorSwatch")
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        # 124 + 间距 10 + 按钮 112 = CONTROL_WIDTH，与其他行左缘对齐
        self.setFixedSize(124, CONTROL_HEIGHT)
        self._color = QColor(color)
        self.syncStyle()

    def color(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor) -> None:  # noqa: N802
        if not color.isValid():
            return
        self._color = QColor(color)
        self.syncStyle()
        self.colorChanged.emit(QColor(color))

    def syncStyle(self) -> None:
        palette = app_palette()
        color = self._color if self._color.isValid() else QColor(palette.accent)
        self.setToolTip(color.name(QColor.HexRgb))
        self.setStyleSheet(
            f"""
            QPushButton#settingsColorSwatch {{
                background: {color.name(QColor.HexRgb)};
                border: 1px solid {palette.control_border_strong};
                border-radius: 9px;
            }}
            QPushButton#settingsColorSwatch:hover {{
                border: 2px solid {palette.text};
            }}
            """
        )


def _apply_value_label_style(label: QWidget) -> None:
    palette = app_palette()
    label.setStyleSheet(
        f"""
            QLabel#settingsValueLabel {{
                color: {palette.text};
                background: {palette.field};
                border: 1px solid {palette.line_soft};
                border-radius: 9px;
            padding: 0 12px;
            font-weight: bold;
        }}
        """
    )


def _apply_control_style(widget: QWidget) -> None:
    palette = app_palette()
    widget.setStyleSheet(
        f"""
            QWidget#settingsControl,
            ComboBox#settingsControl,
            EditableComboBox#settingsControl,
            QPushButton#settingsControl,
            QToolButton#settingsControl,
            LineEdit#settingsControl {{
            min-height: {CONTROL_HEIGHT}px;
            max-height: {CONTROL_HEIGHT}px;
            color: {palette.text};
            background: {palette.field};
            border: 1px solid {palette.line_soft};
            border-radius: 9px;
            padding: 0 12px;
            font-weight: bold;
        }}
        QWidget#settingsControl:hover,
        ComboBox#settingsControl:hover,
        EditableComboBox#settingsControl:hover,
        QPushButton#settingsControl:hover,
        QToolButton#settingsControl:hover,
        LineEdit#settingsControl:hover {{
            border-color: {palette.accent_border};
        }}
        EditableComboBox#settingsControl:focus,
        LineEdit#settingsControl:focus {{
            border: 1px solid {palette.accent};
        }}
        """
    )


def _apply_button_style(button: QWidget, primary: bool) -> None:
    palette = app_palette()
    if primary:
        bg = palette.accent
        fg = palette.accent_fg
        border = palette.accent
    else:
        bg = palette.panel
        fg = palette.text
        border = palette.line
    button.setStyleSheet(
        f"""
        QPushButton#settingsButton {{
            color: {fg};
            background: {bg};
            border: 1px solid {border};
            border-radius: 9px;
            padding: 0 14px;
            font-weight: bold;
        }}
        QPushButton#settingsButton:hover {{
            background: {palette.accent_soft if not primary else palette.accent};
        }}
        QPushButton#settingsButton:disabled {{
            color: {palette.subtle};
            background: {palette.disabled};
            border-color: {palette.line_soft};
        }}
        """
    )
