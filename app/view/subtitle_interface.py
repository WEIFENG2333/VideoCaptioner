# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PyQt5.QtCore import QAbstractTableModel, Qt, QTime, pyqtSignal, QModelIndex
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeyEvent, QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CommandBar,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    TableView,
    TextEdit,
    TransparentDropDownPushButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.components.SubtitleSettingDialog import SubtitleSettingDialog
from app.config import SUBTITLE_STYLE_PATH
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import (
    OutputSubtitleFormatEnum,
    SubtitleTask,
    SupportedSubtitleFormats,
    TargetLanguageEnum,
)
from app.core.task_factory import TaskFactory
from app.core.utils.get_subtitle_style import get_subtitle_style
from app.core.utils.platform_utils import open_folder
from app.thread.subtitle_thread import SubtitleThread


class SubtitleTableModel(QAbstractTableModel):
    def __init__(self, data: Union[str, Dict[str, Any]] = ""):
        super().__init__()
        self._data: Dict[str, Any] = {}
        if isinstance(data, str):
            self.load_data(data)
        else:
            self._data = data

    def load_data(self, data: str):
        """加载字幕数据"""
        try:
            self._data = json.loads(data)
            self.layoutChanged.emit()
        except json.JSONDecodeError:
            pass

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore
        if not index.isValid() or not self._data:
            return None

        row = index.row()
        col = index.column()
        segment = self._data.get(str(row + 1))

        if not segment:
            return None

        if role == Qt.DisplayRole or role == Qt.EditRole:  # type: ignore
            if col == 0:
                return (
                    QTime(0, 0)
                    .addMSecs(segment["start_time"])
                    .toString("hh:mm:ss.zzz")[:-2]
                )
            elif col == 1:
                return (
                    QTime(0, 0)
                    .addMSecs(segment["end_time"])
                    .toString("hh:mm:ss.zzz")[:-2]
                )
            elif col == 2:
                return segment["original_subtitle"]
            elif col == 3:
                return segment["translated_subtitle"]
        elif role == Qt.TextAlignmentRole:  # type: ignore
            if col in [0, 1]:
                return Qt.AlignCenter  # type: ignore
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:  # type: ignore
        if not index.isValid() or not self._data:
            return False

        if role == Qt.EditRole:  # type: ignore
            row = index.row()
            col = index.column()
            segment = self._data.get(str(row + 1))

            if not segment:
                return False

            if col == 2:
                segment["original_subtitle"] = value
            elif col == 3:
                segment["translated_subtitle"] = value
            else:
                return False

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])  # type: ignore
            return True
        return False

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,  # type: ignore
    ) -> Any:  # type: ignore
        if role == Qt.DisplayRole:  # type: ignore
            if orientation == Qt.Horizontal:  # type: ignore
                return [
                    self.tr("开始时间"),
                    self.tr("结束时间"),
                    self.tr("字幕内容"),
                    (
                        self.tr("翻译字幕")
                        if cfg.need_translate.value
                        else self.tr("优化字幕")
                    ),
                ][section]
            elif orientation == Qt.Vertical:  # type: ignore
                return str(section + 1)  # 显示行号
        elif role == Qt.TextAlignmentRole:  # type: ignore
            return Qt.AlignCenter  # type: ignore  # 居中对齐
        return None

    def rowCount(self, parent: Optional[QModelIndex] = None) -> int:
        return len(self._data)

    def columnCount(self, parent: Optional[QModelIndex] = None) -> int:
        return 4

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags  # type: ignore
        if index.column() in [2, 3]:
            return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable  # type: ignore
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable  # type: ignore

    def update_data(self, new_data: Dict[str, str]) -> None:
        """更新字幕数据"""
        updated_rows = set()

        # 更新内部数据
        for key, value in new_data.items():
            if key in self._data:
                if "||" in value:
                    original_subtitle, translated_subtitle = value.split("||", 1)
                    self._data[key]["original_subtitle"] = original_subtitle
                    self._data[key]["translated_subtitle"] = translated_subtitle
                else:
                    self._data[key]["translated_subtitle"] = value
                row = list(self._data.keys()).index(key)
                updated_rows.add(row)

        # 如果有更新，发出dataChanged信号
        if updated_rows:
            min_row = min(updated_rows)
            max_row = max(updated_rows)
            top_left = self.index(min_row, 2)
            bottom_right = self.index(max_row, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.EditRole])  # type: ignore

    def update_all(self, data: Dict[str, Any]) -> None:
        """更新所有数据"""
        self._data = data
        self.layoutChanged.emit()


