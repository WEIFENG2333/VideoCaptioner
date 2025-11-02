# -*- coding: utf-8 -*-
from qfluentwidgets import (
    BodyLabel,
    ComboBoxSettingCard,
    MessageBoxBase,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.core.entities import TranscribeOutputFormatEnum


class TranscriptionOutputDialog(MessageBoxBase):
    """转录输出格式设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("输出设置"), self)

        # 创建输出格式选择卡片
        self.output_format_card = ComboBoxSettingCard(
            cfg.transcribe_output_format,
            FIF.SAVE,
            self.tr("输出格式"),
            self.tr("选择转录字幕的输出格式"),
            texts=[fmt.value for fmt in TranscribeOutputFormatEnum],
            parent=self,
        )

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.output_format_card)
        # 设置间距
        self.viewLayout.setSpacing(10)

        # 设置窗口标题
        self.setWindowTitle(self.tr("输出设置"))

        # 只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))

