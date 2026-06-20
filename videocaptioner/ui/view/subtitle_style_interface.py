# coding:utf-8
"""字幕样式页（三栏工作台）。

左「样式库」(渲染模式分页 + 样式卡)、中「预览」(实时渲染当前样式)、
右「参数」(分组参数行)。编辑即自动保存到当前用户样式（编辑内置样式时自动
fork 成用户样式），与合成页共用 subtitle_style_name。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontDatabase
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ImageLabel, InfoBar, InfoBarPosition, ScrollArea

from videocaptioner.config import ASSETS_PATH, USER_SUBTITLE_STYLE_PATH
from videocaptioner.core.constant import INFOBAR_DURATION_SUCCESS, INFOBAR_DURATION_WARNING
from videocaptioner.core.entities import SubtitleLayoutEnum, SubtitleRenderModeEnum
from videocaptioner.core.subtitle import get_builtin_fonts, render_ass_preview, render_preview
from videocaptioner.core.subtitle.style_manager import (
    AssSecondaryStyle,
    AssSubtitleStyle,
    RoundedSubtitleStyle,
    StyleSource,
    SubtitleRenderer,
    SubtitleStylePreset,
    delete_user_style,
    list_styles,
    load_style,
    normalize_style_id,
    save_user_style,
)
from videocaptioner.core.subtitle.styles import RoundedBgStyle
from videocaptioner.core.utils.platform_utils import open_folder
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.app_dialog import AppDialog, ConfirmDialog
from videocaptioner.ui.components.inspector_controls import (
    ColorValueControl,
    InspectorGroup,
    InspectorRow,
    StyleCard,
)
from videocaptioner.ui.components.workbench import (
    AppLineEdit,
    CompactButton,
    FilterTabs,
    PillSelect,
    SectionLabel,
    StatusPill,
    StepperControl,
    ToggleSwitch,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    draw_rounded_surface,
)

# 预览示例文本（原文, 译文）的兜底：用户清空自定义时回落到配置里的默认值，
# 直接取 SettingField 默认，避免再硬编码一份导致与 config 漂移。
PREVIEW_TEXT = (
    cfg.subtitle_preview_source.defaultValue,
    cfg.subtitle_preview_target.defaultValue,
)

DEFAULT_BG_LANDSCAPE = ASSETS_PATH / "default_bg_landscape.png"
DEFAULT_BG_PORTRAIT = ASSETS_PATH / "default_bg_portrait.png"

_FONT_CHOICES: Optional[list[str]] = None


def _font_choices() -> list[str]:
    """字体下拉的候选：内置字体在前（已随程序打包，渲染最稳），其后接系统已装字体。

    系统字体枚举略有开销且程序运行期不变，缓存一次即可。
    """
    global _FONT_CHOICES
    if _FONT_CHOICES is not None:
        return _FONT_CHOICES
    names: list[str] = []
    seen: set[str] = set()
    for item in get_builtin_fonts():
        name = item["name"]
        if name not in seen:
            names.append(name)
            seen.add(name)
    for family in QFontDatabase().families():
        if family not in seen:
            names.append(family)
            seen.add(family)
    _FONT_CHOICES = names
    return names


# 对齐取值与显示文案（存 left/center/right，展示居左/居中/居右）。
_ALIGN_ITEMS = (("left", "居左"), ("center", "居中"), ("right", "居右"))

# 样式卡固定宽度（坞横向滚动按此累加内容宽度）。容纳一行「复制/重命名/删除」图标按钮。
_CARD_WIDTH = 260


def _rgba_hex_to_qcolor(hex_color: str) -> QColor:
    raw = hex_color.lstrip("#")
    if len(raw) == 8:
        return QColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), int(raw[6:8], 16))
    if len(raw) == 6:
        return QColor(f"#{raw}")
    return QColor(25, 25, 25, 200)


def _qcolor_to_rgba_hex(color: QColor) -> str:
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}{color.alpha():02x}"


# ---------------------------------------------------------------------------
# 预览线程：渲染异常不得 qFatal（裸抛会 abort 进程），失败打日志不 emit。
# ---------------------------------------------------------------------------


class AssPreviewThread(QThread):
    previewReady = pyqtSignal(str)

    def __init__(self, preview_text: Tuple[str, Optional[str]], style_str: str, bg_image_path: str, line_gap: int = 0):
        super().__init__()
        self.preview_text = preview_text
        self.style_str = style_str
        self.bg_image_path = bg_image_path
        self.line_gap = line_gap

    def run(self):
        try:
            path = render_ass_preview(
                style_str=self.style_str,
                preview_text=self.preview_text,
                line_gap=self.line_gap,
                bg_image_path=self.bg_image_path,
            )
        except Exception:
            import traceback

            traceback.print_exc()
            return
        self.previewReady.emit(path)


class RoundedBgPreviewThread(QThread):
    previewReady = pyqtSignal(str)

    def __init__(self, preview_text: Tuple[str, Optional[str]], style: RoundedBgStyle, bg_image_path: str):
        super().__init__()
        self.preview_text = preview_text
        self.style = style
        self.bg_image_path = bg_image_path

    def run(self):
        try:
            path = render_preview(
                primary_text=self.preview_text[0],
                secondary_text=self.preview_text[1] or "",
                style=self.style,
                bg_image_path=self.bg_image_path,
            )
        except Exception:
            import traceback

            traceback.print_exc()
            return
        self.previewReady.emit(path)


class _Stage(QFrame):
    """预览舞台容器：自绘圆角底，居中放预览图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("styleStage")
        self.setStyleSheet("QFrame#styleStage { background: transparent; border: none; }")

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.field, palette.line_soft, 14)
        super().paintEvent(event)


class SubtitleStyleInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SubtitleStyleInterface")
        self.setWindowTitle(self.tr("字幕样式配置"))
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self._loading = False  # 程序化更新控件时抑制自动保存
        self._mode_key = self._renderer_key()  # 当前渲染模式的唯一真源（不依赖控件状态）
        # 每个渲染模式各记住最近选中的样式 id：切到另一模式再切回时据此还原。
        # subtitle_style_name 只存一份，否则切模式往返会把本模式的选择丢回内置默认，
        # 下一次编辑又把内置 fork 成新样式，导致样式越积越多。
        self._mode_style: dict[str, str] = {
            self._mode_key: normalize_style_id(
                cfg.subtitle_style_name.value, self._mode_key
            )
        }
        self._orientation = "横屏"
        self._preview_threads: list[QThread] = []
        self._preview_generation = 0
        self._cards: list[StyleCard] = []
        # 预览防抖（前沿触发）：空闲后第一次调用立即渲染（首屏/切换不闪空），
        # 紧接着的连拍（连点步进器等）合并到末尾再渲一次，避免 ASS(ffmpeg) 渲染堆积。
        self._last_preview_ts = 0.0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._render_preview_now)
        # 渲染模式专属控件引用（重建参数面板时刷新）
        self._ass: dict = {}
        self._rounded: dict = {}

        self._build_ui()
        self._on_mode_changed(self._renderer_key(), initial=True)

    # ---------------------------------------------------------------- 构建

    def _build_ui(self):
        # 上下左右两栏布局：左上预览（占主空间）、左下样式坞、右侧参数（通栏）。
        # 让预览尽量大，样式库收到底部横向陈列。
        root = QGridLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setHorizontalSpacing(18)
        root.setVerticalSpacing(18)
        preview = self._build_preview()
        inspector = self._build_inspector()
        dock = self._build_dock()
        root.addWidget(preview, 0, 0)
        root.addWidget(inspector, 0, 1, 2, 1)
        root.addWidget(dock, 1, 0)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 0)
        root.setRowStretch(0, 1)
        root.setRowStretch(1, 0)
        self._apply_page_style()

    def _build_dock(self) -> QWidget:
        """底部样式坞：单行横向陈列所有样式卡，点选即高亮（卡片定高，不重排不闪动）。

        坞高 = 头部(58) + 分隔线(1) + 轨道视口(卡片 126 + 上下内边距 24 = 150) = 209，
        刚好容纳一行卡片：横向滚动条是叠加层不占高度，视口与卡片等高则既不截断也不留空白。
        """
        panel = WorkbenchPanel(padded=False)
        panel.setFixedHeight(209)
        layout = panel.bodyLayout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(14, 10, 14, 10)
        head.setSpacing(12)
        is_rounded = self._renderer_key() == "rounded"
        self.modeTabs = FilterTabs(
            [("ass", self.tr("ASS 描边")), ("rounded", self.tr("圆角背景"))]
        )
        self.modeTabs.setCurrent("rounded" if is_rounded else "ass")
        self.modeTabs.changed.connect(self._on_mode_changed)
        head.addWidget(self.modeTabs)
        head.addStretch(1)
        self.countChip = StatusPill("", "neutral")
        head.addWidget(self.countChip)
        self.newButton = WorkbenchButton(self.tr("新建"), AppIcon.ADD, primary=True, height=34)
        self.newButton.clicked.connect(self._on_new_style)
        self.folderButton = WorkbenchButton(self.tr("目录"), AppIcon.FOLDER, height=34)
        self.folderButton.clicked.connect(lambda: open_folder(str(USER_SUBTITLE_STYLE_PATH)))
        head.addWidget(self.newButton)
        head.addWidget(self.folderButton)
        layout.addLayout(head)
        layout.addWidget(self._hline())

        # 单行横向滚动陈列所有样式
        self.trackScroll = ScrollArea()
        self.trackScroll.setWidgetResizable(True)
        self.trackScroll.enableTransparentBackground()
        self.trackScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self.trackBody = QWidget()
        self.trackBody.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.trackBody.setStyleSheet("background: transparent;")
        self.trackLayout = QHBoxLayout(self.trackBody)
        self.trackLayout.setContentsMargins(14, 12, 14, 12)
        self.trackLayout.setSpacing(12)
        self.trackLayout.addStretch(1)
        self.trackScroll.setWidget(self.trackBody)
        layout.addWidget(self.trackScroll, 1)
        return panel

    def _build_preview(self) -> QWidget:
        panel = WorkbenchPanel(padded=False)
        panel.setMinimumWidth(380)
        layout = panel.bodyLayout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 头部与「参数」栏同款（16/14/16/13 内边距、17/880 标题），标题随 HBox 垂直居中，
        # 与右侧 32 高按钮对齐——不再借用 PanelHeader（其自带 18px 底边距会顶高标题）。
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 14, 16, 13)
        toolbar.setSpacing(10)
        self.previewTitle = SectionLabel(self.tr("预览"))
        apply_font(self.previewTitle, 17, 880)
        toolbar.addWidget(self.previewTitle)
        toolbar.addStretch(1)
        self.textButton = CompactButton(self.tr("预览文字"), AppIcon.FONT)
        self.textButton.clicked.connect(self._edit_preview_text)
        self.orientationButton = CompactButton(self.tr("横屏预览"), AppIcon.LAYOUT)
        self.orientationButton.clicked.connect(self._toggle_orientation)
        self.bgButton = CompactButton(self.tr("更换背景"), AppIcon.PHOTO)
        self.bgButton.clicked.connect(self._pick_background)
        for btn in (self.textButton, self.orientationButton, self.bgButton):
            toolbar.addWidget(btn)
        layout.addLayout(toolbar)
        layout.addWidget(self._hline())

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 12)
        body.setSpacing(0)
        self.stage = _Stage()
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(10, 10, 10, 10)  # 细边框留薄边，预览图尽量铺满舞台
        self.previewImage = ImageLabel(self.stage)
        self.previewImage.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        stage_layout.addWidget(self.previewImage, 0, Qt.AlignCenter)  # type: ignore[arg-type]
        body.addWidget(self.stage, 1)
        layout.addLayout(body)
        return panel

    def _build_inspector(self) -> QWidget:
        panel = WorkbenchPanel(padded=False)
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(398)
        layout = panel.bodyLayout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 自定义头：与「样式库」头同款 16px 内边距，让"参数"标题与下面的分组左对齐。
        head = QHBoxLayout()
        head.setContentsMargins(16, 14, 16, 13)
        title = SectionLabel(self.tr("参数"))
        apply_font(title, 17, 880)
        head.addWidget(title)
        head.addStretch(1)
        self.autoSavePill = StatusPill(self.tr("自动保存"), "ok")
        head.addWidget(self.autoSavePill)
        layout.addLayout(head)
        layout.addWidget(self._hline())

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
        self.inspectorBody = QWidget()
        self.inspectorBody.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.inspectorBody.setStyleSheet("background: transparent;")
        self.inspectorLayout = QVBoxLayout(self.inspectorBody)
        self.inspectorLayout.setContentsMargins(16, 16, 16, 16)
        self.inspectorLayout.setSpacing(18)
        self.inspectorLayout.addStretch(1)
        scroll.setWidget(self.inspectorBody)
        layout.addWidget(scroll, 1)
        return panel

    def _hline(self) -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        palette = app_palette()
        line.setStyleSheet(f"background: {palette.line_soft}; border: none;")
        return line

    # ---------------------------------------------------------------- 渲染模式

    def _renderer_key(self) -> str:
        mode = cfg.subtitle_render_mode.value
        return "rounded" if mode == SubtitleRenderModeEnum.ROUNDED_BG else "ass"

    def _on_mode_changed(self, key: str, initial: bool = False):
        mode = (
            SubtitleRenderModeEnum.ROUNDED_BG
            if key == "rounded"
            else SubtitleRenderModeEnum.ASS_STYLE
        )
        if not initial:
            cfg.set(cfg.subtitle_render_mode, mode)
        self._rebuild_inspector(key)
        self._refresh_style_list()

    # ---------------------------------------------------------------- 参数面板

    def _clear_inspector(self):
        while self.inspectorLayout.count() > 1:  # 保留末尾 stretch
            item = self.inspectorLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先脱离父级立即从显示移除：deleteLater 是异步的，
                # 否则重建时旧控件未销毁会与新控件叠成重影。
                widget.setParent(None)
                widget.deleteLater()

    def _stepper(self, value, minimum, maximum, step=1, decimals=0, suffix=""):
        ctl = StepperControl(value, minimum, maximum, step, decimals, suffix, width=124)
        ctl.valueChanged.connect(self._on_edit)
        return ctl

    def _font_select(self) -> PillSelect:
        """字体下拉：与「双语顺序」同款胶囊（设计语言一致），内置 + 系统字体，

        候选很多时菜单自动限高滚动。先填充再接信号，避免初始填充误触自动保存。"""
        pill = PillSelect()
        pill.setItems(_font_choices())
        pill.currentTextChanged.connect(lambda _t: self._on_edit())
        return pill

    @staticmethod
    def _set_font(pill: PillSelect, name: str):
        """选中字体；若样式里的字体不在候选中（如来自他机），临时补进列表再选中。"""
        if name and name not in pill.items():
            pill.setItems(pill.items() + [name], current=name)
        else:
            pill.setCurrentText(name)

    def _toggle(self, checked: bool) -> ToggleSwitch:
        sw = ToggleSwitch(checked)
        sw.toggled.connect(lambda _v: self._on_edit())
        return sw

    def _align_select(self) -> PillSelect:
        pill = PillSelect()
        pill.setItems([label for _v, label in _ALIGN_ITEMS])
        pill.currentTextChanged.connect(lambda _t: self._on_edit())
        return pill

    @staticmethod
    def _align_value(pill: PillSelect) -> str:
        label = pill.currentText()
        return next((v for v, lab in _ALIGN_ITEMS if lab == label), "center")

    @staticmethod
    def _set_align(pill: PillSelect, value: str):
        label = next((lab for v, lab in _ALIGN_ITEMS if v == value), "居中")
        pill.setCurrentText(label)

    def _color(self, color: QColor, title: str, alpha: bool = False) -> ColorValueControl:
        ctl = ColorValueControl(color, title, alpha=alpha, width=124)
        ctl.colorChanged.connect(lambda _c: self._on_edit())
        return ctl

    def _build_layout_group(self) -> InspectorGroup:
        group = InspectorGroup(self.tr("字幕排布"))
        self.contentSeg = FilterTabs(
            [("bilingual", self.tr("双语")), ("source", self.tr("原文")), ("target", self.tr("译文"))]
        )
        self.contentSeg.changed.connect(self._on_content_changed)
        group.addRow(InspectorRow(AppIcon.LANGUAGE, self.tr("显示内容"), self.contentSeg))

        self.orderPill = PillSelect()
        self.orderPill.setItems([self.tr("原文在上"), self.tr("译文在上")])
        self.orderPill.currentTextChanged.connect(lambda _t: self._on_edit())
        self.orderRow = InspectorRow(AppIcon.ALIGNMENT, self.tr("双语顺序"), self.orderPill)
        group.addRow(self.orderRow)
        return group

    def _gap_row(self) -> InspectorRow:
        """主副间距行（放在「位置」组）：ASS 映射上行对话 MarginV；圆角映射两气泡间距。"""
        self.gapStepper = self._stepper(10, 0, 80, 1, suffix="px")
        self.gapRow = InspectorRow(AppIcon.LAYOUT, self.tr("主副间距"), self.gapStepper)
        return self.gapRow

    def _rebuild_inspector(self, key: str):
        self._mode_key = key
        self._clear_inspector()
        self._ass, self._rounded = {}, {}
        groups: list[InspectorGroup] = [self._build_layout_group()]

        if key == "rounded":
            r = self._rounded
            bg = InspectorGroup(self.tr("背景"))
            r["bg_color"] = self._color(QColor(13, 227, 255, 230), self.tr("背景颜色"), alpha=True)
            bg.addRow(InspectorRow(AppIcon.PALETTE, self.tr("背景颜色"), r["bg_color"]))
            r["radius"] = self._stepper(14, 0, 60, 1, suffix="px")
            bg.addRow(InspectorRow(AppIcon.ZOOM, self.tr("圆角半径"), r["radius"]))
            groups.append(bg)

            text = InspectorGroup(self.tr("文字"), self.tr("主副字幕"))
            r["font"] = self._font_select()
            text.addRow(InspectorRow(AppIcon.FONT, self.tr("字体"), r["font"]))
            r["size"] = self._stepper(34, 8, 160, 1, suffix="px")
            text.addRow(InspectorRow(AppIcon.FONT_SIZE, self.tr("字号"), r["size"]))
            r["text_color"] = self._color(QColor("#ffffff"), self.tr("文字颜色"))
            text.addRow(InspectorRow(AppIcon.PALETTE, self.tr("文字颜色"), r["text_color"]))
            r["letter"] = self._stepper(0, 0, 40, 1, suffix="px")
            text.addRow(InspectorRow(AppIcon.FONT, self.tr("字间距"), r["letter"]))
            groups.append(text)

            inner = InspectorGroup(self.tr("内边距"))
            r["pad_h"] = self._stepper(28, 0, 120, 1, suffix="px")
            inner.addRow(InspectorRow(AppIcon.LAYOUT, self.tr("水平内边距"), r["pad_h"]))
            r["pad_v"] = self._stepper(14, 0, 80, 1, suffix="px")
            inner.addRow(InspectorRow(AppIcon.LAYOUT, self.tr("垂直内边距"), r["pad_v"]))
            groups.append(inner)

            position = InspectorGroup(self.tr("位置"))
            r["margin"] = self._stepper(60, 0, 400, 2, suffix="px")
            position.addRow(InspectorRow(AppIcon.ALIGNMENT, self.tr("底部边距"), r["margin"]))
            position.addRow(self._gap_row())
            r["max_width"] = self._stepper(90, 30, 100, 2, suffix="%")
            position.addRow(InspectorRow(AppIcon.LAYOUT, self.tr("最大宽度"), r["max_width"]))
            r["align"] = self._align_select()
            position.addRow(InspectorRow(AppIcon.ALIGNMENT, self.tr("对齐方式"), r["align"]))
            groups.append(position)
        else:
            a = self._ass
            primary = InspectorGroup(self.tr("主字幕"), self.tr("原文"))
            a["font"] = self._font_select()
            primary.addRow(InspectorRow(AppIcon.FONT, self.tr("字体"), a["font"]))
            a["size"] = self._stepper(42, 8, 160, 1, suffix="px")
            primary.addRow(InspectorRow(AppIcon.FONT_SIZE, self.tr("字号"), a["size"]))
            a["color"] = self._color(QColor("#ffffff"), self.tr("文字颜色"))
            primary.addRow(InspectorRow(AppIcon.PALETTE, self.tr("文字颜色"), a["color"]))
            a["outline_color"] = self._color(QColor("#000000"), self.tr("描边颜色"))
            primary.addRow(InspectorRow(AppIcon.BRUSH, self.tr("描边颜色"), a["outline_color"]))
            a["outline"] = self._stepper(3, 0, 12, 0.5, decimals=1, suffix="px")
            primary.addRow(InspectorRow(AppIcon.BRUSH, self.tr("描边宽度"), a["outline"]))
            a["spacing"] = self._stepper(0.2, 0, 12, 0.2, decimals=1, suffix="px")
            primary.addRow(InspectorRow(AppIcon.FONT, self.tr("字间距"), a["spacing"]))
            a["bold"] = self._toggle(True)
            primary.addRow(InspectorRow(AppIcon.FONT, self.tr("加粗"), a["bold"]))
            groups.append(primary)

            secondary = InspectorGroup(self.tr("副字幕"), self.tr("译文"))
            a["sec_font"] = self._font_select()
            secondary.addRow(InspectorRow(AppIcon.FONT, self.tr("字体"), a["sec_font"]))
            a["sec_size"] = self._stepper(27, 8, 160, 1, suffix="px")
            secondary.addRow(InspectorRow(AppIcon.FONT_SIZE, self.tr("字号"), a["sec_size"]))
            a["sec_color"] = self._color(QColor("#ffe36b"), self.tr("文字颜色"))
            secondary.addRow(InspectorRow(AppIcon.PALETTE, self.tr("文字颜色"), a["sec_color"]))
            a["sec_outline_color"] = self._color(QColor("#000000"), self.tr("描边颜色"))
            secondary.addRow(InspectorRow(AppIcon.BRUSH, self.tr("描边颜色"), a["sec_outline_color"]))
            a["sec_outline"] = self._stepper(2, 0, 12, 0.5, decimals=1, suffix="px")
            secondary.addRow(InspectorRow(AppIcon.BRUSH, self.tr("描边宽度"), a["sec_outline"]))
            a["sec_spacing"] = self._stepper(0.8, 0, 12, 0.2, decimals=1, suffix="px")
            secondary.addRow(InspectorRow(AppIcon.FONT, self.tr("字间距"), a["sec_spacing"]))
            a["sec_bold"] = self._toggle(True)
            secondary.addRow(InspectorRow(AppIcon.FONT, self.tr("加粗"), a["sec_bold"]))
            groups.append(secondary)

            position = InspectorGroup(self.tr("位置"))
            a["margin"] = self._stepper(42, 0, 400, 2, suffix="px")
            position.addRow(InspectorRow(AppIcon.ALIGNMENT, self.tr("底部边距"), a["margin"]))
            position.addRow(self._gap_row())
            a["max_width"] = self._stepper(100, 30, 100, 2, suffix="%")
            position.addRow(InspectorRow(AppIcon.LAYOUT, self.tr("最大宽度"), a["max_width"]))
            a["align"] = self._align_select()
            position.addRow(InspectorRow(AppIcon.ALIGNMENT, self.tr("对齐方式"), a["align"]))
            groups.append(position)

        for group in groups:
            self.inspectorLayout.insertWidget(self.inspectorLayout.count() - 1, group)

    # ---------------------------------------------------------------- 字幕排布

    def _on_content_changed(self, _key: str):
        bilingual = self.contentSeg.current() == "bilingual"
        self.orderRow.setVisible(bilingual)
        self.gapRow.setVisible(bilingual)  # 主副间距只在双语时有意义
        self._on_edit()

    def _current_layout(self) -> SubtitleLayoutEnum:
        content = self.contentSeg.current()
        if content == "source":
            return SubtitleLayoutEnum.ONLY_ORIGINAL
        if content == "target":
            return SubtitleLayoutEnum.ONLY_TRANSLATE
        if self.orderPill.currentText() == self.tr("译文在上"):
            return SubtitleLayoutEnum.TRANSLATE_ON_TOP
        return SubtitleLayoutEnum.ORIGINAL_ON_TOP

    def _apply_layout_to_controls(self, layout: SubtitleLayoutEnum):
        if layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
            self.contentSeg.setCurrent("source")
        elif layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
            self.contentSeg.setCurrent("target")
        elif layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP:
            self.contentSeg.setCurrent("bilingual")
            self.orderPill.setCurrentText(self.tr("译文在上"))
        else:
            self.contentSeg.setCurrent("bilingual")
            self.orderPill.setCurrentText(self.tr("原文在上"))
        bilingual = self.contentSeg.current() == "bilingual"
        self.orderRow.setVisible(bilingual)
        self.gapRow.setVisible(bilingual)

    # ---------------------------------------------------------------- 样式库

    def _clear_dock_cards(self):
        """清空横向轨道（setParent(None) 立即脱离，避免 deleteLater 异步重影）。"""
        self._cards = []
        while self.trackLayout.count() > 1:  # 保留末尾 stretch
            item = self.trackLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _set_current_style(self, style_id: str):
        """提交当前模式选中的样式：写配置 + 记住该模式的选择（切模式往返可还原）。"""
        self._mode_style[self._mode_key] = style_id
        cfg.set(cfg.subtitle_style_name, style_id)

    def _refresh_style_list(self):
        """重建样式卡（仅在新增/复制/重命名/删除/切换模式时调用，点选切换不重建）。"""
        self._clear_dock_cards()

        key = self._mode_key
        styles = list_styles(renderer=key)
        styles.sort(key=lambda s: (s.id != f"{key}/default", s.source.value, s.short_id))
        self.countChip.setText(self.tr("共 {} 套").format(len(styles)))

        # 优先用本模式记住的选择；它若属于另一模式（normalize 仍带原前缀）则解析不到，
        # 回退到该模式首张卡（内置默认），而不会污染另一模式的记忆。
        active_id = self._mode_style.get(key) or normalize_style_id(
            cfg.subtitle_style_name.value, key
        )
        active_preset = next((s for s in styles if s.id == active_id), None)
        if active_preset is None:
            active_preset = styles[0] if styles else None
        active_norm = active_preset.id if active_preset is not None else ""

        active_card = None
        for idx, preset in enumerate(styles):
            card = self._make_card(preset)
            card.setActive(preset.id == active_norm)
            if preset.id == active_norm:
                active_card = card
            self.trackLayout.insertWidget(idx, card)
            self._cards.append(card)

        # 让坞内容宽度等于所有卡片之和，横向才能真正滚动（否则 setWidgetResizable
        # 会把内容压成视口宽度，超出的卡片被裁还滚不到）。
        margins = self.trackLayout.contentsMargins()
        spacing = self.trackLayout.spacing()
        content_w = (
            margins.left() + margins.right()
            + len(self._cards) * _CARD_WIDTH
            + max(0, len(self._cards) - 1) * spacing
        )
        self.trackBody.setMinimumWidth(content_w)

        if active_preset is not None:
            self._set_current_style(active_preset.id)
            self._load_into_controls(active_preset)
            self.update_preview()
        self._scroll_card_into_view(active_card)

    def _make_card(self, preset: SubtitleStylePreset) -> StyleCard:
        icon = AppIcon.PALETTE if preset.renderer == SubtitleRenderer.ROUNDED else AppIcon.BRUSH
        card = StyleCard(
            preset.id,
            preset.name,
            self._swatches(preset),
            preset.editable,
            icon,
        )
        card.setFixedWidth(_CARD_WIDTH)  # 统一宽度，可容纳选中态的三个文字动作按钮
        card.clicked.connect(self._select_style)
        card.duplicateRequested.connect(self._duplicate_style)
        card.renameRequested.connect(self._rename_style)
        card.deleteRequested.connect(self._delete_style)
        return card

    def _swatches(self, preset: SubtitleStylePreset) -> list[str]:
        style = preset.style
        if isinstance(style, RoundedSubtitleStyle):
            return [style.text_color, _rgba_hex_to_qcolor(style.bg_color).name(QColor.HexRgb)]
        if isinstance(style, AssSubtitleStyle):
            colors = [style.primary_color, style.outline_color]
            if style.secondary and style.secondary.color not in colors:
                colors.append(style.secondary.color)
            return colors
        return []

    def _select_style(self, style_id: str):
        """点选某个样式 → 仅高亮 + 载入参数 + 刷新预览（不重建卡片，避免重排闪动）。"""
        key = self._mode_key
        if normalize_style_id(style_id, key) == normalize_style_id(cfg.subtitle_style_name.value, key):
            return  # 已是当前样式
        preset = load_style(style_id, renderer=key)
        if preset is None:
            return
        self._set_current_style(preset.id)
        active_card = None
        for card in self._cards:
            card.setActive(card.style_id == preset.id)
            if card.style_id == preset.id:
                active_card = card
        self._load_into_controls(preset)
        self.update_preview()
        self._scroll_card_into_view(active_card)

    def _scroll_card_into_view(self, card: Optional[StyleCard]):
        """把指定卡片横向滚动到可见处（延后到布局完成，确保滚动范围已就绪）。"""
        if card is None:
            return

        def _do(c=card):
            if c in self._cards:
                self.trackScroll.ensureWidgetVisible(c, 24, 0)

        QTimer.singleShot(0, _do)

    # ---------------------------------------------------------------- 控件 ↔ 样式

    def _load_into_controls(self, preset: SubtitleStylePreset):
        self._loading = True
        self._apply_layout_to_controls(cfg.subtitle_layout.value)
        if isinstance(preset.style, RoundedSubtitleStyle):
            s, r = preset.style, self._rounded
            self._set_font(r["font"], s.font_name)
            r["size"].setValue(s.font_size)
            r["text_color"].setColor(QColor(s.text_color))
            r["bg_color"].setColor(_rgba_hex_to_qcolor(s.bg_color))
            r["radius"].setValue(s.corner_radius)
            self.gapStepper.setValue(s.line_spacing)
            r["letter"].setValue(s.letter_spacing)
            r["pad_h"].setValue(s.padding_h)
            r["pad_v"].setValue(s.padding_v)
            r["margin"].setValue(s.margin_bottom)
            r["max_width"].setValue(s.max_width)
            self._set_align(r["align"], s.align)
        elif isinstance(preset.style, AssSubtitleStyle):
            s, a = preset.style, self._ass
            self._set_font(a["font"], s.font_name)
            a["size"].setValue(s.font_size)
            a["color"].setColor(QColor(s.primary_color))
            a["outline_color"].setColor(QColor(s.outline_color))
            a["outline"].setValue(s.outline_width)
            a["spacing"].setValue(s.spacing)
            a["bold"].setChecked(s.bold)
            a["margin"].setValue(s.margin_bottom)
            a["max_width"].setValue(s.max_width)
            self._set_align(a["align"], s.align)
            self.gapStepper.setValue(s.line_gap)
            sec = s.secondary
            if sec:
                self._set_font(a["sec_font"], sec.font_name)
                a["sec_size"].setValue(sec.font_size)
                a["sec_color"].setColor(QColor(sec.color))
                a["sec_outline_color"].setColor(QColor(sec.outline_color))
                a["sec_outline"].setValue(sec.outline_width)
                a["sec_spacing"].setValue(sec.spacing)
                a["sec_bold"].setChecked(sec.bold)
            else:
                self._set_font(a["sec_font"], s.font_name)
                a["sec_bold"].setChecked(s.bold)  # 无副字幕样式时沿用主字幕加粗
        self._loading = False

    def _preset_from_controls(self, style_id: str, name: Optional[str] = None) -> SubtitleStylePreset:
        key = self._mode_key
        if key == "rounded":
            r = self._rounded
            style = RoundedSubtitleStyle(
                font_name=r["font"].currentText(),
                font_size=int(r["size"].value()),
                text_color=r["text_color"].color().name(QColor.HexRgb),
                bg_color=_qcolor_to_rgba_hex(r["bg_color"].color()),
                corner_radius=int(r["radius"].value()),
                padding_h=int(r["pad_h"].value()),
                padding_v=int(r["pad_v"].value()),
                margin_bottom=int(r["margin"].value()),
                line_spacing=int(self.gapStepper.value()),
                letter_spacing=int(r["letter"].value()),
                max_width=int(r["max_width"].value()),
                align=self._align_value(r["align"]),
            )
            renderer = SubtitleRenderer.ROUNDED
        else:
            a = self._ass
            style = AssSubtitleStyle(
                font_name=a["font"].currentText(),
                font_size=int(a["size"].value()),
                primary_color=a["color"].color().name(QColor.HexRgb),
                outline_color=a["outline_color"].color().name(QColor.HexRgb),
                outline_width=a["outline"].value(),
                bold=a["bold"].isChecked(),
                spacing=a["spacing"].value(),
                margin_bottom=int(a["margin"].value()),
                max_width=int(a["max_width"].value()),
                align=self._align_value(a["align"]),
                line_gap=int(self.gapStepper.value()),
                secondary=AssSecondaryStyle(
                    font_name=a["sec_font"].currentText(),
                    font_size=int(a["sec_size"].value()),
                    color=a["sec_color"].color().name(QColor.HexRgb),
                    outline_color=a["sec_outline_color"].color().name(QColor.HexRgb),
                    outline_width=a["sec_outline"].value(),
                    spacing=a["sec_spacing"].value(),
                    bold=a["sec_bold"].isChecked(),
                ),
            )
            renderer = SubtitleRenderer.ASS
        return SubtitleStylePreset(
            id=style_id,
            name=name or style_id.split("/", 1)[-1],
            renderer=renderer,
            source=StyleSource.USER,
            style=style,
        )

    def _new_user_id(self, name: str) -> str:
        """从显示名生成唯一的用户样式 id（中文名会被 slug 化，塌成 default 时回退）。"""
        key = self._mode_key
        base = normalize_style_id(name, key)
        if base == f"{key}/default":
            base = f"{key}/style"
        candidate, index = base, 2
        while load_style(candidate, renderer=key) is not None:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _on_edit(self):
        """任一参数变化：刷新预览 + 自动保存（编辑内置样式时自动 fork）。"""
        if self._loading:
            return
        cfg.set(cfg.subtitle_layout, self._current_layout())
        self.update_preview()
        self._auto_save()

    def _auto_save(self):
        current_id = normalize_style_id(cfg.subtitle_style_name.value, self._mode_key)
        preset = load_style(current_id, renderer=self._mode_key)
        if preset is not None and preset.source == StyleSource.BUILTIN:
            # 内置只读：编辑即派生出该内置「唯一」的「· 自定义」影子样式。
            # 用确定性 id（不递增 -custom-N）：已存在就复用并更新，避免每次
            # 选择被重置回内置后又新建一个，导致样式越积越多。
            fork_id = f"{self._mode_key}/{preset.short_id}-custom"
            existing = load_style(fork_id, renderer=self._mode_key)
            name = (
                existing.name
                if existing is not None and existing.source == StyleSource.USER
                else f"{preset.name} · {self.tr('自定义')}"
            )
            save_user_style(self._preset_from_controls(fork_id, name))
            self._set_current_style(fork_id)
            self._refresh_style_list()
            return
        # 已是用户样式：保留其显示名，只更新参数
        keep_name = preset.name if preset is not None else None
        save_user_style(self._preset_from_controls(current_id, keep_name))
        # 颜色可能变化，刷新当前卡的色块
        for card in self._cards:
            if card.style_id == current_id:
                updated = load_style(current_id, renderer=self._mode_key)
                if updated:
                    card.setSwatches(self._swatches(updated))
                break

    def _unique_user_id(self, preset: SubtitleStylePreset) -> str:
        renderer = preset.renderer.value
        base = f"{renderer}/{preset.short_id}-custom"
        candidate, index = base, 2
        while load_style(candidate, renderer=renderer) is not None:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    # ---------------------------------------------------------------- 库动作

    def _on_new_style(self):
        name = self._ask_name(self.tr("新建样式"))
        if not name:
            return
        style_id = self._new_user_id(name)
        save_user_style(self._preset_from_controls(style_id, name))
        self._set_current_style(style_id)
        self._refresh_style_list()
        self._toast(self.tr("已创建样式「{}」").format(name))

    def _duplicate_style(self, style_id: str):
        preset = load_style(style_id, renderer=self._mode_key)
        if preset is None:
            return
        new_id = self._unique_user_id(preset)
        copy = SubtitleStylePreset(
            id=new_id,
            name=f"{preset.name} {self.tr('副本')}",
            renderer=preset.renderer,
            source=StyleSource.USER,
            style=preset.style,
        )
        save_user_style(copy)
        self._set_current_style(new_id)
        self._refresh_style_list()
        self._toast(self.tr("已复制为「{}」").format(copy.name))

    def _rename_style(self, style_id: str):
        # 只改显示名，文件 id 保持不变：避免中文名 slug 化撞名、也省去删旧文件。
        preset = load_style(style_id, renderer=self._mode_key)
        if preset is None or not preset.editable:
            return
        name = self._ask_name(self.tr("重命名样式"), preset.name)
        if not name or name == preset.name:
            return
        renamed = SubtitleStylePreset(
            id=style_id, name=name, renderer=preset.renderer,
            source=StyleSource.USER, style=preset.style,
        )
        save_user_style(renamed)
        self._refresh_style_list()
        self._toast(self.tr("已重命名为「{}」").format(name))

    def _delete_style(self, style_id: str):
        preset = load_style(style_id, renderer=self._mode_key)
        if preset is None or not preset.editable:
            return
        dialog = ConfirmDialog(
            self.tr("删除样式"),
            self.tr("确定删除样式「{}」吗？此操作不可恢复。").format(preset.name),
            self,
        )
        if not dialog.exec():
            return
        delete_user_style(style_id)
        self._set_current_style(f"{self._mode_key}/default")
        self._refresh_style_list()
        self._toast(self.tr("样式已删除"))

    # ---------------------------------------------------------------- 预览

    def _toggle_orientation(self):
        self._orientation = "竖屏" if self._orientation == "横屏" else "横屏"
        self.orientationButton.setText(self.tr("{}预览").format(self._orientation))
        # 切方向时回退到内置背景（用户自定义背景按固定尺寸渲染不区分横竖）
        cfg.set(cfg.subtitle_preview_image, "")
        self.update_preview()

    def _pick_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择背景图片"), "", self.tr("图片文件") + " (*.png *.jpg *.jpeg)"
        )
        if path:
            cfg.set(cfg.subtitle_preview_image, path)
            self.update_preview()

    def _edit_preview_text(self):
        """编辑预览示例文字（原文 / 译文），持久化后立即刷新预览。"""
        dialog = PreviewTextDialog(
            cfg.subtitle_preview_source.value, cfg.subtitle_preview_target.value, self
        )
        if dialog.exec():
            cfg.set(cfg.subtitle_preview_source, dialog.sourceEdit.text().strip() or PREVIEW_TEXT[0])
            cfg.set(cfg.subtitle_preview_target, dialog.targetEdit.text().strip() or PREVIEW_TEXT[1])
            self.update_preview()

    def _preview_pair(self) -> Tuple[str, Optional[str]]:
        original = cfg.subtitle_preview_source.value or PREVIEW_TEXT[0]
        translation = cfg.subtitle_preview_target.value or PREVIEW_TEXT[1]
        layout = self._current_layout()
        if layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
            main, sub = original, None
        elif layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
            main, sub = translation, None
        elif layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP:
            main, sub = translation, original
        else:
            main, sub = original, translation
        return main, sub

    def _background_path(self) -> str:
        user_bg = cfg.subtitle_preview_image.value
        if user_bg and Path(user_bg).exists():
            return user_bg
        return str(DEFAULT_BG_LANDSCAPE if self._orientation == "横屏" else DEFAULT_BG_PORTRAIT)

    def update_preview(self):
        """预览刷新入口：空闲后首次立即渲染，连拍则防抖合并到末尾。"""
        if time.monotonic() - self._last_preview_ts > 0.15:
            self._preview_timer.stop()
            self._render_preview_now()
        else:
            self._preview_timer.start()

    def _render_preview_now(self):
        self._last_preview_ts = time.monotonic()
        if not (self._ass or self._rounded):
            return
        main, sub = self._preview_pair()
        bg = self._background_path()
        if self._mode_key == "rounded":
            r = self._rounded
            style = RoundedBgStyle(
                font_name=r["font"].currentText(),
                font_size=int(r["size"].value()),
                bg_color=_qcolor_to_rgba_hex(r["bg_color"].color()),
                text_color=r["text_color"].color().name(QColor.HexRgb),
                corner_radius=int(r["radius"].value()),
                padding_h=int(r["pad_h"].value()),
                padding_v=int(r["pad_v"].value()),
                margin_bottom=int(r["margin"].value()),
                line_spacing=int(self.gapStepper.value()),
                letter_spacing=int(r["letter"].value()),
                max_width=int(r["max_width"].value()),
                align=self._align_value(r["align"]),
            )
            thread: QThread = RoundedBgPreviewThread((main, sub), style, bg)
        else:
            # 预览与合成共用同一份样式字符串（AssSubtitleStyle.to_ass_string），避免漂移
            ass_style = self._preset_from_controls("ass/preview", "preview").style
            thread = AssPreviewThread(
                (main, sub), ass_style.to_ass_string(), bg, line_gap=int(self.gapStepper.value())
            )

        self._preview_generation += 1
        generation = self._preview_generation
        thread.previewReady.connect(
            lambda path, gen=generation: self._on_preview_ready(path)
            if gen == self._preview_generation
            else None
        )
        thread.finished.connect(lambda t=thread: self._preview_threads.remove(t) if t in self._preview_threads else None)
        self._preview_threads.append(thread)
        thread.start()

    def _on_preview_ready(self, path: str):
        self.previewImage.setImage(path)
        img = getattr(self.previewImage, "image", None)
        self._preview_native = (
            (img.width(), img.height()) if img is not None and not img.isNull() else None
        )
        self._fit_preview()

    def _fit_preview(self):
        """等比缩放预览图尽量铺满舞台（仅留薄边），同时适配宽屏/矮屏/全屏。

        取「按宽适配」与「按高适配」的较小比例，确保任一维度都不溢出；上限为原生
        分辨率（默认背景 1280×720），避免放大发糊。宽而矮的屏由高度约束自动收窄、
        横向居中——所以铺得满又不裁切。
        """
        native = getattr(self, "_preview_native", None)
        if not native:
            return
        nw, nh = native
        if nw <= 0 or nh <= 0:
            return
        margin = 20  # 对应舞台 stage_layout 上下/左右各 10 的薄边
        avail_w = self.stage.width() - margin
        avail_h = self.stage.height() - margin
        if avail_w <= 0 or avail_h <= 0:
            return
        scale = min(avail_w / nw, avail_h / nh, 1.0)
        self.previewImage.scaledToWidth(max(1, int(nw * scale)))
        if self.previewImage.height() > avail_h:
            self.previewImage.scaledToHeight(avail_h)
        self.previewImage.setBorderRadius(12, 12, 12, 12)

    # ---------------------------------------------------------------- 杂项

    def _ask_name(self, title: str, initial: str = "") -> str:
        dialog = StyleNameDialog(title, initial, self)
        if dialog.exec():
            return dialog.nameLineEdit.text().strip()
        return ""

    def _toast(self, text: str):
        InfoBar.success(
            "", text, orient=Qt.Horizontal, isClosable=True,  # type: ignore[arg-type]
            position=InfoBarPosition.TOP, duration=INFOBAR_DURATION_SUCCESS, parent=self,
        )

    def _warn(self, text: str):
        InfoBar.warning(
            "", text, orient=Qt.Horizontal, isClosable=True,  # type: ignore[arg-type]
            position=InfoBarPosition.TOP, duration=INFOBAR_DURATION_WARNING, parent=self,
        )

    def _apply_page_style(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QWidget#SubtitleStyleInterface {{ background: {palette.bg}; }}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_preview()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_preview()
        # 首次显示时把当前样式滚到可见处（构建时页面还没尺寸，滚动不生效）
        active = next((c for c in self._cards if c.isActive()), None)
        self._scroll_card_into_view(active)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".png", ".jpg", ".jpeg")):
                    event.accept()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".png", ".jpg", ".jpeg")):
                cfg.set(cfg.subtitle_preview_image, path)
                self.update_preview()
                self._toast(self.tr("已设置预览背景：") + Path(path).name)
                break

    def closeEvent(self, event):
        for thread in list(self._preview_threads):
            if thread.isRunning():
                thread.wait(3000)
        self._preview_threads.clear()
        super().closeEvent(event)


