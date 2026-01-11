import json
from pathlib import Path
from typing import Optional, Tuple

from PIL import ImageFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFontDatabase
from PyQt5.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ImageLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PushSettingCard,
    ScrollArea,
    SettingCardGroup,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.components.MySettingCard import (
    ColorSettingCard,
    ComboBoxSettingCard,
    DoubleSpinBoxSettingCard,
    SpinBoxSettingCard,
)
from app.config import ASSETS_PATH, SUBTITLE_STYLE_PATH
from app.core.subtitle import get_builtin_fonts
from app.core.constant import INFOBAR_DURATION_SUCCESS, INFOBAR_DURATION_WARNING
from app.core.entities import SubtitleLayoutEnum, SubtitleRenderModeEnum
from app.core.subtitle import render_ass_preview, render_preview
from app.core.subtitle.styles import RoundedBgStyle
from app.core.utils.platform_utils import open_folder

PERVIEW_TEXTS = {
    "长文本": (
        "This is a long text for testing subtitle preview, text wrapping, and style settings.",
        "这是一段用于测试字幕预览、自动换行以及样式设置的较长文本内容。",
    ),
    "中文本": (
        "Welcome to apply for the prestigious South China Normal University!",
        "欢迎报考百年名校华南师范大学",
    ),
    "短文本": ("Elementary school students know this", "小学二年级的都知道"),
}

DEFAULT_BG_LANDSCAPE = {
    "path": ASSETS_PATH / "default_bg_landscape.png",
    "width": 1280,
    "height": 720,
}
DEFAULT_BG_PORTRAIT = {
    "path": ASSETS_PATH / "default_bg_portrait.png",
    "width": 480,
    "height": 852,
}


