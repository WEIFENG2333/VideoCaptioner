# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from pathlib import Path

from PyQt5.QtCore import *
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QColor
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QHeaderView, QFileDialog
from qfluentwidgets import ComboBox, PrimaryPushButton, ProgressBar, PushButton, InfoBar, BodyLabel, TableView, ToolButton, TextEdit, MessageBoxBase
from qfluentwidgets import FluentIcon as FIF, InfoBarPosition

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
    finished = pyqtSignal(Task)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task = None
        self.custom_prompt_text = ""  # 添加提示文本属性
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._setup_signals()
        self._update_prompt_button_style()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def _setup_top_layout(self):
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
        self.open_folder_button = ToolButton(FIF.FOLDER, self)
        self.file_select_button = PushButton(self.tr("选择SRT文件"), self, icon=FIF.FOLDER_ADD)
        self.prompt_button = PushButton(self.tr("文稿提示"), self, icon=FIF.DOCUMENT)
        # 添加字幕设置按钮
        self.subtitle_setting_button = ToolButton(FIF.SETTING, self)
        self.subtitle_setting_button.setFixedSize(32, 32)
        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)
        
        self.right_layout.addWidget(self.open_folder_button)
        self.right_layout.addWidget(self.file_select_button)
        self.right_layout.addWidget(self.prompt_button)
        self.right_layout.addWidget(self.subtitle_setting_button)
        self.right_layout.addWidget(self.start_button)

        self.top_layout.addLayout(self.left_layout)
        self.top_layout.addStretch(1)
        self.top_layout.addLayout(self.right_layout)

        self.main_layout.addLayout(self.top_layout)

    def _setup_subtitle_table(self):
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
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self):
        self.start_button.clicked.connect(self.process)
        self.file_select_button.clicked.connect(self.on_file_select)
        self.save_button.clicked.connect(self.on_save_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)
        self.prompt_button.clicked.connect(self.show_prompt_dialog)
        self.layout_combobox.currentTextChanged.connect(signalBus.on_subtitle_layout_changed)
        signalBus.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)
        self.subtitle_setting_button.clicked.connect(self.show_subtitle_settings)

    def show_prompt_dialog(self):
        dialog = PromptDialog(self, self.custom_prompt_text)
        if dialog.exec_():  # 注意这里改用MessageBoxBase.Accepted
            self.custom_prompt_text = dialog.get_prompt()
            self._update_prompt_button_style()

    def _update_prompt_button_style(self):
        if self.custom_prompt_text.strip():
            green_icon = FIF.DOCUMENT.colored(QColor(76,255,165), QColor(76,255,165))
            self.prompt_button.setIcon(green_icon)
        else:
            self.prompt_button.setIcon(FIF.DOCUMENT)

    def on_subtitle_layout_changed(self, layout: str):
        cfg.subtitle_layout.value = layout
        self.layout_combobox.setCurrentText(layout)

    def create_task(self, file_path):
        """创建任务"""
        self.task = CreateTaskThread.create_subtitle_optimization_task(file_path)

    def set_task(self, task: Task):
        """设置任务并更新UI"""
        if hasattr(self, 'subtitle_optimization_thread'):
            self.subtitle_optimization_thread.stop()
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        self.task = task
        self.update_info(task)

    def update_info(self, task: Task):
        """更新页面信息"""
        original_subtitle_save_path = Path(self.task.original_subtitle_save_path)
        asr_data = from_subtitle_file(original_subtitle_save_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))
        self.custom_prompt_text = ""
        self._update_prompt_button_style()

    def process(self):
        """主处理函数"""
        self.start_button.setEnabled(False)
        self.file_select_button.setEnabled(False)
        self.progress_bar.resume()
        self._update_task_config()

        self.subtitle_optimization_thread = SubtitleOptimizationThread(self.task)
        self.subtitle_optimization_thread.finished.connect(self.on_subtitle_optimization_finished)
        self.subtitle_optimization_thread.progress.connect(self.on_subtitle_optimization_progress)
        self.subtitle_optimization_thread.update.connect(self.update_data)
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        self.subtitle_optimization_thread.error.connect(self.on_subtitle_optimization_error)
        self.subtitle_optimization_thread.set_custom_prompt_text(self.custom_prompt_text)
        self.subtitle_optimization_thread.start()
        InfoBar.info(self.tr("开始优化"), self.tr("开始优化字幕"), duration=3000, parent=self)

    def _update_task_config(self):
        self.task.need_optimize = cfg.need_optimize.value
        self.task.need_translate = cfg.need_translate.value
        self.task.api_key = cfg.api_key.value
        self.task.base_url = cfg.api_base.value
        self.task.llm_model = cfg.model.value
        self.task.batch_size = cfg.batch_size.value
        self.task.thread_num = cfg.thread_num.value
        self.task.target_language = cfg.target_language.value.value
        self.task.subtitle_layout = cfg.subtitle_layout.value
        self.task.need_split = cfg.need_split.value
        self.task.max_word_count_cjk = cfg.max_word_count_cjk.value
        self.task.max_word_count_english = cfg.max_word_count_english.value

    def on_subtitle_optimization_finished(self, task: Task):
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        if self.task.status == Task.Status.PENDING:
            self.finished.emit(task)
        InfoBar.success(
            self.tr("优化完成"),
            self.tr("优化完成字幕..."),
            duration=3000,
            position=InfoBarPosition.BOTTOM,
            parent=self.parent()
        )
    
    def on_subtitle_optimization_error(self, error):
        self.start_button.setEnabled(True)
        self.file_select_button.setEnabled(True)
        self.progress_bar.error()
        InfoBar.error(self.tr("优化失败"), self.tr(error), duration=20000, parent=self)

    def on_subtitle_optimization_progress(self, value, status):
        self.progress_bar.setValue(value)
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
        # 构建文件过滤器
        subtitle_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedSubtitleFormats)
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"

        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("选择字幕文件"), "", filter_str)
        if file_path:
            self.file_select_button.setProperty("selected_file", file_path)
            self.load_subtitle_file(file_path)

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
        self.create_task(file_path)
        asr_data = from_subtitle_file(file_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))
        self.custom_custom_prompt_text = ""
        self._update_prompt_button_style()

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

class PromptDialog(MessageBoxBase):
    def __init__(self, parent=None, current_prompt=""):
        super().__init__(parent)
        self.custom_prompt_text = current_prompt
        self.setup_ui()
        self.setWindowTitle(self.tr('文稿提示'))
        
    def setup_ui(self):
        self.titleLabel = BodyLabel(self.tr('文稿提示'), self)
        
        # 添加文本编辑框
        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("请输入文稿提示（优化字幕或者翻译字幕的提示参考）"))
        self.text_edit.setText(self.custom_prompt_text)
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


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = SubtitleOptimizationInterface()
    window.show()
    sys.exit(app.exec_())

