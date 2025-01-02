# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from pathlib import Path
from collections import deque
import tempfile

from PyQt5.QtCore import *
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QColor
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QHeaderView, QFileDialog
from qfluentwidgets import ComboBox, PrimaryPushButton, ProgressBar, PushButton, InfoBar, BodyLabel, TableView, ToolButton, TextEdit, MessageBoxBase, RoundMenu, Action, FluentIcon as FIF
from qfluentwidgets import InfoBarPosition
from PyQt5.QtCore import QUrl

from app.config import SUBTITLE_STYLE_PATH

from ..core.thread.subtitle_optimization_thread import SubtitleOptimizationThread
from ..common.config import cfg
from ..core.bk_asr.ASRData import from_subtitle_file, from_json
from ..core.entities import OutputSubtitleFormatEnum, SupportedSubtitleFormats
from ..core.entities import Task
from ..core.thread.create_task_thread import CreateTaskThread
from ..common.signal_bus import signalBus
from ..components.SubtitleSettingDialog import SubtitleSettingDialog


class SubtitleTableModel(QAbstractTableModel):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return 4

    def data(self, index, role):
        if role == Qt.DisplayRole or role == Qt.EditRole:
            row = index.row()
            col = index.column()
            item = list(self._data.values())[row]
            if col == 0:
                return QTime(0, 0, 0).addMSecs(item['start_time']).toString('hh:mm:ss.zzz')
            elif col == 1:
                return QTime(0, 0, 0).addMSecs(item['end_time']).toString('hh:mm:ss.zzz')
            elif col == 2:
                return item['original_subtitle']
            elif col == 3:
                return item['translated_subtitle']
        return None

    def update_data(self, new_data):
        updated_rows = set()

        # 更新内部数据
        for key, value in new_data.items():
            if key in self._data:
                if "\n" in value:
                    original_subtitle, translated_subtitle = value.split("\n", 1)
                    self._data[key]['original_subtitle'] = original_subtitle
                    self._data[key]['translated_subtitle'] = translated_subtitle
                else:
                    self._data[key]['translated_subtitle'] = value
                row = list(self._data.keys()).index(key)
                updated_rows.add(row)

        # 如果有更新，发出dataChanged信号
        if updated_rows:
            min_row = min(updated_rows)
            max_row = max(updated_rows)
            top_left = self.index(min_row, 2)
            bottom_right = self.index(max_row, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.EditRole])

    def update_all(self, data):
        self._data = data
        self.layoutChanged.emit()

    def setData(self, index, value, role):
        if role == Qt.EditRole:
            row = index.row()
            col = index.column()
            item = list(self._data.values())[row]
            if col == 0:
                time = QTime.fromString(value, 'hh:mm:ss.zzz')
                item['start_time'] = QTime(0, 0, 0).msecsTo(time)
            elif col == 1:
                time = QTime.fromString(value, 'hh:mm:ss.zzz')
                item['end_time'] = QTime(0, 0, 0).msecsTo(time)
            elif col == 2:
                item['original_subtitle'] = value
            elif col == 3:
                item['translated_subtitle'] = value
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def flags(self, index):
        return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                headers = [self.tr("开始时间"), self.tr("结束时间"), self.tr("字幕内容"),
                           self.tr("翻译字幕") if cfg.need_translate.value else self.tr("优化字幕")]
                return headers[section]
            elif orientation == Qt.Vertical:
                return str(section + 1)
        return None


