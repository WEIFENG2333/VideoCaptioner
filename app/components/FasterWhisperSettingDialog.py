import sys
import subprocess
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTableWidgetItem, QHeaderView, QHBoxLayout
from qfluentwidgets import (MessageBoxBase, BodyLabel, SubtitleLabel,
                          SettingCardGroup, InfoBar, InfoBarPosition, 
                          ComboBoxSettingCard, SwitchSettingCard, SingleDirectionScrollArea,
                          PushButton, ProgressBar, ComboBox, TableWidget, TableItemDelegate, PushSettingCard, HyperlinkButton, HyperlinkCard)
from qfluentwidgets import FluentIcon as FIF

from .SpinBoxSettingCard import DoubleSpinBoxSettingCard
from ..common.config import cfg
from ..core.entities import FasterWhisperModelEnum, TranscribeLanguageEnum, WhisperModelEnum, VadMethodEnum
from ..components.LineEditSettingCard import LineEditSettingCard
from ..components.EditComboBoxSettingCard import EditComboBoxSettingCard
from ..config import BIN_PATH, CACHE_PATH, MODEL_PATH
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

from modelscope.hub.snapshot_download import snapshot_download

from ..core.thread.download_thread import DownloadThread
from ..core.thread.modelscope_download_thread import ModelscopeDownloadThread


# 在文件开头添加常量定义
FASTER_WHISPER_PROGRAMS = [
    {
        "label": "GPU + CPU 版本",
        "value": "faster-whisper-gpu.7z",
        "type": "GPU",
        "size": "1.35 GB",
        "downloadLink": "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/Faster-Whisper-XXL_r194.5_windows.7z",
    },
    {
        "label": "CPU版本",
        "value": "faster-whisper.exe",
        "type": "CPU",
        "size": "78.7 MB",
        "downloadLink": "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster.exe",
    }
]

FASTER_WHISPER_MODELS = [
    {
        "label": "Tiny",
        "value": "faster-whisper-tiny", 
        "size": "77824",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-tiny",
        "modelScopeLink": "pengzhendong/faster-whisper-tiny",
    },
    {
        "label": "Base",
        "value": "faster-whisper-base",
        "size": "148480",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-base",
        "modelScopeLink": "pengzhendong/faster-whisper-base",
    },
    {
        "label": "Small",
        "value": "faster-whisper-small",
        "size": "495616",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-small",
        "modelScopeLink": "pengzhendong/faster-whisper-small",
    },
    {
        "label": "Medium",
        "value": "faster-whisper-medium",
        "size": "1572864",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-medium",
        "modelScopeLink": "pengzhendong/faster-whisper-medium",
    },
    {
        "label": "Large-v1",
        "value": "faster-whisper-large-v1",
        "size": "3145728",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-large-v1",
        "modelScopeLink": "pengzhendong/faster-whisper-large-v1",
    },
    {
        "label": "Large-v2",
        "value": "faster-whisper-large-v2",
        "size": "3145728",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-large-v2",
        "modelScopeLink": "pengzhendong/faster-whisper-large-v2",
    },
    {
        "label": "Large-v3",
        "value": "faster-whisper-large-v3",
        "size": "3145728",
        "downloadLink": "https://huggingface.co/Systran/faster-whisper-large-v3",
        "modelScopeLink": "pengzhendong/faster-whisper-large-v3",
    }
]

# 在类外添加这个工具函数
def check_faster_whisper_exists() -> tuple[bool, list[str]]:
    """检查 faster-whisper 程序是否存在
    
    检查以下两种情况:
    1. bin目录下是否有 faster-whisper.exe
    2. bin目录下是否有 Faster-Whisper-XXL/faster-whisper-xxl.exe
    
    Returns:
        tuple[bool, list[str]]: (是否存在程序, 已安装的版本列表)
    """
    bin_path = Path(BIN_PATH)
    installed_versions = []
    
    # 检查 faster-whisper.exe(CPU版本)
    if (bin_path / "faster-whisper.exe").exists():
        installed_versions.append("CPU")
        
    # 检查 Faster-Whisper-XXL/faster-whisper-xxl.exe(GPU版本)
    xxl_path = bin_path / "Faster-Whisper-XXL" / "faster-whisper-xxl.exe"
    if xxl_path.exists():
        installed_versions.extend(["GPU", "CPU"])
    installed_versions = list(set(installed_versions))
        
    return bool(installed_versions), installed_versions

