# -*- coding: utf-8 -*-
"""字幕优化与翻译页：两栏审校工作台。

左侧是字幕表格面板（文件行 + 可编辑表格 + 底部状态条），
右侧是固定 340px 的处理设置栏（选项卡片 + 主操作按钮）。

页面状态机（PageState）：

    EMPTY   未加载字幕：表格区为拖放导入空态，按钮禁用
    READY   准备处理：字幕已载入表格，可编辑、可开始
    RUNNING 处理中：底部进度条 + 当前条数，表格未处理行变暗，可取消
    DONE    完成检查：表格展示处理结果，按钮变“进入合成”
    FAILED  配置未就绪 / 处理失败：错误卡片 + 引导去配置或重试

线程统一由 SubtitleProcessController 持有；表格数据由 SubtitleTableModel
管理（双击编辑原文/译文，右键合并 / 删除 / 重新翻译，快捷键
Ctrl+M / Delete / Ctrl+T）。

对外接口（HomeInterface 依赖，保持兼容）：
    finished(str, str)  视频路径、处理后字幕路径
    set_task(task) / process() / close()
"""

from __future__ import annotations

import os
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from PyQt5.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Action, InfoBar, RoundMenu
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.entities import (
    OutputSubtitleFormatEnum,
    SubtitleLayoutEnum,
    SubtitleTask,
    SupportedSubtitleFormats,
    TranslatorServiceEnum,
)
from videocaptioner.core.subtitle import get_subtitle_style
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.utils.platform_utils import open_folder, reveal_in_explorer
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.enum_labels import enum_from_label, enum_label, enum_options
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import AppDialog, ConfirmDialog
from videocaptioner.ui.components.workbench import (
    AppTextEdit,
    CollapsibleSideHost,
    CompactButton,
    DangerButton,
    DropZone,
    ElidedLabel,
    ErrorCard,
    OptionCard,
    PanelHeader,
    PillSelect,
    ProgressBarLine,
    RoundIconButton,
    StatusPill,
    ToggleSwitch,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
    icon_pixmap,
    to_qcolor,
)
from videocaptioner.ui.i18n import N_, tr
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.subtitle_thread import RetranslateThread, SubtitleThread

_SUBTITLE_FORMATS = {fmt.value for fmt in SupportedSubtitleFormats}
_FORMATS_PILL_TEXT = " / ".join(fmt.value.upper() for fmt in SupportedSubtitleFormats)


class PageState(Enum):
    EMPTY = auto()
    READY = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()


def _format_table_clock(ms: int) -> str:
    """表格时间戳短格式：00:01.12，超过 1 小时带小时位。"""
    centis = (max(0, int(ms)) % 1000) // 10
    total = max(0, int(ms)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


# ---------------------------------------------------------------------------
# 线程编排
# ---------------------------------------------------------------------------


class SubtitleProcessController(QObject):
    """持有字幕处理 / 重新翻译线程，页面只消费信号。"""

    progressChanged = pyqtSignal(int, str)
    rowsUpdated = pyqtSignal(dict)
    allUpdated = pyqtSignal(dict)
    completed = pyqtSignal(str, str)  # video_path, output_path
    failed = pyqtSignal(str)
    retranslated = pyqtSignal(dict)
    retranslateFailed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._process_thread: Optional[SubtitleThread] = None
        self._retranslate_thread: Optional[RetranslateThread] = None

    def start_processing(self, task: SubtitleTask, prompt: str) -> bool:
        if self.is_processing():
            return False
        thread = SubtitleThread(task)
        thread.set_custom_prompt_text(prompt)
        thread.finished.connect(self.completed)
        thread.progress.connect(self.progressChanged)
        thread.update.connect(self.rowsUpdated)
        thread.update_all.connect(self.allUpdated)
        thread.error.connect(self.failed)
        self._process_thread = thread
        thread.start()
        return True

    def retranslate(self, rows: Dict[str, Any], config, file_name: str) -> bool:
        if self.is_processing():
            return False
        thread = RetranslateThread(rows, config, file_name)
        thread.finished.connect(self.retranslated)
        thread.progress.connect(self.progressChanged)
        thread.error.connect(self.retranslateFailed)
        self._retranslate_thread = thread
        thread.start()
        return True

    def is_processing(self) -> bool:
        return any(
            thread is not None and thread.isRunning()
            for thread in (self._process_thread, self._retranslate_thread)
        )

    def cancel(self) -> None:
        thread = self._process_thread
        self._process_thread = None
        if thread is not None and thread.isRunning():
            try:
                thread.finished.disconnect()
                thread.progress.disconnect()
                thread.update.disconnect()
                thread.update_all.disconnect()
                thread.error.disconnect()
            except TypeError:
                pass
            thread.stop()

    def shutdown(self) -> None:
        """页面关闭时调用：协作停止（基类内部超时才强杀）。"""
        for thread in (self._process_thread, self._retranslate_thread):
            if thread is not None:
                thread.stop()


# ---------------------------------------------------------------------------
# 表格模型
# ---------------------------------------------------------------------------


class SubtitleTableModel(QAbstractTableModel):
    """字幕表格模型：开始 / 结束 / 原文 / 译文，原文与译文可编辑。

    数据结构与 ASRData.to_json() 一致：{"1": {start_time, end_time,
    original_subtitle, translated_subtitle}, ...}。
    """

    HEADER_KEYS = (
        N_("subtitle.col.start"),
        N_("subtitle.col.end"),
        N_("subtitle.col.original"),
        N_("subtitle.col.translated"),
    )

    def __init__(self, data: Union[Dict[str, Any], None] = None):
        super().__init__()
        self._data: Dict[str, Any] = data or {}
        self._dim_from: Optional[int] = None

    # ----- 数据存取 -----

    def raw(self) -> Dict[str, Any]:
        return self._data

    def replace_all(self, data: Dict[str, Any]) -> None:
        self.beginResetModel()
        self._data = data
        self._dim_from = None
        self.endResetModel()

    def merge_translations(self, new_data: Dict[str, str]) -> None:
        """合并增量翻译结果（key 为行号字符串）。"""
        updated = set()
        keys = list(self._data.keys())
        for key, value in new_data.items():
            if key in self._data:
                self._data[key]["translated_subtitle"] = value
                updated.add(keys.index(key))
        if updated:
            top, bottom = min(updated), max(updated)
            self.dataChanged.emit(
                self.index(top, 2), self.index(bottom, 3), [Qt.DisplayRole]
            )

    def set_dim_from(self, row: Optional[int]) -> None:
        """处理中：row 之后的行变暗（running 态的未处理行）。"""
        if row != self._dim_from:
            self._dim_from = row
            if self.rowCount():
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self.rowCount() - 1, 3),
                    [Qt.ForegroundRole],
                )

    def segment_at(self, row: int) -> Optional[Dict[str, Any]]:
        keys = list(self._data.keys())
        if 0 <= row < len(keys):
            return self._data[keys[row]]
        return None

    def remove_rows(self, rows: list[int]) -> None:
        keys = list(self._data.keys())
        keep = [key for index, key in enumerate(keys) if index not in set(rows)]
        self.replace_all(
            {str(i + 1): self._data[key] for i, key in enumerate(keep)}
        )

    def merge_rows(self, rows: list[int]) -> None:
        """把连续选中的行合并为一条（时间取首尾，文本拼接）。"""
        if len(rows) < 2:
            return
        keys = list(self._data.keys())
        items = [self._data[keys[row]] for row in rows]
        merged = {
            "start_time": items[0]["start_time"],
            "end_time": items[-1]["end_time"],
            "original_subtitle": " ".join(i["original_subtitle"] for i in items),
            "translated_subtitle": " ".join(
                i["translated_subtitle"] for i in items if i["translated_subtitle"]
            ),
        }
        selected = set(rows)
        new_items = []
        for index, key in enumerate(keys):
            if index == rows[0]:
                new_items.append(merged)
            elif index not in selected:
                new_items.append(self._data[key])
        self.replace_all({str(i + 1): item for i, item in enumerate(new_items)})

    # ----- Qt 模型接口 -----

    def rowCount(self, parent: Optional[QModelIndex] = None) -> int:
        return len(self._data)

    def columnCount(self, parent: Optional[QModelIndex] = None) -> int:
        return 4

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[assignment]
        if not index.isValid():
            return None
        segment = self.segment_at(index.row())
        if segment is None:
            return None
        column = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):  # type: ignore[attr-defined]
            if column == 0:
                return _format_table_clock(segment["start_time"])
            if column == 1:
                return _format_table_clock(segment["end_time"])
            if column == 2:
                return segment["original_subtitle"]
            return segment["translated_subtitle"]
        if role == Qt.ForegroundRole and self._dim_from is not None:  # type: ignore[attr-defined]
            if index.row() >= self._dim_from:
                return QColor(app_palette().subtle)
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # type: ignore[assignment]
        if not index.isValid() or role != Qt.EditRole:  # type: ignore[attr-defined]
            return False
        segment = self.segment_at(index.row())
        if segment is None or index.column() not in (2, 3):
            return False
        field = "original_subtitle" if index.column() == 2 else "translated_subtitle"
        segment[field] = value
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):  # type: ignore[assignment]
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:  # type: ignore[attr-defined]
            return tr(self.HEADER_KEYS[section])
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags  # type: ignore[attr-defined]
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable  # type: ignore[attr-defined]
        if index.column() in (2, 3):
            return base | Qt.ItemIsEditable  # type: ignore[attr-defined]
        return base


