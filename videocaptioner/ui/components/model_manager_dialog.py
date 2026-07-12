"""本地模型管理弹窗。

结构：标题栏 → 引擎页签（单引擎平台隐藏）→ 运行程序区（按平台给出
变体行：检测 / 直接下载 / 复制命令 / 打开页面）→ 模型表（文件名 +
用途 + 大小 + 状态点 + 下载/继续/删除/取消）→ 底栏（打开模型目录 /
打开程序目录 / 关闭）。

状态约定：
- 同一时刻只跑一个下载任务（模型或程序），其余操作按钮禁用；
- 当前配置选中的已下载模型显示「当前」且不可删除；
- 有 .part 残留的模型显示「继续」（断点续传）；
- 关闭弹窗即取消进行中的下载（.part 保留）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videocaptioner.config import BIN_PATH, MODEL_PATH
from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.download import (
    ModelSpec,
    ProgramVariant,
    has_partial_download,
    iter_models,
    model_install_state,
    program_variants,
    remove_model,
)
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import AppDialog, ConfirmDialog
from videocaptioner.ui.components.workbench import (
    AccentButton,
    CompactButton,
    DangerButton,
    IconBox,
    ProgressBarLine,
    SectionLabel,
    apply_font,
    draw_rounded_surface,
    icon_pixmap,
)
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.artifact_download_thread import (
    ArtifactDownloadThread,
    model_download_thread,
    program_download_thread,
)

KIND_TITLES = {"whisper-cpp": "Whisper CPP", "faster-whisper": "Faster Whisper"}
SIZE_COLUMN = 86
STATUS_COLUMN = 92
ACTION_COLUMN = 104


def available_model_kinds(platform: str | None = None) -> list[str]:
    """当前平台可用的本地引擎；macOS 不出现 Faster Whisper。"""
    plat = platform or sys.platform
    kinds = ["whisper-cpp"]
    if plat.startswith("win"):
        kinds.append("faster-whisper")
    return kinds


# ---------------------------------------------------------------------------
# 基础小件
# ---------------------------------------------------------------------------


class _StatusDot(QWidget):
    """状态点：小圆点 + 文字。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.dot = QLabel(self)
        self.dot.setFixedSize(7, 7)
        self.textLabel = QLabel(self)
        self.textLabel.setObjectName("statusDotText")
        apply_font(self.textLabel, 12, 720)
        layout.addWidget(self.dot)
        layout.addWidget(self.textLabel)
        layout.addStretch(1)
        self._level = "neutral"
        self.setState("", "neutral")

    def setState(self, text: str, level: str):
        self._level = level
        self.textLabel.setText(text)
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        color = {
            "ok": palette.accent_text,
            "missing": palette.danger_fg,
            "neutral": palette.subtle,
        }.get(self._level, palette.subtle)
        dot_color = {
            "ok": palette.accent,
            "missing": palette.danger,
            "neutral": palette.subtle,
        }.get(self._level, palette.subtle)
        self.dot.setStyleSheet(
            f"background: {dot_color}; border-radius: 3px; border: none;"
        )
        self.textLabel.setStyleSheet(f"color: {color}; background: transparent; border: none;")


class _EngineTabs(QFrame):
    """引擎页签：均分两块，单引擎时整体隐藏。"""

    changed = pyqtSignal(str)

    def __init__(self, kinds: list[str], current: str, parent=None):
        super().__init__(parent)
        self._tabs: dict[str, QLabel] = {}
        self._current = current
        self.setFixedHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)
        for kind in kinds:
            tab = QLabel(KIND_TITLES[kind], self)
            tab.setObjectName("engineTab")
            tab.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
            tab.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]
            apply_font(tab, 14, 800)
            tab.mousePressEvent = lambda _e, k=kind: self._on_tab(k)  # type: ignore[method-assign]
            layout.addWidget(tab, 1)
            self._tabs[kind] = tab
        self.syncStyle()

    def _on_tab(self, kind: str):
        if kind != self._current:
            self._current = kind
            self.syncStyle()
            self.changed.emit(kind)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        for kind, tab in self._tabs.items():
            active = kind == self._current
            bg = palette.field if active else "transparent"
            border = palette.line if active else "transparent"
            color = palette.text if active else palette.muted
            tab.setStyleSheet(
                f"""
                QLabel#engineTab {{
                    background: {bg};
                    border: 1px solid {border};
                    border-radius: 9px;
                    color: {color};
                }}
                """
            )
        self.setStyleSheet("QFrame { background: transparent; border: none; }")