# 添加新的解压线程类
class UnzipThread(QThread):
    """7z解压线程"""
    finished = pyqtSignal()  # 解压完成信号
    error = pyqtSignal(str)  # 解压错误信号
    
    def __init__(self, zip_file, extract_path):
        super().__init__()
        self.zip_file = zip_file
        self.extract_path = extract_path
        
    def run(self):
        try:
            subprocess.run(
                ["7z", "x", self.zip_file, f"-o{self.extract_path}", "-y"],
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            # 删除压缩包
            os.remove(self.zip_file)
            self.finished.emit()
        except subprocess.CalledProcessError as e:
            self.error.emit(f"解压失败: {str(e)}")
        except Exception as e:
            self.error.emit(str(e))

class FasterWhisperDownloadDialog(MessageBoxBase):
    """Faster Whisper 下载对话框"""
    
    # 添加类变量跟踪下载状态
    is_downloading = False
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(600)
        self.program_download_thread = None
        self.model_download_thread = None
        self._setup_ui()
        self._connect_signals()
        
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout()
        self._setup_program_section(layout)
        layout.addSpacing(20)
        self._setup_model_section(layout)
        self._setup_progress_section(layout)
        
        self.viewLayout.addLayout(layout)
        self.cancelButton.setText(self.tr("关闭"))
        self.yesButton.hide()
        
    def _setup_program_section(self, layout):
        """设置程序下载部分UI"""
        # 标题
        faster_whisper_title = SubtitleLabel(self.tr("Faster Whisper 下载"), self)
        layout.addWidget(faster_whisper_title)
        layout.addSpacing(10)

        # 检查已安装的版本
        has_program, installed_versions = check_faster_whisper_exists()
        
        if has_program:
            # 显示已安装版本
            versions_text = " + ".join(installed_versions)
            program_status = BodyLabel(self.tr(f"已安装版本: {versions_text}"), self)
            program_status.setStyleSheet("color: green")
            layout.addWidget(program_status)
            
            # 添加说明标签
            if len(installed_versions) == 1:
                desc_label = BodyLabel(self.tr("您可以继续下载其他版本:"), self)
                layout.addWidget(desc_label)
        else:
            desc_label = BodyLabel(self.tr("未下载Faster Whisper 程序"), self)
            layout.addWidget(desc_label)

        # 下载控件
        program_layout = QHBoxLayout()
        self.program_combo = ComboBox(self)
        self.program_combo.setFixedWidth(300)
        
        # 只显示未安装的版本
        for program in FASTER_WHISPER_PROGRAMS:
            version_type = program['type']
            if version_type not in installed_versions:
                self.program_combo.addItem(f"{program['label']} ({program['size']})")
        
        # 如果还有可下载的版本，显示下载控件
        if self.program_combo.count() > 0:
            self.program_download_btn = PushButton(self.tr("下载程序"), self)
            self.program_download_btn.clicked.connect(self._start_download)
            program_layout.addWidget(self.program_combo)
            program_layout.addWidget(self.program_download_btn)
            program_layout.addStretch()
            layout.addLayout(program_layout)

    def _setup_model_section(self, layout):
        """设置模型下载部分UI"""
        # 标题和按钮的水平布局
        title_layout = QHBoxLayout()
        
        # 标题
        model_title = SubtitleLabel(self.tr("模型下载"), self)
        title_layout.addWidget(model_title)
        
        # 添加打开文件夹按钮
        open_folder_btn = HyperlinkButton(
            "",
            self.tr("打开模型文件夹"),
            parent=self
        )
        open_folder_btn.setIcon(FIF.FOLDER)
        open_folder_btn.clicked.connect(self._open_model_folder)
        title_layout.addStretch()
        title_layout.addWidget(open_folder_btn)
        
        layout.addLayout(title_layout)
        layout.addSpacing(10)

        # 模型表格
        self.model_table = self._create_model_table()
        self._populate_model_table()
        layout.addWidget(self.model_table)

    def _create_model_table(self):
        """创建模型表格"""
        table = TableWidget(self)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.NoSelection)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels([
            self.tr("模型名称"), self.tr("大小"), 
            self.tr("状态"), self.tr("操作")
        ])
        
        # 设置表格样式
        table.setBorderVisible(True)
        table.setBorderRadius(8)
        table.setItemDelegate(TableItemDelegate(table))
        
        # 设置列宽
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 80)
        table.setColumnWidth(3, 150)
        
        # 设置行高
        row_height = 50
        table.verticalHeader().setDefaultSectionSize(row_height)
        
        # 设置表格高度
        header_height = 35
        table_height = row_height * len(FASTER_WHISPER_MODELS) + header_height
        table.setFixedHeight(table_height)
        
        return table

    def _setup_progress_section(self, layout):
        """设置进度显示部分UI"""
        self.progress_bar = ProgressBar(self)
        self.progress_label = BodyLabel("", self)
        self.progress_bar.hide()
        self.progress_label.hide()
        
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)

    def _populate_model_table(self):
        """填充模型表格数据"""
        self.model_table.setRowCount(len(FASTER_WHISPER_MODELS))
        for i, model in enumerate(FASTER_WHISPER_MODELS):
            self._add_model_row(i, model)

    def _add_model_row(self, row, model):
        """添加模型表格行"""
        # 模型名称
        name_item = QTableWidgetItem(model['label'])
        name_item.setTextAlignment(Qt.AlignCenter)
        self.model_table.setItem(row, 0, name_item)
        
        # 大小
        size_item = QTableWidgetItem(f"{int(model['size'])/1024:.1f} MB")
        size_item.setTextAlignment(Qt.AlignCenter)
        self.model_table.setItem(row, 1, size_item)
        
        # 状态
        model_path = os.path.join(MODEL_PATH, model['value'])
        model_bin_path = os.path.join(model_path, "model.bin")
        status_item = QTableWidgetItem(
            self.tr("已下载") if os.path.exists(model_bin_path) else self.tr("未下载")
        )
        if os.path.exists(model_bin_path):
            status_item.setForeground(Qt.green)
        status_item.setTextAlignment(Qt.AlignCenter)
        self.model_table.setItem(row, 2, status_item)
        
        # 下载按钮
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(4, 4, 4, 4)
        
        download_btn = HyperlinkButton(
            "",
            self.tr("重新下载") if os.path.exists(model_bin_path) else self.tr("下载"),
            parent=self
        )
        download_btn.setIcon(FIF.DOWNLOAD)
        download_btn.clicked.connect(lambda checked, r=row: self._download_model(r))
        
        button_layout.addStretch()
        button_layout.addWidget(download_btn)
        button_layout.addStretch()
        self.model_table.setCellWidget(row, 3, button_container)

    def _connect_signals(self):
        """连接信号"""
        self.rejected.connect(self._on_dialog_reject)
        
    def _start_download(self):
        """开始下载"""
        if FasterWhisperDownloadDialog.is_downloading:
            InfoBar.warning(
                self.tr("下载进行中"),
                self.tr("请等待当前下载任务完成"),
                duration=3000,
                parent=self
            )
            return
            
        FasterWhisperDownloadDialog.is_downloading = True
        # 禁用所有下载按钮
        self._set_all_download_buttons_enabled(False)
        
        # 获取选中的文本
        selected_text = self.program_combo.currentText()
        
        # 从显示文本中提取程序标签
        selected_label = selected_text.split(" (")[0]
        
        # 根据标签找到对应的程序配置
        program = next(
            (p for p in FASTER_WHISPER_PROGRAMS if p['label'] == selected_label),
            None
        )
        
        if not program:
            InfoBar.error(
                self.tr("下载错误"),
                self.tr("未找到对应的程序配置"),
                duration=3000,
                parent=self
            )
            FasterWhisperDownloadDialog.is_downloading = False
            self._set_all_download_buttons_enabled(True)
            return
        
        # 确保 BIN_PATH 目录存在
        os.makedirs(BIN_PATH, exist_ok=True)
        
        self.progress_bar.show()
        self.progress_label.show()
        self.program_download_btn.setEnabled(False)
        self.program_combo.setEnabled(False)
        
        # 直接下载到bin目录
        save_path = os.path.join(BIN_PATH, program['value'])
        
        self.program_download_thread = DownloadThread(program['downloadLink'], save_path)
        self.program_download_thread.progress.connect(self._on_program_download_progress)
        self.program_download_thread.finished.connect(lambda: self._on_program_download_finished(save_path))
        self.program_download_thread.error.connect(self._on_program_download_error)
        self.program_download_thread.start()
        
    def _on_program_download_progress(self, value, status_msg):
        """更新程序下载进度"""
        self.progress_bar.setValue(int(value))
        self.progress_label.setText(status_msg)
        
    def _on_program_download_finished(self, save_path):
        """程序下载完成处理"""
        try:
            # 检查是否是 CPU 版本的直接下载
            if save_path.endswith('.exe'):
                # 如果是exe文件,重命名为faster-whisper.exe
                os.rename(save_path, os.path.join(BIN_PATH, "faster-whisper.exe"))
                self._finish_program_installation()
            else:
                # GPU 版本需要解压
                self.progress_label.setText(self.tr("正在解压文件..."))
                
                # 创建并启动解压线程
                self.unzip_thread = UnzipThread(save_path, BIN_PATH)
                self.unzip_thread.finished.connect(self._finish_program_installation)
                self.unzip_thread.error.connect(self._on_unzip_error)
                self.unzip_thread.start()
                return  # 提前返回,等待解压完成

        except Exception as e:
            InfoBar.error(
                self.tr("安装失败"),
                str(e),
                duration=3000,
                parent=self
            )
            self._cleanup_installation()

    def _on_program_download_error(self, error):
        """程序下载错误处理"""
        InfoBar.error(
            self.tr("下载失败"),
            error,
            duration=3000,
            parent=self
        )
        FasterWhisperDownloadDialog.is_downloading = False
        self._set_all_download_buttons_enabled(True)
        self.program_download_btn.setEnabled(True)
        self.program_combo.setEnabled(True)
        self.progress_bar.hide()
        self.progress_label.hide()
        
    def _on_dialog_reject(self):
        """对话框关闭处理"""
        if self.program_download_thread and self.program_download_thread.isRunning():
            self.program_download_thread.stop()
        if self.model_download_thread and self.model_download_thread.isRunning():
            self.model_download_thread.terminate()
        FasterWhisperDownloadDialog.is_downloading = False
        self.reject()

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        self._on_dialog_reject()
        super().closeEvent(event)

    def _download_model(self, row):
        """下载选中的模型"""
        if FasterWhisperDownloadDialog.is_downloading:
            InfoBar.warning(
                self.tr("下载进行中"),
                self.tr("请等待当前下载任务完成"),
                duration=3000,
                parent=self
            )
            return
            
        FasterWhisperDownloadDialog.is_downloading = True
        self._set_all_download_buttons_enabled(False)
        
        model = FASTER_WHISPER_MODELS[row]
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_label.setText(self.tr(f"正在下载 {model['label']} 模型..."))
        
        # 禁用当前行的下载按钮
        button_container = self.model_table.cellWidget(row, 3)
        download_btn = button_container.findChild(HyperlinkButton)
        if download_btn:
            download_btn.setEnabled(False)
        
        # 创建并启动下载线程，保存到类属性
        self.model_download_thread = ModelscopeDownloadThread(
            model['modelScopeLink'],
            os.path.join(MODEL_PATH, model['value'])
        )
        
        def _on_model_download_progress(value, msg):
            self.progress_bar.setValue(value)
            self.progress_label.setText(msg)
            
        def _on_model_download_finished():
            FasterWhisperDownloadDialog.is_downloading = False
            self._set_all_download_buttons_enabled(True)
            # 更新状态
            status_item = QTableWidgetItem(self.tr("已下载"))
            status_item.setForeground(Qt.green)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.model_table.setItem(row, 2, status_item)
            
            # 更新下载按钮文本
            if download_btn:
                download_btn.setText(self.tr("重新下载"))
                download_btn.setEnabled(True)
            
            # 更新主设置对话框的模型选择
            parent = self.parent()
            if isinstance(parent, FasterWhisperSettingDialog):
                model = FASTER_WHISPER_MODELS[row]
                model_text = model['label']
                if parent.model_card.comboBox.findText(model_text) == -1:
                    parent.model_card.comboBox.addItem(model_text)
            
            InfoBar.success(
                self.tr("下载成功"),
                self.tr(f"{model['label']} 模型已下载完成"),
                duration=3000,
                parent=self
            )
            self.progress_bar.hide()
            self.progress_label.hide()
            
        def _on_model_download_error(error):
            FasterWhisperDownloadDialog.is_downloading = False
            self._set_all_download_buttons_enabled(True)
            if download_btn:
                download_btn.setEnabled(True)
            
            InfoBar.error(
                self.tr("下载失败"),
                str(error),
                duration=3000,
                parent=self
            )
            self.progress_bar.hide()
            self.progress_label.hide()
            
        self.model_download_thread.progress.connect(_on_model_download_progress)
        self.model_download_thread.finished.connect(_on_model_download_finished)
        self.model_download_thread.error.connect(_on_model_download_error)
        self.model_download_thread.start()

    def _set_all_download_buttons_enabled(self, enabled: bool):
        """设置所有下载按钮的启用状态"""
        # 设置程序下载按钮
        if hasattr(self, 'program_download_btn'):
            self.program_download_btn.setEnabled(enabled)
            self.program_combo.setEnabled(enabled)
        
        # 设置所有模型下载按钮
        for row in range(self.model_table.rowCount()):
            button_container = self.model_table.cellWidget(row, 3)
            if button_container:
                download_btn = button_container.findChild(HyperlinkButton)
                if download_btn:
                    download_btn.setEnabled(enabled)

    def _open_model_folder(self):
        """打开模型文件夹"""
        if os.path.exists(MODEL_PATH):
            # 根据操作系统打开文件夹
            if sys.platform == "win32":
                os.startfile(MODEL_PATH)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", MODEL_PATH])
            else:  # Linux
                subprocess.run(["xdg-open", MODEL_PATH])

    def _finish_program_installation(self):
        """完成程序安装"""
        InfoBar.success(
            self.tr("安装完成"),
            self.tr("Faster Whisper 程序已安装成功"),
            duration=3000,
            parent=self
        )
        self.accept()
        self._cleanup_installation()

    def _on_unzip_error(self, error_msg):
        """处理解压错误"""
        InfoBar.error(
            self.tr("安装失败"), 
            error_msg,
            duration=3000,
            parent=self
        )
        self._cleanup_installation()

    def _cleanup_installation(self):
        """清理安装状态"""
        FasterWhisperDownloadDialog.is_downloading = False
        self._set_all_download_buttons_enabled(True)
        self.progress_bar.hide()
        self.progress_label.hide()

