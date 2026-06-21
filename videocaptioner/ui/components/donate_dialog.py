"""捐助弹窗：说明 + 微信/支付宝二维码，基于 AppDialog 壳。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from videocaptioner.config import ASSETS_PATH
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import apply_font, draw_rounded_surface
from videocaptioner.ui.i18n import tr


class _QrCard(QFrame):
    """二维码卡：圆角面板包住二维码与渠道名。"""

    def __init__(self, image_path: Path, caption: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)
        qr = QLabel(self)
        qr.setPixmap(
            QPixmap(str(image_path)).scaled(
                228,
                228,
                Qt.KeepAspectRatio,  # type: ignore[arg-type]
                Qt.SmoothTransformation,  # type: ignore[arg-type]
            )
        )
        qr.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        qr.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(qr)
        self.captionLabel = QLabel(caption, self)
        self.captionLabel.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.captionLabel, 13, 750)
        layout.addWidget(self.captionLabel)
        self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.field, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        self.captionLabel.setStyleSheet(
            f"color: {app_palette().muted}; background: transparent; border: none;"
        )


class DonateDialog(AppDialog):
    """支持作者：感谢语 + 两个收款二维码。"""

    def __init__(self, parent=None):
        super().__init__(tr("donate.title"), icon=AppIcon.HEART, parent=parent, width=620)
        desc = self.addBodyText(tr("donate.desc"))
        desc.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]

        qr_row = QHBoxLayout()
        qr_row.setSpacing(13)
        qr_row.addWidget(
            _QrCard(ASSETS_PATH / "donate_blue.jpg", tr("donate.alipay"), self.widget)
        )
        qr_row.addWidget(
            _QrCard(ASSETS_PATH / "donate_green.jpg", tr("donate.wechat"), self.widget)
        )
        self.bodyLayout.addLayout(qr_row)

        self.addFooterStretch()
        self.dismissButton = self.addFooterButton(tr("common.close"))
        self.dismissButton.clicked.connect(lambda: self.done(0))