# ---------------------------------------------------------------------------
# 左侧：表格面板
# ---------------------------------------------------------------------------


class SubtitleTableView(QTableView):
    """带悬浮行高亮的表格视图（专业编辑器的基础体验）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_row = -1
        self._dbl_global = None  # 最近一次双击的全局坐标，供行内编辑器定位光标
        self.setMouseTracking(True)

    def hoverRow(self) -> int:
        return self._hover_row

    def takeDoubleClickPos(self):
        pos, self._dbl_global = self._dbl_global, None
        return pos

    def mouseDoubleClickEvent(self, event):
        self._dbl_global = event.globalPos()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        row = self.rowAt(event.pos().y())
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()
        super().leaveEvent(event)


class SubtitleLineEditor(QLineEdit):
    """字幕行内编辑器：双击进入编辑不再全选整格——光标落在点击处（取不到则置于末尾），

    与专业字幕工具（Aegisub / Subtitle Edit）一致：双击定位、可直接续编而非误删全行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._click_global = None

    def setClickPoint(self, global_pos):
        self._click_global = global_pos

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Qt 默认聚焦即 selectAll；改为按点击处定位光标、不选中
        self.deselect()
        pos = len(self.text())
        if self._click_global is not None:
            local = self.mapFromGlobal(self._click_global)
            if self.rect().contains(local):
                pos = self.cursorPositionAt(local)
            self._click_global = None
        self.setCursorPosition(pos)


class SubtitleEditDelegate(QStyledItemDelegate):
    """字幕单元格编辑委托。

    - 深色行内编辑器（替换系统白色编辑框），accent 边框、与单元格排版对齐
    - 双击定位光标（不全选）；Enter 提交并编辑下一条、Shift+Enter 上一条、Esc 取消
    - 悬浮行画淡色高亮
    """

    def __init__(self, view: SubtitleTableView):
        super().__init__(view)
        self._view = view

    def paint(self, painter, option, index):
        if (
            index.row() == self._view.hoverRow()
            and not option.state & QStyle.State_Selected  # type: ignore[attr-defined]
        ):
            hover = app_palette().card_surface_hover
            painter.fillRect(option.rect, to_qcolor(hover))
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        palette = app_palette()
        editor = SubtitleLineEditor(parent)
        editor.setClickPoint(self._view.takeDoubleClickPos())
        apply_font(editor, 15, 650)
        editor.setStyleSheet(
            f"""
            QLineEdit {{
                background: {palette.panel_deep};
                color: {palette.text};
                border: 1px solid {rgba(palette.accent, 0.85)};
                border-radius: 6px;
                padding: 0 10px;
                selection-background-color: {rgba(palette.accent, 0.35)};
                selection-color: {palette.text};
            }}
            """
        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(4, 7, -4, -7))

    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:  # type: ignore[attr-defined]
                # 取消编辑、还原原文（Qt 默认也会处理，这里显式以确保一致）
                self.closeEditor.emit(editor, QStyledItemDelegate.RevertModelCache)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):  # type: ignore[attr-defined]
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)
                # Shift+Enter 编辑上一条，Enter 编辑下一条（连续审校流）
                step = -1 if event.modifiers() & Qt.ShiftModifier else 1  # type: ignore[attr-defined]
                current = self._view.currentIndex()
                target = current.sibling(current.row() + step, current.column())
                if target.isValid():
                    QTimer.singleShot(0, lambda: self._edit_at(target))
                return True
        return super().eventFilter(editor, event)

    def _edit_at(self, index):
        self._view.setCurrentIndex(index)
        self._view.scrollTo(index)
        self._view.edit(index)


