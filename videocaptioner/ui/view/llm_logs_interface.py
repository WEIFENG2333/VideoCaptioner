"""LLM 请求日志页（排查工具）。

工具栏（搜索 + 刷新 + 清空）、一屏内的日志表格
（时间/任务ID/文件/阶段/模型/耗时/Tokens）、底部统计 + 分页；空日志时表格换成空态面板。
双击行打开完整 JSON 详情。全部用第一方 workbench 组件 + 主题 token，qfluent 仅作底层
TableWidget/PlainTextEdit 来源。
"""

import json
from typing import Any, Dict, List

from PyQt5.QtCore import QFileSystemWatcher, Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBar, InfoBarPosition

from videocaptioner.config import LLM_LOG_FILE, LOG_PATH
from videocaptioner.ui.common.app_icons import AppIcon, render_svg_icon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import AppDialog, ConfirmDialog
from videocaptioner.ui.components.workbench import (
    AppLineEdit,
    CompactButton,
    IconBox,
    RoundIconButton,
    SectionLabel,
    StatusPill,
    WorkbenchButton,
    WorkbenchPanel,
    apply_font,
)
from videocaptioner.ui.i18n import N_, tr

PAGE_SIZE = 50


class _LogTable(QTableWidget):
    """日志表格：构造时表格在隐藏的 stack 页上，Qt 首次显示会重新 show 行号竖表头，
    构造期的 setVisible(False) 不持久；故在每次 showEvent 后再隐藏一次，彻底去掉左侧行号槽。"""

    def showEvent(self, event):
        super().showEvent(event)
        self.verticalHeader().setVisible(False)


