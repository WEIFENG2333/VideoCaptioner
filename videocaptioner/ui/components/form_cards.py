from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, IconWidget, PushButton

from videocaptioner.ui.common.theme_tokens import app_palette


class FormGroup(QWidget):
    """Grouped form rows with shared card styling."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[QWidget, QFrame | None]] = []

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)

        self.titleLabel = BodyLabel(title, self)
        self.titleLabel.setObjectName("formGroupTitle")
        self.layout.addWidget(self.titleLabel)

        self.cardBox = QFrame(self)
        self.cardBox.setObjectName("formCardBox")
        self.boxLayout = QVBoxLayout(self.cardBox)
        self.boxLayout.setContentsMargins(0, 0, 0, 0)
        self.boxLayout.setSpacing(0)
        self.layout.addWidget(self.cardBox)

        self.syncStyle()

    def addCard(self, card: QWidget) -> None:  # noqa: N802
        separator = None
        if self._rows:
            separator = QFrame(self.cardBox)
            separator.setObjectName("formSeparator")
            separator.setFixedHeight(1)
            self.boxLayout.addWidget(separator)

        self.boxLayout.addWidget(card)
        card.installEventFilter(self)
        self._rows.append((card, separator))
        self._refresh_separators()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in {QEvent.Show, QEvent.Hide}:
            self._refresh_separators()
        return super().eventFilter(watched, event)

    def _refresh_separators(self) -> None:
        has_visible_before = False
        for card, separator in self._rows:
            is_visible = card.isVisible()
            if separator is not None:
                separator.setVisible(is_visible and has_visible_before)
            if is_visible:
                has_visible_before = True

    def syncStyle(self) -> None:  # noqa: N802
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QLabel#formGroupTitle {{
                color: {palette.text};
                font-size: 17px;
                font-weight: bold;
                background: transparent;
            }}
            QFrame#formCardBox {{
                border: 1px solid {palette.line};
                border-radius: 12px;
                background: {palette.panel};
            }}
            QFrame#formSeparator {{
                border: 0;
                background: {palette.line_soft};
            }}
            """
        )
        for card, _separator in self._rows:
            sync_style = getattr(card, "syncStyle", None)
            if callable(sync_style):
                sync_style()


class FormCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, icon: Any, title: str, content: str = "", parent=None):
        super().__init__(parent)
        self._content = content or ""
        self.setObjectName("formCard")
        self.setMinimumHeight(70)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        self.rootLayout = QHBoxLayout(self)
        self.rootLayout.setContentsMargins(18, 12, 18, 12)
        self.rootLayout.setSpacing(20)

        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(0, 0)
        self.iconWidget.hide()
        self.rootLayout.addWidget(self.iconWidget, 0, Qt.AlignVCenter)  # type: ignore[arg-type]

        self.textLayout = QVBoxLayout()
        self.textLayout.setContentsMargins(0, 0, 0, 0)
        self.textLayout.setSpacing(4)
        self.titleLabel = BodyLabel(title, self)
        self.contentLabel = CaptionLabel(self._content, self)
        self.contentLabel.setWordWrap(False)
        self.titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.contentLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.textLayout.addWidget(self.titleLabel)
        if self._content:
            self.textLayout.addWidget(self.contentLabel)
        self.rootLayout.addLayout(self.textLayout, 1)

        self.controlLayout = QHBoxLayout()
        self.controlLayout.setContentsMargins(0, 0, 0, 0)
        self.controlLayout.setSpacing(8)
        self.controlLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        self.rootLayout.addLayout(self.controlLayout, 0)

        self.syncStyle()

    def setContent(self, content: str) -> None:  # noqa: N802
        self._content = content or ""
        self.contentLabel.setText(self._content)
        self.contentLabel.setVisible(bool(self._content))

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def syncStyle(self) -> None:  # noqa: N802
        self.setStyleSheet(
            """
            QFrame#formCard {
                border: 0;
                border-radius: 0;
                background: transparent;
            }
            QFrame#formCard:hover {
                background: transparent;
            }
            QLabel {
                background: transparent;
            }
            """
        )


class PushFormCard(FormCard):
    def __init__(self, text: str, icon: Any, title: str, content: str = "", parent=None):
        super().__init__(icon, title, content, parent)
        self.button = PushButton(text, self)
        self.button.setFixedWidth(112)
        self.button.setFixedHeight(40)
        self.controlLayout.addWidget(self.button)
        self.button.clicked.connect(self.clicked)
        self.syncStyle()

    def syncStyle(self) -> None:  # noqa: N802
        super().syncStyle()
        if not hasattr(self, "button"):
            return
        palette = app_palette()
        self.button.setStyleSheet(
            f"""
            PushButton {{
                color: {palette.text};
                background: {palette.field};
                border: 1px solid {palette.line_soft};
                border-radius: 8px;
                font-weight: bold;
            }}
            PushButton:hover {{
                border-color: {palette.accent};
            }}
            """
        )