class TableBottomBar(QFrame):
    """表格底部状态条：按状态展示条数 / 进度 / 输出信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tableBottomBar")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 14, 0)
        layout.setSpacing(14)

        self.leftPill = StatusPill("", "fail", self)
        layout.addWidget(self.leftPill)
        self.infoLabel = QLabel(self)
        self.infoLabel.setObjectName("bottomInfo")
        apply_font(self.infoLabel, 14, 730)
        layout.addWidget(self.infoLabel)
        self.hintLabel = QLabel(self)
        self.hintLabel.setObjectName("bottomHint")
        apply_font(self.hintLabel, 14, 730)
        layout.addWidget(self.hintLabel)
        self.progressLine = ProgressBarLine(self)
        self.progressLine.setFixedWidth(320)
        layout.addWidget(self.progressLine)
        self.percentLabel = QLabel(self)
        self.percentLabel.setObjectName("bottomInfo")
        self.percentLabel.setMinimumWidth(46)
        apply_font(self.percentLabel, 14, 730)
        layout.addWidget(self.percentLabel)
        layout.addStretch(1)
        self.rightLabel = QLabel(self)
        self.rightLabel.setObjectName("bottomHint")
        apply_font(self.rightLabel, 14, 730)
        layout.addWidget(self.rightLabel)
        self.rightPill = StatusPill("", "ok", self)
        self.rightPill.setMinimumWidth(118)
        layout.addWidget(self.rightPill)
        self.syncStyle()

    def _show(self, **visible):
        widgets = {
            "left_pill": self.leftPill,
            "info": self.infoLabel,
            "hint": self.hintLabel,
            "progress": self.progressLine,
            "percent": self.percentLabel,
            "right_label": self.rightLabel,
            "right_pill": self.rightPill,
        }
        for name, widget in widgets.items():
            widget.setVisible(visible.get(name, False))

    def showReady(self, count: int):
        self.infoLabel.setText(tr("subtitle.bottom.count", count=count))
        self.hintLabel.setText(tr("subtitle.bottom.hint"))
        self.rightPill.setState(tr("subtitle.bottom.loaded"), "ok")
        self._show(info=True, hint=True, right_pill=True)

    def showRunning(self, stage: str, percent: int, current: int, total: int):
        self.infoLabel.setText(stage)
        self.progressLine.setValue(percent)
        self.percentLabel.setText(f"{percent}%")
        self.rightPill.setState(
            tr("subtitle.bottom.progress", current=current, total=total), "warn"
        )
        self._show(info=True, progress=True, percent=True, right_pill=True)

    def showFailed(self, title: str, detail: str):
        self.leftPill.setState(title, "fail")
        self.infoLabel.setText(detail)
        self._show(left_pill=True, info=True)

    def showDone(self, output_name: str):
        self.infoLabel.setText(tr("subtitle.bottom.output", name=output_name))
        self.rightPill.setState(tr("subtitle.bottom.can_synthesize"), "ok")
        self._show(info=True, right_pill=True)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame#tableBottomBar {{
                background: transparent;
                border: none;
                border-top: 1px solid {palette.line_soft};
            }}
            QLabel#bottomInfo {{ color: {palette.muted}; background: transparent; }}
            QLabel#bottomHint {{ color: {palette.subtle}; background: transparent; }}
            """
        )