class LogDetailDialog(AppDialog):
    """日志详情：标题副行 + 元信息条（时间/阶段/耗时/Tokens/结果）+ 请求体 / 响应体并排，

    每块独立复制；请求失败时右侧切「错误响应」并染危险色。用第一方 AppDialog + workbench 风格实现。"""

    def __init__(self, log_entry: Dict[str, Any], parent=None):
        self.log_entry = log_entry
        super().__init__(tr("llmlog.detail.title"), icon=AppIcon.DOCUMENT, parent=parent, width=1000)
        self._build()

    def _is_failure(self) -> bool:
        status = self.log_entry.get("status", 0) or 0
        response = self.log_entry.get("response") or {}
        if isinstance(response, dict) and response.get("error"):
            return True
        if status:
            return not (200 <= status < 300)
        return not response  # 无状态码且响应为空，视为失败

    def _build(self):
        entry = self.log_entry
        request = entry.get("request", {}) or {}
        response = entry.get("response", {}) or {}
        model = request.get("model") or entry.get("model") or tr("llmlog.unknown")
        stage = entry.get("stage") or "-"
        file_name = entry.get("file_name") or "-"
        failed = self._is_failure()
        usage = response.get("usage") or {}
        ptok = usage.get("prompt_tokens", 0)
        ctok = usage.get("completion_tokens", 0)
        tokens = f"{ptok} / {ctok}" if (ptok or ctok) else "-"
        duration = entry.get("duration_ms", 0) / 1000

        # 标题副行：文件 · 阶段 · 模型
        subtitle = QLabel(" · ".join(x for x in (file_name, stage, model) if x and x != "-"))
        subtitle.setObjectName("logSubtitle")
        apply_font(subtitle, 13, 720)
        self.bodyLayout.addWidget(subtitle)

        # 元信息条
        strip = QHBoxLayout()
        strip.setSpacing(10)
        metas = [
            (tr("llmlog.meta.time"), entry.get("time", "-")),
            (tr("llmlog.meta.stage"), stage),
            (tr("llmlog.meta.duration"), f"{duration:.1f}s"),
            ("Tokens", tokens),
            (tr("llmlog.meta.result"), tr("llmlog.result.failed") if failed else tr("llmlog.result.done")),
        ]
        for idx, (label, value) in enumerate(metas):
            strip.addWidget(self._meta_item(label, value, result=(idx == len(metas) - 1), failed=failed))
        self.bodyLayout.addLayout(strip)

        # 请求体 / 响应体 并排（请求更宽，失败时右侧为错误响应）
        row = QHBoxLayout()
        row.setSpacing(12)
        req_panel, self.copyReqBtn = self._payload_panel(
            tr("llmlog.panel.request"), tr("llmlog.panel.request.desc"), request, danger=False
        )
        resp_panel, self.copyRespBtn = self._payload_panel(
            tr("llmlog.panel.error") if failed else tr("llmlog.panel.response"),
            tr("llmlog.panel.error.desc") if failed else tr("llmlog.panel.response.desc"),
            response,
            danger=failed,
        )
        row.addWidget(req_panel, 3)
        row.addWidget(resp_panel, 2)
        self.bodyLayout.addLayout(row, 1)
        self.copyReqBtn.clicked.connect(lambda: self._copy("request"))
        self.copyRespBtn.clicked.connect(lambda: self._copy("response"))

        # 底栏：提示 + 关闭
        hint = QLabel(tr("llmlog.detail.foot_hint"))
        hint.setObjectName("logFootHint")
        apply_font(hint, 12, 600)
        self.footerLayout.addWidget(hint)
        self.addFooterStretch()
        self.addFooterButton(tr("common.close"), kind="accent").clicked.connect(lambda: self.done(0))
        self.syncStyle()

    def _meta_item(self, label: str, value: str, *, result: bool = False, failed: bool = False) -> QFrame:
        card = QFrame(self.widget)
        card.setObjectName("logMeta")
        box = QVBoxLayout(card)
        box.setContentsMargins(13, 9, 13, 10)
        box.setSpacing(4)
        lab = QLabel(label, card)
        lab.setObjectName("logMetaLabel")
        apply_font(lab, 11, 840)
        val = QLabel(value, card)
        apply_font(val, 15, 780)
        val.setObjectName(("logResultFail" if failed else "logResultOk") if result else "logMetaValue")
        box.addWidget(lab)
        box.addWidget(val)
        return card

    def _payload_panel(self, title: str, desc: str, payload, *, danger: bool):
        palette = app_palette()
        panel = QFrame(self.widget)
        panel.setObjectName("logPanel")
        panel.setProperty("danger", "true" if danger else "false")
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QFrame(panel)
        head.setObjectName("logPanelHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 9, 11, 9)
        hl.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel(title, head)
        t.setObjectName("logPanelTitle")
        apply_font(t, 15, 820)
        d = QLabel(desc, head)
        d.setObjectName("logPanelDesc")
        apply_font(d, 11, 600)
        titles.addWidget(t)
        titles.addWidget(d)
        hl.addLayout(titles, 1)
        copy_btn = CompactButton(tr("common.copy"), AppIcon.COPY, head, pad_h=8)
        hl.addWidget(copy_btn, 0, Qt.AlignVCenter)  # type: ignore[arg-type]
        col.addWidget(head)

        code = QPlainTextEdit(panel)
        code.setObjectName("logCode")
        code.setReadOnly(True)
        code.setMinimumHeight(300)
        code.setFrameShape(QFrame.NoFrame)  # type: ignore[attr-defined]
        mono = QFont("SF Mono")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(12)
        code.setFont(mono)
        # 只读代码区背景走 QPalette（QSS background 到不了 viewport，会露白底）
        pal = code.palette()
        pal.setColor(QPalette.Base, QColor(palette.panel_deep))
        pal.setColor(QPalette.Text, QColor(palette.text))
        code.setPalette(pal)
        # 滚动条样式直接设在控件上（祖先样式表的后代选择器到不了原生滚动条）
        code.setStyleSheet(
            f"""
            QPlainTextEdit#logCode {{ background: transparent; border: none; padding: 6px 10px; }}
            QScrollBar:vertical {{ background: transparent; width: 7px; margin: 4px 2px; border: none; }}
            QScrollBar::handle:vertical {{ background: {palette.line}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{ height: 0; }}
            """
        )
        code.setPlainText(
            json.dumps(payload, indent=2, ensure_ascii=False) if payload else tr("llmlog.empty_payload")
        )
        col.addWidget(code, 1)
        return panel, copy_btn

    def extraStyleRules(self, palette) -> str:
        return f"""
            QLabel#logSubtitle {{ color: {palette.muted}; background: transparent; }}
            QLabel#logFootHint {{ color: {palette.subtle}; background: transparent; }}
            QFrame#logMeta {{
                background: {palette.card_surface};
                border: 1px solid {palette.line_soft};
                border-radius: 12px;
            }}
            QLabel#logMetaLabel {{ color: {palette.subtle}; background: transparent; }}
            QLabel#logMetaValue {{ color: {palette.text}; background: transparent; }}
            QLabel#logResultOk {{ color: {palette.accent_text}; background: transparent; }}
            QLabel#logResultFail {{ color: {palette.danger_fg}; background: transparent; }}
            QFrame#logPanel {{
                background: {palette.panel_deep};
                border: 1px solid {palette.line_soft};
                border-radius: 14px;
            }}
            QFrame#logPanel[danger="true"] {{
                border: 1px solid {rgba(palette.danger, 0.5)};
            }}
            QFrame#logPanelHead {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QLabel#logPanelTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#logPanelDesc {{ color: {palette.subtle}; background: transparent; }}
        """

    def _copy(self, key: str):
        text = json.dumps(self.log_entry.get(key, {}), indent=2, ensure_ascii=False)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        InfoBar.success("", tr("llmlog.copied"), parent=self.window(),
                        position=InfoBarPosition.TOP, duration=1500)


class LLMLogsInterface(QWidget):
    """LLM 请求日志界面。"""

    # (label, fixed_width, mode)；mode ∈ {fixed, stretch, content}
    # 时间/阶段/模型 按内容自适应（绝不截断，时间是固定格式必须完整显示）；文件做唯一弹性列吸收余宽；
    # 耗时/Tokens 定宽数字列。不设任务ID列：对用户无意义且占宽（搜索仍可匹配 task_id）。
    _COLUMNS = (
        (N_("llmlog.col.time"), 0, "content"),
        (N_("llmlog.col.file"), 0, "stretch"),
        (N_("llmlog.col.stage"), 0, "content"),
        (N_("llmlog.col.model"), 0, "content"),
        (N_("llmlog.col.duration"), 80, "fixed"),
        ("Tokens", 92, "fixed"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("llmLogsInterface")
        self.setWindowTitle(tr("llmlog.title"))
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]

        self.all_logs: List[Dict[str, Any]] = []
        self.filtered_logs: List[Dict[str, Any]] = []
        self.current_page = 0

        self._build_ui()
        self._connect_signals()
        self._load_logs()
        self._setup_file_watcher()

    # ---------------------------------------------------------------- 构建

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(14)
        root.addLayout(self._build_toolbar())

        self.contentStack = QStackedWidget()
        self.contentStack.addWidget(self._build_table())  # 0 表格
        self.contentStack.addWidget(self._build_empty())  # 1 空态
        root.addWidget(self.contentStack, 1)

        root.addLayout(self._build_footer())
        self._sync_style()

    def _build_toolbar(self) -> QHBoxLayout:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self.search_edit = AppLineEdit(height=44)
        self.search_edit.setPlaceholderText(tr("llmlog.search.placeholder"))
        self.search_edit.setMinimumWidth(320)
        self.search_action = self.search_edit.addAction(
            render_svg_icon(AppIcon.SEARCH, app_palette().muted, 16),
            QLineEdit.LeadingPosition,  # type: ignore[attr-defined]
        )
        toolbar.addWidget(self.search_edit, 1)

        self.empty_pill = StatusPill(tr("llmlog.no_records"), "neutral")
        self.empty_pill.setVisible(False)
        toolbar.addWidget(self.empty_pill)

        self.refresh_btn = WorkbenchButton(tr("llmlog.btn.refresh"), AppIcon.SYNC, height=44)
        self.clear_btn = WorkbenchButton(tr("llmlog.btn.clear"), AppIcon.DELETE, height=44)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.clear_btn)
        return toolbar

    def _build_table(self) -> QWidget:
        # 用原生 QTableWidget（_LogTable）而非 qfluent TableWidget：后者会在显示时强制
        # 重现行号竖表头（setVisible/setFixedWidth 都被覆盖），且暗色下交替行发白。样式全部自管。
        self.table = _LogTable()
        self.table.setObjectName("llmLogTable")
        self.table.setColumnCount(len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c[0]) for c in self._COLUMNS])

        header = self.table.horizontalHeader()
        if header:
            header.setFixedHeight(48)
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore[operator]
            header.setMinimumSectionSize(72)  # 拖窄时任何列都不塌到不可读
            modes = {
                "fixed": QHeaderView.Fixed,
                "stretch": QHeaderView.Stretch,
                "content": QHeaderView.ResizeToContents,
            }
            for i, (_label, width, mode) in enumerate(self._COLUMNS):
                header.setSectionResizeMode(i, modes[mode])
                if mode == "fixed":
                    self.table.setColumnWidth(i, width)
        v_header = self.table.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(54)
            v_header.setVisible(False)  # 原生表格不再强塞行号槽

        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setSelectionMode(self.table.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setFrameShape(self.table.NoFrame)
        return self.table

    def _build_empty(self) -> QWidget:
        panel = WorkbenchPanel()
        lay = panel.bodyLayout
        lay.addStretch(1)
        self.empty_mark = IconBox(AppIcon.HISTORY, panel, size=64)
        lay.addWidget(self.empty_mark, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        lay.addSpacing(16)
        self.empty_title = SectionLabel(tr("llmlog.empty.title"))
        apply_font(self.empty_title, 19, 860)
        self.empty_title.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        lay.addWidget(self.empty_title, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        lay.addSpacing(8)
        self.empty_hint = QLabel(tr("llmlog.empty.hint"))
        self.empty_hint.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
        apply_font(self.empty_hint, 13, 680)
        lay.addWidget(self.empty_hint, 0, Qt.AlignHCenter)  # type: ignore[arg-type]
        lay.addStretch(1)
        return panel

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.status_label = QLabel(tr("llmlog.status.total_zero"))
        apply_font(self.status_label, 13, 740)
        footer.addWidget(self.status_label)
        footer.addStretch(1)

        self.prev_btn = RoundIconButton(AppIcon.ARROW_LEFT)
        self.prev_btn.setEnabled(False)
        self.page_label = QLabel("1 / 1")
        apply_font(self.page_label, 13, 760)
        self.next_btn = RoundIconButton(AppIcon.RIGHT_ARROW)
        self.next_btn.setEnabled(False)
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_btn)
        return footer

    # ---------------------------------------------------------------- 样式

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_style()

    def _sync_style(self):
        palette = app_palette()
        self.setStyleSheet(f"QWidget#llmLogsInterface {{ background: {palette.bg}; }}")
        self.search_action.setIcon(render_svg_icon(AppIcon.SEARCH, palette.muted, 16))
        self.search_edit.syncStyle()
        self.refresh_btn.syncStyle()
        self.clear_btn.syncStyle()
        self.empty_pill.syncStyle()
        self.empty_mark.syncStyle()
        for label in (self.status_label, self.page_label):
            label.setStyleSheet(f"color: {palette.muted}; background: transparent;")
        self.empty_title.setStyleSheet(f"color: {palette.text}; background: transparent;")
        self.empty_hint.setStyleSheet(f"color: {palette.muted}; background: transparent;")
        self._style_table(palette)

    def _style_table(self, palette):
        selection_bg = rgba(palette.accent, 0.08)
        self.table.setStyleSheet(
            f"""
            QTableView#llmLogTable {{
                background: {palette.panel};
                border: 1px solid {palette.line};
                border-radius: 14px;
                color: {palette.muted};
                font-size: 14px;
                selection-background-color: {selection_bg};
                selection-color: {palette.text};
                outline: none;
            }}
            QTableView#llmLogTable::item {{
                padding: 0 12px;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QTableView#llmLogTable::item:selected {{
                background: {selection_bg}; color: {palette.text};
            }}
            """
        )
        header = self.table.horizontalHeader()
        if header:
            header.setStyleSheet(
                f"""
                QHeaderView {{ background: transparent; border: none; }}
                QHeaderView::section {{
                    background: {palette.panel_deep};
                    color: {palette.subtle};
                    border: none;
                    border-bottom: 1px solid {palette.line_soft};
                    padding-left: 12px;
                    font-size: 13px;
                    font-weight: bold;
                }}
                /* 表头不透明矩形会盖住面板左右上角圆角；首尾段同步圆角 (14 面板半径 - 1 边框) */
                QHeaderView::section:first {{ border-top-left-radius: 13px; }}
                QHeaderView::section:last {{ border-top-right-radius: 13px; }}
                """
            )
        scrollbar = self.table.verticalScrollBar()
        if scrollbar:
            scrollbar.setStyleSheet(
                f"""
                QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; border: none; }}
                QScrollBar::handle:vertical {{ background: {palette.line}; border-radius: 3px; min-height: 32px; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
                """
            )

    # ---------------------------------------------------------------- 信号 / 数据

    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.clear_btn.clicked.connect(self._clear_logs)
        self.search_edit.textChanged.connect(self._filter_logs)
        self.table.doubleClicked.connect(self._show_detail)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn.clicked.connect(self._next_page)

    def _setup_file_watcher(self):
        self.file_watcher = QFileSystemWatcher(self)
        if LLM_LOG_FILE.exists():
            self.file_watcher.addPath(str(LLM_LOG_FILE))
        self.file_watcher.addPath(str(LOG_PATH))
        self.file_watcher.fileChanged.connect(self._on_file_changed)
        self.file_watcher.directoryChanged.connect(self._on_dir_changed)

    def _on_file_changed(self, path: str):
        self._load_logs()
        if LLM_LOG_FILE.exists() and str(LLM_LOG_FILE) not in self.file_watcher.files():
            self.file_watcher.addPath(str(LLM_LOG_FILE))

    def _on_dir_changed(self, path: str):
        if LLM_LOG_FILE.exists() and str(LLM_LOG_FILE) not in self.file_watcher.files():
            self.file_watcher.addPath(str(LLM_LOG_FILE))
            self._load_logs()

    def _on_refresh_clicked(self):
        self._load_logs()
        InfoBar.success("", tr("llmlog.refresh.success"), parent=self,
                        position=InfoBarPosition.TOP, duration=1000)

    def _load_logs(self):
        self.all_logs = []
        if not LLM_LOG_FILE.exists():
            self._filter_logs()
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
            InfoBar.error(tr("common.error"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)
            return
        self.all_logs.reverse()
        self._filter_logs()

    def _filter_logs(self):
        search_text = self.search_edit.text().lower()
        if not search_text:
            self.filtered_logs = self.all_logs.copy()
        else:
            self.filtered_logs = [log for log in self.all_logs if self._matches(log, search_text)]
        self.current_page = 0
        self._update_view()

    @staticmethod
    def _matches(log: Dict[str, Any], text: str) -> bool:
        request = log.get("request", {})
        haystacks = (
            request.get("model", ""),
            log.get("task_id", ""),
            log.get("file_name", ""),
            log.get("stage", ""),
            json.dumps(request.get("messages", []), ensure_ascii=False),
            json.dumps(log.get("response", {}), ensure_ascii=False),
        )
        return any(text in str(h).lower() for h in haystacks)

    # ---------------------------------------------------------------- 视图

    def _update_view(self):
        has_logs = bool(self.filtered_logs)
        self.contentStack.setCurrentIndex(0 if has_logs else 1)
        self.empty_pill.setVisible(not self.all_logs)
        if not has_logs:
            self._apply_empty_text()
        self._fill_table()

    def _apply_empty_text(self):
        if self.all_logs:  # 有日志但筛选无结果
            self.empty_title.setText(tr("llmlog.empty.no_match.title"))
            self.empty_hint.setText(tr("llmlog.empty.no_match.hint"))
        else:
            self.empty_title.setText(tr("llmlog.empty.title"))
            self.empty_hint.setText(tr("llmlog.empty.hint"))

    def _fill_table(self):
        self.table.setRowCount(0)
        total_pages = max(1, (len(self.filtered_logs) + PAGE_SIZE - 1) // PAGE_SIZE)
        start = self.current_page * PAGE_SIZE
        for log in self.filtered_logs[start:start + PAGE_SIZE]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            time_str = log.get("time", "")
            if len(time_str) > 5:
                time_str = time_str[5:]  # 去掉 "YYYY-"
            usage = log.get("response", {}).get("usage") or {}
            total_tokens = usage.get("total_tokens") or (
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            )
            values = (
                time_str,
                log.get("file_name", "") or "-",
                log.get("stage", "") or "-",
                log.get("request", {}).get("model", tr("llmlog.unknown")),
                f"{log.get('duration_ms', 0) / 1000:.1f}s",
                str(total_tokens),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                # 耗时/Tokens 是数字，右对齐更易读；其余左对齐
                if col in (4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[operator]
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # type: ignore[operator]
                item.setToolTip(value)  # 极窄时仍可悬停看全文，省略号不丢信息
                self.table.setItem(row, col, item)

        self.page_label.setText(f"{self.current_page + 1} / {total_pages}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)
        self.status_label.setText(self._status_text())

    def _status_text(self) -> str:
        total = len(self.all_logs)
        shown = len(self.filtered_logs)
        if total == 0:
            return tr("llmlog.status.total_zero")
        if shown != total:
            return tr("llmlog.status.filtered", total=total, shown=shown)
        return tr("llmlog.status.total", total=total)

    def _show_detail(self, index):
        actual_idx = self.current_page * PAGE_SIZE + index.row()
        if 0 <= actual_idx < len(self.filtered_logs):
            LogDetailDialog(self.filtered_logs[actual_idx], self).exec()

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._fill_table()

    def _next_page(self):
        total_pages = (len(self.filtered_logs) + PAGE_SIZE - 1) // PAGE_SIZE
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._fill_table()

    def _clear_logs(self):
        dialog = ConfirmDialog(
            tr("llmlog.clear.confirm_title"),
            tr("llmlog.clear.confirm_body"),
            self,
            confirm_text=tr("llmlog.clear.confirm_btn"),
            danger=True,
            icon=AppIcon.DELETE,
        )
        if not dialog.exec():
            return
        try:
            if LLM_LOG_FILE.exists():
                LLM_LOG_FILE.unlink()
            self.all_logs = []
            self.filtered_logs = []
            self._update_view()
            InfoBar.success("", tr("llmlog.clear.success"), parent=self,
                            position=InfoBarPosition.TOP, duration=2000)
        except Exception as e:
            InfoBar.error(tr("common.error"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)