class AssPreviewThread(QThread):
    """ASS 样式预览线程"""

    previewReady = pyqtSignal(str)

    def __init__(
        self,
        preview_text: Tuple[str, Optional[str]],
        style_str: str,
        bg_image_path: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        super().__init__()
        self.preview_text = preview_text
        self.width = width
        self.height = height
        self.style_str = style_str
        self.bg_image_path = bg_image_path

    def run(self):
        preview_path = render_ass_preview(
            style_str=self.style_str,
            preview_text=self.preview_text,
            bg_image_path=self.bg_image_path,
            width=self.width,
            height=self.height,
        )
        self.previewReady.emit(preview_path)


class RoundedBgPreviewThread(QThread):
    """圆角背景预览线程"""

    previewReady = pyqtSignal(str)

    def __init__(
        self,
        style: RoundedBgStyle,
        preview_text: Tuple[str, Optional[str]],
        width: Optional[int] = None,
        height: Optional[int] = None,
        bg_image_path: Optional[str] = None,
    ):
        super().__init__()
        self.primary_text = preview_text[0]
        self.secondary_text = preview_text[1] or ""
        self.width = width
        self.height = height
        self.style = style
        self.bg_image_path = bg_image_path

    def run(self):
        preview_path = render_preview(
            primary_text=self.primary_text,
            secondary_text=self.secondary_text,
            width=self.width,
            height=self.height,
            style=self.style,
            bg_image_path=self.bg_image_path,
        )
        self.previewReady.emit(preview_path)


class SubtitleStyleInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SubtitleStyleInterface")
        self.setWindowTitle(self.tr("字幕样式配置"))
        self.setAcceptDrops(True)  # 启用拖放功能

        # 创建主布局
        self.hBoxLayout = QHBoxLayout(self)

        # 初始化界面组件
        self._initSettingsArea()
        self._initPreviewArea()
        self._initSettingCards()
        self._initLayout()
        self._initStyle()

        # 控制是否触发样式变更回调（加载样式时禁用）
        self._loading_style = False

        # 设置初始值,加载样式
        self.__setValues()

        # 连接信号
        self.connectSignals()

    def _initSettingsArea(self):
        """初始化左侧设置区域"""
        self.settingsScrollArea = ScrollArea()
        self.settingsScrollArea.setFixedWidth(350)
        self.settingsWidget = QWidget()
        self.settingsLayout = QVBoxLayout(self.settingsWidget)
        self.settingsScrollArea.setWidget(self.settingsWidget)
        self.settingsScrollArea.setWidgetResizable(True)

        # 创建设置组 - 通用
        self.layoutGroup = SettingCardGroup(self.tr("字幕排布"), self.settingsWidget)

        # ASS 样式设置组
        self.assPrimaryGroup = SettingCardGroup(
            self.tr("主字幕样式"), self.settingsWidget
        )
        self.assSecondaryGroup = SettingCardGroup(
            self.tr("副字幕样式"), self.settingsWidget
        )

        # 圆角背景设置组
        self.roundedBgGroup = SettingCardGroup(
            self.tr("圆角背景样式"), self.settingsWidget
        )

        # 预览设置组
        self.previewGroup = SettingCardGroup(self.tr("预览设置"), self.settingsWidget)

    def _initPreviewArea(self):
        """初始化右侧预览区域"""
        self.previewCard = CardWidget()
        self.previewLayout = QVBoxLayout(self.previewCard)
        self.previewLayout.setSpacing(16)

        # 顶部预览区域
        self.previewTopWidget = QWidget()
        self.previewTopWidget.setFixedHeight(430)
        self.previewTopLayout = QVBoxLayout(self.previewTopWidget)

        self.previewLabel = BodyLabel(self.tr("预览效果"))
        self.previewImage = ImageLabel()
        self.previewImage.setAlignment(Qt.AlignCenter)  # type: ignore
        self.previewTopLayout.addWidget(self.previewImage, 0, Qt.AlignCenter)  # type: ignore
        self.previewTopLayout.setAlignment(Qt.AlignVCenter)  # type: ignore

        # 底部控件区域
        self.previewBottomWidget = QWidget()
        self.previewBottomLayout = QVBoxLayout(self.previewBottomWidget)

        self.styleNameComboBox = ComboBoxSettingCard(
            FIF.VIEW,  # type: ignore
            self.tr("选择样式"),
            self.tr("选择已保存的字幕样式"),
            texts=[],  # type: ignore
        )

        self.newStyleButton = PushSettingCard(
            self.tr("新建样式"),
            FIF.ADD,
            self.tr("新建样式"),
            self.tr("基于当前样式新建预设"),
        )

        self.openStyleFolderButton = PushSettingCard(
            self.tr("打开样式文件夹"),
            FIF.FOLDER,
            self.tr("打开样式文件夹"),
            self.tr("在文件管理器中打开样式文件夹"),
        )

        self.previewBottomLayout.addWidget(self.styleNameComboBox)
        self.previewBottomLayout.addWidget(self.newStyleButton)
        self.previewBottomLayout.addWidget(self.openStyleFolderButton)

        self.previewLayout.addWidget(self.previewTopWidget)
        self.previewLayout.addWidget(self.previewBottomWidget)
        self.previewLayout.addStretch(1)

    def _initSettingCards(self):
        """初始化所有设置卡片"""
        # 渲染模式切换
        self.renderModeCard = ComboBoxSettingCard(
            FIF.BRUSH,  # type: ignore
            self.tr("渲染模式"),
            self.tr("选择字幕渲染方式"),
            texts=[e.value for e in SubtitleRenderModeEnum],
        )

        # 字幕排布设置
        self.layoutCard = ComboBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("字幕排布"),
            self.tr("设置主字幕和副字幕的显示方式"),
            texts=["译文在上", "原文在上", "仅译文", "仅原文"],
        )

        # ASS 模式 - 垂直间距
        self.assVerticalSpacingCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("垂直间距"),
            self.tr("设置字幕的垂直间距"),
            minimum=8,
            maximum=10000,
        )

        # ASS 模式 - 主字幕样式
        self.assPrimaryFontCard = ComboBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("主字幕字体"),
            self.tr("设置主字幕的字体"),
        )

        self.assPrimarySizeCard = SpinBoxSettingCard(
            FIF.FONT_SIZE,  # type: ignore
            self.tr("主字幕字号"),
            self.tr("设置主字幕的大小"),
            minimum=8,
            maximum=1000,
        )

        self.assPrimarySpacingCard = DoubleSpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("主字幕间距"),
            self.tr("设置主字幕的字符间距"),
            minimum=0.0,
            maximum=10.0,
            decimals=1,
        )

        self.assPrimaryColorCard = ColorSettingCard(
            QColor(255, 255, 255),
            FIF.PALETTE,  # type: ignore
            self.tr("主字幕颜色"),
            self.tr("设置主字幕的颜色"),
        )

        self.assPrimaryOutlineColorCard = ColorSettingCard(
            QColor(0, 0, 0),
            FIF.PALETTE,  # type: ignore
            self.tr("主字幕边框颜色"),
            self.tr("设置主字幕的边框颜色"),
        )

        self.assPrimaryOutlineSizeCard = DoubleSpinBoxSettingCard(
            FIF.ZOOM,  # type: ignore
            self.tr("主字幕边框大小"),
            self.tr("设置主字幕的边框粗细"),
            minimum=0.0,
            maximum=10.0,
            decimals=1,
        )

        # ASS 模式 - 副字幕样式
        self.assSecondaryFontCard = ComboBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("副字幕字体"),
            self.tr("设置副字幕的字体"),
        )

        self.assSecondarySizeCard = SpinBoxSettingCard(
            FIF.FONT_SIZE,  # type: ignore
            self.tr("副字幕字号"),
            self.tr("设置副字幕的大小"),
            minimum=8,
            maximum=1000,
        )

        self.assSecondarySpacingCard = DoubleSpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("副字幕间距"),
            self.tr("设置副字幕的字符间距"),
            minimum=0.0,
            maximum=50.0,
            decimals=1,
        )

        self.assSecondaryColorCard = ColorSettingCard(
            QColor(255, 255, 255),
            FIF.PALETTE,  # type: ignore
            self.tr("副字幕颜色"),
            self.tr("设置副字幕的颜色"),
        )

        self.assSecondaryOutlineColorCard = ColorSettingCard(
            QColor(0, 0, 0),
            FIF.PALETTE,  # type: ignore
            self.tr("副字幕边框颜色"),
            self.tr("设置副字幕的边框颜色"),
        )

        self.assSecondaryOutlineSizeCard = DoubleSpinBoxSettingCard(
            FIF.ZOOM,  # type: ignore
            self.tr("副字幕边框大小"),
            self.tr("设置副字幕的边框粗细"),
            minimum=0.0,
            maximum=50.0,
            decimals=1,
        )

        # 圆角背景样式设置
        self.roundedFontCard = ComboBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("字体"),
            self.tr("设置字幕字体"),
        )

        self.roundedFontSizeCard = SpinBoxSettingCard(
            FIF.FONT_SIZE,  # type: ignore
            self.tr("字体大小"),
            self.tr("设置字幕字体大小"),
            minimum=16,
            maximum=120,
        )

        self.roundedTextColorCard = ColorSettingCard(
            QColor(255, 255, 255),
            FIF.PALETTE,  # type: ignore
            self.tr("文字颜色"),
            self.tr("设置字幕文字颜色"),
        )

        self.roundedBgColorCard = ColorSettingCard(
            QColor(25, 25, 25, 200),
            FIF.PALETTE,  # type: ignore
            self.tr("背景颜色"),
            self.tr("设置圆角矩形背景颜色"),
            enableAlpha=True,
        )

        self.roundedCornerRadiusCard = SpinBoxSettingCard(
            FIF.ZOOM,  # type: ignore
            self.tr("圆角半径"),
            self.tr("设置背景圆角大小"),
            minimum=0,
            maximum=50,
        )

        self.roundedPaddingHCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("水平内边距"),
            self.tr("文字与背景边缘的水平距离"),
            minimum=4,
            maximum=100,
        )

        self.roundedPaddingVCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("垂直内边距"),
            self.tr("文字与背景边缘的垂直距离"),
            minimum=4,
            maximum=50,
        )

        self.roundedMarginBottomCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("底部边距"),
            self.tr("字幕距视频底部的距离"),
            minimum=20,
            maximum=300,
        )

        self.roundedLineSpacingCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("行间距"),
            self.tr("双语字幕的行间距"),
            minimum=0,
            maximum=50,
        )

        self.roundedLetterSpacingCard = SpinBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("字符间距"),
            self.tr("每个字符之间的额外间距"),
            minimum=0,
            maximum=20,
            step=1,
        )

        # 预览设置
        self.previewTextCard = ComboBoxSettingCard(
            FIF.MESSAGE,  # type: ignore
            self.tr("预览文字"),
            self.tr("设置预览显示的文字内容"),
            texts=list(PERVIEW_TEXTS.keys()),
            parent=self.previewGroup,
        )

        self.orientationCard = ComboBoxSettingCard(
            FIF.LAYOUT,  # type: ignore
            self.tr("预览方向"),
            self.tr("设置预览图片的显示方向"),
            texts=["横屏", "竖屏"],
            parent=self.previewGroup,
        )

        self.previewImageCard = PushSettingCard(
            self.tr("选择图片"),
            FIF.PHOTO,
            self.tr("预览背景"),
            self.tr("选择预览使用的背景图片"),
            parent=self.previewGroup,
        )

    def _initLayout(self):
        """初始化布局"""
        # 通用设置
        self.layoutGroup.addSettingCard(self.renderModeCard)
        self.layoutGroup.addSettingCard(self.layoutCard)
        self.layoutGroup.addSettingCard(self.assVerticalSpacingCard)

        # ASS 样式卡片
        self.assPrimaryGroup.addSettingCard(self.assPrimaryFontCard)
        self.assPrimaryGroup.addSettingCard(self.assPrimarySizeCard)
        self.assPrimaryGroup.addSettingCard(self.assPrimarySpacingCard)
        self.assPrimaryGroup.addSettingCard(self.assPrimaryColorCard)
        self.assPrimaryGroup.addSettingCard(self.assPrimaryOutlineColorCard)
        self.assPrimaryGroup.addSettingCard(self.assPrimaryOutlineSizeCard)

        self.assSecondaryGroup.addSettingCard(self.assSecondaryFontCard)
        self.assSecondaryGroup.addSettingCard(self.assSecondarySizeCard)
        self.assSecondaryGroup.addSettingCard(self.assSecondarySpacingCard)
        self.assSecondaryGroup.addSettingCard(self.assSecondaryColorCard)
        self.assSecondaryGroup.addSettingCard(self.assSecondaryOutlineColorCard)
        self.assSecondaryGroup.addSettingCard(self.assSecondaryOutlineSizeCard)

        # 圆角背景卡片
        self.roundedBgGroup.addSettingCard(self.roundedFontCard)
        self.roundedBgGroup.addSettingCard(self.roundedFontSizeCard)
        self.roundedBgGroup.addSettingCard(self.roundedTextColorCard)
        self.roundedBgGroup.addSettingCard(self.roundedBgColorCard)
        self.roundedBgGroup.addSettingCard(self.roundedCornerRadiusCard)
        self.roundedBgGroup.addSettingCard(self.roundedPaddingHCard)
        self.roundedBgGroup.addSettingCard(self.roundedPaddingVCard)
        self.roundedBgGroup.addSettingCard(self.roundedMarginBottomCard)
        self.roundedBgGroup.addSettingCard(self.roundedLineSpacingCard)
        self.roundedBgGroup.addSettingCard(self.roundedLetterSpacingCard)

        # 预览设置
        self.previewGroup.addSettingCard(self.previewTextCard)
        self.previewGroup.addSettingCard(self.orientationCard)
        self.previewGroup.addSettingCard(self.previewImageCard)

        # 添加组到布局
        self.settingsLayout.addWidget(self.layoutGroup)
        self.settingsLayout.addWidget(self.assPrimaryGroup)
        self.settingsLayout.addWidget(self.assSecondaryGroup)
        self.settingsLayout.addWidget(self.roundedBgGroup)
        self.settingsLayout.addWidget(self.previewGroup)
        self.settingsLayout.addStretch(1)

        # 添加左右两侧到主布局
        self.hBoxLayout.addWidget(self.settingsScrollArea)
        self.hBoxLayout.addWidget(self.previewCard)

    def _initStyle(self):
        """初始化样式"""
        self.settingsWidget.setObjectName("settingsWidget")
        self.setStyleSheet(
            """
            SubtitleStyleInterface, #settingsWidget {
                background-color: transparent;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """
        )

    def __setValues(self):
        """设置初始值"""
        # 设置渲染模式
        self.renderModeCard.comboBox.setCurrentText(
            cfg.subtitle_render_mode.value.value
        )

        # 设置字幕排布
        self.layoutCard.comboBox.setCurrentText(cfg.subtitle_layout.value.value)

        # 设置字幕样式
        self.styleNameComboBox.comboBox.setCurrentText(cfg.get(cfg.subtitle_style_name))

        # 获取字体列表（内置字体 + 系统字体）
        builtin_fonts = get_builtin_fonts()
        builtin_font_names = [f["name"] for f in builtin_fonts]

        fontDatabase = QFontDatabase()
        fontFamilies = fontDatabase.families()

        # 过滤系统字体：
        # 1. 排除私有字体（以 . 开头）
        # 2. 排除已有的内置字体
        # 3. 只保留 PIL 能实际加载的字体（用于圆角背景渲染）
        system_fonts = []
        for font_name in fontFamilies:
            if font_name.startswith(".") or font_name in builtin_font_names:
                continue
            # 测试 PIL 是否能加载此字体
            try:
                ImageFont.truetype(font_name, 12)  # 测试用小尺寸
                system_fonts.append(font_name)
            except (OSError, IOError):
                # PIL 无法加载，跳过此字体
                pass

        # 合并字体列表：内置字体在最前面
        all_fonts = builtin_font_names + sorted(system_fonts)

        # ASS 模式字体
        self.assPrimaryFontCard.addItems(all_fonts)
        self.assSecondaryFontCard.addItems(all_fonts)
        self.assPrimaryFontCard.comboBox.setMaxVisibleItems(12)
        self.assSecondaryFontCard.comboBox.setMaxVisibleItems(12)

        # 圆角背景模式字体
        self.roundedFontCard.addItems(all_fonts)
        self.roundedFontCard.comboBox.setMaxVisibleItems(12)

        # 设置圆角背景模式的初始值
        self.roundedFontSizeCard.spinBox.setValue(cfg.get(cfg.rounded_bg_font_size))
        self.roundedCornerRadiusCard.spinBox.setValue(
            cfg.get(cfg.rounded_bg_corner_radius)
        )
        self.roundedPaddingHCard.spinBox.setValue(cfg.get(cfg.rounded_bg_padding_h))
        self.roundedPaddingVCard.spinBox.setValue(cfg.get(cfg.rounded_bg_padding_v))
        self.roundedMarginBottomCard.spinBox.setValue(
            cfg.get(cfg.rounded_bg_margin_bottom)
        )
        self.roundedLineSpacingCard.spinBox.setValue(
            cfg.get(cfg.rounded_bg_line_spacing)
        )
        self.roundedLetterSpacingCard.spinBox.setValue(
            cfg.get(cfg.rounded_bg_letter_spacing)
        )

        # 设置颜色
        text_color = cfg.get(cfg.rounded_bg_text_color)
        self.roundedTextColorCard.setColor(QColor(text_color))
        bg_color = cfg.get(cfg.rounded_bg_color)
        self.roundedBgColorCard.setColor(self._parseRgbaHex(bg_color))

        # 加载样式列表（根据当前模式）
        self._refreshStyleList()

        # 根据当前渲染模式显示/隐藏设置组
        self._updateVisibleGroups()

    def connectSignals(self):
        """连接所有设置变更的信号到预览更新函数"""
        # 渲染模式切换
        self.renderModeCard.currentTextChanged.connect(self.onRenderModeChanged)

        # 字幕排布（通用设置）
        self.layoutCard.currentTextChanged.connect(self.updatePreview)
        self.layoutCard.currentTextChanged.connect(
            lambda: cfg.set(
                cfg.subtitle_layout,
                SubtitleLayoutEnum(self.layoutCard.comboBox.currentText()),
            )
        )
        # ASS 模式 - 垂直间距
        self.assVerticalSpacingCard.spinBox.valueChanged.connect(
            self.onAssSettingChanged
        )

        # ASS 模式 - 主字幕样式
        self.assPrimaryFontCard.currentTextChanged.connect(self.onAssSettingChanged)
        self.assPrimarySizeCard.spinBox.valueChanged.connect(self.onAssSettingChanged)
        self.assPrimarySpacingCard.spinBox.valueChanged.connect(
            self.onAssSettingChanged
        )
        self.assPrimaryColorCard.colorChanged.connect(self.onAssSettingChanged)
        self.assPrimaryOutlineColorCard.colorChanged.connect(self.onAssSettingChanged)
        self.assPrimaryOutlineSizeCard.spinBox.valueChanged.connect(
            self.onAssSettingChanged
        )

        # ASS 模式 - 副字幕样式
        self.assSecondaryFontCard.currentTextChanged.connect(self.onAssSettingChanged)
        self.assSecondarySizeCard.spinBox.valueChanged.connect(self.onAssSettingChanged)
        self.assSecondarySpacingCard.spinBox.valueChanged.connect(
            self.onAssSettingChanged
        )
        self.assSecondaryColorCard.colorChanged.connect(self.onAssSettingChanged)
        self.assSecondaryOutlineColorCard.colorChanged.connect(self.onAssSettingChanged)
        self.assSecondaryOutlineSizeCard.spinBox.valueChanged.connect(
            self.onAssSettingChanged
        )

        # 圆角背景样式信号
        self.roundedFontCard.currentTextChanged.connect(self.onRoundedBgSettingChanged)
        self.roundedFontSizeCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedTextColorCard.colorChanged.connect(self.onRoundedBgSettingChanged)
        self.roundedBgColorCard.colorChanged.connect(self.onRoundedBgSettingChanged)
        self.roundedCornerRadiusCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedPaddingHCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedPaddingVCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedMarginBottomCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedLineSpacingCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )
        self.roundedLetterSpacingCard.spinBox.valueChanged.connect(
            self.onRoundedBgSettingChanged
        )

        # 预览设置（通用设置）
        self.previewTextCard.currentTextChanged.connect(self.updatePreview)
        self.orientationCard.currentTextChanged.connect(self.onOrientationChanged)
        self.previewImageCard.clicked.connect(self.selectPreviewImage)

        # 连接样式切换信号
        self.styleNameComboBox.currentTextChanged.connect(self.loadStyle)
        self.newStyleButton.clicked.connect(self.createNewStyle)
        self.openStyleFolderButton.clicked.connect(self.on_open_style_folder_clicked)

        # 连接字幕排布信号
        self.layoutCard.comboBox.currentTextChanged.connect(
            signalBus.subtitle_layout_changed
        )
        signalBus.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)

    def on_open_style_folder_clicked(self):
        """打开样式文件夹"""
        open_folder(str(SUBTITLE_STYLE_PATH))

    def on_subtitle_layout_changed(self, layout: str):
        layout_enum = SubtitleLayoutEnum(layout)
        cfg.subtitle_layout.value = layout_enum
        self.layoutCard.setCurrentText(layout)

    def onRenderModeChanged(self):
        """渲染模式切换"""
        mode_text = self.renderModeCard.comboBox.currentText()
        mode = SubtitleRenderModeEnum(mode_text)
        cfg.set(cfg.subtitle_render_mode, mode)
        self._updateVisibleGroups()
        self._refreshStyleList()
        self.updatePreview()

    def onRoundedBgSettingChanged(self):
        """圆角背景设置变更"""
        if self._loading_style:
            return

        # 保存圆角背景配置
        cfg.set(cfg.rounded_bg_font_name, self.roundedFontCard.comboBox.currentText())
        cfg.set(cfg.rounded_bg_font_size, self.roundedFontSizeCard.spinBox.value())
        cfg.set(
            cfg.rounded_bg_corner_radius, self.roundedCornerRadiusCard.spinBox.value()
        )
        cfg.set(cfg.rounded_bg_padding_h, self.roundedPaddingHCard.spinBox.value())
        cfg.set(cfg.rounded_bg_padding_v, self.roundedPaddingVCard.spinBox.value())
        cfg.set(
            cfg.rounded_bg_margin_bottom, self.roundedMarginBottomCard.spinBox.value()
        )
        cfg.set(
            cfg.rounded_bg_line_spacing, self.roundedLineSpacingCard.spinBox.value()
        )
        cfg.set(
            cfg.rounded_bg_letter_spacing, self.roundedLetterSpacingCard.spinBox.value()
        )

        # 保存颜色
        text_color = self.roundedTextColorCard.colorPicker.color.name()
        cfg.set(cfg.rounded_bg_text_color, text_color)
        bg_color = self.roundedBgColorCard.colorPicker.color
        bg_color_hex = f"#{bg_color.red():02x}{bg_color.green():02x}{bg_color.blue():02x}{bg_color.alpha():02x}"
        cfg.set(cfg.rounded_bg_color, bg_color_hex)

        # 自动保存当前样式
        current_style = self.styleNameComboBox.comboBox.currentText()
        if current_style:
            self.saveStyle(current_style)

        self.updatePreview()

    def _updateVisibleGroups(self):
        """根据渲染模式显示/隐藏设置组"""
        mode_text = self.renderModeCard.comboBox.currentText()
        is_ass_mode = mode_text == SubtitleRenderModeEnum.ASS_STYLE.value

        # ASS 样式设置组
        self.assVerticalSpacingCard.setVisible(is_ass_mode)
        self.assPrimaryGroup.setVisible(is_ass_mode)
        self.assSecondaryGroup.setVisible(is_ass_mode)

        # 圆角背景设置组
        self.roundedBgGroup.setVisible(not is_ass_mode)

    def _getStyleFileExtension(self) -> str:
        """获取当前模式的样式文件扩展名"""
        mode = self._getCurrentRenderMode()
        return ".txt" if mode == SubtitleRenderModeEnum.ASS_STYLE else ".json"

    def _refreshStyleList(self):
        """根据当前渲染模式刷新样式列表"""
        ext = self._getStyleFileExtension()
        pattern = f"*{ext}"

        # 清空现有列表
        self.styleNameComboBox.comboBox.clear()

        # 获取样式文件
        style_files = [f.stem for f in SUBTITLE_STYLE_PATH.glob(pattern)]

        # 确保有默认样式
        if "default" not in style_files:
            style_files.insert(0, "default")
            self.saveStyle("default")
        else:
            style_files.insert(0, style_files.pop(style_files.index("default")))

        self.styleNameComboBox.comboBox.addItems(style_files)

        # 加载默认样式或配置中保存的样式
        subtitle_style_name = cfg.get(cfg.subtitle_style_name)
        if subtitle_style_name in style_files:
            self.styleNameComboBox.comboBox.setCurrentText(subtitle_style_name)
            self.loadStyle(subtitle_style_name)
        else:
            self.styleNameComboBox.comboBox.setCurrentText(style_files[0])
            self.loadStyle(style_files[0])

    def _getCurrentRenderMode(self) -> SubtitleRenderModeEnum:
        """获取当前渲染模式"""
        mode_text = self.renderModeCard.comboBox.currentText()
        return SubtitleRenderModeEnum(mode_text)

    def _parseRgbaHex(self, hex_color: str) -> QColor:
        """解析 #RRGGBBAA 格式的颜色"""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 8:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            a = int(hex_color[6:8], 16)
            return QColor(r, g, b, a)
        elif len(hex_color) == 6:
            return QColor(f"#{hex_color}")
        return QColor(25, 25, 25, 200)  # 默认值

    def onOrientationChanged(self):
        """当预览方向改变时调用"""
        orientation = self.orientationCard.comboBox.currentText()
        preview_image = (
            DEFAULT_BG_LANDSCAPE if orientation == "横屏" else DEFAULT_BG_PORTRAIT
        )
        cfg.set(cfg.subtitle_preview_image, str(Path(preview_image["path"])))
        self.updatePreview()

    def onAssSettingChanged(self):
        """ASS 样式设置变更"""
        if self._loading_style:
            return

        self.updatePreview()
        current_style = self.styleNameComboBox.comboBox.currentText()
        if current_style:
            self.saveStyle(current_style)
        else:
            self.saveStyle("default")

    def selectPreviewImage(self):
        """选择预览背景图片"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择背景图片"),
            "",
            self.tr("图片文件") + " (*.png *.jpg *.jpeg)",
        )
        if file_path:
            cfg.set(cfg.subtitle_preview_image, file_path)
            self.updatePreview()

    def generateAssStyles(self) -> str:
        """生成 ASS 样式字符串（固定720P分辨率）"""
        style_format = "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"

        # 垂直间距
        vertical_spacing = self.assVerticalSpacingCard.spinBox.value()

        # 主字幕样式
        primary_font = self.assPrimaryFontCard.comboBox.currentText()
        primary_size = self.assPrimarySizeCard.spinBox.value()

        # 颜色转换为 ASS 格式 (AABBGGRR)
        primary_color_hex = self.assPrimaryColorCard.colorPicker.color.name()
        primary_outline_hex = self.assPrimaryOutlineColorCard.colorPicker.color.name()
        primary_color = f"&H00{primary_color_hex[5:7]}{primary_color_hex[3:5]}{primary_color_hex[1:3]}"
        primary_outline_color = f"&H00{primary_outline_hex[5:7]}{primary_outline_hex[3:5]}{primary_outline_hex[1:3]}"
        primary_spacing = self.assPrimarySpacingCard.spinBox.value()
        primary_outline_size = self.assPrimaryOutlineSizeCard.spinBox.value()

        # 副字幕样式
        secondary_font = self.assSecondaryFontCard.comboBox.currentText()
        secondary_size = self.assSecondarySizeCard.spinBox.value()

        secondary_color_hex = self.assSecondaryColorCard.colorPicker.color.name()
        secondary_outline_hex = (
            self.assSecondaryOutlineColorCard.colorPicker.color.name()
        )
        secondary_color = f"&H00{secondary_color_hex[5:7]}{secondary_color_hex[3:5]}{secondary_color_hex[1:3]}"
        secondary_outline_color = f"&H00{secondary_outline_hex[5:7]}{secondary_outline_hex[3:5]}{secondary_outline_hex[1:3]}"
        secondary_spacing = self.assSecondarySpacingCard.spinBox.value()
        secondary_outline_size = self.assSecondaryOutlineSizeCard.spinBox.value()

        # 生成样式字符串
        primary_style = f"Style: Default,{primary_font},{primary_size},{primary_color},&H000000FF,{primary_outline_color},&H00000000,-1,0,0,0,100,100,{primary_spacing},0,1,{primary_outline_size},0,2,10,10,{vertical_spacing},1,\\q1"
        secondary_style = f"Style: Secondary,{secondary_font},{secondary_size},{secondary_color},&H000000FF,{secondary_outline_color},&H00000000,-1,0,0,0,100,100,{secondary_spacing},0,1,{secondary_outline_size},0,2,10,10,{vertical_spacing},1,\\q1"

        return f"[V4+ Styles]\n{style_format}\n{primary_style}\n{secondary_style}"

    def updatePreview(self):
        """更新预览图片"""
        # 获取预览文本
        main_text, sub_text = PERVIEW_TEXTS[self.previewTextCard.comboBox.currentText()]

        # 字幕布局
        layout = self.layoutCard.comboBox.currentText()
        if layout == "译文在上":
            main_text, sub_text = sub_text, main_text
        elif layout == "原文在上":
            main_text, sub_text = main_text, sub_text
        elif layout == "仅译文":
            main_text, sub_text = sub_text, None
        elif layout == "仅原文":
            main_text, sub_text = main_text, None

        # 获取预览方向和背景
        orientation = self.orientationCard.comboBox.currentText()
        default_preview = (
            DEFAULT_BG_LANDSCAPE if orientation == "横屏" else DEFAULT_BG_PORTRAIT
        )

        # 获取背景图片路径
        user_bg_path = cfg.get(cfg.subtitle_preview_image)
        if user_bg_path and Path(user_bg_path).exists():
            path = user_bg_path
            # 获取原始图片尺寸
            from PIL import Image
            with Image.open(path) as img:
                orig_width, orig_height = img.size
        else:
            path = default_preview["path"]
            orig_width = default_preview["width"]
            orig_height = default_preview["height"]

        # 限制预览尺寸以提高渲染性能（最大高度 480 像素）
        max_preview_height = 480
        if orig_height > max_preview_height:
            scale = max_preview_height / orig_height
            width = int(orig_width * scale)
            height = max_preview_height
        else:
            width = orig_width
            height = orig_height

        # 根据渲染模式创建不同的预览线程
        render_mode = self._getCurrentRenderMode()

        if render_mode == SubtitleRenderModeEnum.ROUNDED_BG:
            # 圆角背景模式（样式720P基准，由渲染层自动缩放）
            bg_color = self.roundedBgColorCard.colorPicker.color
            bg_color_hex = f"#{bg_color.red():02x}{bg_color.green():02x}{bg_color.blue():02x}{bg_color.alpha():02x}"

            style = RoundedBgStyle(
                font_name=self.roundedFontCard.comboBox.currentText(),
                font_size=self.roundedFontSizeCard.spinBox.value(),
                bg_color=bg_color_hex,
                text_color=self.roundedTextColorCard.colorPicker.color.name(),
                corner_radius=self.roundedCornerRadiusCard.spinBox.value(),
                padding_h=self.roundedPaddingHCard.spinBox.value(),
                padding_v=self.roundedPaddingVCard.spinBox.value(),
                margin_bottom=self.roundedMarginBottomCard.spinBox.value(),
                line_spacing=self.roundedLineSpacingCard.spinBox.value(),
                letter_spacing=self.roundedLetterSpacingCard.spinBox.value(),
            )

            self.preview_thread = RoundedBgPreviewThread(
                preview_text=(main_text, sub_text),
                width=width,
                height=height,
                style=style,
                bg_image_path=str(path),
            )
        else:
            # ASS 样式模式（样式720P基准，由渲染层自动缩放）
            style_str = self.generateAssStyles()
            self.preview_thread = AssPreviewThread(
                preview_text=(main_text, sub_text),
                width=width,
                height=height,
                style_str=style_str,
                bg_image_path=str(path),
            )

        self.preview_thread.previewReady.connect(self.onPreviewReady)
        self.preview_thread.start()

    def onPreviewReady(self, preview_path):
        """预览图片生成完成的回调"""
        self.previewImage.setImage(preview_path)
        self.updatePreviewImage()

    def updatePreviewImage(self):
        """更新预览图片"""
        height = int(self.previewTopWidget.height() * 0.98)
        width = int(self.previewTopWidget.width() * 0.98)
        self.previewImage.scaledToWidth(width)
        if self.previewImage.height() > height:
            self.previewImage.scaledToHeight(height)
        self.previewImage.setBorderRadius(8, 8, 8, 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updatePreviewImage()

    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        self.updatePreviewImage()

    def loadStyle(self, style_name):
        """加载指定样式（根据当前渲染模式加载对应格式）"""
        ext = self._getStyleFileExtension()
        style_path = SUBTITLE_STYLE_PATH / f"{style_name}{ext}"

        if not style_path.exists():
            return

        self._loading_style = True

        mode = self._getCurrentRenderMode()
        if mode == SubtitleRenderModeEnum.ROUNDED_BG:
            self._loadRoundedBgStyle(style_path)
        else:
            self._loadAssStyle(style_path)

        cfg.set(cfg.subtitle_style_name, style_name)
        self._loading_style = False
        self.updatePreview()

        InfoBar.success(
            title=self.tr("成功"),
            content=self.tr("已加载样式 ") + style_name,
            orient=Qt.Horizontal,  # type: ignore
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self,
        )

    def _loadAssStyle(self, style_path: Path):
        """加载 ASS 样式 (.txt)"""
        with open(style_path, "r", encoding="utf-8") as f:
            style_content = f.read()

        for line in style_content.split("\n"):
            if line.startswith("Style: Default"):
                parts = line.split(",")
                self.assPrimaryFontCard.setCurrentText(parts[1])
                self.assPrimarySizeCard.spinBox.setValue(int(parts[2]))
                self.assVerticalSpacingCard.spinBox.setValue(int(parts[21]))

                primary_color = parts[3].strip()
                if primary_color.startswith("&H"):
                    color_hex = primary_color[2:]
                    a, b, g, r = (
                        int(color_hex[0:2], 16),
                        int(color_hex[2:4], 16),
                        int(color_hex[4:6], 16),
                        int(color_hex[6:8], 16),
                    )
                    self.assPrimaryColorCard.setColor(QColor(r, g, b, a))

                outline_color = parts[5].strip()
                if outline_color.startswith("&H"):
                    color_hex = outline_color[2:]
                    a, b, g, r = (
                        int(color_hex[0:2], 16),
                        int(color_hex[2:4], 16),
                        int(color_hex[4:6], 16),
                        int(color_hex[6:8], 16),
                    )
                    self.assPrimaryOutlineColorCard.setColor(QColor(r, g, b, a))

                self.assPrimarySpacingCard.spinBox.setValue(float(parts[13]))
                self.assPrimaryOutlineSizeCard.spinBox.setValue(float(parts[16]))

            elif line.startswith("Style: Secondary"):
                parts = line.split(",")

                self.assSecondaryFontCard.setCurrentText(parts[1])
                self.assSecondarySizeCard.spinBox.setValue(int(parts[2]))

                secondary_color = parts[3].strip()
                if secondary_color.startswith("&H"):
                    color_hex = secondary_color[2:]
                    a, b, g, r = (
                        int(color_hex[0:2], 16),
                        int(color_hex[2:4], 16),
                        int(color_hex[4:6], 16),
                        int(color_hex[6:8], 16),
                    )
                    self.assSecondaryColorCard.setColor(QColor(r, g, b, a))

                outline_color = parts[5].strip()
                if outline_color.startswith("&H"):
                    color_hex = outline_color[2:]
                    a, b, g, r = (
                        int(color_hex[0:2], 16),
                        int(color_hex[2:4], 16),
                        int(color_hex[4:6], 16),
                        int(color_hex[6:8], 16),
                    )
                    self.assSecondaryOutlineColorCard.setColor(QColor(r, g, b, a))

                self.assSecondarySpacingCard.spinBox.setValue(float(parts[13]))
                self.assSecondaryOutlineSizeCard.spinBox.setValue(float(parts[16]))

    def _loadRoundedBgStyle(self, style_path: Path):
        """加载圆角背景样式 (.json)"""
        with open(style_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "font_name" in data:
            self.roundedFontCard.setCurrentText(data["font_name"])
        if "font_size" in data:
            self.roundedFontSizeCard.spinBox.setValue(data["font_size"])
        if "text_color" in data:
            self.roundedTextColorCard.setColor(QColor(data["text_color"]))
        if "bg_color" in data:
            self.roundedBgColorCard.setColor(self._parseRgbaHex(data["bg_color"]))
        if "corner_radius" in data:
            self.roundedCornerRadiusCard.spinBox.setValue(data["corner_radius"])
        if "padding_h" in data:
            self.roundedPaddingHCard.spinBox.setValue(data["padding_h"])
        if "padding_v" in data:
            self.roundedPaddingVCard.spinBox.setValue(data["padding_v"])
        if "margin_bottom" in data:
            self.roundedMarginBottomCard.spinBox.setValue(data["margin_bottom"])
        if "line_spacing" in data:
            self.roundedLineSpacingCard.spinBox.setValue(data["line_spacing"])
        if "letter_spacing" in data:
            self.roundedLetterSpacingCard.spinBox.setValue(data["letter_spacing"])

    def createNewStyle(self):
        """创建新样式"""
        dialog = StyleNameDialog(self)
        if dialog.exec():
            style_name = dialog.nameLineEdit.text().strip()
            if not style_name:
                return

            # 检查是否已存在同名样式
            ext = self._getStyleFileExtension()
            if (SUBTITLE_STYLE_PATH / f"{style_name}{ext}").exists():
                InfoBar.warning(
                    title=self.tr("警告"),
                    content=self.tr("样式 ") + style_name + self.tr(" 已存在"),
                    orient=Qt.Horizontal,  # type: ignore
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=INFOBAR_DURATION_WARNING,
                    parent=self,
                )
                return

            # 保存新样式
            self.saveStyle(style_name)

            # 更新样式列表并选中新样式
            self.styleNameComboBox.addItem(style_name)
            self.styleNameComboBox.comboBox.setCurrentText(style_name)

            InfoBar.success(
                title=self.tr("成功"),
                content=self.tr("已创建新样式 ") + style_name,
                orient=Qt.Horizontal,  # type: ignore
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )

    def saveStyle(self, style_name):
        """保存样式（根据当前渲染模式保存对应格式）"""
        SUBTITLE_STYLE_PATH.mkdir(parents=True, exist_ok=True)

        mode = self._getCurrentRenderMode()
        ext = self._getStyleFileExtension()
        style_path = SUBTITLE_STYLE_PATH / f"{style_name}{ext}"

        if mode == SubtitleRenderModeEnum.ROUNDED_BG:
            self._saveRoundedBgStyle(style_path)
        else:
            self._saveAssStyle(style_path)

    def _saveAssStyle(self, style_path: Path):
        """保存 ASS 样式 (.txt)"""
        style_content = self.generateAssStyles()
        with open(style_path, "w", encoding="utf-8") as f:
            f.write(style_content)

    def _saveRoundedBgStyle(self, style_path: Path):
        """保存圆角背景样式 (.json)"""
        bg_color = self.roundedBgColorCard.colorPicker.color
        bg_color_hex = f"#{bg_color.red():02x}{bg_color.green():02x}{bg_color.blue():02x}{bg_color.alpha():02x}"

        data = {
            "font_name": self.roundedFontCard.comboBox.currentText(),
            "font_size": self.roundedFontSizeCard.spinBox.value(),
            "text_color": self.roundedTextColorCard.colorPicker.color.name(),
            "bg_color": bg_color_hex,
            "corner_radius": self.roundedCornerRadiusCard.spinBox.value(),
            "padding_h": self.roundedPaddingHCard.spinBox.value(),
            "padding_v": self.roundedPaddingVCard.spinBox.value(),
            "margin_bottom": self.roundedMarginBottomCard.spinBox.value(),
            "line_spacing": self.roundedLineSpacingCard.spinBox.value(),
            "letter_spacing": self.roundedLetterSpacingCard.spinBox.value(),
        }
        with open(style_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def dragEnterEvent(self, event):
        """拖入事件：检查是否为图片文件"""
        if event.mimeData().hasUrls():
            # 检查是否有图片文件
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith((".png", ".jpg", ".jpeg")):
                    event.accept()
                    return
        event.ignore()

    def dropEvent(self, event):
        """放下事件：将图片设置为预览背景"""
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            # 检查是否为图片文件
            if file_path.lower().endswith((".png", ".jpg", ".jpeg")):
                # 设置为预览背景
                cfg.set(cfg.subtitle_preview_image, file_path)
                # 更新预览
                self.updatePreview()
                # 显示成功提示
                InfoBar.success(
                    title=self.tr("成功"),
                    content=self.tr("已设置预览背景：") + Path(file_path).name,
                    orient=Qt.Horizontal,  # type: ignore
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=INFOBAR_DURATION_SUCCESS,
                    parent=self,
                )
                break  # 只处理第一个图片文件


class StyleNameDialog(MessageBoxBase):
    """样式名称输入对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("新建样式"), self)
        self.nameLineEdit = LineEdit(self)

        self.nameLineEdit.setPlaceholderText(self.tr("输入样式名称"))
        self.nameLineEdit.setClearButtonEnabled(True)

        # 添加控件到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.nameLineEdit)

        # 设置按钮文本
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.widget.setMinimumWidth(350)
        self.yesButton.setDisabled(True)
        self.nameLineEdit.textChanged.connect(self._validateInput)

    def _validateInput(self, text):
        self.yesButton.setEnabled(bool(text.strip()))