class SubtitleTablePanel(WorkbenchPanel):
    """左侧表格面板：文件行 + 头部操作 + 可编辑表格 / 空态 + 底部状态条。"""

    browseRequested = pyqtSignal()
    saveFormatRequested = pyqtSignal(str)
    openFolderRequested = pyqtSignal()
    resetRequested = pyqtSignal()

    def __init__(self, model: SubtitleTableModel, parent=None):
        super().__init__(parent, padded=False)

        # 头部：文件行 + 操作按钮。56 高 + 22 左边距与各页标题栏统一；
        # 空态显示分区标题字号（20/860），载入后切回文件名字号（15/840）。
        self.head = QFrame(self)
        self.head.setObjectName("tableHead")
        self.head.setFixedHeight(56)
        head_layout = QHBoxLayout(self.head)
        # 左右 22 与各页 PanelHeader 标题栏一致，折叠态展开钮才能与转录/合成页对齐
        head_layout.setContentsMargins(22, 0, 22, 0)
        head_layout.setSpacing(9)  # 与 PanelHeader 的按钮间距一致
        self.fileIcon = QLabel(self.head)
        self.fileIcon.hide()
        head_layout.addWidget(self.fileIcon)
        self.fileName = ElidedLabel(tr("subtitle.no_file"), self.head)
        self.fileName.setObjectName("tableFileName")
        apply_font(self.fileName, 20, 860)
        head_layout.addWidget(self.fileName, 1)
        head_layout.addSpacing(8)

        self.saveButton = CompactButton(tr("common.save"), AppIcon.SAVE, self.head)
        self.saveButton.clicked.connect(self._show_save_menu)
        head_layout.addWidget(self.saveButton)
        self.folderButton = CompactButton(tr("subtitle.btn.folder"), AppIcon.FOLDER, self.head)
        self.folderButton.clicked.connect(self.openFolderRequested)
        head_layout.addWidget(self.folderButton)
        self.replaceButton = CompactButton(tr("subtitle.btn.replace"), AppIcon.FOLDER_ADD, self.head)
        self.replaceButton.clicked.connect(self.browseRequested)
        head_layout.addWidget(self.replaceButton)
        # 清空当前字幕、回到初始态（报错/完成后可一键重来）
        self.resetButton = DangerButton(tr("subtitle.btn.clear"), AppIcon.DELETE, self.head)
        self.resetButton.clicked.connect(self.resetRequested)
        head_layout.addWidget(self.resetButton)
        # 右栏折叠时的主操作入口（状态与右栏主按钮同步，32 高与头部按钮组一致）。
        self.headStartButton = WorkbenchButton(
            tr("subtitle.btn.start"), AppIcon.PLAY, primary=True, height=32, parent=self.head
        )
        self.headStartButton.setMinimumWidth(104)
        self.headStartButton.hide()
        head_layout.addWidget(self.headStartButton)
        # 右栏折叠后的展开入口（固定在头部，位置不漂移）。
        self.expandButton = RoundIconButton(AppIcon.LAYOUT, diameter=32, parent=self.head)
        self.expandButton.setToolTip(tr("subtitle.tip.expand_settings"))
        self.expandButton.hide()
        head_layout.addWidget(self.expandButton)
        self.bodyLayout.addWidget(self.head)

        # 主体：空态拖放区 / 表格
        self.stack = QStackedWidget(self)
        # 空态与转录页完全同构：虚线框 + 辉光 + 同尺寸图标与标题。
        self.dropZone = DropZone(
            icon=AppIcon.SUBTITLE,
            title=tr("subtitle.drop.title"),
            pick_text=tr("subtitle.drop.pick"),
            pick_icon=AppIcon.FOLDER_ADD,
            formats_line=_FORMATS_PILL_TEXT.lower(),
            parent=self,
        )
        self.dropZone.browseRequested.connect(self.browseRequested)
        drop_host = QWidget(self)
        drop_layout = QVBoxLayout(drop_host)
        drop_layout.setContentsMargins(16, 16, 16, 16)
        drop_layout.addWidget(self.dropZone)
        self.stack.addWidget(drop_host)

        self.table = SubtitleTableView(self)
        self.table.setModel(model)
        self.table.setItemDelegate(SubtitleEditDelegate(self.table))
        self.table.setObjectName("subtitleTable")
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 108)
        self.table.setColumnWidth(1, 108)
        self.table.horizontalHeader().setFixedHeight(46)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignLeft | Qt.AlignVCenter  # type: ignore[arg-type]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.stack.addWidget(self.table)
        self.bodyLayout.addWidget(self.stack, 1)

        self.bottomBar = TableBottomBar(self)
        self.bodyLayout.addWidget(self.bottomBar)
        self.syncStyle()

    def setFile(self, name: str, loaded: bool):
        palette = app_palette()
        self.fileName.setText(name)
        apply_font(self.fileName, 15 if loaded else 20, 840 if loaded else 860)
        self.fileIcon.setVisible(loaded)
        if loaded:
            self.fileIcon.setPixmap(icon_pixmap(AppIcon.SUBTITLE, palette.muted, 18))

    def setHeadState(self, state: PageState):
        """头部操作随状态切换：空态只留标题（导入入口在拖放区），
        其余状态显示保存/目录/更换；状态与条数统一由底部状态条表达。"""
        empty = state == PageState.EMPTY
        running = state == PageState.RUNNING
        for button in (self.saveButton, self.folderButton, self.replaceButton, self.resetButton):
            button.setVisible(not empty)
            button.setEnabled(not running)

    def _show_save_menu(self):
        menu = RoundMenu(parent=self)
        for fmt in OutputSubtitleFormatEnum:
            action = Action(fmt.value.upper())
            action.triggered.connect(
                lambda _=False, value=fmt.value: self.saveFormatRequested.emit(value)
            )
            menu.addAction(action)
        menu.exec(self.saveButton.mapToGlobal(self.saveButton.rect().bottomLeft()))

    def syncStyle(self):
        super().syncStyle()
        palette = app_palette()
        selection_bg = rgba(palette.accent, 0.10)
        self.head.setStyleSheet(
            f"""
            QFrame#tableHead {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QLabel#tableFileName {{ color: {palette.text}; background: transparent; }}
            """
        )
        self.table.setStyleSheet(
            f"""
            QTableView#subtitleTable {{
                background: transparent;
                border: none;
                color: {palette.muted};
                font-size: 15px;
                selection-background-color: {selection_bg};
                selection-color: {palette.text};
                outline: none;
            }}
            QTableView#subtitleTable::item {{
                padding: 0 14px;
                border-bottom: 1px solid {palette.line_soft};
                border-right: 1px solid {palette.line_soft};
            }}
            QTableView#subtitleTable::item:selected {{
                background: {selection_bg};
                color: {palette.text};
            }}
            QHeaderView::section {{
                background: {palette.panel_deep};
                color: {palette.muted};
                border: none;
                border-bottom: 1px solid {palette.line_soft};
                border-right: 1px solid {palette.line_soft};
                padding-left: 14px;
                font-size: 15px;
                font-weight: bold;
                text-align: left;
            }}
            QTableView QTableCornerButton::section {{
                background: {palette.panel_deep}; border: none;
            }}
            """
        )
        # qfluent 全局样式会覆盖嵌在 QTableView qss 里的表头/滚动条规则，
        # 必须直接设到子控件上才生效。
        self.table.horizontalHeader().setStyleSheet(
            f"""
            QHeaderView {{ background: {palette.panel_deep}; border: none; }}
            QHeaderView::section {{
                background: {palette.panel_deep};
                color: {palette.muted};
                border: none;
                border-bottom: 1px solid {palette.line_soft};
                border-right: 1px solid {palette.line_soft};
                padding-left: 14px;
                font-size: 15px;
                font-weight: bold;
            }}
            """
        )
        scrollbar_style = f"""
            QScrollBar:vertical {{
                background: transparent; width: 5px; margin: 0; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {palette.line}; border-radius: 2px; min-height: 32px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; width: 0; background: transparent; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            """
        self.table.verticalScrollBar().setStyleSheet(scrollbar_style)


# ---------------------------------------------------------------------------
# 右侧：处理设置面板
# ---------------------------------------------------------------------------


