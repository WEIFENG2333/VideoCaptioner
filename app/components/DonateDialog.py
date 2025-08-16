import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import BodyLabel, MessageBoxBase

from app.config import ASSETS_PATH


class DonateDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 定义二维码路径
        self.WECHAT_QR_PATH = os.path.join(ASSETS_PATH, "donate_green.jpg")
        self.ALIPAY_QR_PATH = os.path.join(ASSETS_PATH, "donate_blue.jpg")

        self.setup_ui()
        self.setWindowTitle(self.tr("支持作者"))

    def setup_ui(self):
        # 创建标题标签
        self.titleLabel = BodyLabel(self.tr("感谢支持"), self)

        # 创建说明文本
        self.descLabel = BodyLabel(
            self.tr(
                "目前本人精力有限，您的支持让我有动力继续折腾这个项目！\n感谢您对开源事业的热爱与支持！"
            ),
            self,
        )
        self.descLabel.setAlignment(Qt.AlignCenter)  # type: ignore

        # 创建水平布局放置两个二维码
        self.qrLayout = QHBoxLayout()

        # 创建支付宝二维码标签
        self.alipayContainer = QVBoxLayout()
        self.alipayQR = QLabel()
        self.alipayQR.setPixmap(
            QPixmap(self.ALIPAY_QR_PATH).scaled(
                300,
                300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.SmoothTransformation,  # type: ignore
            )
        )
        self.alipayLabel = BodyLabel(self.tr("支付宝"))
        self.alipayLabel.setAlignment(Qt.AlignCenter)  # type: ignore
        self.alipayContainer.addWidget(self.alipayQR, alignment=Qt.AlignCenter)  # type: ignore
        self.alipayContainer.addWidget(self.alipayLabel)

        # 创建微信二维码标签
        self.wechatContainer = QVBoxLayout()
        self.wechatQR = QLabel()
        self.wechatQR.setPixmap(
            QPixmap(self.WECHAT_QR_PATH).scaled(
                300,
                300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.SmoothTransformation,  # type: ignore
            )
        )
        self.wechatLabel = BodyLabel(self.tr("微信"))
        self.wechatLabel.setAlignment(Qt.AlignCenter)  # type: ignore
        self.wechatContainer.addWidget(self.wechatQR, alignment=Qt.AlignCenter)  # type: ignore
        self.wechatContainer.addWidget(self.wechatLabel)

        # 将二维码添加到水平布局
        self.qrLayout.addLayout(self.alipayContainer)
        self.qrLayout.addLayout(self.wechatContainer)

        self.viewLayout.setSpacing(30)
        # 添加到主布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        # 添加垂直间距
        self.viewLayout.addLayout(self.qrLayout)

        # 设置对话框最小宽度
        self.widget.setMinimumWidth(800)
        # 设置对话框最小高度
        self.widget.setMinimumHeight(500)

        # 隐藏是按钮，只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))
