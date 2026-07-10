"""第一方侧边栏：可展开/收纳的应用导航（替代 qfluent NavigationInterface）。

设计要点（对齐产品参考稿）：
- 两态：展开（图标+文字+active 胶囊）/ 收纳（纯图标 rail）；宽度动画过渡。
- 图标列的水平位置在两态间完全不变——只有文字区伸缩，切换不跳动。
- 文字随宽度动画按比例淡出/淡入并被裁切，不换行不挤压。
- 颜色全部取自 app_palette()，亮/暗主题自适应；收纳态悬停显示 tooltip。

用法：
    sidebar = Sidebar()
    sidebar.add_page("home", AppIcon.HOME, tr("app.nav.home"))
    sidebar.add_action("github", AppIcon.GITHUB, "GitHub", on_click)   # 底部动作，不参与选中
    sidebar.currentChanged.connect(...)   # 参数为页面 key
    sidebar.set_current("home")
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import QAbstractButton, QFrame, QVBoxLayout

from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.workbench import icon_pixmap, qt_font_weight
from videocaptioner.ui.i18n import tr

# 几何常量：图标中心在两态下都固定在 x=COLLAPSED_WIDTH/2，保证切换不跳动
COLLAPSED_WIDTH = 64
EXPANDED_WIDTH = 224
ITEM_HEIGHT = 40
ITEM_MARGIN_X = 10  # 胶囊距侧栏左右边缘
ICON_SIZE = 20
LABEL_X = COLLAPSED_WIDTH - ITEM_MARGIN_X + 2  # 文字起点：图标区右侧
ANIM_MS = 180


class SidebarItem(QAbstractButton):
    """一行导航项：自绘 胶囊底 + 固定位图标 + 随展开度淡入的文字。"""

    def __init__(
        self,
        key: str,
        icon: AppIcon,
        label: str,
        parent: "Sidebar",
        *,
        selectable: bool = True,
        variant: str = "nav",
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._icon = icon
        self._label = label
        self._selectable = selectable
        # "nav"=导航页面项（选中胶囊+文字）；"toggle"=展开/收纳控件（不同语义：图标按钮、无文字）
        self._variant = variant
        self._active = False
        self._hover = False
        self._sidebar = parent
        self.setFixedHeight(ITEM_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(qt_font_weight(600))
        self.setFont(font)

    # ---- 状态 ----

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.update()

    def label(self) -> str:
        return self._label

    def set_label(self, label: str) -> None:
        self._label = label
        self.update()

    # ---- 事件 ----

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def _paint_toggle(self, painter: QPainter, palette) -> None:
        """收纳/展开控件：与导航项不同语义 —— 无胶囊、无文字，紧凑图标按钮。

        图标固定在图标列（与下方导航图标同一条竖线，两态都不移动），语义区分靠 panel 图标 +
        无胶囊 + muted 色 + 下方分隔线。悬停只在图标周围显示小圆角方块，不占满整行。
        """
        icon_x = COLLAPSED_WIDTH // 2 - ICON_SIZE // 2
        icon_y = (ITEM_HEIGHT - ICON_SIZE) // 2

        if self._hover:
            side = ICON_SIZE + 12
            sq = QRectF(icon_x + ICON_SIZE / 2 - side / 2, (ITEM_HEIGHT - side) / 2, side, side)
            hover = QColor(palette.field)
            hover.setAlphaF(0.55)
            painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
            painter.setBrush(hover)
            painter.drawRoundedRect(sq, 9, 9)

        color = palette.text if self._hover else palette.subtle
        painter.drawPixmap(icon_x, icon_y, icon_pixmap(self._icon, color, ICON_SIZE))

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._variant == "toggle":
            self._paint_toggle(painter, palette)
            return

        # 胶囊底：active 实底、hover 弱底；宽度跟随当前侧栏宽度
        pill = QRectF(
            ITEM_MARGIN_X,
            2,
            self._sidebar.width() - ITEM_MARGIN_X * 2,
            ITEM_HEIGHT - 4,
        )
        if self._active:
            painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
            painter.setBrush(QColor(palette.field))
            painter.drawRoundedRect(pill, 10, 10)
        elif self._hover:
            hover = QColor(palette.field)
            hover.setAlphaF(0.55)
            painter.setPen(Qt.NoPen)  # type: ignore[arg-type]
            painter.setBrush(hover)
            painter.drawRoundedRect(pill, 10, 10)

        # 图标：中心固定在收纳态 rail 的中线，两态不移动
        color = palette.accent if self._active else palette.muted
        pixmap = icon_pixmap(self._icon, color, ICON_SIZE)
        icon_x = COLLAPSED_WIDTH // 2 - ICON_SIZE // 2
        icon_y = (ITEM_HEIGHT - ICON_SIZE) // 2
        painter.drawPixmap(icon_x, icon_y, pixmap)

        # 文字：透明度随展开进度（宽度比例）淡入淡出；裁切在胶囊内，不换行
        progress = self._sidebar.expand_progress()
        if progress > 0.05:
            painter.setOpacity(progress)
            painter.setPen(QColor(palette.text if self._active else palette.subtle))
            painter.setFont(self.font())
            avail = int(pill.right()) - LABEL_X - 6
            if avail > 12:
                text = QFontMetrics(self.font()).elidedText(
                    self._label, Qt.ElideRight, avail  # type: ignore[arg-type]
                )
                painter.drawText(
                    LABEL_X,
                    0,
                    avail,
                    ITEM_HEIGHT,
                    Qt.AlignVCenter | Qt.AlignLeft,  # type: ignore[arg-type]
                    text,
                )


class _SidebarSeparator(QFrame):
    """控件区与导航区之间的细分隔线，随宽度内缩（收纳态更短、展开态更长）。"""

    def __init__(self, parent: "Sidebar") -> None:
        super().__init__(parent)
        self.setFixedHeight(11)

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        color = QColor(palette.line_soft)
        color.setAlphaF(0.7)
        painter.setPen(color)
        y = self.height() // 2
        painter.drawLine(ITEM_MARGIN_X + 4, y, self.width() - ITEM_MARGIN_X - 4, y)


class Sidebar(QFrame):
    """应用侧边导航栏。页面项互斥选中；动作项只触发回调（如 GitHub / 设置弹窗）。"""

    currentChanged = pyqtSignal(str)
    expandedChanged = pyqtSignal(bool)

    def __init__(self, parent=None, *, expanded: bool = True, top_inset: int = 0) -> None:
        """``top_inset``：顶部让位高度（如宿主的自绘标题栏区），内容从其下方开始。"""
        super().__init__(parent)
        self.setObjectName("appSidebar")
        self._expanded = expanded
        self._current: Optional[str] = None
        self._items: dict[str, SidebarItem] = {}
        self._width_anim = QPropertyAnimation(self, b"paneWidth", self)
        self._width_anim.setDuration(ANIM_MS)
        self._width_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setFixedWidth(EXPANDED_WIDTH if expanded else COLLAPSED_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 8 + top_inset, 0, 10)
        self._layout.setSpacing(2)

        # 顶部：展开/收纳控件。用 panel 图标 + toggle 变体（与下方导航项不同语义），仅图标无文字
        self._toggle = SidebarItem(
            "__toggle__", AppIcon.PANEL_LEFT, self._toggle_label(), self,
            selectable=False, variant="toggle",
        )
        self._toggle.clicked.connect(self.toggle)
        self._toggle.setToolTip(self._toggle_label())  # 图标控件：两态都给 tooltip
        self._layout.addWidget(self._toggle)
        # 控件区与导航区之间的分隔线，强化「不同语义」
        self._layout.addWidget(_SidebarSeparator(self))

        self._main_index = self._layout.count()  # 页面项插入点
        self._layout.addStretch(1)  # 主区与底部区之间的弹性空隙

    # ---- 组装 ----

    def add_page(self, key: str, icon: AppIcon, label: str) -> None:
        """主导航页面项（互斥选中，点击发 currentChanged）。"""
        item = self._make_item(key, icon, label, selectable=True)
        self._layout.insertWidget(self._main_index, item)
        self._main_index += 1

    def add_action(
        self, key: str, icon: AppIcon, label: str, on_click: Callable[[], None]
    ) -> None:
        """底部动作项（不参与选中，点击执行回调）。"""
        item = self._make_item(key, icon, label, selectable=False)
        item.clicked.connect(on_click)
        self._layout.addWidget(item)

    def _make_item(self, key: str, icon: AppIcon, label: str, *, selectable: bool) -> SidebarItem:
        item = SidebarItem(key, icon, label, self, selectable=selectable)
        if selectable:
            item.clicked.connect(lambda _=False, k=key: self.set_current(k))
        self._items[key] = item
        self._sync_tooltips()
        return item

    # ---- 选中 ----

    def set_current(self, key: str) -> None:
        if key == self._current or key not in self._items:
            return
        self._current = key
        for item_key, item in self._items.items():
            item.set_active(item_key == key)
        self.currentChanged.emit(key)

    def current(self) -> Optional[str]:
        return self._current

    # ---- 展开/收纳 ----

    def is_expanded(self) -> bool:
        return self._expanded

    def expand_progress(self) -> float:
        """0=完全收纳，1=完全展开（供子项按进度渲染文字透明度）。"""
        span = EXPANDED_WIDTH - COLLAPSED_WIDTH
        return max(0.0, min(1.0, (self.width() - COLLAPSED_WIDTH) / span))

    def set_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        target = EXPANDED_WIDTH if expanded else COLLAPSED_WIDTH
        self._width_anim.stop()
        if animate:
            self._width_anim.setStartValue(self.width())
            self._width_anim.setEndValue(target)
            self._width_anim.start()
        else:
            self.setFixedWidth(target)
        self._toggle.set_label(self._toggle_label())
        self._toggle.setToolTip(self._toggle_label())
        self._sync_tooltips()
        self.expandedChanged.emit(expanded)

    def _toggle_label(self) -> str:
        return tr("app.sidebar.collapse") if self._expanded else tr("app.sidebar.expand")

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def _sync_tooltips(self) -> None:
        # 导航项：收纳态看不到文字用 tooltip 兜底，展开态不打扰。
        # toggle 是纯图标控件，两态都保留 tooltip（在 set_expanded 里维护）。
        for item in self._items.values():
            item.setToolTip("" if self._expanded else item.label())

    # 动画属性：QFrame 没有 paneWidth，这里落到 fixedWidth 上驱动布局与子项重绘
    def _get_pane_width(self) -> int:
        return self.width()

    def _set_pane_width(self, value: int) -> None:
        self.setFixedWidth(int(value))
        for item in self._items.values():
            item.update()
        self._toggle.update()

    paneWidth = pyqtProperty(int, fget=_get_pane_width, fset=_set_pane_width)

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(palette.bg))
        # 右缘 1px 分隔线，与内容区形成轻边界
        painter.setPen(QColor(palette.line_soft))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