class SubtitleInterface(QWidget):
    finished = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task: Optional[SubtitleTask] = None
        self.subtitle_path: Optional[str] = None
        self.custom_prompt_text: str = cfg.custom_prompt_text.value
        self.setAttribute(Qt.WA_DeleteOnClose)  # type: ignore
        self._init_ui()
        self._setup_signals()
        self._update_prompt_button_style()
        self.set_values()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def set_values(self):
        self.layout_button.setText(cfg.subtitle_layout.value)
        self.translate_button.setChecked(cfg.need_translate.value)
        self.optimize_button.setChecked(cfg.need_optimize.value)
        self.target_language_button.setText(cfg.target_language.value.value)
        self.target_language_button.setEnabled(cfg.need_translate.value)

    def _setup_top_layout(self):
        # 创建水平布局
        top_layout = QHBoxLayout()

        # 创建命令栏
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(
            Qt.ToolButtonTextBesideIcon  # type: ignore
        )  # 设置图标和文字并排显示
        top_layout.addWidget(self.command_bar, 1)  # 设置stretch为1，使其尽可能占用空间

        # 创建保存按钮的下拉菜单
        save_menu = RoundMenu(parent=self)
        save_menu.view.setMaxVisibleItems(8)  # 设置菜单最大高度
        for format in OutputSubtitleFormatEnum:
            action = Action(text=format.value)
            action.triggered.connect(
                lambda checked, f=format.value: self.on_save_format_clicked(f)
            )
            save_menu.addAction(action)

        # 添加保存按钮(带下拉菜单)
        save_button = TransparentDropDownPushButton(self.tr("保存"), self, FIF.SAVE)
        save_button.setMenu(save_menu)
        save_button.setFixedHeight(34)
        self.command_bar.addWidget(save_button)

        # 添加字幕排布下拉按钮
        self.layout_button = TransparentDropDownPushButton(
            self.tr("字幕排布"), self, FIF.LAYOUT
        )
        self.layout_button.setFixedHeight(34)
        self.layout_button.setMinimumWidth(125)
        self.layout_menu = RoundMenu(parent=self)
        for layout in ["译文在上", "原文在上", "仅译文", "仅原文"]:
            action = Action(text=layout)
            action.triggered.connect(
                lambda checked,
                layout_value=layout: signalBus.subtitle_layout_changed.emit(
                    layout_value
                )
            )
            self.layout_menu.addAction(action)
        self.layout_button.setMenu(self.layout_menu)
        self.command_bar.addWidget(self.layout_button)

        self.command_bar.addSeparator()

        # 添加字幕优化按钮
        self.optimize_button = Action(
            FIF.EDIT,
            self.tr("字幕校正"),
            triggered=self.on_subtitle_optimization_changed,
            checkable=True,
        )
        self.command_bar.addAction(self.optimize_button)

        # 添加字幕翻译按钮
        self.translate_button = Action(
            FIF.LANGUAGE,
            self.tr("字幕翻译"),
            triggered=self.on_subtitle_translation_changed,
            checkable=True,
        )
        self.command_bar.addAction(self.translate_button)

        # 添加翻译语言选择
        self.target_language_button = TransparentDropDownPushButton(
            self.tr("翻译语言"), self, FIF.LANGUAGE
        )
        self.target_language_button.setFixedHeight(34)
        self.target_language_button.setMinimumWidth(125)
        self.target_language_menu = RoundMenu(parent=self)
        self.target_language_menu.setMaxVisibleItems(10)
        for lang in TargetLanguageEnum:
            action = Action(text=lang.value)
            action.triggered.connect(
                lambda checked,
                lang_value=lang.value: signalBus.target_language_changed.emit(
                    lang_value
                )
            )
            self.target_language_menu.addAction(action)
        self.target_language_button.setMenu(self.target_language_menu)

        self.command_bar.addWidget(self.target_language_button)

        self.command_bar.addSeparator()

        # 添加文稿提示按钮
        self.prompt_button = Action(
            FIF.DOCUMENT, self.tr("文稿提示"), triggered=self.show_prompt_dialog
        )
        self.command_bar.addAction(self.prompt_button)

        # 添加设置按钮
        self.command_bar.addAction(
            Action(FIF.SETTING, "", triggered=self.show_subtitle_settings)
        )

        # 添加视频播放按钮
        # self.command_bar.addAction(Action(FIF.VIDEO, "", triggered=self.show_video_player))

        # 添加打开文件夹按钮
        self.command_bar.addAction(
            Action(FIF.FOLDER, "", triggered=self.on_open_folder_clicked)
        )

        self.command_bar.addSeparator()

        # 添加文件选择按钮
        self.command_bar.addAction(
            Action(FIF.FOLDER_ADD, "", triggered=self.on_file_select)
        )

        # 添加开始按钮到水平布局
        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)
        self.start_button.clicked.connect(
            lambda: self.start_subtitle_optimization(need_create_task=True)
        )
        self.start_button.setFixedHeight(34)
        top_layout.addWidget(self.start_button)

        self.main_layout.addLayout(top_layout)

    def _setup_subtitle_table(self):
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Fixed
        )
        self.subtitle_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Fixed
        )
        self.subtitle_table.setColumnWidth(0, 120)
        self.subtitle_table.setColumnWidth(1, 120)

        # 配置垂直表头
        self.subtitle_table.verticalHeader().setVisible(True)  # 显示垂直表头
        self.subtitle_table.verticalHeader().setDefaultAlignment(
            Qt.AlignCenter  # type: ignore
        )  # 居中对齐
        self.subtitle_table.verticalHeader().setDefaultSectionSize(50)  # 行高
        self.subtitle_table.verticalHeader().setMinimumWidth(20)  # 设置最小宽度

        self.subtitle_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed  # type: ignore
        )
        self.subtitle_table.clicked.connect(self.on_subtitle_clicked)
        # 添加右键菜单支持
        self.subtitle_table.setContextMenuPolicy(Qt.CustomContextMenu)  # type: ignore
        self.subtitle_table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)  # type: ignore

        # 添加取消按钮
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CANCEL)
        self.cancel_button.hide()  # 初始隐藏
        self.cancel_button.clicked.connect(self.cancel_optimization)

        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.bottom_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self) -> None:
        signalBus.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)
        signalBus.target_language_changed.connect(self.on_target_language_changed)
        signalBus.subtitle_optimization_changed.connect(
            self.on_subtitle_optimization_changed
        )
        signalBus.subtitle_translation_changed.connect(
            self.on_subtitle_translation_changed
        )
        # self.subtitle_setting_button.clicked.connect(self.show_subtitle_settings)
        # self.video_player_button.clicked.connect(self.show_video_player)

    def show_prompt_dialog(self) -> None:
        dialog = PromptDialog(self)
        if dialog.exec_():
            self.custom_prompt_text = cfg.custom_prompt_text.value
            self._update_prompt_button_style()

    def _update_prompt_button_style(self) -> None:
        if self.custom_prompt_text.strip():
            green_icon = FIF.DOCUMENT.colored(
                QColor(76, 255, 165), QColor(76, 255, 165)
            )
            self.prompt_button.setIcon(green_icon)
        else:
            self.prompt_button.setIcon(FIF.DOCUMENT)

    def set_task(self, task: SubtitleTask) -> None:
        """设置任务并更新UI"""
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()  # type: ignore
        self.start_button.setEnabled(True)
        self.task = task
        self.subtitle_path = task.subtitle_path
        self.update_info(task)

    def update_info(self, task: SubtitleTask) -> None:
        """更新页面信息"""
        if not self.task:
            return
        original_subtitle_save_path = Path(str(self.task.subtitle_path))
        asr_data = ASRData.from_subtitle_file(str(original_subtitle_save_path))
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))

    def start_subtitle_optimization(self, need_create_task: bool = True) -> None:
        # 检查是否有任务
        if not self.subtitle_path:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return
        self.start_button.setEnabled(False)
        self.progress_bar.reset()
        self.cancel_button.show()

        if need_create_task:
            self.task = TaskFactory.create_subtitle_task(file_path=self.subtitle_path)
        if self.task:
            self.subtitle_optimization_thread = SubtitleThread(self.task)
        self.subtitle_optimization_thread.finished.connect(
            self.on_subtitle_optimization_finished
        )
        self.subtitle_optimization_thread.progress.connect(
            self.on_subtitle_optimization_progress
        )
        self.subtitle_optimization_thread.update.connect(self.update_data)
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        self.subtitle_optimization_thread.error.connect(
            self.on_subtitle_optimization_error
        )
        self.subtitle_optimization_thread.set_custom_prompt_text(
            self.custom_prompt_text
        )
        self.subtitle_optimization_thread.start()
        InfoBar.info(
            self.tr("开始优化"), self.tr("开始优化字幕"), duration=3000, parent=self
        )

    def process(self) -> None:
        """主处理函数"""
        # 检查是否有任务
        self.start_subtitle_optimization(need_create_task=False)

    def on_subtitle_optimization_finished(
        self, video_path: str, output_path: str
    ) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.hide()  # 隐藏取消按钮
        if self.task and self.task.need_next_task:
            self.finished.emit(video_path, output_path)
        InfoBar.success(
            self.tr("优化完成"),
            self.tr("优化完成字幕..."),
            duration=3000,
            position=InfoBarPosition.BOTTOM,
            parent=self.parent(),
        )

    def on_subtitle_optimization_error(self, error: str) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.hide()  # 隐藏取消按钮
        self.progress_bar.error()
        InfoBar.error(self.tr("优化失败"), self.tr(error), duration=20000, parent=self)

    def on_subtitle_optimization_progress(self, value: int, status: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def update_data(self, data):
        self.model.update_data(data)

    def update_all(self, data):
        self.model.update_all(data)

    def remove_widget(self) -> None:
        """隐藏顶部开始按钮和底部进度条"""
        self.start_button.hide()
        for i in range(self.bottom_layout.count()):
            item = self.bottom_layout.itemAt(i)
            if item:
                widget = item.widget()
                if widget:
                    widget.hide()

    def on_file_select(self) -> None:
        # 构建文件过滤器
        subtitle_formats = " ".join(
            f"*.{fmt.value}" for fmt in SupportedSubtitleFormats
        )
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", filter_str
        )
        if file_path:
            self.subtitle_path = file_path
            self.load_subtitle_file(file_path)

    def on_save_format_clicked(self, format: str) -> None:
        """处理保存格式的选择"""
        if not self.subtitle_path:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return

        # 获取保存路径
        default_name = Path(self.subtitle_path).stem
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("保存字幕文件"),
            default_name,  # 使用原文件名作为默认名
            f"{self.tr('字幕文件')} (*.{format})",
        )
        if not file_path:
            return

        try:
            # 转换并保存字幕
            asr_data = ASRData.from_json(self.model._data)
            layout = cfg.subtitle_layout.value

            if file_path.endswith(".ass"):
                style_str = get_subtitle_style(cfg.subtitle_style_name.value)
                asr_data.to_ass(style_str, layout, file_path)
            else:
                asr_data.save(file_path, layout=layout)
            InfoBar.success(
                self.tr("保存成功"),
                self.tr("字幕已保存至:") + file_path,
                duration=3000,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                self.tr("保存失败"),
                self.tr("保存字幕文件失败: ") + str(e),
                duration=5000,
                parent=self,
            )

    def on_open_folder_clicked(self) -> None:
        """打开文件夹按钮点击事件"""
        if not self.task:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return
        if not self.task:
            return
        if self.task.output_path:
            output_path = Path(self.task.output_path)
            target_dir = str(
                output_path.parent
                if output_path.exists()
                else Path(self.task.subtitle_path).parent
            )
        else:
            target_dir = str(Path(self.task.subtitle_path).parent)
        open_folder(target_dir)

    def load_subtitle_file(self, file_path: str) -> None:
        self.subtitle_path = file_path
        asr_data = ASRData.from_subtitle_file(file_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedSubtitleFormats}
            is_supported = file_ext in supported_formats

            if is_supported:
                self.load_subtitle_file(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("成功导入") + os.path.basename(file_path),
                    duration=3000,
                    position=InfoBarPosition.BOTTOM,
                    parent=self,
                )
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext,
                    self.tr("支持的字幕格式:") + str(supported_formats),
                    duration=3000,
                    parent=self,
                )
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()  # type: ignore
        super().closeEvent(event)

    def show_subtitle_settings(self) -> None:
        """显示字幕设置对话框"""
        dialog = SubtitleSettingDialog(self.window())
        dialog.exec_()

    def show_video_player(self) -> None:
        """显示视频播放器窗口"""
        # 创建视频播放器窗口
        from ..components.MyVideoWidget import MyVideoWidget

        self.video_player = MyVideoWidget()
        self.video_player.resize(800, 600)

        def signal_update() -> None:
            if not self.model._data:
                return
            ass_style_name = cfg.subtitle_style_name.value
            ass_style_path = SUBTITLE_STYLE_PATH / f"{ass_style_name}.txt"
            if ass_style_path.exists():
                subtitle_style_srt = ass_style_path.read_text(encoding="utf-8")
            else:
                subtitle_style_srt = None
            temp_srt_path = os.path.join(tempfile.gettempdir(), "temp_subtitle.ass")
            asr_data = ASRData.from_json(self.model._data)
            asr_data.save(
                temp_srt_path,
                layout=cfg.subtitle_layout.value,
                ass_style=subtitle_style_srt or "",
            )
            signalBus.add_subtitle(temp_srt_path)

        # 如果有字幕文件,则添加字幕
        signal_update()

        signalBus.subtitle_layout_changed.connect(signal_update)
        self.model.dataChanged.connect(signal_update)
        self.model.layoutChanged.connect(signal_update)

        # 如果有关联的视频文件,则自动加载
        # Note: SubtitleTask doesn't have file_path attribute
        # if self.task and hasattr(self.task, "file_path") and self.task.file_path:
        #     self.video_player.setVideo(QUrl.fromLocalFile(self.task.file_path))

        self.video_player.show()
        self.video_player.play()

    def on_subtitle_clicked(self, index: QModelIndex) -> None:
        row = index.row()
        item = list(self.model._data.values())[row]
        start_time = item["start_time"]  # 毫秒
        end_time = (
            item["end_time"] - 50
            if item["end_time"] - 50 > start_time
            else item["end_time"]
        )
        signalBus.play_video_segment(start_time, end_time)

    def show_context_menu(self, pos) -> None:
        """显示右键菜单"""
        menu = RoundMenu(parent=self)

        # 获取选中的行
        indexes = self.subtitle_table.selectedIndexes()
        if not indexes:
            return

        # 获取唯一的行号
        rows = sorted(set(index.row() for index in indexes))
        if not rows:
            return

        # 添加菜单项
        # retranslate_action = Action(FIF.SYNC, self.tr("重新翻译"))
        merge_action = Action(FIF.LINK, self.tr("合并"))  # 添加快捷键提示
        # menu.addAction(retranslate_action)
        menu.addAction(merge_action)
        merge_action.setShortcut("Ctrl+M")  # 设置快捷键

        # 设置动作状态
        # retranslate_action.setEnabled(cfg.need_translate.value)
        merge_action.setEnabled(len(rows) > 1)

        # 连接动作信号
        # retranslate_action.triggered.connect(lambda: self.retranslate_selected_rows(rows))
        merge_action.triggered.connect(lambda: self.merge_selected_rows(rows))

        # 显示菜单
        menu.exec(self.subtitle_table.viewport().mapToGlobal(pos))

    def merge_selected_rows(self, rows: List[int]) -> None:
        """合并选中的字幕行"""
        if not rows or len(rows) < 2:
            return

        # 获取选中行的数据
        data = self.model._data
        data_list = list(data.values())

        # 获取第一行和最后一行的时间戳
        first_row = data_list[rows[0]]
        last_row = data_list[rows[-1]]
        start_time = first_row["start_time"]
        end_time = last_row["end_time"]

        # 合并字幕内容
        original_subtitles = []
        translated_subtitles = []
        for row in rows:
            item = data_list[row]
            original_subtitles.append(item["original_subtitle"])
            translated_subtitles.append(item["translated_subtitle"])

        merged_original = " ".join(original_subtitles)
        merged_translated = " ".join(translated_subtitles)

        # 创建新的合并后的字幕项
        merged_item = {
            "start_time": start_time,
            "end_time": end_time,
            "original_subtitle": merged_original,
            "translated_subtitle": merged_translated,
        }

        # 获取所有需要保留的键
        keys = list(data.keys())
        preserved_keys = keys[: rows[0]] + keys[rows[-1] + 1 :]

        # 创建新的数据字典
        new_data = {}
        for i, key in enumerate(preserved_keys):
            if i == rows[0]:
                new_key = f"{len(new_data) + 1}"
                new_data[new_key] = merged_item
            new_key = f"{len(new_data) + 1}"
            new_data[new_key] = data[key]

        # 如果合并的是最后几行，需要确保合并项被添加
        if rows[0] >= len(preserved_keys):
            new_key = f"{len(new_data) + 1}"
            new_data[new_key] = merged_item

        # 更新模型数据
        self.model.update_all(new_data)

        # 显示成功提示
        InfoBar.success(
            self.tr("合并成功"),
            self.tr("已成功合并选中的字幕行"),
            duration=1000,
            parent=self,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """处理键盘事件"""
        # 处理 Ctrl+M 快捷键
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_M:  # type: ignore
            indexes = self.subtitle_table.selectedIndexes()
            if indexes:
                rows = sorted(set(index.row() for index in indexes))
                if len(rows) > 1:
                    self.merge_selected_rows(rows)
            event.accept()
        else:
            super().keyPressEvent(event)

    def cancel_optimization(self) -> None:
        """取消字幕校正"""
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()  # type: ignore
            self.start_button.setEnabled(True)
            self.cancel_button.hide()
            self.progress_bar.setValue(0)
            self.status_label.setText(self.tr("已取消校正"))
            InfoBar.warning(
                self.tr("已取消"), self.tr("字幕校正已取消"), duration=3000, parent=self
            )

    def on_target_language_changed(self, language: str) -> None:
        """处理翻译语言变更"""
        for lang in TargetLanguageEnum:
            if lang.value == language:
                self.target_language_button.setText(lang.value)
                cfg.set(cfg.target_language, lang)
                break

    def on_subtitle_optimization_changed(self, checked: bool) -> None:
        """处理字幕优化开关变更"""
        cfg.set(cfg.need_optimize, checked)
        self.optimize_button.setChecked(checked)

    def on_subtitle_translation_changed(self, checked: bool) -> None:
        """处理字幕翻译开关变更"""
        cfg.set(cfg.need_translate, checked)
        self.translate_button.setChecked(checked)
        # 控制翻译语言选择按钮的启用状态
        self.target_language_button.setEnabled(checked)

    def on_subtitle_layout_changed(self, layout: str) -> None:
        """处理字幕排布变更"""
        cfg.set(cfg.subtitle_layout, layout)
        self.layout_button.setText(layout)


class PromptDialog(MessageBoxBase):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setup_ui()
        self.setWindowTitle(self.tr("文稿提示"))
        # 连接按钮点击事件
        self.yesButton.clicked.connect(self.save_prompt)

    def setup_ui(self) -> None:
        self.titleLabel = BodyLabel(self.tr("文稿提示"), self)

        # 添加文本编辑框
        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(
            self.tr(
                "请输入文稿提示（辅助校正字幕和翻译）\n\n"
                "支持以下内容:\n"
                "1. 术语表 - 专业术语、人名、特定词语的修正对照表\n"
                "示例:\n机器学习->Machine Learning\n马斯克->Elon Musk\n打call->应援\n\n"
                "2. 原字幕文稿 - 视频的原有文稿或相关内容\n"
                "示例: 完整的演讲稿、课程讲义等\n\n"
                "3. 修正要求 - 内容相关的具体修正要求\n"
                "示例: 统一人称代词、规范专业术语等\n\n"
                "注意: 使用小型LLM模型时建议控制文稿在1千字内。对于不同字幕文件,请使用与该字幕相关的文稿提示。"
            )
        )
        self.text_edit.setText(cfg.custom_prompt_text.value)

        self.text_edit.setMinimumWidth(420)
        self.text_edit.setMinimumHeight(380)

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.text_edit)
        self.viewLayout.setSpacing(10)

        # 设置按钮文本
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

    def get_prompt(self) -> str:
        return self.text_edit.toPlainText()

    def save_prompt(self) -> None:
        # 在点击确定按钮时保存提示文本到配置
        prompt_text = self.text_edit.toPlainText()
        cfg.set(cfg.custom_prompt_text, prompt_text)


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough  # type: ignore
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)  # type: ignore
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)  # type: ignore

    app = QApplication(sys.argv)
    window = SubtitleInterface()
    window.show()
    sys.exit(app.exec_())