# 小节标题用第一方 SectionLabel（本页历史别名，保留调用点不变）
_SectionLabel = SectionLabel


# ---------------------------------------------------------------------------
# 运行程序行 / 模型行
# ---------------------------------------------------------------------------


class _ProgramRow(QFrame):
    """运行程序行：图标盒 + 名称/说明 + 状态点 + 操作。"""

    actionRequested = pyqtSignal(object)  # ProgramVariant
    recheckRequested = pyqtSignal()

    def __init__(self, variant: ProgramVariant, parent=None):
        super().__init__(parent)
        self.variant = variant
        self.setFixedHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 0, 13, 0)
        layout.setSpacing(12)
        layout.addWidget(IconBox(AppIcon.TERMINAL, self))

        column = QVBoxLayout()
        column.setSpacing(3)
        self.nameLabel = QLabel(variant.title, self)
        self.nameLabel.setObjectName("rowName")
        apply_font(self.nameLabel, 14, 820)
        column.addWidget(self.nameLabel)
        self.descLabel = QLabel("", self)
        self.descLabel.setObjectName("rowDesc")
        apply_font(self.descLabel, 12, 650)
        column.addWidget(self.descLabel)
        layout.addLayout(column, 1)
        layout.setAlignment(column, Qt.AlignVCenter)  # type: ignore[arg-type]

        self.status = _StatusDot(self)
        self.status.setFixedWidth(STATUS_COLUMN)
        layout.addWidget(self.status)

        self.actionButton = AccentButton("", None, self)
        self.actionButton.clicked.connect(lambda: self.actionRequested.emit(self.variant))
        layout.addWidget(self.actionButton)
        self.recheckButton = CompactButton(tr("modelmgr.program.recheck"), AppIcon.SYNC, self)
        self.recheckButton.clicked.connect(self.recheckRequested)
        layout.addWidget(self.recheckButton)
        self.syncStyle()

    def refresh(self, busy: bool):
        status = self.variant.detect()
        if status.installed:
            self.nameLabel.setText(self.variant.title)
            self.descLabel.setText(tr("modelmgr.program.found", name=status.name or ""))
            self.descLabel.setToolTip(status.path or "")
            self.status.setState(tr("modelmgr.program.available"), "ok")
            self.actionButton.hide()
        else:
            self.nameLabel.setText(self.variant.title)
            self.descLabel.setText(self.variant.description_missing)
            self.descLabel.setToolTip("")
            self.status.setState(tr("modelmgr.program.missing"), "missing")
            if self.variant.download is not None:
                self.actionButton.setText(tr("modelmgr.action.download"))
                self.actionButton.setIcon(AppIcon.DOWNLOAD)
                self.actionButton.show()
            elif self.variant.command:
                self.actionButton.hide()  # 命令行在下方 _CommandRow 展示
            elif self.variant.link:
                self.actionButton.setText(tr("modelmgr.program.open_page"))
                self.actionButton.setIcon(AppIcon.LINK)
                self.actionButton.show()
            else:
                self.actionButton.hide()
        self.actionButton.setEnabled(not busy)
        self.recheckButton.setEnabled(not busy)

    def showDownloading(self):
        self.status.setState(tr("modelmgr.status.downloading"), "neutral")
        self.actionButton.setText(tr("common.cancel"))
        self.actionButton.setIcon(AppIcon.CANCEL)
        self.actionButton.setEnabled(True)
        self.actionButton.show()
        self.recheckButton.setEnabled(False)

    def setProgressText(self, message: str):
        self.descLabel.setText(message)

    def paintEvent(self, event):
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame {{ background: transparent; border: none; }}
            QLabel#rowName {{ color: {palette.text}; background: transparent; }}
            QLabel#rowDesc {{ color: {palette.subtle}; background: transparent; }}
            """
        )


class _CommandRow(QFrame):
    """安装命令行：命令文本 + 复制按钮。"""

    def __init__(self, command: str, parent=None):
        super().__init__(parent)
        self.command = command
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 9, 0)
        layout.setSpacing(10)
        self.commandLabel = QLabel(command, self)
        self.commandLabel.setObjectName("commandText")
        self.commandLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)  # type: ignore[arg-type]
        apply_font(self.commandLabel, 13, 700)
        layout.addWidget(self.commandLabel, 1)
        self.copyButton = AccentButton(tr("modelmgr.command.copy"), AppIcon.COPY, self)
        self.copyButton.clicked.connect(self._copy)
        layout.addWidget(self.copyButton)
        self.syncStyle()

    def _copy(self):
        QApplication.clipboard().setText(self.command)
        from qfluentwidgets import InfoBar

        InfoBar.success(
            tr("modelmgr.command.copied_title"),
            tr("modelmgr.command.copied_body"),
            duration=INFOBAR_DURATION_WARNING,
            parent=self.window(),
        )

    def paintEvent(self, event):
        palette = app_palette()
        draw_rounded_surface(self, palette.field, palette.line, 12)
        super().paintEvent(event)

    def syncStyle(self):
        palette = app_palette()
        self.setStyleSheet(
            f"""
            QFrame {{ background: transparent; border: none; }}
            QLabel#commandText {{ color: {palette.text}; background: transparent; }}
            """
        )


class _ModelRow(QFrame):
    """模型行：图标盒 + 文件名/用途 + 大小 + 状态点 + 操作（或下载进度）。"""

    downloadRequested = pyqtSignal(object)
    removeRequested = pyqtSignal(object)
    cancelRequested = pyqtSignal()

    def __init__(self, spec: ModelSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._last = False
        self.setObjectName("modelRow")
        self.setFixedHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 0, 13, 0)
        layout.setSpacing(12)
        icon = AppIcon.FILE if spec.kind == "whisper-cpp" else AppIcon.DOCUMENT
        layout.addWidget(IconBox(icon, self))

        column = QVBoxLayout()
        column.setSpacing(3)
        self.nameLabel = QLabel(spec.display_name, self)
        self.nameLabel.setObjectName("rowName")
        apply_font(self.nameLabel, 14, 820)
        column.addWidget(self.nameLabel)
        self.descLabel = QLabel(spec.description, self)
        self.descLabel.setObjectName("rowDesc")
        apply_font(self.descLabel, 12, 650)
        column.addWidget(self.descLabel)
        layout.addLayout(column, 1)
        layout.setAlignment(column, Qt.AlignVCenter)  # type: ignore[arg-type]

        self.sizeLabel = QLabel(spec.size_text, self)
        self.sizeLabel.setObjectName("rowSize")
        self.sizeLabel.setFixedWidth(SIZE_COLUMN)
        apply_font(self.sizeLabel, 13, 720)
        layout.addWidget(self.sizeLabel)

        self.status = _StatusDot(self)
        self.status.setFixedWidth(STATUS_COLUMN)
        layout.addWidget(self.status)

        # 进度区（下载中替代 大小+状态 列）
        self.progressLine = ProgressBarLine(self)
        self.progressLine.setFixedWidth(132)
        self.progressLine.hide()
        layout.addWidget(self.progressLine)
        self.percentLabel = QLabel("", self)
        self.percentLabel.setObjectName("rowSize")
        self.percentLabel.setMinimumWidth(40)
        self.percentLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore[arg-type]
        apply_font(self.percentLabel, 12, 750)
        self.percentLabel.hide()
        layout.addWidget(self.percentLabel)

        # 操作列：固定宽度容器，三种按钮切换，行宽不抖
        action_host = QWidget(self)
        action_host.setFixedWidth(ACTION_COLUMN)
        action_layout = QHBoxLayout(action_host)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addStretch(1)
        self.downloadButton = AccentButton(tr("modelmgr.action.download"), AppIcon.DOWNLOAD, action_host)
        self.downloadButton.clicked.connect(lambda: self.downloadRequested.emit(self.spec))
        action_layout.addWidget(self.downloadButton)
        self.removeButton = DangerButton(tr("common.delete"), None, action_host)
        self.removeButton.clicked.connect(lambda: self.removeRequested.emit(self.spec))
        action_layout.addWidget(self.removeButton)
        self.currentButton = CompactButton(tr("modelmgr.action.current"), None, action_host)
        self.currentButton.setEnabled(False)
        action_layout.addWidget(self.currentButton)
        self.cancelButton = CompactButton(tr("common.cancel"), None, action_host)
        self.cancelButton.clicked.connect(self.cancelRequested)
        action_layout.addWidget(self.cancelButton)
        layout.addWidget(action_host)
        self.syncStyle()

    def _show_action(self, widget: QWidget | None):
        for button in (self.downloadButton, self.removeButton, self.currentButton, self.cancelButton):
            button.setVisible(button is widget)

    def _show_progress(self, downloading: bool):
        self.progressLine.setVisible(downloading)
        self.percentLabel.setVisible(downloading)
        self.sizeLabel.setVisible(not downloading)
        self.status.setVisible(not downloading)

    def showState(self, state: str, *, busy: bool, is_current: bool):
        """state: installed / absent / partial。busy=有任务在跑。"""
        self._show_progress(False)
        self.descLabel.setText(self.spec.description)
        if state == "installed":
            self.status.setState(tr("modelmgr.status.installed"), "ok")
            if is_current:
                self._show_action(self.currentButton)
            else:
                self._show_action(self.removeButton)
                self.removeButton.setEnabled(not busy)
        elif state == "partial":
            self.status.setState(tr("modelmgr.status.paused"), "neutral")
            self.downloadButton.setText(tr("modelmgr.action.resume"))
            self.downloadButton.setIcon(AppIcon.DOWNLOAD)
            self._show_action(self.downloadButton)
            self.downloadButton.setEnabled(not busy)
        else:
            self.status.setState(tr("modelmgr.status.pending"), "neutral")
            self.downloadButton.setText(tr("modelmgr.action.download"))
            self.downloadButton.setIcon(AppIcon.DOWNLOAD)
            self._show_action(self.downloadButton)
            self.downloadButton.setEnabled(not busy)

    def showDownloading(self):
        self._show_progress(True)
        self.progressLine.setValue(0)
        self.percentLabel.setText("0%")
        self.descLabel.setText(tr("modelmgr.progress.connecting"))
        self._show_action(self.cancelButton)
        self.cancelButton.setEnabled(True)

    def setProgress(self, percent: int, message: str):
        if percent >= 0:
            self.progressLine.setValue(percent)
            self.percentLabel.setText(f"{percent}%")
        self.descLabel.setText(message)

    def setLast(self, last: bool):
        self._last = last
        self.syncStyle()

    def syncStyle(self):
        palette = app_palette()
        border = "none" if self._last else f"1px solid {palette.line_soft}"
        self.setStyleSheet(
            f"""
            QFrame#modelRow {{ background: transparent; border: none; border-bottom: {border}; }}
            QFrame {{ background: transparent; border: none; }}
            QLabel#rowName {{ color: {palette.text}; background: transparent; }}
            QLabel#rowDesc {{ color: {palette.subtle}; background: transparent; }}
            QLabel#rowSize {{ color: {palette.muted}; background: transparent; }}
            """
        )


# ---------------------------------------------------------------------------
# 弹窗
# ---------------------------------------------------------------------------


class ModelManagerDialog(AppDialog):
    """本地模型管理：运行程序 + 模型下载/删除，单任务串行。"""

    modelsChanged = pyqtSignal()

    def __init__(self, kind: str = "whisper-cpp", parent: QWidget | None = None):
        kinds = available_model_kinds()
        self._kinds = kinds
        self._kind = kind if kind in kinds else kinds[0]
        self._thread: ArtifactDownloadThread | None = None
        self._active_model: _ModelRow | None = None
        self._active_program: _ProgramRow | None = None
        self._model_rows: dict[str, list[_ModelRow]] = {}
        self._program_rows: dict[str, list[_ProgramRow]] = {}
        self._command_rows: dict[str, _CommandRow] = {}
        self._containers: dict[str, QWidget] = {}

        super().__init__(tr("modelmgr.title"), icon=AppIcon.FOLDER_ADD, parent=parent, width=720)
        self._build_ui()
        self._switch_kind(self._kind)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        card = self.widget
        layout = self.bodyLayout

        # 引擎页签
        self.engineTabs = _EngineTabs(self._kinds, self._kind, card)
        self.engineTabs.changed.connect(self._switch_kind)
        self.engineTabs.setVisible(len(self._kinds) > 1)
        layout.addWidget(self.engineTabs)

        # 每个引擎一个内容容器
        for kind in self._kinds:
            container = QWidget(card)
            column = QVBoxLayout(container)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(10)

            column.addWidget(_SectionLabel(tr("modelmgr.section.programs"), container))
            program_rows = []
            for variant in program_variants(kind):
                row = _ProgramRow(variant, container)
                row.actionRequested.connect(self._on_program_action)
                row.recheckRequested.connect(lambda r=row: self._on_recheck(r))
                column.addWidget(row)
                program_rows.append(row)
            self._program_rows[kind] = program_rows
            command = next(
                (v.command for v in program_variants(kind) if v.command), None
            )
            if command:
                command_row = _CommandRow(command, container)
                column.addWidget(command_row)
                self._command_rows[kind] = command_row

            column.addSpacing(2)
            column.addWidget(_SectionLabel(tr("modelmgr.section.models"), container))
            table = QFrame(container)
            table.setObjectName("modelTable")
            table_layout = QVBoxLayout(table)
            table_layout.setContentsMargins(0, 0, 0, 0)
            table_layout.setSpacing(0)
            table_layout.addWidget(self._build_table_head(table))

            list_host = QWidget(table)
            list_layout = QVBoxLayout(list_host)
            list_layout.setContentsMargins(0, 0, 0, 0)
            list_layout.setSpacing(0)
            rows = []
            for spec in iter_models(kind):
                row = _ModelRow(spec, list_host)
                row.downloadRequested.connect(self._on_model_download)
                row.removeRequested.connect(self._on_model_remove)
                row.cancelRequested.connect(self._cancel_active)
                list_layout.addWidget(row)
                rows.append(row)
            if rows:
                rows[-1].setLast(True)
            self._model_rows[kind] = rows

            scroll = QScrollArea(table)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[arg-type]
            scroll.setWidget(list_host)
            # 最多露 3 行半：弹窗总高留在 ~700 内，半行提示下方还有内容可滚
            scroll.setFixedHeight(min(len(rows) * 64, 3 * 64 + 32) + 6)
            self._style_scroll(scroll)
            table_layout.addWidget(scroll)
            column.addWidget(table)
            container.hide()
            layout.addWidget(container)
            self._containers[kind] = container

        # 底栏：模型与程序装在不同目录，各给一个直达入口
        self.openModelDirButton = self.addFooterButton(
            tr("modelmgr.footer.open_model_dir"), icon=AppIcon.FOLDER
        )
        self.openModelDirButton.setToolTip(str(MODEL_PATH))
        self.openModelDirButton.clicked.connect(
            lambda: self._open_dir(self._models_dir(self._kind))
        )
        self.openProgramDirButton = self.addFooterButton(
            tr("modelmgr.footer.open_program_dir"), icon=AppIcon.FOLDER
        )
        self.openProgramDirButton.setToolTip(str(BIN_PATH))
        self.openProgramDirButton.clicked.connect(lambda: self._open_dir(Path(BIN_PATH)))
        self.addFooterStretch()
        self.dismissButton = self.addFooterButton(tr("common.close"))
        self.dismissButton.clicked.connect(lambda: self.done(0))
        self.syncStyle()

    def _build_table_head(self, parent: QWidget) -> QFrame:
        head = QFrame(parent)
        head.setObjectName("modelTableHead")
        head.setFixedHeight(36)
        layout = QHBoxLayout(head)
        layout.setContentsMargins(13, 0, 13, 0)
        layout.setSpacing(12)
        for text, width in (
            (tr("modelmgr.col.model"), None),
            (tr("modelmgr.col.size"), SIZE_COLUMN),
            (tr("modelmgr.col.status"), STATUS_COLUMN),
            (tr("modelmgr.col.action"), ACTION_COLUMN),
        ):
            label = QLabel(text, head)
            label.setObjectName("modelTableHeadText")
            apply_font(label, 12, 780)
            if width is None:
                layout.addWidget(label, 1)
            else:
                label.setFixedWidth(width)
                layout.addWidget(label)
        return head

    def _style_scroll(self, scroll: QScrollArea):
        palette = app_palette()
        scrollbar_rules = f"""
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 3px; }}
            QScrollBar::handle:vertical {{
                background: {rgba(palette.muted, 0.32)};
                border-radius: 2px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; width: 0; background: transparent; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """
        # 规则同时设到 area（关掉 macOS transient 浮层）与 scrollbar 本体
        # （qfluent 主题样式会覆盖仅写在容器里的滚动条规则）
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scrollbar_rules
        )
        scroll.verticalScrollBar().setStyleSheet(scrollbar_rules)
        scroll.widget().setStyleSheet("background: transparent;")

    def extraStyleRules(self, palette) -> str:
        return f"""
            QFrame#modelTable {{
                background: transparent;
                border: 1px solid {palette.line_soft};
                border-radius: 12px;
            }}
            QFrame#modelTableHead {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QLabel#modelTableHeadText {{ color: {palette.subtle}; background: transparent; }}
            """

    def syncStyle(self):
        super().syncStyle()
        if hasattr(self, "footIcon"):
            self.footIcon.setPixmap(icon_pixmap(AppIcon.FOLDER, app_palette().muted, 15))

    # ------------------------------------------------------------- 状态刷新

    @property
    def _busy(self) -> bool:
        return self._thread is not None

    def _switch_kind(self, kind: str):
        self._kind = kind
        for name in self._kinds:
            self._containers[name].setVisible(name == kind)
        self._refresh_current()
        self.widget.adjustSize()

    def _refresh_current(self):
        models_dir = self._models_dir(self._kind)
        current_name = self._current_model_name(self._kind)
        for row in self._model_rows[self._kind]:
            if row is self._active_model:
                continue
            if model_install_state(row.spec, models_dir):
                state = "installed"
            elif has_partial_download(row.spec, models_dir):
                state = "partial"
            else:
                state = "absent"
            row.showState(
                state,
                busy=self._busy,
                is_current=state == "installed" and row.spec.name == current_name,
            )
        missing_command = False
        for row in self._program_rows[self._kind]:
            if row is self._active_program:
                continue
            row.refresh(busy=self._busy)
            if not row.variant.detect().installed and row.variant.command:
                missing_command = True
        command_row = self._command_rows.get(self._kind)
        if command_row is not None:
            command_row.setVisible(missing_command)
            command_row.copyButton.setEnabled(not self._busy)
        self.widget.adjustSize()

    @staticmethod
    def _models_dir(kind: str) -> Path:
        if kind == "faster-whisper":
            from videocaptioner.ui.common.config import cfg

            return Path(cfg.faster_whisper_model_dir.value or MODEL_PATH)
        return Path(MODEL_PATH)

    @staticmethod
    def _current_model_name(kind: str) -> str:
        from videocaptioner.ui.common.config import cfg

        field = cfg.whisper_model if kind == "whisper-cpp" else cfg.faster_whisper_model
        return str(getattr(field.value, "value", field.value))

    # ------------------------------------------------------------- 模型操作

    def _on_model_download(self, spec: ModelSpec):
        if self._busy:
            return
        row = next((r for r in self._model_rows[spec.kind] if r.spec.key == spec.key), None)
        if row is None:
            return
        thread = model_download_thread(spec, self._models_dir(spec.kind), self)
        self._thread = thread
        self._active_model = row
        row.showDownloading()
        thread.progress.connect(row.setProgress)
        thread.completed.connect(lambda _path, s=spec: self._on_download_done(s))
        thread.error.connect(self._on_download_error)
        thread.finished.connect(self._on_thread_finished)
        self._refresh_current()
        thread.start()

    def _on_model_remove(self, spec: ModelSpec):
        if self._busy:
            return
        box = ConfirmDialog(
            tr("modelmgr.remove.title"),
            tr("modelmgr.remove.body", name=spec.display_name, size=spec.size_text),
            self,
            confirm_text=tr("common.delete"),
            danger=True,
            icon=AppIcon.DELETE,
        )
        if not box.exec():
            return
        try:
            remove_model(spec, self._models_dir(spec.kind))
        except OSError as exc:
            self._error(tr("modelmgr.remove.failed"), str(exc))
            return
        self._info(tr("modelmgr.remove.done"), spec.display_name)
        self.modelsChanged.emit()
        self._refresh_current()

    # ------------------------------------------------------------- 程序操作

    def _on_program_action(self, variant: ProgramVariant):
        row = next(
            (r for r in self._program_rows[self._kind] if r.variant is variant), None
        )
        if row is not None and row is self._active_program:
            self._cancel_active()
            return
        if self._busy:
            return
        if variant.download is not None:
            self._start_program_download(variant, row)
        elif variant.link:
            QDesktopServices.openUrl(QUrl(variant.link))
            self._info(tr("modelmgr.program.opened_title"), tr("modelmgr.program.opened_body"))

    def _on_recheck(self, row: _ProgramRow):
        self._refresh_current()
        status = row.variant.detect()
        if status.installed:
            self._info(
                tr("modelmgr.recheck.available_title"),
                tr("modelmgr.recheck.available_body", name=status.name or row.variant.title),
            )
        else:
            self._warn(
                tr("modelmgr.recheck.missing_title"),
                row.variant.description_missing,
            )

    def _start_program_download(self, variant: ProgramVariant, row: _ProgramRow | None):
        if variant.download is None or row is None:
            return
        thread = program_download_thread(variant.download, Path(BIN_PATH), self)
        self._thread = thread
        self._active_program = row
        row.showDownloading()
        thread.progress.connect(lambda _p, message, r=row: r.setProgressText(message))
        thread.completed.connect(self._on_program_downloaded)
        thread.error.connect(self._on_download_error)
        thread.finished.connect(self._on_thread_finished)
        self._refresh_current()
        thread.start()

    def _on_program_downloaded(self, path: str):
        if self._kind == "faster-whisper":
            from videocaptioner.ui.common.config import cfg

            cfg.set(cfg.faster_whisper_program, Path(path).name)
        self._info(tr("modelmgr.program.ready_title"), tr("modelmgr.program.ready_body"))

    # ------------------------------------------------------------- 任务收尾

    def _on_download_done(self, spec: ModelSpec):
        self._info(tr("modelmgr.download.done_title"), tr("modelmgr.download.done_body", name=spec.display_name))
        self.modelsChanged.emit()

    def _on_download_error(self, message: str):
        self._error(tr("modelmgr.download.failed"), message)

    def _on_thread_finished(self):
        thread = self._thread
        self._thread = None
        self._active_model = None
        self._active_program = None
        if thread is not None:
            thread.deleteLater()
        self._refresh_current()

    def _cancel_active(self):
        if self._thread is not None:
            self._thread.stop()

    def done(self, code: int):  # noqa: A003
        # 关闭即取消进行中的下载（.part 保留，下次显示「继续」）
        self._cancel_active()
        super().done(code)

    # ------------------------------------------------------------- 工具

    @staticmethod
    def _open_dir(directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _info(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.success(title, message, duration=INFOBAR_DURATION_SUCCESS, parent=self.window())

    def _warn(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.warning(title, message, duration=INFOBAR_DURATION_WARNING, parent=self.window())

    def _error(self, title: str, message: str):
        from qfluentwidgets import InfoBar

        InfoBar.error(title, message, duration=INFOBAR_DURATION_ERROR, parent=self.window())
