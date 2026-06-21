"""第一方弹窗壳。

AppDialog 是应用内所有弹窗统一的外壳：半透明遮罩 + 居中卡片 +
标题栏（图标盒 / 标题 / 圆形关闭钮 / 分隔线）。内容加到
``self.bodyLayout``，底部按钮加到 ``self.footerLayout``。

parent 一律提升为 ``parent.window()``：弹窗永远基于整个程序窗口
居中与遮罩，而不是触发它的子页面（tab）。

ConfirmDialog 是标准确认框（标题 + 正文 + 取消/确认），替代
qfluent MessageBox；确认返回 1，取消/Esc/关闭返回 0。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.workbench import (
    AccentButton,
    AppLineEdit,
    CompactButton,
    DangerButton,
    IconBox,
    RoundIconButton,
    apply_font,
)
from videocaptioner.ui.i18n import tr

# 哨兵：区分「未传按钮文案」（→ 取当前语言默认）与显式传 None（ConfirmDialog 表示隐藏取消钮）
_UNSET = object()


class AppDialog(MaskDialogBase):
    """通用弹窗壳：遮罩 + 居中卡片 + 标题栏。"""

    def __init__(
        self,
        title: str,
        icon: AppIcon | None = None,
        parent: QWidget | None = None,
        width: int = 460,
    ):
        # 强制基于程序主窗口：遮罩盖满整个程序，卡片相对主窗口居中
        super().__init__(parent.window() if parent is not None else None)
        self.setShadowEffect(60, (0, 8), QColor(0, 0, 0, 100))
        self.setMaskColor(QColor(0, 0, 0, 150))
        self.setClosableOnMaskClicked(True)  # 点遮罩空白处关闭（等同取消/Esc）
        # MaskDialogBase 默认把 widget 拉伸占满遮罩，卡片必须居中按内容收身
        self._hBoxLayout.setAlignment(self.widget, Qt.AlignCenter)  # type: ignore[arg-type]

        card = self.widget
        card.setObjectName("appDialogCard")
        card.setFixedWidth(width)
        self.cardLayout = QVBoxLayout(card)
        self.cardLayout.setContentsMargins(22, 18, 22, 16)
        self.cardLayout.setSpacing(13)

        header = QHBoxLayout()
        header.setSpacing(11)
        if icon is not None:
            header.addWidget(IconBox(icon, card, size=34))
        self.titleLabel = QLabel(title, card)
        self.titleLabel.setObjectName("appDialogTitle")
        apply_font(self.titleLabel, 16, 860)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        self.closeButton = RoundIconButton(AppIcon.CLOSE, parent=card)
        self.closeButton.clicked.connect(lambda: self.done(0))
        header.addWidget(self.closeButton)
        self.cardLayout.addLayout(header)

        self.headDivider = QFrame(card)
        self.headDivider.setObjectName("appDialogDivider")
        self.headDivider.setFixedHeight(1)
        self.cardLayout.addWidget(self.headDivider)

        self.bodyLayout = QVBoxLayout()
        self.bodyLayout.setContentsMargins(0, 0, 0, 0)
        self.bodyLayout.setSpacing(10)
        self.cardLayout.addLayout(self.bodyLayout)

        self.footerLayout = QHBoxLayout()
        self.footerLayout.setContentsMargins(0, 3, 0, 0)
        self.footerLayout.setSpacing(10)
        self.cardLayout.addLayout(self.footerLayout)

        self.syncStyle()

    # ------------------------------------------------------------- helpers

    def addBodyText(self, text: str) -> QLabel:
        """正文段落：可换行、可选中的次级文字。"""
        label = QLabel(text, self.widget)
        label.setObjectName("appDialogBodyText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore[arg-type]
        apply_font(label, 13, 600)
        self.bodyLayout.addWidget(label)
        return label

    def addFooterButton(
        self, text: str, *, kind: str = "plain", icon: AppIcon | None = None
    ) -> CompactButton:
        """底栏按钮，从左到右排列；kind: plain / accent / danger。"""
        cls = {"plain": CompactButton, "accent": AccentButton, "danger": DangerButton}[
            kind
        ]
        button = cls(text, icon, self.widget)
        self.footerLayout.addWidget(button)
        return button

    def addFooterStretch(self):
        self.footerLayout.addStretch(1)

    # --------------------------------------------------------------- style

    def extraStyleRules(self, palette) -> str:
        """子类追加卡片内部样式规则。"""
        return ""

    def syncStyle(self):
        palette = app_palette()
        self.widget.setStyleSheet(
            f"""
            QWidget#appDialogCard {{
                background: {palette.panel};
                border: 1px solid {palette.line};
                border-radius: 16px;
            }}
            QLabel#appDialogTitle {{ color: {palette.text}; background: transparent; }}
            QFrame#appDialogDivider {{ background: {palette.line_soft}; border: none; }}
            QLabel#appDialogBodyText {{ color: {palette.muted}; background: transparent; }}
            QLabel#appDialogSectionLabel {{ color: {palette.subtle}; background: transparent; }}
            """
            + self.extraStyleRules(palette)
        )


class ConfirmDialog(AppDialog):
    """标准确认框：确认返回 1，取消/Esc/关闭返回 0。

    cancel_text 传 None 只留一个确认按钮（公告式）。danger=True 时
    确认按钮用危险样式（删除/清空等不可逆操作）。
    """

    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        confirm_text: str | None = None,
        cancel_text: str | None = _UNSET,  # type: ignore[assignment]
        danger: bool = False,
        icon: AppIcon | None = None,
        width: int = 430,
    ):
        super().__init__(title, icon=icon, parent=parent, width=width)
        # 默认文案在运行时取，跟随当前语言；显式传 None 表示隐藏取消钮
        if confirm_text is None:
            confirm_text = tr("common.ok")
        if cancel_text is _UNSET:
            cancel_text = tr("common.cancel")
        self.messageLabel = self.addBodyText(message)
        self.addFooterStretch()
        self.cancelButton: CompactButton | None = None
        if cancel_text is not None:
            self.cancelButton = self.addFooterButton(cancel_text)
            self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(
            confirm_text, kind="danger" if danger else "accent"
        )
        self.confirmButton.clicked.connect(lambda: self.done(1))


class InputDialog(AppDialog):
    """单行文本输入框：确认返回 1（``value()`` 取文本），取消/Esc/关闭返回 0。

    回车即确认，打开即聚焦并全选既有文本（重命名场景方便直接改）。
    """

    def __init__(
        self,
        title: str,
        *,
        text: str = "",
        placeholder: str = "",
        parent: QWidget | None = None,
        confirm_text: str | None = None,
        cancel_text: str | None = None,
        icon: AppIcon | None = None,
        width: int = 430,
    ):
        super().__init__(title, icon=icon, parent=parent, width=width)
        # 默认按钮文案在运行时取，跟随当前语言
        if confirm_text is None:
            confirm_text = tr("common.ok")
        if cancel_text is None:
            cancel_text = tr("common.cancel")
        self.edit = AppLineEdit(text, self.widget)
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(lambda: self.done(1))  # 回车=确认
        self.bodyLayout.addWidget(self.edit)
        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(cancel_text)
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(confirm_text, kind="accent")
        self.confirmButton.clicked.connect(lambda: self.done(1))
        self.edit.setFocus()
        self.edit.selectAll()

    def value(self) -> str:
        return self.edit.text().strip()