class ProcessSidePanel(WorkbenchPanel):
    """右侧处理设置：开关卡片 + 取值卡片 + 主操作按钮。"""

    settingsRequested = pyqtSignal()
    promptRequested = pyqtSignal()
    primaryRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    collapseRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, padded=True)
        self.bodyLayout.setSpacing(0)

        self.header = PanelHeader(
            tr("subtitle.process_settings"), inline=True, underline=True, parent=self
        )
        self.collapseButton = RoundIconButton(AppIcon.RIGHT_ARROW, parent=self)
        self.collapseButton.setToolTip(tr("subtitle.tip.collapse_settings"))
        self.collapseButton.clicked.connect(self.collapseRequested)
        self.header.addRight(self.collapseButton)
        self.configButton = RoundIconButton(AppIcon.SETTING, parent=self)
        self.configButton.setToolTip(tr("subtitle.btn.open_config"))
        self.configButton.clicked.connect(self.settingsRequested)
        self.header.addRight(self.configButton)
        self.bodyLayout.addWidget(self.header)

        self.errorCard = ErrorCard(parent=self)
        self.errorCard.hide()

        self.optimizeSwitch = ToggleSwitch(parent=self)
        self.translateSwitch = ToggleSwitch(parent=self)
        self.splitSwitch = ToggleSwitch(parent=self)
        self.languageSelect = PillSelect(self)
        self.layoutSelect = PillSelect(self)
        self.promptChip = CompactButton(tr("subtitle.prompt.unset"), None, self)
        self.promptChip.clicked.connect(self.promptRequested)

        # 子布局统一间距：隐藏的卡片不再残留 addSpacing 导致间距叠加。
        options = QVBoxLayout()
        options.setContentsMargins(0, 18, 0, 0)
        options.setSpacing(14)
        options.addWidget(self.errorCard)
        cards = [
            OptionCard(tr("subtitle.opt.optimize"), self.optimizeSwitch, self),
            OptionCard(tr("subtitle.opt.translate"), self.translateSwitch, self),
            OptionCard(tr("subtitle.opt.split"), self.splitSwitch, self),
            OptionCard(tr("subtitle.opt.language"), self.languageSelect, self),
            OptionCard(tr("subtitle.opt.layout"), self.layoutSelect, self),
            OptionCard(tr("subtitle.opt.prompt"), self.promptChip, self),
        ]
        self.languageCard = cards[3]
        for card in cards:
            options.addWidget(card)
        self.bodyLayout.addLayout(options)

        self.bodyLayout.addStretch(1)
        self.cancelButton = WorkbenchButton(tr("common.cancel"), AppIcon.CANCEL, parent=self)
        self.cancelButton.clicked.connect(self.cancelRequested)
        self.cancelButton.hide()
        self.bodyLayout.addWidget(self.cancelButton)
        self.bodyLayout.addSpacing(10)
        self.primaryButton = WorkbenchButton(
            tr("subtitle.btn.wait_subtitle"), AppIcon.FILE, primary=False, height=48, parent=self
        )
        self.primaryButton.setEnabled(False)
        self.primaryButton.clicked.connect(self.primaryRequested)
        self.bodyLayout.addWidget(self.primaryButton)
        self.syncStyle()

    def setError(self, message: str):
        self.errorCard.setText(message)
        self.errorCard.setVisible(bool(message))

    def setPromptState(self, has_prompt: bool):
        self.promptChip.textLabel.setText(
            tr("subtitle.prompt.set") if has_prompt else tr("subtitle.prompt.unset")
        )

    def setButton(self, text: str, *, icon: AppIcon, primary: bool, enabled: bool):
        self.primaryButton.setText(text)
        self.primaryButton.setIcon(icon)
        self.primaryButton.setPrimary(primary)
        self.primaryButton.setEnabled(enabled)

    def syncStyle(self):
        super().syncStyle()
        if hasattr(self, "errorCard"):
            self.errorCard.syncStyle()


# ---------------------------------------------------------------------------
# 文稿提示对话框
# ---------------------------------------------------------------------------


