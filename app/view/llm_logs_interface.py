"""LLM 请求日志查看界面"""

import json
from typing import Any, Dict, List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    MessageBoxBase,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    TableWidget,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.config import LOG_PATH

LLM_LOG_FILE = LOG_PATH / "llm_requests.jsonl"
PAGE_SIZE = 50


class LogDetailDialog(MessageBoxBase):
    """日志详情对话框"""

    def __init__(self, log_entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.log_entry = log_entry
        self._setup_ui()

    def _setup_ui(self):
        # 标题
        self.titleLabel = SubtitleLabel(self.tr("请求详情"))
        self.viewLayout.addWidget(self.titleLabel)

        # 基本信息
        time_str = self.log_entry.get("time", "")
        model = self.log_entry.get("request", {}).get("model", "未知")
        duration = self.log_entry.get("duration_ms", 0) / 1000

        usage = self.log_entry.get("response", {}).get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        # 任务上下文
        task_id = self.log_entry.get("task_id", "")
        file_name = self.log_entry.get("file_name", "")
        stage = self.log_entry.get("stage", "")

        info_lines = [
            f"时间: {time_str}  |  模型: {model}  |  耗时: {duration:.1f}s  |  Tokens: {prompt_tokens} → {completion_tokens}"
        ]
        if task_id:
            info_lines.append(f"任务: {task_id}  |  文件: {file_name}  |  阶段: {stage}")

        for line in info_lines:
            self.viewLayout.addWidget(BodyLabel(line))

        # Request
        self.viewLayout.addWidget(SubtitleLabel("Request"))
        self.request_edit = PlainTextEdit()
        self.request_edit.setReadOnly(True)
        self.request_edit.setMinimumHeight(180)
        request_text = json.dumps(self.log_entry.get("request", {}), indent=2, ensure_ascii=False)
        self.request_edit.setPlainText(request_text)
        self.viewLayout.addWidget(self.request_edit)

        # Response
        self.viewLayout.addWidget(SubtitleLabel("Response"))
        self.response_edit = PlainTextEdit()
        self.response_edit.setReadOnly(True)
        self.response_edit.setMinimumHeight(180)
        response_text = json.dumps(self.log_entry.get("response", {}), indent=2, ensure_ascii=False)
        self.response_edit.setPlainText(response_text)
        self.viewLayout.addWidget(self.response_edit)

        # 底部按钮：替换默认按钮
        self.yesButton.setText(self.tr("关闭"))
        self.cancelButton.hide()  # type: ignore

        copy_req_btn = PushButton(FIF.COPY, self.tr("复制请求"))
        copy_req_btn.clicked.connect(self._copy_request)
        self.buttonLayout.insertWidget(0, copy_req_btn)  # type: ignore

        copy_resp_btn = PushButton(FIF.COPY, self.tr("复制响应"))
        copy_resp_btn.clicked.connect(self._copy_response)
        self.buttonLayout.insertWidget(1, copy_resp_btn)  # type: ignore

        self.widget.setMinimumWidth(700)

    def _copy_request(self):
        text = json.dumps(self.log_entry.get("request", {}), indent=2, ensure_ascii=False)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        InfoBar.success(
            title="",
            content=self.tr("已复制"),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=1500,
        )

    def _copy_response(self):
        text = json.dumps(self.log_entry.get("response", {}), indent=2, ensure_ascii=False)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        InfoBar.success(
            title="",
            content=self.tr("已复制"),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=1500,
        )


class LLMLogsInterface(QWidget):
    """LLM 请求日志界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("llmLogsInterface")

        self.all_logs: List[Dict[str, Any]] = []
        self.filtered_logs: List[Dict[str, Any]] = []
        self.current_page = 0

        self._setup_ui()
        self._connect_signals()
        self._load_logs()

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(12)

        self._setup_toolbar()
        self._setup_table()
        self._setup_footer()

    def _setup_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText(self.tr("搜索任务ID、文件名、模型..."))
        self.search_edit.setFixedWidth(280)
        toolbar.addWidget(self.search_edit)

        toolbar.addStretch()

        self.refresh_btn = PushButton(FIF.SYNC, self.tr("刷新"))
        toolbar.addWidget(self.refresh_btn)

        self.clear_btn = PushButton(FIF.DELETE, self.tr("清空日志"))
        toolbar.addWidget(self.clear_btn)

        self.main_layout.addLayout(toolbar)

    def _setup_table(self):
        self.table = TableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("时间"),
                self.tr("任务ID"),
                self.tr("文件"),
                self.tr("阶段"),
                self.tr("模型"),
                self.tr("耗时"),
                self.tr("Tokens"),
            ]
        )

        header = self.table.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, QHeaderView.Fixed)
            header.setSectionResizeMode(1, QHeaderView.Fixed)
            header.setSectionResizeMode(2, QHeaderView.Stretch)  # 文件 - 自适应
            header.setSectionResizeMode(3, QHeaderView.Fixed)
            header.setSectionResizeMode(4, QHeaderView.Stretch)  # 模型 - 自适应
            header.setSectionResizeMode(5, QHeaderView.Fixed)
            header.setSectionResizeMode(6, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 130)  # 时间
        self.table.setColumnWidth(1, 100)  # 任务ID
        self.table.setColumnWidth(3, 90)  # 阶段
        self.table.setColumnWidth(5, 70)  # 耗时
        self.table.setColumnWidth(6, 70)  # Tokens

        v_header = self.table.verticalHeader()
        if v_header:
            v_header.setVisible(False)

        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setSelectionMode(self.table.SingleSelection)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)

        self.main_layout.addWidget(self.table)

    def _setup_footer(self):
        """底部：提示 + 记录数 + 分页"""
        footer = QHBoxLayout()
        footer.setSpacing(15)

        # 左侧：双击提示
        hint_label = CaptionLabel(self.tr("双击查看详情"))
        hint_label.setStyleSheet("color: gray;")
        footer.addWidget(hint_label)

        # 记录数
        self.status_label = BodyLabel(self.tr("共 0 条"))
        footer.addWidget(self.status_label)

        footer.addStretch()

        # 右侧：分页
        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.setEnabled(False)
        footer.addWidget(self.prev_btn)

        self.page_label = BodyLabel("1 / 1")
        footer.addWidget(self.page_label)

        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.setEnabled(False)
        footer.addWidget(self.next_btn)

        self.main_layout.addLayout(footer)

    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self._load_logs)
        self.clear_btn.clicked.connect(self._clear_logs)
        self.search_edit.textChanged.connect(self._filter_logs)
        self.table.doubleClicked.connect(self._show_detail)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn.clicked.connect(self._next_page)

    def _load_logs(self):
        """加载日志文件"""
        self.all_logs = []

        if not LLM_LOG_FILE.exists():
            self._update_table()
            return

        try:
            with open(LLM_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.all_logs.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            InfoBar.error(
                title=self.tr("错误"),
                content=str(e),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        self.all_logs.reverse()
        self._filter_logs()

    def _filter_logs(self):
        """根据搜索词过滤日志"""
        search_text = self.search_edit.text().lower()

        if not search_text:
            self.filtered_logs = self.all_logs.copy()
        else:
            self.filtered_logs = []
            for log in self.all_logs:
                model = log.get("request", {}).get("model", "").lower()
                task_id = log.get("task_id", "").lower()
                file_name = log.get("file_name", "").lower()
                stage = log.get("stage", "").lower()
                messages = json.dumps(log.get("request", {}).get("messages", []))
                response = json.dumps(log.get("response", {}))

                if (
                    search_text in model
                    or search_text in task_id
                    or search_text in file_name
                    or search_text in stage
                    or search_text in messages.lower()
                    or search_text in response.lower()
                ):
                    self.filtered_logs.append(log)

        self.current_page = 0
        self._update_table()

    def _update_table(self):
        """更新表格显示"""
        self.table.setRowCount(0)

        total_pages = max(1, (len(self.filtered_logs) + PAGE_SIZE - 1) // PAGE_SIZE)
        start_idx = self.current_page * PAGE_SIZE
        end_idx = min(start_idx + PAGE_SIZE, len(self.filtered_logs))

        for log in self.filtered_logs[start_idx:end_idx]:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 时间（不显示年份：MM-DD HH:MM:SS）
            time_str = log.get("time", "")
            if time_str and len(time_str) > 5:
                time_str = time_str[5:]  # 去掉 "YYYY-"
            self.table.setItem(row, 0, self._create_item(time_str))

            # 任务ID
            task_id = log.get("task_id", "") or "-"
            self.table.setItem(row, 1, self._create_item(task_id))

            # 文件
            file_name = log.get("file_name", "") or "-"
            self.table.setItem(row, 2, self._create_item(file_name, align_left=True))

            # 阶段
            stage = log.get("stage", "") or "-"
            self.table.setItem(row, 3, self._create_item(stage))

            # 模型
            model = log.get("request", {}).get("model", "未知")
            self.table.setItem(row, 4, self._create_item(model))

            # 耗时
            duration = log.get("duration_ms", 0) / 1000
            self.table.setItem(row, 5, self._create_item(f"{duration:.1f}s"))

            # 总 Tokens
            usage = log.get("response", {}).get("usage", {})
            total_tokens = usage.get("total_tokens", 0)
            if not total_tokens:
                total_tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            self.table.setItem(row, 6, self._create_item(str(total_tokens)))

        # 更新分页和统计
        self.page_label.setText(f"{self.current_page + 1} / {total_pages}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)
        self.status_label.setText(f"共 {len(self.filtered_logs)} 条")

    def _create_item(self, text: str, align_left: bool = False) -> QTableWidgetItem:
        """创建表格项"""
        item = QTableWidgetItem(text)
        if align_left:
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore
        else:
            item.setTextAlignment(Qt.AlignCenter)  # type: ignore
        return item

    def _show_detail(self, index):
        """显示日志详情"""
        actual_idx = self.current_page * PAGE_SIZE + index.row()
        if 0 <= actual_idx < len(self.filtered_logs):
            dialog = LogDetailDialog(self.filtered_logs[actual_idx], self)
            dialog.exec()

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_table()

    def _next_page(self):
        total_pages = (len(self.filtered_logs) + PAGE_SIZE - 1) // PAGE_SIZE
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._update_table()

    def _clear_logs(self):
        """清空日志"""
        w = MessageBox(
            self.tr("确认清空"),
            self.tr("确定要清空所有日志吗？此操作不可恢复。"),
            self,
        )
        if w.exec():
            try:
                if LLM_LOG_FILE.exists():
                    LLM_LOG_FILE.unlink()
                self.all_logs = []
                self.filtered_logs = []
                self._update_table()
                InfoBar.success(
                    title="",
                    content=self.tr("日志已清空"),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
            except Exception as e:
                InfoBar.error(
                    title=self.tr("错误"),
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