class StyleNameDialog(AppDialog):
    """样式名称输入弹窗（新建 / 重命名共用）。"""

    def __init__(self, title: str = "新建样式", initial: str = "", parent=None):
        super().__init__(title, icon=AppIcon.EDIT, parent=parent, width=380)
        self.nameLineEdit = AppLineEdit(parent=self.widget)
        self.nameLineEdit.setPlaceholderText(self.tr("输入样式名称"))
        self.nameLineEdit.setClearButtonEnabled(True)
        self.nameLineEdit.setText(initial)
        self.bodyLayout.addWidget(self.nameLineEdit)

        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(self.tr("取消"))
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(self.tr("确定"), kind="accent")
        self.confirmButton.clicked.connect(lambda: self.done(1))
        self.confirmButton.setEnabled(bool(initial.strip()))
        self.nameLineEdit.textChanged.connect(
            lambda text: self.confirmButton.setEnabled(bool(text.strip()))
        )


class PreviewTextDialog(AppDialog):
    """编辑预览示例文字（原文 / 译文）。"""

    def __init__(self, source: str = "", target: str = "", parent=None):
        super().__init__("预览文字", icon=AppIcon.FONT, parent=parent, width=420)
        source_label = SectionLabel(self.tr("原文"))
        apply_font(source_label, 13, 800)
        self.bodyLayout.addWidget(source_label)
        self.sourceEdit = AppLineEdit(parent=self.widget)
        self.sourceEdit.setPlaceholderText(self.tr("用于预览的原文示例"))
        self.sourceEdit.setText(source)
        self.bodyLayout.addWidget(self.sourceEdit)

        target_label = SectionLabel(self.tr("译文"))
        apply_font(target_label, 13, 800)
        self.bodyLayout.addWidget(target_label)
        self.targetEdit = AppLineEdit(parent=self.widget)
        self.targetEdit.setPlaceholderText(self.tr("用于预览的译文示例"))
        self.targetEdit.setText(target)
        self.bodyLayout.addWidget(self.targetEdit)

        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(self.tr("取消"))
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(self.tr("确定"), kind="accent")
        self.confirmButton.clicked.connect(lambda: self.done(1))
