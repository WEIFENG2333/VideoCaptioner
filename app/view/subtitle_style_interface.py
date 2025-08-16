from pathlib import Path
from typing import Optional, Tuple

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
from app.core.utils.platform_utils import open_folder
from app.core.utils.subtitle_preview import generate_preview

PERVIEW_TEXTS = {
    "长文本": (
        "This is a long text used for testing subtitle preview and style settings.",
        "这是一段用于测试字幕预览和样式设置的长文本内容",
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


class PreviewThread(QThread):
    previewReady = pyqtSignal(str)

    def __init__(
        self,
        style_str: str,
        preview_text: Tuple[str, Optional[str]],
        bg_path: str,
        width: int,
        height: int,
    ):
        """
        Args:
            style_str: ASS 样式字符串
            preview_text: 预览文本元组 (主字幕, 副字幕), 副字幕可选
        """
        super().__init__()
        self.style_str = style_str
        self.preview_text = preview_text
        self.bg_path = bg_path
        self.width = width
        self.height = height

    def run(self):
        preview_path = generate_preview(
            style_str=self.style_str,
            preview_text=self.preview_text,
            bg_path=self.bg_path,
            width=self.width,
            height=self.height,
        )
        self.previewReady.emit(preview_path)


class SubtitleStyleInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SubtitleStyleInterface")
        self.setWindowTitle(self.tr("字幕样式配置"))

        # 创建主布局
        self.hBoxLayout = QHBoxLayout(self)

        # 初始化界面组件
        self._initSettingsArea()
        self._initPreviewArea()
        self._initSettingCards()
        self._initLayout()
        self._initStyle()

        # 添加一个标志位来控制是否触发onSettingChanged
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

        # 创建设置组
        self.layoutGroup = SettingCardGroup(self.tr("字幕排布"), self.settingsWidget)
        self.mainGroup = SettingCardGroup(self.tr("主字幕样式"), self.settingsWidget)
        self.subGroup = SettingCardGroup(self.tr("副字幕样式"), self.settingsWidget)
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
        # 字幕排布设置
        self.layoutCard = ComboBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("字幕排布"),
            self.tr("设置主字幕和副字幕的显示方式"),
            texts=["译文在上", "原文在上", "仅译文", "仅原文"],
        )

        # 垂直间距
        self.verticalSpacingCard = SpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("垂直间距"),
            self.tr("设置字幕的垂直间距"),
            minimum=8,
            maximum=10000,
        )

        # 主字幕样式设置
        self.mainFontCard = ComboBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("主字幕字体"),
            self.tr("设置主字幕的字体"),
            texts=["Arial"],
        )

        self.mainSizeCard = SpinBoxSettingCard(
            FIF.FONT_SIZE,  # type: ignore
            self.tr("主字幕字号"),
            self.tr("设置主字幕的大小"),
            minimum=8,
            maximum=1000,
        )

        self.mainSpacingCard = DoubleSpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("主字幕间距"),
            self.tr("设置主字幕的字符间距"),
            minimum=0.0,
            maximum=10.0,
            decimals=1,
        )

        self.mainColorCard = ColorSettingCard(
            QColor(255, 255, 255),
            FIF.PALETTE,  # type: ignore
            self.tr("主字幕颜色"),
            self.tr("设置主字幕的颜色"),
        )

        self.mainOutlineColorCard = ColorSettingCard(
            QColor(0, 0, 0),
            FIF.PALETTE,  # type: ignore
            self.tr("主字幕边框颜色"),
            self.tr("设置主字幕的边框颜色"),
        )

        self.mainOutlineSizeCard = DoubleSpinBoxSettingCard(
            FIF.ZOOM,  # type: ignore
            self.tr("主字幕边框大小"),
            self.tr("设置主字幕的边框粗细"),
            minimum=0.0,
            maximum=10.0,
            decimals=1,
        )

        # 副字幕样式设置
        self.subFontCard = ComboBoxSettingCard(
            FIF.FONT,  # type: ignore
            self.tr("副字幕字体"),
            self.tr("设置副字幕的字体"),
            texts=["Arial"],
        )

        self.subSizeCard = SpinBoxSettingCard(
            FIF.FONT_SIZE,  # type: ignore
            self.tr("副字幕字号"),
            self.tr("设置副字幕的大小"),
            minimum=8,
            maximum=1000,
        )

        self.subSpacingCard = DoubleSpinBoxSettingCard(
            FIF.ALIGNMENT,  # type: ignore
            self.tr("副字幕间距"),
            self.tr("设置副字幕的字符间距"),
            minimum=0.0,
            maximum=50.0,
            decimals=1,
        )

        self.subColorCard = ColorSettingCard(
            QColor(255, 255, 255),
            FIF.PALETTE,  # type: ignore
            self.tr("副字幕颜色"),
            self.tr("设置副字幕的颜色"),
        )

        self.subOutlineColorCard = ColorSettingCard(
            QColor(0, 0, 0),
            FIF.PALETTE,  # type: ignore
            self.tr("副字幕边框颜色"),
            self.tr("设置副字幕的边框颜色"),
        )

        self.subOutlineSizeCard = DoubleSpinBoxSettingCard(
            FIF.ZOOM,  # type: ignore
            self.tr("副字幕边框大小"),
            self.tr("设置副字幕的边框粗细"),
            minimum=0.0,
            maximum=50.0,
            decimals=1,
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
        # 添加卡片到组
        self.layoutGroup.addSettingCard(self.layoutCard)
        self.layoutGroup.addSettingCard(self.verticalSpacingCard)
        self.mainGroup.addSettingCard(self.mainFontCard)
        self.mainGroup.addSettingCard(self.mainSizeCard)
        self.mainGroup.addSettingCard(self.mainSpacingCard)
        self.mainGroup.addSettingCard(self.mainColorCard)
        self.mainGroup.addSettingCard(self.mainOutlineColorCard)
        self.mainGroup.addSettingCard(self.mainOutlineSizeCard)

        self.subGroup.addSettingCard(self.subFontCard)
        self.subGroup.addSettingCard(self.subSizeCard)
        self.subGroup.addSettingCard(self.subSpacingCard)
        self.subGroup.addSettingCard(self.subColorCard)
        self.subGroup.addSettingCard(self.subOutlineColorCard)
        self.subGroup.addSettingCard(self.subOutlineSizeCard)

        self.previewGroup.addSettingCard(self.previewTextCard)
        self.previewGroup.addSettingCard(self.orientationCard)
        self.previewGroup.addSettingCard(self.previewImageCard)

        # 添加组到布局
        self.settingsLayout.addWidget(self.layoutGroup)
        self.settingsLayout.addWidget(self.mainGroup)
        self.settingsLayout.addWidget(self.subGroup)
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
        # 设置字幕排布
        self.layoutCard.comboBox.setCurrentText(cfg.get(cfg.subtitle_layout))
        # 设置字幕样式
        self.styleNameComboBox.comboBox.setCurrentText(cfg.get(cfg.subtitle_style_name))

        # 获取系统字体,设置comboBox的选项
        fontDatabase = QFontDatabase()
        fontFamilies = fontDatabase.families()
        self.mainFontCard.addItems(fontFamilies)
        self.subFontCard.addItems(fontFamilies)

        # 设置字体选项框最大显示数量
        self.mainFontCard.comboBox.setMaxVisibleItems(12)
        self.subFontCard.comboBox.setMaxVisibleItems(12)

        # 获取样式目录下的所有txt文件名
        style_files = [f.stem for f in SUBTITLE_STYLE_PATH.glob("*.txt")]
        if "default" in style_files:
            style_files.insert(0, style_files.pop(style_files.index("default")))
        else:
            style_files.insert(0, "default")
            self.saveStyle("default")
        self.styleNameComboBox.comboBox.addItems(style_files)

        # 加载默认样式
        subtitle_style_name = cfg.get(cfg.subtitle_style_name)
        if subtitle_style_name in style_files:
            self.loadStyle(subtitle_style_name)
            self.styleNameComboBox.comboBox.setCurrentText(subtitle_style_name)
        else:
            self.loadStyle(style_files[0])
            self.styleNameComboBox.comboBox.setCurrentText(style_files[0])

    def connectSignals(self):
        """连接所有设置变更的信号到预览更新函数"""
        # 字幕排布
        self.layoutCard.currentTextChanged.connect(self.onSettingChanged)
        self.layoutCard.currentTextChanged.connect(
            lambda: cfg.set(cfg.subtitle_layout, self.layoutCard.comboBox.currentText())
        )
        # 垂直间距
        self.verticalSpacingCard.spinBox.valueChanged.connect(self.onSettingChanged)

        # 主字幕样式
        self.mainFontCard.currentTextChanged.connect(self.onSettingChanged)
        self.mainSizeCard.spinBox.valueChanged.connect(self.onSettingChanged)
        self.mainSpacingCard.spinBox.valueChanged.connect(self.onSettingChanged)
        self.mainColorCard.colorChanged.connect(self.onSettingChanged)
        self.mainOutlineColorCard.colorChanged.connect(self.onSettingChanged)
        self.mainOutlineSizeCard.spinBox.valueChanged.connect(self.onSettingChanged)

        # 副字幕样式
        self.subFontCard.currentTextChanged.connect(self.onSettingChanged)
        self.subSizeCard.spinBox.valueChanged.connect(self.onSettingChanged)
        self.subSpacingCard.spinBox.valueChanged.connect(self.onSettingChanged)
        self.subColorCard.colorChanged.connect(self.onSettingChanged)
        self.subOutlineColorCard.colorChanged.connect(self.onSettingChanged)
        self.subOutlineSizeCard.spinBox.valueChanged.connect(self.onSettingChanged)

        # 预览设置
        self.previewTextCard.currentTextChanged.connect(self.onSettingChanged)
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
        cfg.subtitle_layout.value = layout
        self.layoutCard.setCurrentText(layout)

    def onOrientationChanged(self):
        """当预览方向改变时调用"""
        orientation = self.orientationCard.comboBox.currentText()
        preview_image = (
            DEFAULT_BG_LANDSCAPE if orientation == "横屏" else DEFAULT_BG_PORTRAIT
        )
        cfg.set(cfg.subtitle_preview_image, str(Path(preview_image["path"])))
        self.updatePreview()

    def onSettingChanged(self):
        """当任何设置改变时调用"""
        # 如果正在加载样式，不触发更新
        if self._loading_style:
            return

        self.updatePreview()
        # 获取当前选择的样式名称
        current_style = self.styleNameComboBox.comboBox.currentText()
        if current_style:
            self.saveStyle(current_style)  # 自动保存为当前选择的样式
        else:
            self.saveStyle("default")  # 如果没有选择样式,保存为默认样式

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
        """生成 ASS 样式字符串"""
        style_format = "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"

        # 从控件获取当前设置
        # 获取垂直间距
        vertical_spacing = int(
            self.verticalSpacingCard.spinBox.value()
        )  # 转换为ASS单位

        # 提取主字幕样式元素
        main_font = self.mainFontCard.comboBox.currentText()
        main_size = self.mainSizeCard.spinBox.value()

        # 获取颜色值并转换为 ASS 格式 (AABBGGRR)
        main_color_hex = self.mainColorCard.colorPicker.color.name()
        main_outline_hex = self.mainOutlineColorCard.colorPicker.color.name()
        main_color = (
            f"&H00{main_color_hex[5:7]}{main_color_hex[3:5]}{main_color_hex[1:3]}"
        )
        main_outline_color = (
            f"&H00{main_outline_hex[5:7]}{main_outline_hex[3:5]}{main_outline_hex[1:3]}"
        )
        main_spacing = self.mainSpacingCard.spinBox.value()
        main_outline_size = self.mainOutlineSizeCard.spinBox.value()

        # 提取副字幕样式元素
        sub_font = self.subFontCard.comboBox.currentText()
        sub_size = self.subSizeCard.spinBox.value()

        # 获取颜色值并转换为 ASS 格式 (AABBGGRR)
        sub_color_hex = self.subColorCard.colorPicker.color.name()
        sub_outline_hex = self.subOutlineColorCard.colorPicker.color.name()
        sub_color = f"&H00{sub_color_hex[5:7]}{sub_color_hex[3:5]}{sub_color_hex[1:3]}"
        sub_outline_color = (
            f"&H00{sub_outline_hex[5:7]}{sub_outline_hex[3:5]}{sub_outline_hex[1:3]}"
        )
        sub_spacing = self.subSpacingCard.spinBox.value()
        sub_outline_size = self.subOutlineSizeCard.spinBox.value()

        # 生成样式字符串
        main_style = f"Style: Default,{main_font},{main_size},{main_color},&H000000FF,{main_outline_color},&H00000000,-1,0,0,0,100,100,{main_spacing},0,1,{main_outline_size},0,2,10,10,{vertical_spacing},1,\\q1"
        sub_style = f"Style: Secondary,{sub_font},{sub_size},{sub_color},&H000000FF,{sub_outline_color},&H00000000,-1,0,0,0,100,100,{sub_spacing},0,1,{sub_outline_size},0,2,10,10,{vertical_spacing},1,\\q1"

        return f"[V4+ Styles]\n{style_format}\n{main_style}\n{sub_style}"

    def updatePreview(self):
        """更新预览图片"""
        # 生成 ASS 样式字符串
        style_str = self.generateAssStyles()

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

        # 获取预览方向
        orientation = self.orientationCard.comboBox.currentText()
        default_preview = (
            DEFAULT_BG_LANDSCAPE if orientation == "横屏" else DEFAULT_BG_PORTRAIT
        )

        # 检查是否存在用户自定义背景图片
        user_bg_path = cfg.get(cfg.subtitle_preview_image)
        if user_bg_path and Path(user_bg_path).exists():
            path = user_bg_path
            # 可以保持默认宽高或获取实际图片宽高
            width = default_preview["width"]
            height = default_preview["height"]
        else:
            path = default_preview["path"]
            width = default_preview["width"]
            height = default_preview["height"]

        # 创建预览线程
        self.preview_thread = PreviewThread(
            style_str=style_str,
            preview_text=(main_text, sub_text),
            bg_path=path,
            width=width,
            height=height,
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
        """加载指定样式"""
        style_path = SUBTITLE_STYLE_PATH / f"{style_name}.txt"

        if not style_path.exists():
            return

        # 设置标志位，防止触发onSettingChanged
        self._loading_style = True

        with open(style_path, "r", encoding="utf-8") as f:
            style_content = f.read()

        # 解析样式内容
        for line in style_content.split("\n"):
            if line.startswith("Style: Default"):
                # 解析主字幕样式
                parts = line.split(",")
                self.mainFontCard.setCurrentText(parts[1])
                self.mainSizeCard.spinBox.setValue(int(parts[2]))

                vertical_spacing = int(parts[21])
                self.verticalSpacingCard.spinBox.setValue(vertical_spacing)

                # 将 &HAARRGGBB 格式转换为 QColor
                primary_color = parts[3].strip()
                if primary_color.startswith("&H"):
                    # 移除 &H 前缀,转换为 RGB
                    color_hex = primary_color[2:]
                    alpha = int(color_hex[0:2], 16)
                    blue = int(color_hex[2:4], 16)
                    green = int(color_hex[4:6], 16)
                    red = int(color_hex[6:8], 16)
                    self.mainColorCard.setColor(QColor(red, green, blue, alpha))

                outline_color = parts[5].strip()
                if outline_color.startswith("&H"):
                    color_hex = outline_color[2:]
                    alpha = int(color_hex[0:2], 16)
                    blue = int(color_hex[2:4], 16)
                    green = int(color_hex[4:6], 16)
                    red = int(color_hex[6:8], 16)
                    self.mainOutlineColorCard.setColor(QColor(red, green, blue, alpha))

                self.mainSpacingCard.spinBox.setValue(float(parts[13]))
                self.mainOutlineSizeCard.spinBox.setValue(float(parts[16]))
            elif line.startswith("Style: Secondary"):
                # 解析副字幕样式
                parts = line.split(",")
                self.subFontCard.setCurrentText(parts[1])
                self.subSizeCard.spinBox.setValue(int(parts[2]))
                # 将 &HAARRGGBB 格式转换为 QColor
                primary_color = parts[3].strip()
                if primary_color.startswith("&H"):
                    color_hex = primary_color[2:]
                    alpha = int(color_hex[0:2], 16)
                    blue = int(color_hex[2:4], 16)
                    green = int(color_hex[4:6], 16)
                    red = int(color_hex[6:8], 16)
                    self.subColorCard.setColor(QColor(red, green, blue, alpha))

                outline_color = parts[5].strip()
                if outline_color.startswith("&H"):
                    color_hex = outline_color[2:]
                    alpha = int(color_hex[0:2], 16)
                    blue = int(color_hex[2:4], 16)
                    green = int(color_hex[4:6], 16)
                    red = int(color_hex[6:8], 16)
                    self.subOutlineColorCard.setColor(QColor(red, green, blue, alpha))

                self.subSpacingCard.spinBox.setValue(float(parts[13]))
                self.subOutlineSizeCard.spinBox.setValue(float(parts[16]))

        cfg.set(cfg.subtitle_style_name, style_name)

        # 重置标志位
        self._loading_style = False

        # 手动更新一次预览
        self.updatePreview()

        # 显示加载成功提示
        InfoBar.success(
            title=self.tr("成功"),
            content=self.tr("已加载样式 ") + style_name,
            orient=Qt.Horizontal,  # type: ignore
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1500,
            parent=self,
        )

    def createNewStyle(self):
        """创建新样式"""
        dialog = StyleNameDialog(self)
        if dialog.exec():
            style_name = dialog.nameLineEdit.text().strip()
            if not style_name:
                return

            # 检查是否已存在同名样式
            if (SUBTITLE_STYLE_PATH / f"{style_name}.txt").exists():
                InfoBar.warning(
                    title=self.tr("警告"),
                    content=self.tr("样式 ") + style_name + self.tr(" 已存在"),
                    orient=Qt.Horizontal,  # type: ignore
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self,
                )
                return

            # 保存新样式
            self.saveStyle(style_name)

            # 更新样式列表并选中新样式
            self.styleNameComboBox.addItem(style_name)
            self.styleNameComboBox.comboBox.setCurrentText(style_name)

            # 显示创建成功提示
            InfoBar.success(
                title=self.tr("成功"),
                content=self.tr("已创建新样式 ") + style_name,
                orient=Qt.Horizontal,  # type: ignore
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )

    def saveStyle(self, style_name):
        """保存样式
        Args:
            style_name (str): 样式名称
        """
        # 确保样式目录存在
        SUBTITLE_STYLE_PATH.mkdir(parents=True, exist_ok=True)

        # 生成样式内容并保存
        style_content = self.generateAssStyles()
        style_path = SUBTITLE_STYLE_PATH / f"{style_name}.txt"

        with open(style_path, "w", encoding="utf-8") as f:
            f.write(style_content)


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