class PromptDialog(AppDialog):
    """文稿提示：术语表 / 原文稿 / 修正要求，辅助 LLM 校正与翻译。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(tr("subtitle.opt.prompt"), icon=AppIcon.DOCUMENT, parent=parent, width=560)
        self.textEdit = AppTextEdit(parent=self.widget, min_height=360)
        self.textEdit.setPlaceholderText(tr("subtitle.prompt.placeholder"))
        self.textEdit.setPlainText(cfg.custom_prompt_text.value)
        self.bodyLayout.addWidget(self.textEdit)

        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(tr("common.cancel"))
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.confirmButton = self.addFooterButton(tr("common.ok"), kind="accent")
        self.confirmButton.clicked.connect(self._on_confirm)

    def _on_confirm(self):
        cfg.set(cfg.custom_prompt_text, self.textEdit.toPlainText())
        self.done(1)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


class SubtitleInterface(QWidget):
    """字幕优化与翻译页（两栏审校工作台）。"""

    finished = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("SubtitleInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        self.setAcceptDrops(True)

        self.state = PageState.EMPTY
        self.task: Optional[SubtitleTask] = None
        self.subtitle_path: Optional[str] = None
        self._output_path: Optional[str] = None
        # FAILED 细分：配置缺失（→打开配置）还是运行期失败（→重试），决定按钮文案=行为
        self._failure_is_config = False
        self._translated_count = 0
        self._config_signal_connections: list[tuple[Any, Callable]] = []

        self.controller = SubtitleProcessController(self)
        self.model = SubtitleTableModel()
        self._build_ui()
        self._connect_signals()
        self._load_options_from_config()
        self.sideHost.setCollapsed(
            bool(cfg.subtitle_panel_collapsed.value), animate=False
        )
        self._apply_state(PageState.EMPTY)

    def _on_panel_collapsed(self, collapsed: bool):
        if cfg.subtitle_panel_collapsed.value != collapsed:
            cfg.set(cfg.subtitle_panel_collapsed, collapsed)
        self._sync_collapsed_controls()

    def _sync_collapsed_controls(self):
        """折叠态头部控件：展开按钮始终可达；主按钮空态无意义则隐藏。

        运行中且侧栏折叠时，侧栏里的「取消」不可见——把头部主按钮变成「取消」，
        否则用户折叠后就没有任何可取消的入口（对齐转录页 always-visible 取消）。
        """
        collapsed = self.sideHost.isCollapsed()
        head = self.tablePanel.headStartButton
        self.tablePanel.expandButton.setVisible(collapsed)
        if collapsed and self.state == PageState.RUNNING:
            head.setVisible(True)
            head.setText(tr("common.cancel"))
            head.setIcon(AppIcon.CANCEL)
            head.setPrimary(False)
            head.setEnabled(True)
        else:
            head.setVisible(collapsed and self.state != PageState.EMPTY)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        palette = app_palette()
        self.setStyleSheet(
            f"QWidget#SubtitleInterface {{ background: {palette.bg}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 2)
        root.setSpacing(18)
        self.tablePanel = SubtitleTablePanel(self.model, self)
        root.addWidget(self.tablePanel, 1)
        self.sidePanel = ProcessSidePanel(self)
        # 弹性右栏（280-330 自适应）+ 可折叠宿主，折叠状态持久化。
        self.sideHost = CollapsibleSideHost(self.sidePanel, 280, 330, self)
        root.addWidget(self.sideHost, 1)

    def _connect_signals(self):
        self.controller.progressChanged.connect(self._on_progress)
        self.controller.rowsUpdated.connect(self._on_rows_updated)
        self.controller.allUpdated.connect(self._on_all_updated)
        self.controller.completed.connect(self._on_completed)
        self.controller.failed.connect(self._on_failed)
        self.controller.retranslated.connect(self._on_retranslated)
        self.controller.retranslateFailed.connect(self._on_retranslate_failed)

        self.tablePanel.browseRequested.connect(self._browse_file)
        self.tablePanel.saveFormatRequested.connect(self._save_as_format)
        self.tablePanel.openFolderRequested.connect(self._open_folder)
        self.tablePanel.resetRequested.connect(self._reset_to_empty)
        self.tablePanel.table.customContextMenuRequested.connect(self._show_context_menu)
        self.tablePanel.table.setContextMenuPolicy(Qt.CustomContextMenu)  # type: ignore[arg-type]

        self.sidePanel.settingsRequested.connect(self.show_subtitle_settings)
        self.sidePanel.collapseRequested.connect(
            lambda: self.sideHost.setCollapsed(True)
        )
        self.sideHost.collapsedChanged.connect(self._on_panel_collapsed)
        self.tablePanel.headStartButton.clicked.connect(self._on_primary_clicked)
        self.tablePanel.expandButton.clicked.connect(
            lambda: self.sideHost.setCollapsed(False)
        )
        self.sidePanel.promptRequested.connect(self._show_prompt_dialog)
        self.sidePanel.primaryRequested.connect(self._on_primary_clicked)
        self.sidePanel.cancelRequested.connect(self._cancel_processing)

        self.sidePanel.optimizeSwitch.toggled.connect(
            lambda checked: self._set_config_bool(cfg.need_optimize, checked)
        )
        self.sidePanel.translateSwitch.toggled.connect(self._on_translate_toggled)
        self.sidePanel.splitSwitch.toggled.connect(
            lambda checked: self._set_config_bool(cfg.need_split, checked)
        )
        self.sidePanel.languageSelect.currentTextChanged.connect(self._on_language_selected)
        self.sidePanel.layoutSelect.currentTextChanged.connect(self._on_layout_selected)

        self._connect_config_signal(cfg.need_optimize, self._sync_switches_from_config)
        self._connect_config_signal(cfg.need_translate, self._sync_switches_from_config)
        self._connect_config_signal(cfg.need_split, self._sync_switches_from_config)

    def _connect_config_signal(self, option, handler: Callable):
        option.valueChanged.connect(handler)
        self._config_signal_connections.append((option.valueChanged, handler))

    def _disconnect_config_signals(self):
        for signal, handler in self._config_signal_connections:
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass
        self._config_signal_connections.clear()

    # ------------------------------------------------------- config <-> UI

    def _load_options_from_config(self):
        self.sidePanel.optimizeSwitch.setChecked(bool(cfg.need_optimize.value))
        self.sidePanel.translateSwitch.setChecked(bool(cfg.need_translate.value))
        self.sidePanel.splitSwitch.setChecked(bool(cfg.need_split.value))
        self.sidePanel.languageSelect.setItems(
            enum_options(TargetLanguage), enum_label(cfg.target_language.value)
        )
        self.sidePanel.layoutSelect.setItems(
            enum_options(SubtitleLayoutEnum),
            enum_label(cfg.subtitle_layout.value),
        )
        self.sidePanel.languageCard.setVisible(bool(cfg.need_translate.value))
        self.sidePanel.setPromptState(bool(cfg.custom_prompt_text.value.strip()))

    def _set_config_bool(self, option, checked: bool):
        if option.value != checked:
            cfg.set(option, checked)

    def _on_translate_toggled(self, checked: bool):
        self._set_config_bool(cfg.need_translate, checked)
        self.sidePanel.languageCard.setVisible(checked)

    def _sync_switches_from_config(self, _value=None):
        self.sidePanel.optimizeSwitch.setChecked(bool(cfg.need_optimize.value))
        self.sidePanel.translateSwitch.setChecked(bool(cfg.need_translate.value))
        self.sidePanel.splitSwitch.setChecked(bool(cfg.need_split.value))
        self.sidePanel.languageCard.setVisible(bool(cfg.need_translate.value))

    def _on_language_selected(self, language_name: str):
        lang = enum_from_label(TargetLanguage, language_name)
        if lang is not None and cfg.target_language.value != lang:
            cfg.set(cfg.target_language, lang)

    def _on_layout_selected(self, layout_name: str):
        layout = enum_from_label(SubtitleLayoutEnum, layout_name)
        if layout is not None and cfg.subtitle_layout.value != layout:
            cfg.set(cfg.subtitle_layout, layout)

    # --------------------------------------------------------- state machine

    def _apply_state(self, state: PageState, *, error: str = ""):
        self.state = state
        loaded = state != PageState.EMPTY
        count = self.model.rowCount()

        self.tablePanel.stack.setCurrentIndex(1 if loaded else 0)
        self.tablePanel.setHeadState(state)

        bar = self.tablePanel.bottomBar
        bar.setVisible(state != PageState.EMPTY)
        if state == PageState.READY:
            bar.showReady(count)
        elif state == PageState.FAILED:
            bar.showFailed(tr("subtitle.fail.config_missing") if self._failure_is_config else tr("subtitle.fail.process"), error)
        elif state == PageState.DONE:
            bar.showDone(Path(self._output_path).name if self._output_path else "")
        # RUNNING 的底部条由进度回调驱动

        buttons = {
            PageState.EMPTY: (tr("subtitle.btn.wait_subtitle"), AppIcon.FILE, False, False),
            PageState.READY: (tr("subtitle.btn.start"), AppIcon.PLAY, True, True),
            PageState.RUNNING: (tr("subtitle.btn.processing"), AppIcon.SYNC, False, False),
            PageState.DONE: (tr("subtitle.btn.enter_synthesis"), AppIcon.RIGHT_ARROW, True, True),
            # 配置缺失→「打开处理配置」(SETTING)；运行期失败→「重试」(SYNC)，文案与点击行为一致
            PageState.FAILED: (
                (tr("subtitle.btn.open_config"), AppIcon.SETTING, True, True)
                if self._failure_is_config
                else (tr("common.retry"), AppIcon.SYNC, True, True)
            ),
        }
        text, icon, primary, enabled = buttons[state]
        self.sidePanel.setButton(text, icon=icon, primary=primary, enabled=enabled)
        head_button = self.tablePanel.headStartButton
        head_button.setText(text)
        head_button.setIcon(icon)
        head_button.setPrimary(primary)
        head_button.setEnabled(enabled)
        self._sync_collapsed_controls()
        self.sidePanel.cancelButton.setVisible(state == PageState.RUNNING)
        self.sidePanel.setError(error if state == PageState.FAILED else "")
        if state != PageState.RUNNING:
            self.model.set_dim_from(None)

    # ------------------------------------------------------------ file flow

    def _browse_file(self):
        if self.controller.is_processing():
            self._warn_processing()
            return
        formats = " ".join(f"*.{fmt}" for fmt in sorted(_SUBTITLE_FORMATS))
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("subtitle.dialog.choose_file"), "", f"{tr('subtitle.file_filter')} ({formats})"
        )
        if file_path:
            self.load_subtitle_file(file_path)

    def load_subtitle_file(self, file_path: str):
        try:
            asr_data = ASRData.from_subtitle_file(file_path)
        except Exception as exc:
            InfoBar.error(
                tr("subtitle.toast.load_failed"), str(exc), duration=INFOBAR_DURATION_ERROR, parent=self
            )
            return
        self.subtitle_path = file_path
        self.task = None
        self._output_path = None
        self.model.replace_all(asr_data.to_json())
        self.tablePanel.setFile(Path(file_path).name, loaded=True)
        self._apply_state(PageState.READY)

    def _reset_to_empty(self):
        """清空当前字幕、回到初始空态：报错或完成后可一键重来（处理中先取消再清）。"""
        if self.state == PageState.RUNNING:
            return
        dialog = ConfirmDialog(
            tr("subtitle.clear.title"),
            tr("subtitle.clear.body"),
            self,
            confirm_text=tr("subtitle.btn.clear"),
            danger=True,
            icon=AppIcon.DELETE,
        )
        if not dialog.exec():
            return
        self.subtitle_path = None
        self.task = None
        self._output_path = None
        self.model.replace_all({})
        self.tablePanel.setFile(tr("subtitle.no_file"), loaded=False)
        self._apply_state(PageState.EMPTY)

    # ------------------------------------------------------- process flow

    def _preflight_error(self) -> Optional[str]:
        """开始前校验 LLM 配置；不可用时进入“配置未就绪”状态。"""
        task = TaskFactory.create_subtitle_task(file_path=self.subtitle_path or "")
        config = task.subtitle_config
        if config is None:
            return tr("subtitle.error.no_config")
        # 校正、智能断句、LLM 翻译三者任一开启都依赖大模型配置。
        needs_llm = (
            bool(cfg.need_optimize.value)
            or bool(cfg.need_split.value)
            or (
                bool(cfg.need_translate.value)
                and cfg.translator_service.value == TranslatorServiceEnum.OPENAI
            )
        )
        if needs_llm and not (config.api_key and config.base_url and config.llm_model):
            return tr("subtitle.error.need_llm")
        return None

    def _on_primary_clicked(self):
        if self.state in (PageState.READY,):
            self._start_processing()
        elif self.state == PageState.RUNNING:
            # 仅折叠态头部主按钮在运行中会变成「取消」并可点（侧栏主按钮此时禁用）
            self._cancel_processing()
        elif self.state == PageState.FAILED:
            # 文案=行为：配置缺失→打开配置；运行期失败→重试（_start_processing 内部仍会预检）
            if self._failure_is_config:
                self.show_subtitle_settings()
            else:
                self._start_processing()
        elif self.state == PageState.DONE:
            self._enter_synthesis()

    def _start_processing(self):
        if not self.subtitle_path:
            return
        if self.controller.is_processing():
            self._warn_processing()
            return
        # 把表格当前内容（含用户编辑/合并/删除）写回源文件再构建任务
        if self.model.raw():
            ASRData.from_json(self.model.raw()).to_srt(save_path=self.subtitle_path)
        self.task = TaskFactory.create_subtitle_task(file_path=self.subtitle_path)
        self._launch_task()

    def _launch_task(self):
        assert self.task is not None
        error = self._preflight_error()
        if error is not None:
            self._output_path = None
            self._failure_is_config = True  # 预检失败＝配置缺失 → 按钮显示「打开处理配置」
            self._apply_state(PageState.FAILED, error=error)
            return
        # start_processing 在控制器忙时返回 False；先启动，忙则直接返回，避免页面进
        # RUNNING/dim 但线程其实在跑上一个任务（流水线 process() 不查 busy 的竞态）。
        if not self.controller.start_processing(self.task, cfg.custom_prompt_text.value):
            return
        self._translated_count = 0
        self.model.set_dim_from(0)
        self._apply_state(PageState.RUNNING)
        self.tablePanel.bottomBar.showRunning(
            tr("subtitle.status.preparing"), 0, 0, self.model.rowCount()
        )

    def _cancel_processing(self):
        self.controller.cancel()
        self._apply_state(PageState.READY)

    def _on_progress(self, value: int, status: str):
        if self.state == PageState.RUNNING:
            self.tablePanel.bottomBar.showRunning(
                status, value, self._translated_count, self.model.rowCount()
            )

    def _on_rows_updated(self, data: dict):
        self.model.merge_translations(data)
        keys = list(self.model.raw().keys())
        indexes = [keys.index(key) for key in data if key in self.model.raw()]
        if indexes:
            self._translated_count = max(self._translated_count, max(indexes) + 1)
            self.model.set_dim_from(self._translated_count + 1)

    def _on_all_updated(self, data: dict):
        self.model.replace_all(data)

    def _on_completed(self, video_path: str, output_path: str):
        # 不从输出文件重载表格：双语 SRT 重新解析会丢失原文/译文映射，
        # 处理过程中的增量信号已让模型持有正确数据。
        self._output_path = output_path
        if output_path:
            self.tablePanel.setFile(Path(output_path).name, loaded=True)
        self._apply_state(PageState.DONE)
        if self.task and self.task.need_next_task:
            self.finished.emit(video_path, output_path)

    def _on_failed(self, error: str):
        self._failure_is_config = False  # 运行期失败 → 按钮显示「重试」
        self._apply_state(PageState.FAILED, error=error)
        self._output_path = None

    def _on_retranslated(self, result: dict):
        self.model.merge_translations(result)
        self._apply_state(PageState.READY)
        InfoBar.success(
            tr("subtitle.toast.translate_done"),
            tr("subtitle.toast.translate_done_body"),
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self,
        )

    def _on_retranslate_failed(self, error: str):
        self._apply_state(PageState.READY)
        InfoBar.error(
            tr("subtitle.toast.translate_failed"), error, duration=INFOBAR_DURATION_ERROR, parent=self
        )

    def _enter_synthesis(self):
        video = str(self.task.video_path) if self.task and self.task.video_path else ""
        if video and self._output_path:
            self.finished.emit(video, self._output_path)
            return
        InfoBar.info(
            tr("common.tip"),
            tr("subtitle.toast.no_video"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self,
        )

    # ------------------------------------------------------- table actions

    def _selected_rows(self) -> list[int]:
        indexes = self.tablePanel.table.selectedIndexes()
        return sorted({index.row() for index in indexes})

    def _show_context_menu(self, pos):
        rows = self._selected_rows()
        if not rows:
            return
        menu = RoundMenu(parent=self)
        merge_action = Action(FIF.LINK, tr("subtitle.menu.merge"))
        delete_action = Action(FIF.DELETE, tr("common.delete"))
        retranslate_action = Action(FIF.SYNC, tr("subtitle.menu.retranslate"))
        merge_action.setShortcut("Ctrl+M")
        delete_action.setShortcut("Delete")
        retranslate_action.setShortcut("Ctrl+T")
        merge_action.setEnabled(len(rows) > 1)
        retranslate_action.setEnabled(
            bool(cfg.need_translate.value) and not self.controller.is_processing()
        )
        merge_action.triggered.connect(lambda: self._merge_rows(rows))
        delete_action.triggered.connect(lambda: self._delete_rows(rows))
        retranslate_action.triggered.connect(lambda: self._retranslate_rows(rows))
        menu.addAction(merge_action)
        menu.addAction(delete_action)
        menu.addAction(retranslate_action)
        menu.exec(self.tablePanel.table.viewport().mapToGlobal(pos))

    def _merge_rows(self, rows: list[int]):
        self.tablePanel.table.clearSelection()
        self.model.merge_rows(rows)
        if self.state in (PageState.READY, PageState.DONE):
            self.tablePanel.bottomBar.showReady(self.model.rowCount())

    def _delete_rows(self, rows: list[int]):
        self.tablePanel.table.clearSelection()
        self.model.remove_rows(rows)
        if self.state in (PageState.READY, PageState.DONE):
            self.tablePanel.bottomBar.showReady(self.model.rowCount())

    def _retranslate_rows(self, rows: list[int]):
        if not rows or self.controller.is_processing():
            return
        keys = list(self.model.raw().keys())
        selected = {keys[row]: self.model.raw()[keys[row]] for row in rows}
        task = TaskFactory.create_subtitle_task(file_path=self.subtitle_path or "")
        if task.subtitle_config is None:
            return
        file_name = Path(self.subtitle_path).name if self.subtitle_path else ""
        self.controller.retranslate(selected, task.subtitle_config, file_name)
        self.tablePanel.bottomBar.showRunning(
            tr("subtitle.status.retranslating"), 0, 0, len(rows)
        )

    def keyPressEvent(self, event):
        rows = self._selected_rows()
        ctrl = event.modifiers() == Qt.ControlModifier  # type: ignore[attr-defined]
        if ctrl and event.key() == Qt.Key_M and len(rows) > 1:  # type: ignore[attr-defined]
            self._merge_rows(rows)
        elif event.key() == Qt.Key_Delete and rows:  # type: ignore[attr-defined]
            self._delete_rows(rows)
        elif ctrl and event.key() == Qt.Key_T and rows:  # type: ignore[attr-defined]
            if cfg.need_translate.value and not self.controller.is_processing():
                self._retranslate_rows(rows)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # ------------------------------------------------------- save / folder

    def _save_as_format(self, fmt: str):
        if not self.model.raw():
            self._warn_no_subtitle()
            return
        default_name = Path(self.subtitle_path).stem if self.subtitle_path else "subtitle"
        file_path, _ = QFileDialog.getSaveFileName(
            self, tr("subtitle.dialog.save_file"), default_name, f"*.{fmt}"
        )
        if not file_path:
            return
        try:
            asr_data = ASRData.from_json(self.model.raw())
            layout = cfg.subtitle_layout.value
            if file_path.endswith(".ass"):
                style = get_subtitle_style(cfg.subtitle_style_name.value)
                asr_data.to_ass(style, layout, file_path)
            else:
                asr_data.save(file_path, layout=layout)
        except Exception as exc:
            InfoBar.error(
                tr("subtitle.toast.save_failed"), str(exc), duration=INFOBAR_DURATION_ERROR, parent=self
            )
            return
        InfoBar.success(
            tr("subtitle.toast.save_done"),
            tr("subtitle.toast.saved_to") + file_path,
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self,
        )
        reveal_in_explorer(file_path)

    def _open_folder(self):
        # 已知具体文件时在文件管理器中直接选中它
        target = None
        if self._output_path and Path(self._output_path).exists():
            target = Path(self._output_path)
        elif self.subtitle_path:
            target = Path(self.subtitle_path)
        if target is None:
            self._warn_no_subtitle()
            return
        if target.exists():
            reveal_in_explorer(str(target))
        else:
            open_folder(str(target.parent))

    def _show_prompt_dialog(self):
        dialog = PromptDialog(self)
        if dialog.exec_():
            self.sidePanel.setPromptState(bool(cfg.custom_prompt_text.value.strip()))

    def show_subtitle_settings(self):
        """弹出全局字幕处理配置（翻译与优化）。"""
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            window.openSettingsPage("translate")  # type: ignore[attr-defined]

    def _warn_processing(self):
        InfoBar.warning(
            tr("common.warning"),
            tr("subtitle.toast.processing_wait"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self,
        )

    def _warn_no_subtitle(self):
        InfoBar.warning(
            tr("common.warning"),
            tr("subtitle.toast.load_first"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self,
        )

    # --------------------------------------------------------- external API

    def set_task(self, task: SubtitleTask):
        """外部（流水线）注入任务：加载字幕进表格，保留任务配置。"""
        self.task = task
        self.subtitle_path = task.subtitle_path
        self._output_path = None
        try:
            asr_data = ASRData.from_subtitle_file(str(task.subtitle_path))
            self.model.replace_all(asr_data.to_json())
        except Exception as exc:
            InfoBar.error(
                tr("subtitle.toast.load_failed"), str(exc), duration=INFOBAR_DURATION_ERROR, parent=self
            )
            return
        self.tablePanel.setFile(Path(str(task.subtitle_path)).name, loaded=True)
        self._apply_state(PageState.READY)

    def process(self):
        """外部注入任务后直接开始处理（流水线模式）。"""
        if self.task is None:
            return
        self._launch_task()

    # ----------------------------------------------------------- drag&drop

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.tablePanel.dropZone.setDragActive(True)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.tablePanel.dropZone.setDragActive(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.tablePanel.dropZone.setDragActive(False)
        if self.controller.is_processing():
            self._warn_processing()
            return
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if not os.path.isfile(file_path):
                continue
            suffix = Path(file_path).suffix.lstrip(".").lower()
            if suffix in _SUBTITLE_FORMATS:
                self.load_subtitle_file(file_path)
                return
            InfoBar.error(
                tr("subtitle.toast.format_error") + suffix,
                tr("subtitle.toast.supported_formats") + _FORMATS_PILL_TEXT,
                duration=INFOBAR_DURATION_ERROR,
                parent=self,
            )

    def closeEvent(self, event):
        self._disconnect_config_signals()
        self.controller.shutdown()
        super().closeEvent(event)
