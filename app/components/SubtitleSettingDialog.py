from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import (MessageBoxBase, BodyLabel, SwitchSettingCard, FluentIcon as FIF)

from ..common.config import cfg
from .SpinBoxSettingCard import SpinBoxSettingCard

class SubtitleSettingDialog(MessageBoxBase):
    """ 字幕设置对话框 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr('字幕设置'), self)

        # 创建设置卡片
        self.split_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr('字幕分割'),
            self.tr('是否对字幕智能分割（仅针对导入字幕有效）'),
            cfg.need_split,
            self
        )

        self.word_count_cjk_card = SpinBoxSettingCard(
            cfg.max_word_count_cjk,
            FIF.TILES,
            self.tr('中文最大字数'),
            self.tr('单条字幕的最大字数 (对于中日韩等字符)'),
            minimum=8,
            maximum=30,
            parent=self
        )

        self.word_count_english_card = SpinBoxSettingCard(
            cfg.max_word_count_english,
            FIF.TILES,
            self.tr('英文最大单词数'),
            self.tr('单条字幕的最大单词数 (英文)'),
            minimum=8,
            maximum=30,
            parent=self
        )

        self.remove_punctuation_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr('去除末尾标点符号'),
            self.tr('是否去除中文字幕中的末尾标点符号'),
            cfg.needs_remove_punctuation,
            self
        )
        
        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.split_card)
        self.viewLayout.addWidget(self.word_count_cjk_card)
        self.viewLayout.addWidget(self.word_count_english_card)
        self.viewLayout.addWidget(self.remove_punctuation_card)
        # 设置间距

        self.viewLayout.setSpacing(10)
        
        # 设置窗口标题
        self.setWindowTitle(self.tr('字幕设置'))

        # 只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr('关闭'))