class SubtitleOptimizationInterface(QWidget):
    """
    字幕优化界面类

    该类继承自 QWidget，用于创建一个字幕优化界面，包含文件选择、保存、开始处理等功能按钮，
    以及一个字幕表格，用于显示和编辑字幕内容。

    信号:
        finished: 当任务完成时发出的信号，携带任务对象。

    属性:
        task: 当前任务对象。
        custom_prompt_text: 用户自定义的提示文本。

    方法:
        __init__: 初始化界面和信号连接。
        _init_ui: 初始化界面布局。
        _setup_top_layout: 设置顶部布局，包含文件选择、保存等按钮。
        _setup_subtitle_table: 设置字幕表格，包含字幕内容的显示和编辑。
        _setup_bottom_layout: 设置底部布局，包含进度条和状态标签。
        on_subtitle_clicked: 处理字幕表格单元格点击事件。
        show_context_menu: 显示字幕表格的上下文菜单。
    """
    finished = pyqtSignal(Task)

    def __init__(self, parent=None):
        """
        初始化字幕优化界面

        参数:
            parent: 父控件，默认为 None。
        """
        super().__init__(parent)

        #改start
        self.file_queue = deque()  # 队列保存文件路径
        #改end
        self.setAcceptDrops(True)
        self.task = None
        self.custom_prompt_text = cfg.custom_prompt_text.value
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._setup_signals()
        self._update_prompt_button_style()

    def _init_ui(self):
        """
        初始化界面布局
        """
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def _setup_top_layout(self):
        """
        设置顶部布局，包含文件选择、保存等按钮
        """
        self.top_layout = QHBoxLayout()

        # =========左侧布局==========
        self.left_layout = QHBoxLayout()
        self.save_button = PushButton(self.tr("保存"), self, icon=FIF.SAVE)

        # 字幕格式下拉框
        self.format_combobox = ComboBox(self)
        self.format_combobox.addItems([format.value for format in OutputSubtitleFormatEnum])

        # 添加字幕排布下拉框
        self.layout_combobox = ComboBox(self)
        self.layout_combobox.addItems(["译文在上", "原文在上", "仅译文", "仅原文"])
        self.layout_combobox.setCurrentText(cfg.subtitle_layout.value)

        self.left_layout.addWidget(self.save_button)
        self.left_layout.addWidget(self.format_combobox)
        self.left_layout.addWidget(self.layout_combobox)

        # =========右侧布局==========
        self.right_layout = QHBoxLayout()

        # 添加批量翻译按钮
        self.batch_translate_button = PushButton(self.tr("批量翻译"), self, icon=FIF.FOLDER_ADD)


        # 添加打开文件夹按钮和文件选择按钮
        self.open_folder_button = ToolButton(FIF.FOLDER, self)
        self.file_select_button = PushButton(self.tr("选择SRT文件"), self, icon=FIF.FOLDER_ADD)
        self.prompt_button = PushButton(self.tr("文稿提示"), self, icon=FIF.DOCUMENT)
        # 添加字幕设置按钮
        self.subtitle_setting_button = ToolButton(FIF.SETTING, self)
        self.subtitle_setting_button.setFixedSize(32, 32)

        # 添加视频播放按钮
        self.video_player_button = ToolButton(FIF.VIDEO, self)
        self.video_player_button.setFixedSize(32, 32)
        self.video_player_button.hide()

        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)

        self.right_layout.addWidget(self.open_folder_button)
        self.right_layout.addWidget(self.file_select_button)

        #改start
        # 将批量翻译按钮添加到右侧布局
        self.right_layout.addWidget(self.batch_translate_button)
        #改end

        self.right_layout.addWidget(self.prompt_button)
        self.right_layout.addWidget(self.subtitle_setting_button)
        self.right_layout.addWidget(self.video_player_button)
        self.right_layout.addWidget(self.start_button)

        self.top_layout.addLayout(self.left_layout)
        self.top_layout.addStretch(1)
        self.top_layout.addLayout(self.right_layout)

        self.main_layout.addLayout(self.top_layout)

    def _setup_subtitle_table(self):
        """
        设置字幕表格，包含字幕内容的显示和编辑
        """
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.subtitle_table.setColumnWidth(0, 120)
        self.subtitle_table.setColumnWidth(1, 120)
        self.subtitle_table.verticalHeader().setDefaultSectionSize(50)
        self.subtitle_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.subtitle_table.clicked.connect(self.on_subtitle_clicked)
        # 添加右键菜单支持
        self.subtitle_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.subtitle_table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        """
        设置底部布局，包含进度条和状态标签
        """
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)

        # 设置状态标签的最小宽度为 100，并居中对齐
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)

        # 添加取消按钮
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CANCEL)
        # 初始隐藏取消按钮
        self.cancel_button.hide()
        # 将取消按钮的 clicked 信号连接到 cancel_optimization 方法
        self.cancel_button.clicked.connect(self.cancel_optimization)

        # 将进度条添加到底部布局中，并设置其拉伸因子为 1
        self.bottom_layout.addWidget(self.progress_bar, 1)
        # 将状态标签添加到底部布局中
        self.bottom_layout.addWidget(self.status_label)
        # 将取消按钮添加到底部布局中
        self.bottom_layout.addWidget(self.cancel_button)
        # 将底部布局添加到主布局中
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self):
        """
        设置信号连接

        该方法将各个按钮的 clicked 信号连接到相应的处理方法。
        """
        # 将开始按钮的 clicked 信号连接到 process 方法
        self.start_button.clicked.connect(self.process)
        # 将文件选择按钮的 clicked 信号连接到 on_file_select 方法
        self.file_select_button.clicked.connect(self.on_file_select)

        # 改start
        # 将批量翻译按钮的 clicked 信号连接到 on_batch_file_select 方法
        self.batch_translate_button.clicked.connect(self.on_batch_file_select)
        #改end

        # 将保存按钮的 clicked 信号连接到 on_save_clicked 方法
        self.save_button.clicked.connect(self.on_save_clicked)
        # 将打开文件夹按钮的 clicked 信号连接到 on_open_folder_clicked 方法
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)
        # 将提示按钮的 clicked 信号连接到 show_prompt_dialog 方法
        self.prompt_button.clicked.connect(self.show_prompt_dialog)
        # 将字幕布局下拉框的 currentTextChanged 信号连接到 on_subtitle_layout_changed 方法
        self.layout_combobox.currentTextChanged.connect(signalBus.on_subtitle_layout_changed)
        # 将信号总线的 subtitle_layout_changed 信号连接到 on_subtitle_layout_changed 方法
        signalBus.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)
        # 将字幕设置按钮的 clicked 信号连接到 show_subtitle_settings 方法
        self.subtitle_setting_button.clicked.connect(self.show_subtitle_settings)
        # 将视频播放按钮的 clicked 信号连接到 show_video_player 方法
        self.video_player_button.clicked.connect(self.show_video_player)

    def show_prompt_dialog(self):
        """
        显示提示对话框

        该方法创建一个 PromptDialog 对话框，并在用户点击确定后更新自定义提示文本。
        """
        # 创建一个提示对话框
        dialog = PromptDialog(self)
        # 执行对话框，如果用户点击确定
        if dialog.exec_():
            # 更新自定义提示文本
            self.custom_prompt_text = cfg.custom_prompt_text.value
            # 更新提示按钮的样式
            self._update_prompt_button_style()

    def _update_prompt_button_style(self):
        """
        更新提示按钮的样式

        该方法根据自定义提示文本是否为空来更新提示按钮的图标。
        """
        # 如果自定义提示文本不为空
        if self.custom_prompt_text.strip():
            # 创建一个绿色的文档图标
            green_icon = FIF.DOCUMENT.colored(QColor(76,255,165), QColor(76,255,165))
            # 设置提示按钮的图标为绿色文档图标
            self.prompt_button.setIcon(green_icon)
        else:
            # 设置提示按钮的图标为默认的文档图标
            self.prompt_button.setIcon(FIF.DOCUMENT)

    def on_subtitle_layout_changed(self, layout: str):
        """
        处理字幕布局更改事件

        该方法更新配置中的字幕布局，并更新下拉框的当前文本。

        参数:
            layout: 新的字幕布局。
        """
        # 更新配置中的字幕布局
        cfg.subtitle_layout.value = layout
        # 更新下拉框的当前文本为新的布局
        self.layout_combobox.setCurrentText(layout)

    def create_task(self, file_path):
        """
        创建任务

        该方法根据文件路径创建一个字幕优化任务。

        参数:
            file_path: 字幕文件的路径。

        返回:
            创建的任务对象。
        """
        # 创建一个字幕优化任务
        self.task = CreateTaskThread.create_subtitle_optimization_task(file_path)
        # 返回创建的任务对象
        return self.task

    def set_task(self, task: Task):
        """
        设置任务并更新UI

        该方法设置当前任务，并更新界面上的按钮状态和信息显示。

        参数:
            task: 要设置的任务对象。
        """
        # 如果已经存在字幕优化线程，停止它
        if hasattr(self, 'subtitle_optimization_thread'):
            self.subtitle_optimization_thread.stop()
        # 启用开始按钮和文件选择按钮
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        # 设置当前任务
        self.task = task
        # 更新任务信息
        self.update_info(task)

    def update_info(self, task: Task):
        """更新页面信息"""
        # 将任务的原始字幕保存路径转换为 Path 对象
        original_subtitle_save_path = Path(self.task.original_subtitle_save_path)
        # 从字幕文件中读取数据
        asr_data = from_subtitle_file(original_subtitle_save_path)
        # 将读取的数据转换为 JSON 格式并保存到模型中
        self.model._data = asr_data.to_json()
        # 发射布局更改信号
        self.model.layoutChanged.emit()
        # 更新状态标签文本
        self.status_label.setText(self.tr("已加载文件"))

    def process(self):
        """主处理函数"""
        # 检查是否有任务
        if not self.task:
            # 如果没有任务，显示警告信息
            InfoBar.warning(
                self.tr("警告"),
                self.tr("请先加载字幕文件"),
                duration=3000,
                parent=self
            )
            return

        # 禁用开始按钮和文件选择按钮
        self.start_button.setEnabled(False)
        self.file_select_button.setEnabled(False)
        # 重置进度条
        self.progress_bar.reset()
        # 显示取消按钮
        self.cancel_button.show()
        # 更新任务配置
        self._update_task_config()

        # 创建字幕优化线程
        self.subtitle_optimization_thread = SubtitleOptimizationThread(self.task)
        # 连接优化完成信号到相应的处理方法
        self.subtitle_optimization_thread.finished.connect(self.on_subtitle_optimization_finished)
        # 连接优化进度信号到相应的处理方法
        self.subtitle_optimization_thread.progress.connect(self.on_subtitle_optimization_progress)
        # 连接更新数据信号到相应的处理方法
        self.subtitle_optimization_thread.update.connect(self.update_data)
        # 连接更新所有数据信号到相应的处理方法
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        # 连接优化错误信号到相应的处理方法
        self.subtitle_optimization_thread.error.connect(self.on_subtitle_optimization_error)
        # 设置自定义提示文本
        self.subtitle_optimization_thread.set_custom_prompt_text(self.custom_prompt_text)
        # 启动线程
        self.subtitle_optimization_thread.start()
        # 显示优化开始信息
        InfoBar.info(self.tr("开始优化"), self.tr("开始优化字幕"), duration=3000, parent=self)

    def _update_task_config(self):
        """更新任务配置"""
        # 更新任务的需要优化标志
        self.task.need_optimize = cfg.need_optimize.value
        # 更新任务的需要翻译标志
        self.task.need_translate = cfg.need_translate.value
        # 更新任务的 API 密钥
        self.task.api_key = cfg.api_key.value
        # 更新任务的 API 基础 URL
        self.task.base_url = cfg.api_base.value
        # 更新任务的 LLM 模型
        self.task.llm_model = cfg.model.value
        # 更新任务的批量大小
        self.task.batch_size = cfg.batch_size.value
        # 更新任务的线程数
        self.task.thread_num = cfg.thread_num.value
        # 更新任务的目标语言
        self.task.target_language = cfg.target_language.value.value
        # 更新任务的字幕布局
        self.task.subtitle_layout = cfg.subtitle_layout.value
        # 更新任务的需要分割标志
        self.task.need_split = cfg.need_split.value
        # 更新任务的中文最大词数
        self.task.max_word_count_cjk = cfg.max_word_count_cjk.value
        # 更新任务的英文最大词数
        self.task.max_word_count_english = cfg.max_word_count_english.value

    def on_subtitle_optimization_finished(self, task: Task):
        """处理字幕优化完成事件"""
        # 启用开始按钮和文件选择按钮
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        # 隐藏取消按钮
        self.cancel_button.hide()
        # 如果任务状态为待处理，发射完成信号
        if self.task.status == Task.Status.PENDING:
            self.finished.emit(task)
        # 显示优化完成信息
        InfoBar.success(
            self.tr("优化完成"),
            self.tr("优化完成字幕..."),
            duration=3000,
            position=InfoBarPosition.BOTTOM,
            parent=self.parent()
        )
        #改start
        if self.file_queue:
            self._process_next_file()
            self.process()  # 调用处理逻辑

        #改end


    def on_subtitle_optimization_error(self, error):
        """处理字幕优化错误事件"""
        # 启用开始按钮和文件选择按钮
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        # 隐藏取消按钮
        self.cancel_button.hide()
        # 进度条显示错误状态
        self.progress_bar.error()
        # 显示优化错误信息
        InfoBar.error(self.tr("优化失败"), self.tr(error), duration=20000, parent=self)

    def on_subtitle_optimization_progress(self, value, status):
        """处理字幕优化进度事件"""
        # 更新进度条的值
        self.progress_bar.setValue(value)
        # 更新状态标签的文本
        self.status_label.setText(status)


    def update_data(self, data):
        self.model.update_data(data)

    def update_all(self, data):
        self.model.update_all(data)

    def remove_widget(self):
        """隐藏顶部开始按钮和底部进度条"""
        self.start_button.hide()
        for i in range(self.bottom_layout.count()):
            widget = self.bottom_layout.itemAt(i).widget()
            if widget:
                widget.hide()

    def on_file_select(self):
        """
        处理文件选择按钮的点击事件

        当用户点击文件选择按钮时，此方法会被调用。它会打开一个文件对话框，
        让用户选择一个字幕文件。如果用户选择了一个文件，它会将文件路径设置
        到文件选择按钮的属性中，并加载这个字幕文件。

        注释：
        - 构建文件过滤器：使用 SupportedSubtitleFormats 中的值构建一个文件过滤器，
          只显示支持的字幕文件格式。
        - 获取文件路径：使用 QFileDialog.getOpenFileName 方法打开文件对话框，
          并获取用户选择的文件路径。
        - 加载字幕文件：如果用户选择了一个文件，调用 load_subtitle_file 方法加载这个文件。
        """
        # 构建文件过滤器
        subtitle_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedSubtitleFormats)
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"
        # # 修改mark s
        # file_paths, _ = QFileDialog.getOpenFileNames(self, self.tr("选择字幕文件"), "", filter_str)
        # if file_paths:
        #     for file_path in file_paths:
        #         self.file_select_button.setProperty("selected_file", file_path)
        #         self.load_subtitle_file(file_path)
        #         print(file_path)
        # # 修改mark e
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("选择字幕文件"), "", filter_str)
        if file_path:
            self.file_select_button.setProperty("selected_file", file_path)
            self.load_subtitle_file(file_path)
            # print(file_path)

    #改start
    def on_batch_file_select(self):
        """
        处理批量文件选择按钮的点击事件

        当用户点击批量文件选择按钮时，此方法会被调用。它会打开一个文件对话框，
        让用户选择多个字幕文件。如果用户选择了多个文件，它会将这些文件路径设置
        到批量文件选择按钮的属性中，并加载这些字幕文件。

        注释：
        - 构建文件过滤器：使用 SupportedSubtitleFormats 中的值构建一个文件过滤器，
          只显示支持的字幕文件格式。
        - 获取文件路径：使用 QFileDialog.getOpenFileNames 方法打开文件对话框，
          并获取用户选择的文件路径。
        - 加载字幕文件：如果用户选择了多个文件，调用 load_subtitle_file 方法加载这些文件。
        """
        # 构建文件过滤器
        subtitle_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedSubtitleFormats)
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"
        file_paths, _ = QFileDialog.getOpenFileNames(self, self.tr("选择字幕文件"), "", filter_str)
        if file_paths:
            # for file_path in file_paths:
            #     self.file_select_button.setProperty("selected_file", file_path)
            #     self.load_subtitle_file(file_path)
            #     self.process()
            self.file_queue.extend(file_paths)  # 将文件路径加入队列
            self._process_next_file()  # 开始处理队列中的第一个文件

    def _process_next_file(self):
        """处理队列中的下一个文件"""
        if not self.file_queue:  # 如果队列为空
            return
        file_path = self.file_queue.popleft()  # 从队列中取出一个文件路径
        self.load_subtitle_file(file_path)  # 加载文件


    # 改end


    def on_save_clicked(self):
        # 检查是否有任务
        if not self.task:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("请先加载字幕文件"),
                duration=3000,
                parent=self
            )
            return

        # 获取保存路径
        default_name = os.path.splitext(os.path.basename(self.task.original_subtitle_save_path))[0]
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("保存字幕文件"),
            default_name,  # 使用原文件名作为默认名
            f"{self.tr('字幕文件')} (*.{self.format_combobox.currentText()})"
        )
        if not file_path:
            return

        try:
            # 转换并保存字幕
            asr_data = from_json(self.model._data)
            layout = cfg.subtitle_layout.value

            if file_path.endswith(".ass"):
                style_str = self.task.subtitle_style_srt
                asr_data.to_ass(style_str, layout, file_path)
            else:
                asr_data.save(file_path, layout=layout)
            InfoBar.success(
                self.tr("保存成功"),
                self.tr(f"字幕已保存至:") + file_path,
                duration=3000,
                parent=self
            )
        except Exception as e:
            InfoBar.error(
                self.tr("保存失败"),
                self.tr("保存字幕文件失败: ") + str(e),
                duration=5000,
                parent=self
            )

    def on_open_folder_clicked(self):
        if not self.task:
            InfoBar.warning(self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self)
            return
        if sys.platform == "win32":
            os.startfile(os.path.dirname(self.task.original_subtitle_save_path))
        elif sys.platform == "darwin":  # macOS
            subprocess.run(["open", os.path.dirname(self.task.original_subtitle_save_path)])
        else:  # Linux
            subprocess.run(["xdg-open", os.path.dirname(self.task.original_subtitle_save_path)])

    def load_subtitle_file(self, file_path):
        """
        加载字幕文件并更新界面

        参数:
            file_path: 字幕文件的路径。

        注释：
        - 创建任务：根据文件路径创建一个字幕优化任务。
        - 加载数据：从字幕文件中加载数据，并将其转换为 JSON 格式。
        - 更新模型：将加载的数据设置到模型中，并触发布局更改信号。
        - 更新状态标签：设置状态标签文本为“已加载文件”。
        """
        self.create_task(file_path)
        asr_data = from_subtitle_file(file_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))


    def dragEnterEvent(self, event: QDragEnterEvent):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedSubtitleFormats}
            is_supported = file_ext in supported_formats

            if is_supported:
                self.file_select_button.setProperty("selected_file", file_path)
                self.load_subtitle_file(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr(f"成功导入") + os.path.basename(file_path),
                    duration=3000,
                    parent=self
                )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    self.tr(f"支持的字幕格式:") + str(supported_formats),
                    duration=3000,
                    parent=self
                )
        event.accept()

    def closeEvent(self, event):
        if hasattr(self, 'subtitle_optimization_thread'):
            self.subtitle_optimization_thread.stop()
        super().closeEvent(event)

    def show_subtitle_settings(self):
        """ 显示字幕设置对话框 """
        dialog = SubtitleSettingDialog(self.window())
        dialog.exec_()

    def show_video_player(self):
        """显示视频播放器窗口"""
        # 创建视频播放器窗口
        from ..components.MyVideoWidget import MyVideoWidget
        self.video_player = MyVideoWidget()
        self.video_player.resize(800, 600)

        def signal_update():
            if not self.model._data:
                return
            ass_style_name = cfg.subtitle_style_name.value
            ass_style_path = SUBTITLE_STYLE_PATH / f"{ass_style_name}.txt"
            if ass_style_path.exists():
                subtitle_style_srt = ass_style_path.read_text(encoding="utf-8")
            else:
                subtitle_style_srt = None
            temp_srt_path = os.path.join(tempfile.gettempdir(), "temp_subtitle.ass")
            asr_data = from_json(self.model._data)
            asr_data.save(temp_srt_path, layout=cfg.subtitle_layout.value, ass_style=subtitle_style_srt)
            signalBus.add_subtitle(temp_srt_path)

        # 如果有字幕文件,则添加字幕
        signal_update()

        signalBus.subtitle_layout_changed.connect(signal_update)
        self.model.dataChanged.connect(signal_update)
        self.model.layoutChanged.connect(signal_update)

        # 如果有关联的视频文件,则自动加载
        if self.task and hasattr(self.task, 'file_path') and self.task.file_path:
            self.video_player.setVideo(QUrl.fromLocalFile(self.task.file_path))

        self.video_player.show()
        self.video_player.play()

    def on_subtitle_clicked(self, index):
        row = index.row()
        item = list(self.model._data.values())[row]
        start_time = item['start_time']  # 毫秒
        end_time = item['end_time'] - 50 if item['end_time'] - 50 > start_time else item['end_time']
        signalBus.play_video_segment(start_time, end_time)

    def show_context_menu(self, pos):
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

    def merge_selected_rows(self, rows):
        """合并选中的字幕行"""
        if not rows or len(rows) < 2:
            return

        # 获取选中行的数据
        data = self.model._data
        data_list = list(data.values())

        # 获取第一行和最后一行的时间戳
        first_row = data_list[rows[0]]
        last_row = data_list[rows[-1]]
        start_time = first_row['start_time']
        end_time = last_row['end_time']

        # 合并字幕内容
        original_subtitles = []
        translated_subtitles = []
        for row in rows:
            item = data_list[row]
            original_subtitles.append(item['original_subtitle'])
            translated_subtitles.append(item['translated_subtitle'])

        merged_original = ' '.join(original_subtitles)
        merged_translated = ' '.join(translated_subtitles)

        # 创建新的合并后的字幕项
        merged_item = {
            'start_time': start_time,
            'end_time': end_time,
            'original_subtitle': merged_original,
            'translated_subtitle': merged_translated
        }

        # 获取所有需要保留的键
        keys = list(data.keys())
        preserved_keys = keys[:rows[0]] + keys[rows[-1]+1:]

        # 创建新的数据字典
        new_data = {}
        for i, key in enumerate(preserved_keys):
            if i == rows[0]:
                new_key = f"{len(new_data)+1}"
                new_data[new_key] = merged_item
            new_key = f"{len(new_data)+1}"
            new_data[new_key] = data[key]

        # 如果合并的是最后几行，需要确保合并项被添加
        if rows[0] >= len(preserved_keys):
            new_key = f"{len(new_data)+1}"
            new_data[new_key] = merged_item

        # 更新模型数据
        self.model.update_all(new_data)

        # 显示成功提示
        InfoBar.success(
            self.tr("合并成功"),
            self.tr("已成功合并选中的字幕行"),
            duration=3000,
            parent=self
        )

    def keyPressEvent(self, event):
        """处理键盘事件"""
        # 处理 Ctrl+M 快捷键
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_M:
            indexes = self.subtitle_table.selectedIndexes()
            if indexes:
                rows = sorted(set(index.row() for index in indexes))
                if len(rows) > 1:
                    self.merge_selected_rows(rows)
            event.accept()
        else:
            super().keyPressEvent(event)

    def cancel_optimization(self):
        """取消字幕优化"""
        if hasattr(self, 'subtitle_optimization_thread'):
            self.subtitle_optimization_thread.stop()
            self.start_button.setEnabled(True)
            self.file_select_button.setEnabled(True)
            self.cancel_button.hide()
            self.progress_bar.setValue(0)
            self.status_label.setText(self.tr("已取消优化"))
            InfoBar.warning(
                self.tr("已取消"),
                self.tr("字幕优化已取消"),
                duration=3000,
                parent=self
            )

class PromptDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.setWindowTitle(self.tr('文稿提示'))
        # 连接按钮点击事件
        self.yesButton.clicked.connect(self.save_prompt)
        
    def setup_ui(self):
        self.titleLabel = BodyLabel(self.tr('文稿提示'), self)
        
        # 添加文本编辑框
        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(
            self.tr("请输入文稿提示（优化字幕或者翻译字幕的提示参考）")
        )
        self.text_edit.setText(cfg.custom_prompt_text.value)
        
        self.text_edit.setMinimumWidth(400)
        self.text_edit.setMinimumHeight(200)
        
        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.text_edit)
        self.viewLayout.setSpacing(10)
        
        # 设置按钮文本
        self.yesButton.setText(self.tr('确定'))
        self.cancelButton.setText(self.tr('取消'))

    def get_prompt(self):
        return self.text_edit.toPlainText()

    def save_prompt(self):
        # 在点击确定按钮时保存提示文本到配置
        prompt_text = self.text_edit.toPlainText()
        cfg.set(cfg.custom_prompt_text, prompt_text)
        print(cfg.custom_prompt_text.value)


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = SubtitleOptimizationInterface()
    window.show()
    sys.exit(app.exec_())