class FasterWhisperSettingDialog(MessageBoxBase):
    """Faster Whisper设置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr('Faster Whisper 设置'), self)
        
        # 创建单向滚动区域和容器
        self.scrollArea = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)
        self.scrollArea.setStyleSheet("QScrollArea{background: transparent; border: none}")

        self.container = QWidget(self)
        self.container.setStyleSheet("QWidget{background: transparent}")
        self.containerLayout = QVBoxLayout(self.container)
        
        # 创建设置卡片组
        self.settingGroup = SettingCardGroup(self.tr("模型设置"), self)
        
        # 模型选择
        self.model_card = ComboBoxSettingCard(
            cfg.faster_whisper_model,
            FIF.ROBOT,
            self.tr("模型"),
            self.tr("选择 Faster Whisper 模型"),
            [model.value for model in FasterWhisperModelEnum],
            self.settingGroup
        )
        
        # 检查未下载的模型并从下拉框中移除
        # 移除未下载的模型选项
        for i in range(self.model_card.comboBox.count() - 1, -1, -1):
            model_text = self.model_card.comboBox.itemText(i).lower()
            model_config = next(
                (model for model in FASTER_WHISPER_MODELS if model['label'].lower() == model_text),
                None
            )
            model_path = MODEL_PATH / model_config['value'] if model_config else None
            if model_config and model_path.exists():
                continue
            self.model_card.comboBox.removeItem(i)

        # 创建管理模型卡片
        self.manage_model_card = HyperlinkCard(
            '',  # 无链接
            self.tr('管理模型'),
            FIF.DOWNLOAD,  # 使用下载图标
            self.tr('模型管理'),
            self.tr('下载或更新 Faster Whisper 模型'),
            self.settingGroup  # 添加到设置组
        )

        # 语言选择
        self.language_card = ComboBoxSettingCard(
            cfg.transcribe_language,
            FIF.LANGUAGE,
            self.tr("源语言"),
            self.tr("音频的源语言"),
            [lang.value for lang in TranscribeLanguageEnum],
            self.settingGroup
        )
        self.language_card.comboBox.setMaxVisibleItems(6)

        # 设备选择
        self.device_card = ComboBoxSettingCard(
            cfg.faster_whisper_device,
            FIF.IOT,
            self.tr("运行设备"),
            self.tr("模型运行设备"),
            ["cuda", "cpu"],
            self.settingGroup
        )
        _, available_devices = check_faster_whisper_exists()
        if "GPU" not in available_devices:
            self.device_card.comboBox.removeItem(0)
        
        # VAD设置组
        self.vad_group = SettingCardGroup(self.tr("VAD设置"), self)
        
        # VAD过滤开关
        self.vad_filter_card = SwitchSettingCard(
            FIF.CHECKBOX,
            self.tr("VAD过滤"),
            self.tr("过滤无人声语音片断，减少幻觉"),
            cfg.faster_whisper_vad_filter,
            self.vad_group
        )
        
        # VAD阈值
        self.vad_threshold_card = DoubleSpinBoxSettingCard(
            cfg.faster_whisper_vad_threshold,
            FIF.VOLUME,
            self.tr("VAD阈值"),
            self.tr("语音概率阈值，高于此值视为语音"),
            minimum=0.00,
            maximum=1.00,
            decimals=2,
            step=0.05
        )
        
        # VAD方法
        self.vad_method_card = ComboBoxSettingCard(
            cfg.faster_whisper_vad_method,
            FIF.MUSIC,
            self.tr("VAD方法"),
            self.tr("选择VAD检测方法"),
            [method.value for method in VadMethodEnum],
            self.vad_group
        )
        
        # 其他设置组
        self.other_group = SettingCardGroup(self.tr("其他设置"), self)
        
        # 音频降噪
        self.ff_mdx_kim2_card = SwitchSettingCard(
            FIF.MUSIC,
            self.tr("人声分离"),
            self.tr("处理前使用MDX-Net降噪，分离人声和背景音乐"),
            cfg.faster_whisper_ff_mdx_kim2,
            self.other_group
        )
        
        # 单词时间戳
        self.one_word_card = SwitchSettingCard(
            FIF.UNIT,
            self.tr("单字时间戳"),
            self.tr("开启生成单字级时间戳；关闭后使用原始分段断句"),
            cfg.faster_whisper_one_word,
            self.other_group
        )
        
        # 翻译成英语
        self.translate_to_english_card = SwitchSettingCard(
            FIF.LANGUAGE,
            self.tr("翻译成英语"),
            self.tr("使用FastWhisper内置的翻译成英语功能"),
            cfg.faster_whisper_translate_to_english,
            self.other_group
        )
        # 提示词
        self.prompt_card = LineEditSettingCard(
            cfg.faster_whisper_prompt,
            FIF.CHAT,
            self.tr("提示词"),
            self.tr("可选的提示词,默认空"),
            "",
            self.other_group
        )


        self.model_card.comboBox.setMinimumWidth(200)
        self.device_card.comboBox.setMinimumWidth(200)
        self.language_card.comboBox.setMinimumWidth(200)
        self.vad_method_card.comboBox.setMinimumWidth(200)
        self.prompt_card.lineEdit.setMinimumWidth(200)

        
        # 添加模型设置组的卡片
        self.settingGroup.addSettingCard(self.model_card)
        self.settingGroup.addSettingCard(self.manage_model_card)
        self.settingGroup.addSettingCard(self.device_card)
        self.settingGroup.addSettingCard(self.language_card)

        # 添加VAD设置组的卡片
        self.vad_group.addSettingCard(self.vad_filter_card)
        self.vad_group.addSettingCard(self.vad_threshold_card)
        self.vad_group.addSettingCard(self.vad_method_card)
        
        # 添加其他设置的卡片
        self.other_group.addSettingCard(self.ff_mdx_kim2_card)
        self.other_group.addSettingCard(self.one_word_card)
        self.other_group.addSettingCard(self.translate_to_english_card)
        self.other_group.addSettingCard(self.prompt_card)

        # 检查并提示下载 faster-whisper
        self._check_faster_whisper()
        
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """设置UI布局"""
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(20)
        
        # 将所有设置组添加到容器布局
        self.containerLayout.addWidget(self.settingGroup)
        self.containerLayout.addWidget(self.vad_group)
        self.containerLayout.addWidget(self.other_group)
        self.containerLayout.addStretch()
        
        # 设置滚动区域
        self.scrollArea.setWidget(self.container)
        self.scrollArea.setWidgetResizable(True)
        
        # 将滚动区域添加到主布局
        self.viewLayout.addWidget(self.scrollArea)
        
        # 设置按钮文本
        self.yesButton.setText(self.tr('确定'))
        self.cancelButton.setText(self.tr('取消'))
        
        # 设置最小宽度
        self.widget.setMinimumWidth(500)
        self.widget.setFixedHeight(560)

    def _connect_signals(self):
        """连接信号"""
        self.manage_model_card.linkButton.clicked.connect(self._show_model_manager)
        self.yesButton.clicked.connect(self._on_yes_button_clicked)
        self.vad_filter_card.checkedChanged.connect(self._on_vad_filter_changed)
        
    def _on_vad_filter_changed(self, checked: bool):
        """VAD过滤开关状态改变时的处理"""
        self.vad_threshold_card.setEnabled(checked)
        self.vad_method_card.setEnabled(checked)

    def _on_yes_button_clicked(self):
        """确定按钮点击处理"""
        has_program, installed_versions  = check_faster_whisper_exists()
        if not has_program:
            self.show_error_info(self.tr('Faster Whisper程序不存在，请先下载程序'))
            return

        # 根据安装的版本设置程路径 
        if "GPU" in installed_versions:
            cfg.faster_whisper_program.value = "faster-whisper-xxl.exe"
        else:
            cfg.faster_whisper_program.value = "faster-whisper.exe"
            cfg.faster_whisper_vad_method.value = VadMethodEnum.NONE

        if self.check_faster_whisper_model():
            self.accept()
            InfoBar.success(
                self.tr("设置已保存"),
                self.tr("Faster Whisper 设置已更新"),
                duration=3000,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM
            )
        
        if cfg.transcribe_language.value == TranscribeLanguageEnum.JAPANESE:
            InfoBar.warning(
                self.tr("请注意身体！！"),
                self.tr("小心肝儿,注意身体哦~"),
                duration=2000,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM
            )

    def _check_faster_whisper(self):
        """检查 faster-whisper 程序是否存在，如不存在则显示下载对话框"""
        has_program, _ = check_faster_whisper_exists()
        if not has_program:
            dialog = FasterWhisperDownloadDialog(self)
            dialog.show()
        
    def _show_model_manager(self):
        """显示模型管理对话框"""
        dialog = FasterWhisperDownloadDialog(self)
        dialog.exec_()

    def show_error_info(self, error_msg):
        InfoBar.error(
            title=self.tr('错误'),
            content=error_msg,
            parent=self.window(),
            duration=5000,
            position=InfoBarPosition.BOTTOM
        )

    def check_faster_whisper_model(self):
        """检查选定的Faster Whisper模型是否存在
        
        Returns:
            bool: 如果模型存在且配置正确返回True，否则返回False
        """
        # 检查程序是否存在
        has_program, _ = check_faster_whisper_exists()
        if not has_program:
            self.show_error_info(self.tr('Faster Whisper程序不存在，请先下载程序'))
            return False
        
        model_value = cfg.faster_whisper_model.value.value
        # 检查模型配置是否存在
        model_config = next((m for m in FASTER_WHISPER_MODELS if m['label'].lower() == model_value.lower()), None)
        if not model_config:
            self.show_error_info(self.tr('模型配置不存在'))
            return False

        model_path = MODEL_PATH / model_config['value']
        model_files = model_path / "model.bin"
        # 检查模型文件是否存在
        if not model_path.exists() and not model_files.exists():
            self.show_error_info(self.tr('模型文件不存在: ') + model_value)
            return False
        return True

