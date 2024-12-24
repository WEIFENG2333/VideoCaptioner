import datetime
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock

from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QMainWindow
from qfluentwidgets import ComboBox, CardWidget, ToolTipFilter, FluentWindow, isDarkTheme, \
    ToolTipPosition, PrimaryPushButton, PushButton, InfoBar, BodyLabel, PillPushButton, setFont, \
    InfoBadgePosition, ProgressRing, InfoBarPosition, ScrollArea, Action, RoundMenu, IconInfoBadge, \
    InfoLevel
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow, StandardTitleBar

from ..config import RESOURCE_PATH
from ..common.config import cfg
from ..core.entities import SupportedVideoFormats, SupportedAudioFormats
from ..core.entities import Task, VideoInfo
from ..core.thread.create_task_thread import CreateTaskThread
from ..core.thread.subtitle_pipeline_thread import SubtitlePipelineThread
from ..core.thread.transcript_thread import TranscriptThread
from ..view.subtitle_optimization_interface import SubtitleOptimizationInterface


class BatchProcessInterface(QWidget):
    """批量处理界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchProcessInterface")
        self.setWindowTitle(self.tr("批量处理"))
        self.setAcceptDrops(True)

        self.tasks = []
        self.task_cards = []
        self.processing = False
        self.lock = Lock()
        self.create_threads = []
        self.setup_ui()
        self._initStyle()
        self.setup_signals()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(20)

        # 顶部操作布局
        self.top_layout = QHBoxLayout()
        self.top_layout.setSpacing(10)

        # 添加文件按钮
        self.add_file_button = PushButton(self.tr("添加视频文件"), self, icon=FIF.ADD)
        self.top_layout.addWidget(self.add_file_button)

        # 清空任务按钮
        self.clear_all_button = PushButton(self.tr("清空任务"), self, icon=FIF.DELETE)
        self.top_layout.addWidget(self.clear_all_button)

        # 任务类型选择
        self.task_type_combo = ComboBox(self)
        self.task_type_combo.addItems([self.tr("视频加字幕"), self.tr("音视频转录")])
        self.top_layout.addWidget(self.task_type_combo)

        self.top_layout.addStretch(1)

        # 添加启动和取消按钮
        self.start_all_button = PrimaryPushButton(self.tr("开始处理"), self, icon=FIF.PLAY)
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CLOSE)
        self.cancel_button.setEnabled(False)
        self.top_layout.addWidget(self.start_all_button)
        self.top_layout.addWidget(self.cancel_button)

        self.main_layout.addLayout(self.top_layout)

        # 创建滚动区域
        self.scroll_area = ScrollArea(self)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll_area)

    def _initStyle(self):
        """初始化样式"""
        self.scroll_widget.setObjectName("scrollWidget")
        self.setObjectName("BatchProcessInterface")
        self.setStyleSheet("""        
            BatchProcessInterface, #scrollWidget {
                background-color: transparent;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

    def setup_signals(self):
        self.add_file_button.clicked.connect(self.on_add_file)
        self.clear_all_button.clicked.connect(self.clear_all_tasks)
        self.start_all_button.clicked.connect(self.start_batch_process)
        self.cancel_button.clicked.connect(self.cancel_batch_process)

    def clear_all_tasks(self):
        """清空所有任务"""
        # 如果正在处理任务,不允许清空
        if self.processing:
            InfoBar.warning(
                self.tr("无法清空"),
                self.tr("正在处理的任务无法清空"),
                duration=2000,
                position=InfoBarPosition.BOTTOM,
                parent=self
            )
            return

        # 清空所有任务卡片
        for task_card in self.task_cards[:]:
            self.remove_task_card(task_card)

        InfoBar.success(
            self.tr("已清空"),
            self.tr("已清空所有任务"),
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

    def start_batch_process(self):
        """开始批量处理"""
        self.processing = True
        self.start_all_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.add_file_button.setEnabled(False)
        self.clear_all_button.setEnabled(False)

        if not self.task_cards:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可处理的任务"),
                duration=2000,
                parent=self
            )
            return

        # 显示开始处理的通知
        InfoBar.info(
            self.tr("开始处理"),
            self.tr("开始批量处理任务"),
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

        # 查找第一个未完成的任务并开始处理
        for task_card in self.task_cards:
            if task_card.task.status not in [Task.Status.COMPLETED, Task.Status.FAILED]:
                task_card.finished.connect(self.on_task_finished)
                task_card.error.connect(self.on_task_error)
                task_card.start()
                break
        # 判断是否所有任务都已完成
        if all(task_card.task.status in [Task.Status.COMPLETED, Task.Status.FAILED] for task_card in self.task_cards):
            self.on_batch_finished()

    def cancel_batch_process(self):
        """取消批量处理"""
        self.processing = False
        self.start_all_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.add_file_button.setEnabled(True)
        self.clear_all_button.setEnabled(True)

        # 停止所有正在运行的任务
        for task_card in self.task_cards:
            if task_card.task.status in [Task.Status.TRANSCRIBING, Task.Status.PENDING, Task.Status.OPTIMIZING,
                                         Task.Status.GENERATING]:
                task_card.stop()

        # 显示取消处理的通知
        InfoBar.warning(
            self.tr("已取消"),
            self.tr("已取消批量处理"),
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

    def on_task_finished(self, task):
        """单个任务完成的处理"""
        InfoBar.success(
            self.tr("任务完成"),
            self.tr("任务已完成"),
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

        # 查找下一个未完成的任务
        next_task = None
        for task_card in self.task_cards:
            if task_card.task.status not in [Task.Status.COMPLETED, Task.Status.FAILED]:
                next_task = task_card
                break

        if next_task:
            next_task.finished.connect(self.on_task_finished)
            next_task.start()
        else:
            # 所有任务都完成了
            self.on_batch_finished()

    def on_task_error(self, error):
        """单个任务出错"""
        InfoBar.error(
            self.tr("任务出错"),
            self.tr("任务出错:") + error,
            duration=5000,
            parent=self
        )
        # 查找下一个未完成的任务
        next_task = None
        for task_card in self.task_cards:
            if task_card.task.status not in [Task.Status.COMPLETED, Task.Status.FAILED]:
                next_task = task_card
                break

        if next_task:
            next_task.finished.connect(self.on_task_finished)
            next_task.start()
        else:
            # 所有任务都完成了
            self.on_batch_finished()
    
    def on_batch_finished(self):
        """批量处理完成的处理"""
        self.processing = False
        self.start_all_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.add_file_button.setEnabled(True)
        self.clear_all_button.setEnabled(True)

        # 显示所有任务完成的通知
        InfoBar.success(
            self.tr("全部完成"),
            self.tr("所有任务已处理完成"),
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

    def on_add_file(self):
        """添加文件按钮点击事件"""
        # 构建文件过滤器字符串
        video_formats = [f"*.{fmt.value}" for fmt in SupportedVideoFormats]
        audio_formats = [f"*.{fmt.value}" for fmt in SupportedAudioFormats]
        if self.task_type_combo.currentText() == self.tr("视频加字幕"):
            filter_str = f"{self.tr('视频文件')} ({' '.join(video_formats)})"
            task_type = Task.Type.SUBTITLE
        else:
            # 音频/视频生成字幕
            filter_str = f"{self.tr('音频文件或视频文件')} ({' '.join(audio_formats + video_formats)})"
            task_type = Task.Type.TRANSCRIBE

        files, _ = QFileDialog.getOpenFileNames(self, self.tr("选择文件"), cfg.last_open_dir.value , filter_str)
        for file_path in files:
            self.create_task(file_path, task_type)
            
        # Save the files' directory for later use
        file_dir = str( Path(files[0]).parent )
        if file_dir != cfg.last_open_dir.value:
            cfg.last_open_dir.value = file_dir

    def create_task(self, file_path, task_type: Task.Type):
        """创建新任务"""
        # 检查文件是否已存在
        for task in self.tasks:
            if Path(task.file_path).resolve() == Path(file_path).resolve():
                InfoBar.warning(
                    self.tr("添加失败"),
                    self.tr("该文件已存在于任务列表中"),
                    duration=3000,
                    position=InfoBarPosition.BOTTOM,
                    parent=self
                )
                return

        # task_type = 'transcription' if self.task_type_combo.currentText() == self.tr("音视频转录") else 'file'
        create_thread = CreateTaskThread(file_path, task_type)
        create_thread.finished.connect(self.add_task_card)
        create_thread.finished.connect(lambda: self.cleanup_thread(create_thread))
        self.create_threads.append(create_thread)
        create_thread.start()

    def cleanup_thread(self, thread):
        """清理完成的线程"""
        if thread in self.create_threads:
            self.create_threads.remove(thread)
            thread.deleteLater()

    def add_task_card(self, task: Task):
        """添加新的任务卡片"""
        task_card = TaskInfoCard(self)
        task_card.set_task(task)
        task_card.remove.connect(self.remove_task_card)
        self.task_cards.append(task_card)
        self.tasks.append(task)
        self.scroll_layout.addWidget(task_card)

        # 当有任务时禁用任务类型选择
        self.task_type_combo.setEnabled(False)

        # 显示成功提示
        InfoBar.success(
            self.tr("添加成功"),
            self.tr(f"已添加视频:") + task.video_info.file_name,
            duration=2000,
            position=InfoBarPosition.BOTTOM,
            parent=self
        )

    def remove_task_card(self, task_card):
        """移除任务卡片"""
        if task_card in self.task_cards:
            # 如果任务正在处理中,不允许删除
            if self.processing:
                InfoBar.warning(
                    self.tr("无法删除"),
                    self.tr("正在处理的任务无法删除"),
                    duration=2000,
                    position=InfoBarPosition.BOTTOM,
                    parent=self
                )
                return

            self.task_cards.remove(task_card)
            self.tasks.remove(task_card.task)
            self.scroll_layout.removeWidget(task_card)
            task_card.deleteLater()

            # 显示删除成功的通知
            InfoBar.success(
                self.tr("删除成功"),
                self.tr(f"已删除任务:") + task_card.task.video_info.file_name,
                duration=2000,
                position=InfoBarPosition.BOTTOM,
                parent=self
            )

            # 当没有任务时启用任务类型选择
            if len(self.task_cards) == 0:  # 因为当前任务还未被移除
                self.task_type_combo.setEnabled(True)

    def dragEnterEvent(self, event):
        """拖拽进入事件处理"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽放下事件处理"""
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 根据任务类型检查文件格式
            if self.task_type_combo.currentText() == self.tr("视频加字幕"):
                supported_formats = {fmt.value for fmt in SupportedVideoFormats}
                task_type = Task.Type.SUBTITLE
            else:
                supported_formats = {fmt.value for fmt in SupportedVideoFormats} | {fmt.value for fmt in SupportedAudioFormats}
                task_type = Task.Type.TRANSCRIBE

            if file_ext in supported_formats:
                self.create_task(file_path, task_type)
            else:
                error_msg = self.tr("请拖入视频文件") if self.task_type_combo.currentText() == self.tr("视频加字幕") else self.tr("请拖入音频或视频文件")
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    error_msg,
                    duration=3000,
                    parent=self
                )

    def closeEvent(self, event):
        """关闭事件处理"""
        self.cancel_batch_process()
        super().closeEvent(event)

class TaskInfoCard(CardWidget):
    finished = pyqtSignal(Task)
    remove = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task: Task = None
        self.setup_ui()
        self.setup_signals()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.installEventFilter(ToolTipFilter(self, 100, ToolTipPosition.BOTTOM))

        self.transcript_thread = None
        self.subtitle_thread = None
        self.subtitle_window = None  # 添加成员变量

    def setup_ui(self):
        self.setFixedHeight(150)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 15, 20, 15)
        self.layout.setSpacing(20)

        # 设置缩略图
        self.setup_thumbnail()
        # 设置视频信息
        self.setup_info_layout()
        # 设置按钮
        self.setup_button_layout()

        self.task_state = IconInfoBadge.info(FIF.REMOVE, self, target=self.video_title,
                                             position=InfoBadgePosition.TOP_RIGHT)

    def setup_thumbnail(self):
        self.video_thumbnail = QLabel(self)
        self.video_thumbnail.setFixedSize(208, 117)
        self.video_thumbnail.setStyleSheet("background-color: #1E1F22;")
        self.video_thumbnail.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.video_thumbnail, 0, Qt.AlignLeft)

    def setup_info_layout(self):
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(3, 8, 3, 8)
        self.info_layout.setSpacing(10)

        # 设置视频标题
        self.video_title = BodyLabel(self.tr("未选择视频"), self)
        self.video_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self.video_title.setWordWrap(True)
        self.info_layout.addWidget(self.video_title, alignment=Qt.AlignTop)

        # 设置视频详细信息
        self.details_layout = QHBoxLayout()
        self.details_layout.setSpacing(15)

        self.resolution_info = self.create_pill_button(self.tr("画质"), 110)
        self.file_size_info = self.create_pill_button(self.tr("文件大小"), 110)
        self.duration_info = self.create_pill_button(self.tr("时长"), 100)

        self.progress_ring = ProgressRing(self)
        self.progress_ring.setFixedSize(20, 20)
        self.progress_ring.setStrokeWidth(4)
        self.progress_ring.hide()

        self.details_layout.addWidget(self.resolution_info)
        self.details_layout.addWidget(self.file_size_info)
        self.details_layout.addWidget(self.duration_info)
        self.details_layout.addWidget(self.progress_ring)
        self.details_layout.addStretch(1)
        self.info_layout.addLayout(self.details_layout)
        self.layout.addLayout(self.info_layout)

    def create_pill_button(self, text, width):
        button = PillPushButton(text, self)
        button.setCheckable(False)
        setFont(button, 11)
        button.setFixedWidth(width)
        return button

    def setup_button_layout(self):
        self.button_layout = QVBoxLayout()
        self.preview_subtitle_button = PushButton(self.tr("预览字幕"), self)
        self.open_folder_button = PushButton(self.tr("打开文件夹"), self)
        self.start_button = PrimaryPushButton(self.tr("未开始转录"), self)
        self.button_layout.addWidget(self.preview_subtitle_button)
        self.button_layout.addWidget(self.open_folder_button)
        self.button_layout.addWidget(self.start_button)

        self.start_button.setDisabled(True)

        button_widget = QWidget()
        button_widget.setLayout(self.button_layout)
        button_widget.setFixedWidth(150)
        self.layout.addWidget(button_widget)

    def mouseDoubleClickEvent(self, event):
        """双击事件处理"""
        self.open_subtitle()

    def update_info(self, video_info: VideoInfo):
        """更新视频信息显示"""
        # self.video_title.setText(video_info.file_name.rsplit('.', 1)[0])
        self.video_title.setText(video_info.file_name + '\n' + video_info.file_path)
        self.resolution_info.setText(self.tr("画质: ") + f"{video_info.width}x{video_info.height}")
        file_size_mb = os.path.getsize(self.task.file_path) / 1024 / 1024
        self.file_size_info.setText(self.tr("大小: ") + f"{file_size_mb:.1f} MB")
        duration = datetime.timedelta(seconds=int(video_info.duration_seconds))
        self.duration_info.setText(self.tr("时长: ") + str(duration))
        # self.start_button.setDisabled(False)
        self.update_thumbnail(video_info.thumbnail_path)
        self.update_tooltip()

    def update_tooltip(self):
        """更新tooltip"""
        # 设置整体tooltip
        strategy_text = self.tr("无")
        if self.task.need_optimize:
            strategy_text = self.tr("字幕优化")
        elif self.task.need_translate:
            # strategy_text = self.tr("字幕优化+翻译 ") + str(self.task.target_language)
            strategy_text = self.tr("字幕翻译 ") + str(self.task.target_language)

        tooltip = self.tr("转录模型: ") + self.task.transcribe_model.value + "\n"
        tooltip += self.tr("文件: ") + self.task.file_path + '\n'
        if self.task.status == Task.Status.PENDING:
            tooltip += self.tr("字幕策略: ") + strategy_text + "\n"
        tooltip += self.tr("任务状态: ") + self.task.status.value
        self.setToolTip(tooltip)

    def update_thumbnail(self, thumbnail_path):
        """更新视频缩略图"""
        if not Path(thumbnail_path).exists():
            thumbnail_path = RESOURCE_PATH / "assets" / "audio-thumbnail.png"

        pixmap = QPixmap(str(thumbnail_path)).scaled(
            self.video_thumbnail.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.video_thumbnail.setPixmap(pixmap)

    def setup_signals(self):
        self.start_button.clicked.connect(self.start)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)
        self.preview_subtitle_button.clicked.connect(self.open_subtitle)

    def show_context_menu(self, pos):
        """显示右键菜单"""
        menu = RoundMenu(parent=self)
        
        # 添加打开字幕选项
        open_subtitle_action = Action(FIF.DOCUMENT, self.tr("打开字幕（双击）"), self)
        open_subtitle_action.triggered.connect(self.open_subtitle)
        menu.addAction(open_subtitle_action)

        # 添加菜单项
        open_folder_action = Action(FIF.FOLDER, self.tr("打开文件夹"), self)
        open_folder_action.triggered.connect(self.on_open_folder_clicked)
        menu.addAction(open_folder_action)

        delete_action = Action(FIF.DELETE, self.tr("删除任务"), self)
        delete_action.triggered.connect(lambda: self.remove.emit(self))
        menu.addAction(delete_action)

        reprocess_action = Action(FIF.SYNC, self.tr("重新处理"), self)
        reprocess_action.triggered.connect(self.start)
        menu.addAction(reprocess_action)

        cancel_action = Action(FIF.CANCEL, self.tr("取消任务"), self)
        cancel_action.triggered.connect(self.cancel)
        menu.addAction(cancel_action)

        # 显示菜单
        menu.exec_(self.mapToGlobal(pos))

    def open_subtitle(self):
        """打开字幕优化界面"""
        preview_subtitle_path = Path(self.task.original_subtitle_save_path)
        if self.task.result_subtitle_save_path:
            preview_subtitle_path = Path(self.task.result_subtitle_save_path)
        if preview_subtitle_path.exists():
            self.subtitle_window = QWidget()
            self.subtitle_window.setWindowTitle(self.tr("字幕预览"))
            subtitle_interface = SubtitleOptimizationInterface(self.subtitle_window)
            subtitle_interface.load_subtitle_file(str(preview_subtitle_path))
            subtitle_interface.remove_widget()
            layout = QHBoxLayout(self.subtitle_window)
            layout.setContentsMargins(3, 0, 3, 3)
            layout.addWidget(subtitle_interface)
            
            self.subtitle_window.resize(1000, 800)

            theme = 'dark' if isDarkTheme() else 'light'
            with open(RESOURCE_PATH / "assets" / "qss" / theme / "demo.qss", encoding='utf-8') as f:
                self.subtitle_window.setStyleSheet(f.read())
            self.subtitle_window.show()
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("字幕文件不存在"), 
                duration=2000,
                parent=self
            )

    def cancel(self):
        """修改任务状态"""
        self.stop()
        self.task.status = Task.Status.PENDING
        self.finished.emit(self.task)
        self.update_tooltip()

    def stop(self):
        """停止转录"""
        if self.transcript_thread and self.transcript_thread.isRunning():
            self.transcript_thread.terminate()
        if self.subtitle_thread and self.subtitle_thread.isRunning():
            self.subtitle_thread.terminate()
        self.reset_ui()
        InfoBar.success(
            self.tr("已取消"),
            self.tr("任务已取消"),
            duration=2000,
            parent=self
        )

    def start(self):
        """开始转录按钮点击事件"""
        # 获取任务类型
        if self.task.status == Task.Status.COMPLETED:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("该任务已完成"),
                duration=2000,
                parent=self
            )
            return

        self.progress_ring.show()
        self.progress_ring.setValue(100)
        # self.start_button.setDisabled(True)
        self.preview_subtitle_button.setDisabled(True)
        self.task_state.setLevel(InfoLevel.WARNING)
        self.task_state.setIcon(FIF.SYNC)
        self.progress_ring.resume()

        # 开始转录过程
        if self.task.type == Task.Type.TRANSCRIBE:
            self.transcript_thread = TranscriptThread(self.task)
            self.transcript_thread.finished.connect(self.on_finished)
            self.transcript_thread.progress.connect(self.on_progress)
            self.transcript_thread.error.connect(self.on_error)
            self.transcript_thread.start()
        elif self.task.type == Task.Type.SUBTITLE:
            self.subtitle_thread = SubtitlePipelineThread(self.task)
            self.subtitle_thread.finished.connect(self.on_finished)
            self.subtitle_thread.progress.connect(self.on_progress)
            self.subtitle_thread.error.connect(self.on_error)
            self.subtitle_thread.start()
        else:
            self.on_error(self.tr("任务类型错误"))

    def on_open_folder_clicked(self):
        """打开文件夹按钮点击事件"""
        if self.task and Path(self.task.file_path).exists():
            if sys.platform == "win32":
                os.startfile(str( Path(self.task.file_path).parent) )
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", str( Path(self.task.file_path).parent) ])
            else:  # Linux
                subprocess.run(["xdg-open", str( Path(self.task.file_path).parent) ])
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("任务未开始"),
                duration=2000,
                parent=self
            )

    def on_progress(self, value, message):
        """更新转录进度"""
        self.start_button.setText(message)
        self.progress_ring.setValue(value)
        self.update_tooltip()

    def on_error(self, error):
        """处理转录错误"""
        self.reset_ui()
        self.task_state.setLevel(InfoLevel.ERROR)
        self.task_state.setIcon(FIF.CLOSE)
        self.progress_ring.error()
        self.update_tooltip()

        self.task.status = Task.Status.FAILED
        self.error.emit(error)
        InfoBar.error(
            self.tr("转录失败"),
            self.tr(error),
            duration=5000,
            parent=self
        )

    def on_finished(self, task):
        """转录完成处理"""
        self.reset_ui()
        self.task_state.setLevel(InfoLevel.SUCCESS)
        self.task_state.setIcon(FIF.ACCEPT)
        self.update_tooltip()

        self.task.status = Task.Status.COMPLETED
        self.finished.emit(task)

    def reset_ui(self):
        """重置UI状态"""
        # self.start_button.setEnabled(True)
        # self.start_button.setText(self.tr("开始转录"))
        self.preview_subtitle_button.setEnabled(True)
        self.progress_ring.setValue(100)
        self.task_state.setLevel(InfoLevel.INFOAMTION)
        self.task_state.setIcon(FIF.REMOVE)
        self.update_tooltip()

    def set_task(self, task):
        """设置任务并更新UI"""
        self.task = task
        self.update_info(self.task.video_info)
        self.reset_ui()
