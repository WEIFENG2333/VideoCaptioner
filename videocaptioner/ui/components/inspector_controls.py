# coding:utf-8
"""检查器/参数面板通用控件：参数行 + 参数分组 + 取色控件 + 省略标签 + 样式卡。

这里放的是「带标签的参数行、可分组的参数面板、取色控件、省略标签」等可复用组合，
以及样式库卡片 StyleCard。数值步进器、胶囊下拉、分段、状态胶囊等更底层的原子复用
workbench。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.workbench import (
    CompactButton,
    DangerButton,
    IconBox,
    StatusPill,
    apply_font,
    draw_rounded_surface,
    icon_pixmap,
)


class ColorSwatch(QFrame):
    """抗锯齿色块：自绘圆角填充 + 细描边。QSS border-radius 无抗锯齿会留锯齿，
    色块/色点统一用它。支持带 alpha 的颜色（圆角背景色）。"""

    def __init__(self, color: QColor, size: int = 18, radius: int = 6, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._radius = radius
        self.setFixedSize(size, size)

    def setColor(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.fillPath(path, self._color)
        pen = painter.pen()
        pen.setColor(QColor(255, 255, 255, 60))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)


class ElideLabel(QLabel):
    """单行省略标签：文本超出宽度时尾部省略，且最小宽度为 0，

    不会把所在卡片撑宽到滚动区视口之外（否则在关闭横向滚动的列表里右侧被裁）。
    """

    def __init__(self, text: str = "", mode=Qt.ElideRight, parent=None):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self._elide()

    def setText(self, text: str):
        self._full = text
        self._elide()

    def fullText(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        width = self.width()
        if width <= 0:
            QLabel.setText(self, self._full)
            return
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, self._mode, width))


class ColorValueControl(QFrame):
    """取色控件：色点 + 取值文本，点击弹系统取色盘。

    ``alpha=True`` 时显示透明度百分比并允许调整 alpha（圆角背景色用）。
    """

    colorChanged = pyqtSignal(QColor)

    def __init__(self, color: QColor, title: str = "", alpha: bool = False, parent=None, width: int = 150):
        super().__init__(parent)
        self.setObjectName("styleColorControl")
        self._title = title
        self._alpha = alpha
        self._color = QColor(color)
        self.setFixedHeight(34)
        self.setFixedWidth(width)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 0, 12, 0)
        layout.setSpacing(9)
        self.dot = ColorSwatch(self._color, 18, 6, self)
        layout.addWidget(self.dot)
        self.textLabel = QLabel(self)
        self.textLabel.setObjectName("styleColorText")
        apply_font(self.textLabel, 13, 800)
        layout.addWidget(self.textLabel, 1)
        self._refresh()
        self.syncStyle()

    def color(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor, *, emit: bool = False):
        self._color = QColor(color)
        self._refresh()
        if emit:
            self.colorChanged.emit(self.color())

    def _refresh(self):
        # 色点显示真实颜色（含透明度时叠棋盘格才直观，这里仍以纯色点为主）；
        # 文本统一显示十六进制色值，透明度由色点 alpha 体现，避免只显示「90%」难以辨色。
        self.dot.setColor(QColor(self._color))
        self.textLabel.setText(self._color.name(QColor.HexRgb).upper())

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            from videocaptioner.ui.components.color_picker import ColorPickerDialog

            title = (self.tr("选择") + self._title) if self._title else self.tr("选择颜色")
            color = ColorPickerDialog.get_color(
                self._color, parent=self.window(), alpha=self._alpha, title=title
            )
            if color is not None:
                self.setColor(color, emit=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        border = rgba(palette.accent, 0.6) if hovered else palette.line
        draw_rounded_surface(self, palette.field, border, 9)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet("QFrame#styleColorControl { background: transparent; border: none; }")
        self.textLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )
        self._refresh()
        self.update()


class InspectorRow(QFrame):
    """参数行：[图标] 名称 ……… [控件]，右侧控件由调用方提供。"""

    def __init__(self, icon: AppIcon, label: str, control: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorRow")
        self.setMinimumHeight(50)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(16, 16)
        layout.addWidget(self.iconLabel)
        self._icon = icon

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.labelLabel = QLabel(label, self)
        self.labelLabel.setObjectName("inspectorRowLabel")
        apply_font(self.labelLabel, 14, 830)
        text_box.addWidget(self.labelLabel)
        self.hintLabel: Optional[QLabel] = None
        if hint:
            self.hintLabel = QLabel(hint, self)
            self.hintLabel.setObjectName("inspectorRowHint")
            apply_font(self.hintLabel, 12, 720)
            text_box.addWidget(self.hintLabel)
        layout.addLayout(text_box, 1)

        self.control = control
        control.setParent(self)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        self.syncStyle()

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.card_surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet("QFrame#inspectorRow { background: transparent; border: none; }")
        self.iconLabel.setPixmap(icon_pixmap(self._icon, palette.muted, 16))
        self.labelLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )
        if self.hintLabel is not None:
            self.hintLabel.setStyleSheet(
                f"color: {palette.muted}; background: transparent; border: none;"
            )
        self.update()


class InspectorGroup(QWidget):
    """参数分组：标题 + 侧注 + 若干参数行。"""

    def __init__(self, title: str, side: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("inspectorGroupTitle")
        apply_font(self.titleLabel, 15, 880)
        head.addWidget(self.titleLabel)
        head.addStretch(1)
        self.sideLabel = QLabel(side, self)
        self.sideLabel.setObjectName("inspectorGroupSide")
        apply_font(self.sideLabel, 12, 720)
        head.addWidget(self.sideLabel)
        layout.addLayout(head)

        self._rows = QVBoxLayout()
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(8)
        layout.addLayout(self._rows)
        self.syncStyle()

    def addRow(self, row: QWidget) -> QWidget:
        self._rows.addWidget(row)
        return row

    def setSide(self, text: str):
        self.sideLabel.setText(text)

    def syncStyle(self):
        palette = app_palette()
        self.titleLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )
        self.sideLabel.setStyleSheet(
            f"color: {palette.muted}; background: transparent; border: none;"
        )


class StyleCard(QFrame):
    """样式库卡片：图标 + 名称 + 状态胶囊 + 色块 + 分隔线 + 动作按钮。

    动作按钮常驻（不再选中才展开）：用户样式给「复制 / 重命名 / 删除」，内置样式给
    「复制」一键 fork。选中态主题色描边 + 胶囊显「当前」。点击卡片主体发 clicked。
    """

    clicked = pyqtSignal(str)
    duplicateRequested = pyqtSignal(str)
    renameRequested = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)

    def __init__(
        self,
        style_id: str,
        name: str,
        swatches: list[str],
        editable: bool,
        icon: AppIcon,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("styleCard")
        self.style_id = style_id
        self._editable = editable
        self._active = False
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        self.setFixedHeight(126)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 11, 12, 11)
        outer.setSpacing(8)

        # 顶行：图标 + 名称 + 状态胶囊（当前 / 我的 / 内置）
        main = QHBoxLayout()
        main.setSpacing(10)
        self.iconBox = IconBox(icon, self, size=30)
        main.addWidget(self.iconBox, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        self.nameLabel = ElideLabel(name, parent=self)
        self.nameLabel.setObjectName("styleCardName")
        apply_font(self.nameLabel, 14, 880)
        main.addWidget(self.nameLabel, 1, Qt.AlignVCenter)  # type: ignore[arg-type]
        self.sourcePill = StatusPill(
            self.tr("我的") if editable else self.tr("内置"), "neutral", self
        )
        main.addWidget(self.sourcePill, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        outer.addLayout(main)

        # 色块行
        self._swatch_widgets: list[ColorSwatch] = []
        self.swatchRow = QHBoxLayout()
        self.swatchRow.setSpacing(5)
        for color in swatches[:4]:
            dot = ColorSwatch(QColor(color), 16, 5, self)
            self.swatchRow.addWidget(dot)
            self._swatch_widgets.append(dot)
        self.swatchRow.addStretch(1)
        outer.addLayout(self.swatchRow)

        # 分隔线
        self.divider = QFrame(self)
        self.divider.setFixedHeight(1)
        outer.addWidget(self.divider)

        # 动作按钮行（常驻，居中陈列；窄卡片用更紧的内边距 + 图标）
        self.actionsRow = QWidget(self)
        actions = QHBoxLayout(self.actionsRow)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(7)
        self.duplicateButton = CompactButton(self.tr("复制"), AppIcon.COPY, self.actionsRow, pad_h=8)
        self.duplicateButton.clicked.connect(lambda: self.duplicateRequested.emit(self.style_id))
        if editable:
            self.renameButton = CompactButton(self.tr("重命名"), AppIcon.EDIT, self.actionsRow, pad_h=8)
            self.deleteButton = DangerButton(self.tr("删除"), AppIcon.DELETE, self.actionsRow, pad_h=8)
            self.renameButton.clicked.connect(lambda: self.renameRequested.emit(self.style_id))
            self.deleteButton.clicked.connect(lambda: self.deleteRequested.emit(self.style_id))
            self._buttons = (self.duplicateButton, self.renameButton, self.deleteButton)
            actions.addStretch(1)
            for btn in self._buttons:
                actions.addWidget(btn)
            actions.addStretch(1)
        else:
            # 内置只读：仅给「复制」做 fork 入口，整行铺满更有存在感（不留空白）
            self.renameButton = None
            self.deleteButton = None
            self._buttons = (self.duplicateButton,)
            actions.addWidget(self.duplicateButton, 1)
        outer.addWidget(self.actionsRow)
        self.syncStyle()

    def setActive(self, active: bool):
        # 选中由卡片描边（paintEvent）表达，不改写标签——保留「我的 / 内置」原始 tag 不变
        self._active = active
        self.update()

    def isActive(self) -> bool:
        return self._active

    def setSwatches(self, colors: list[str]):
        """编辑后颜色变化时刷新色块（多退少补，保持横向陈列宽度不变）。"""
        colors = colors[:4]
        for idx, color in enumerate(colors):
            if idx < len(self._swatch_widgets):
                self._swatch_widgets[idx].setColor(QColor(color))
            else:
                dot = ColorSwatch(QColor(color), 16, 5, self)
                self.swatchRow.insertWidget(idx, dot)
                self._swatch_widgets.append(dot)
        while len(self._swatch_widgets) > len(colors):
            dot = self._swatch_widgets.pop()
            dot.setParent(None)
            dot.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            # 动作区内部的点击由各按钮处理，这里只接卡片主体
            child = self.childAt(event.pos())
            if child is None or not self.actionsRow.isAncestorOf(child):
                self.clicked.emit(self.style_id)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        if self._active:
            draw_rounded_surface(self, rgba(palette.accent, 0.085), rgba(palette.accent, 0.72), 13)
        else:
            draw_rounded_surface(self, palette.card_surface, palette.line_soft, 13)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet("QFrame#styleCard { background: transparent; border: none; }")
        self.nameLabel.setStyleSheet(
            f"color: {palette.text}; background: transparent; border: none;"
        )
        self.divider.setStyleSheet(f"background: {palette.line_soft}; border: none;")
        self.actionsRow.setStyleSheet("background: transparent; border: none;")
        self.iconBox.syncStyle()
        self.sourcePill.syncStyle()
        for btn in self._buttons:
            btn.syncStyle()
        self.update()
