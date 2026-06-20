from dataclasses import dataclass
from enum import Enum
from typing import Callable

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    ScrollArea,
    TitleLabel,
)

from videocaptioner.cli.commands.doctor import Check, run_diagnostics
from videocaptioner.core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from videocaptioner.core.entities import TranscribeModelEnum, TranslatorServiceEnum
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.dubbing_options import get_provider_option
from videocaptioner.ui.common.theme_tokens import (
    AppPalette,
    app_palette,
    rgba,
)
from videocaptioner.ui.components.workbench import StatusPill as WbStatusPill
from videocaptioner.ui.components.workbench import (
    WorkbenchButton,
    apply_font,
    draw_rounded_surface,
)

Translator = Callable[[str], str]


class ItemStatus(Enum):
    PENDING = "pending"
    CHECKING = "checking"
    OK = "ok"
    WARNING = "warning"  # 可选项缺失/需注意：琥珀色，不等于硬错误（不计入"未通过"）
    ERROR = "error"


class ItemAction(Enum):
    TOOL_HELP = "tool_help"
    DOWNLOAD_HELP = "download_help"
    TRANSCRIBE_SETTINGS = "transcribe_settings"
    LLM_SETTINGS = "llm_settings"
    TRANSLATE_SETTINGS = "translate_settings"
    DUBBING_SETTINGS = "dubbing_settings"
    LIVE_CAPTION_SETTINGS = "live_caption_settings"
    DOWNLOAD_DEPENDENCIES = "download_dependencies"


@dataclass(frozen=True)
class DiagnosticItem:
    key: str
    title: str
    description: str
    action: ItemAction
    button_text: str
    status: ItemStatus = ItemStatus.PENDING


@dataclass(frozen=True)
class TaskChipData:
    category: str
    title: str


class DoctorThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(
                run_diagnostics(_build_doctor_config(), check_api=False, check_download=True)
            )
        except Exception as exc:
            self.error.emit(str(exc))


class TaskChip(QFrame):
    def __init__(self, data: TaskChipData, parent=None):
        super().__init__(parent)
        self.setObjectName("taskChip")
        self.setFixedHeight(62)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        category = QLabel(data.category, self)
        category.setObjectName("taskChipCategory")
        apply_font(category, 12, 500)
        title = QLabel(data.title, self)
        title.setObjectName("taskChipTitle")
        apply_font(title, 14, 700)  # 用 apply_font 走正确字重映射，避免 QSS font-weight 被压成黑体糊字
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(category)
        layout.addWidget(title)

    def paintEvent(self, event):
        # 与 OptionCard 等内层卡片同一套表面：panel 上叠半透明卡 + 细边
        palette = app_palette()
        surface = palette.card_surface
        draw_rounded_surface(self, surface, palette.line_soft, 13)
        super().paintEvent(event)


class StatusDot(QWidget):
    def __init__(self, status: ItemStatus, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._status = status
        self.setStatus(status)

    def setStatus(self, status: ItemStatus):
        self._status = status
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = app_palette()

        if self._status == ItemStatus.OK:
            fill = QColor(palette.accent)
            border, mark = palette.accent, palette.accent_fg
        elif self._status == ItemStatus.ERROR:
            fill = QColor(palette.danger)
            fill.setAlphaF(0.16)
            border, mark = palette.danger, palette.danger_fg
        elif self._status == ItemStatus.WARNING:
            fill = QColor(palette.warn)
            fill.setAlphaF(0.18)
            border = mark = palette.warn
        else:
            fill = QColor(palette.field)
            border, mark = palette.line, palette.muted

        painter.setPen(QPen(QColor(border), 1.4))
        painter.setBrush(fill)
        painter.drawEllipse(1, 1, 22, 22)

        pen = QPen(QColor(mark), 1.7)
        pen.setCapStyle(Qt.RoundCap)  # type: ignore
        pen.setJoinStyle(Qt.RoundJoin)  # type: ignore
        painter.setPen(pen)
        if self._status == ItemStatus.OK:
            painter.drawLine(7, 12, 10, 15)
            painter.drawLine(10, 15, 17, 8)
        elif self._status in (ItemStatus.ERROR, ItemStatus.WARNING):
            # 同一个"!"标记：错误红、警告琥珀（颜色已在上面区分）
            painter.drawLine(12, 7, 12, 13)
            painter.drawPoint(12, 17)
        else:
            painter.drawLine(8, 12, 16, 12)


_WB_LEVELS = {"success": "ok", "danger": "fail", "warning": "warn", "neutral": "neutral"}


class StatusPill(WbStatusPill):
    # 诊断状态胶囊：workbench 胶囊 + ItemStatus 映射
    def __init__(self, status: ItemStatus, parent=None):
        super().__init__("", _WB_LEVELS[_status_level(status)], parent)
        self.setMinimumWidth(82)
        self.setStatus(status)

    def setStatus(self, status: ItemStatus):
        self.setState(self.tr(_status_text(status)), _WB_LEVELS[_status_level(status)])


class DiagnosticRow(QFrame):
    actionRequested = pyqtSignal(object)

    def __init__(self, item: DiagnosticItem, actions_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("diagnosticRow")
        if item.status == ItemStatus.ERROR:
            self.setProperty("status", "error")
        elif item.status == ItemStatus.WARNING:
            self.setProperty("status", "warning")
        self.setFixedHeight(78)  # 容纳 标题(16)+描述(13) 两行，紧凑不挤

        layout = QGridLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(1, 1)

        dot = StatusDot(item.status, self)
        layout.addWidget(dot, 0, 0, 2, 1, Qt.AlignCenter)

        title = QLabel(item.title, self)
        title.setObjectName("rowTitle")
        apply_font(title, 16, 700)  # 正确字重(~72)；QSS font-weight 会被 Qt5 压成 ~98 黑体糊字
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        description = QLabel(item.description, self)
        description.setObjectName("rowDescription")
        apply_font(description, 13, 450)
        description.setWordWrap(True)
        description.setTextInteractionFlags(Qt.TextSelectableByMouse)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)  # 标题↔描述紧凑贴合（7 太松，标题副标题该靠近）
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        layout.addLayout(text_layout, 0, 1, 2, 1)

        pill = StatusPill(item.status, self)
        pill.setFixedWidth(84)  # 固定列宽：各行胶囊左右对齐（文字短的也占满）
        layout.addWidget(pill, 0, 2, 2, 1, Qt.AlignVCenter)

        button = WorkbenchButton(
            item.button_text,
            primary=item.status == ItemStatus.ERROR,
            height=36,
            parent=self,
        )
        button.setFixedWidth(132)  # 固定按钮宽：右块（胶囊+按钮）逐行对齐，不随文字长短参差
        button.setEnabled(actions_enabled and item.status != ItemStatus.CHECKING)
        button.clicked.connect(lambda: self.actionRequested.emit(item.action))
        layout.addWidget(button, 0, 3, 2, 1, Qt.AlignVCenter)


class DiagnosticPanel(QFrame):
    actionRequested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diagnosticPanel")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 表头：标题 + 汇总胶囊，底部一条分隔线把标题和清单分开
        self.headerFrame = QFrame(self)
        self.headerFrame.setObjectName("diagnosticHeader")
        header = QHBoxLayout(self.headerFrame)
        header.setContentsMargins(18, 15, 16, 15)
        header.setSpacing(12)
        # 面板标题用第一方字体（不再用 qfluent SubtitleLabel），与全站面板头一致
        title = QLabel(self.tr("检查清单"), self.headerFrame)
        title.setObjectName("diagnosticPanelTitle")  # 需显式着色，否则裸 QLabel 用默认色和深色面板不融合
        apply_font(title, 18, 760)
        header.addWidget(title, 1, Qt.AlignVCenter)
        self.summaryPill = StatusPill(ItemStatus.PENDING, self.headerFrame)
        self.summaryPill.setMinimumWidth(104)
        header.addWidget(self.summaryPill, 0, Qt.AlignVCenter)
        self.layout.addWidget(self.headerFrame)

        self.rowsFrame = QFrame(self)
        self.rowsFrame.setObjectName("rowsFrame")
        self.rowsLayout = QVBoxLayout(self.rowsFrame)
        self.rowsLayout.setContentsMargins(10, 4, 10, 8)
        self.rowsLayout.setSpacing(0)
        self.layout.addWidget(self.rowsFrame)

    def setItems(
        self,
        items: list[DiagnosticItem],
        finished: bool = False,
        actions_enabled: bool = True,
    ):
        _clear_layout(self.rowsLayout)
        errors = sum(item.status == ItemStatus.ERROR for item in items)
        warnings = sum(item.status == ItemStatus.WARNING for item in items)
        checking = any(item.status == ItemStatus.CHECKING for item in items)
        pending = sum(item.status == ItemStatus.PENDING for item in items)
        if errors:
            self.summaryPill.setState(
                self.tr("{count} 项未通过").format(count=errors), "fail"
            )
        elif checking:
            self.summaryPill.setState(self.tr("检查中"), "neutral")
        elif warnings:
            self.summaryPill.setState(
                self.tr("{count} 项需注意").format(count=warnings), "warn"
            )
        elif finished:
            self.summaryPill.setState(self.tr("全部通过"), "ok")
        else:
            self.summaryPill.setState(
                self.tr("{count} 项待检查").format(count=pending), "neutral"
            )

        # 红错误置顶、琥珀警告其次、其余在后；行高与按钮列保持稳定
        ordered = sorted(
            items,
            key=lambda i: 0
            if i.status == ItemStatus.ERROR
            else 1
            if i.status == ItemStatus.WARNING
            else 2,
        )
        for idx, item in enumerate(ordered):
            row = DiagnosticRow(item, actions_enabled=actions_enabled, parent=self.rowsFrame)
            if idx == len(ordered) - 1:
                row.setProperty("last", "true")  # 末行去掉底分隔线，避免悬空线
            row.actionRequested.connect(self.actionRequested)
            self.rowsLayout.addWidget(row)


class DoctorInterface(ScrollArea):
    """桌面端诊断页。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(self.tr("诊断"))
        self._doctor_thread: DoctorThread | None = None
        self.has_results = False
        self.is_running = False
        self.scrollWidget = QWidget()
        self.pageLayout = QVBoxLayout(self.scrollWidget)
        self.taskStrip = QFrame(self.scrollWidget)
        self.taskGrid = QGridLayout(self.taskStrip)
        self.panel = DiagnosticPanel(self.scrollWidget)
        self.runButton = WorkbenchButton(
            self.tr("运行诊断"), AppIcon.SYNC, primary=True, parent=self.scrollWidget
        )
        self._init_ui()

    def _init_ui(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("doctorInterface")
        self.scrollWidget.setObjectName("scrollWidget")
        self.enableTransparentBackground()

        self.pageLayout.setSpacing(18)
        self.pageLayout.setContentsMargins(26, 20, 26, 22)

        toolbar = QWidget(self.scrollWidget)
        toolbarLayout = QHBoxLayout(toolbar)
        toolbarLayout.setContentsMargins(0, 0, 0, 0)
        toolbarLayout.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        self.titleLabel = TitleLabel(self.tr("诊断"), toolbar)
        self.subTitleLabel = CaptionLabel(self.tr("检查当前任务会用到的服务和工具。未启用的功能不会出现在清单里。"), toolbar)
        heading.addWidget(self.titleLabel)
        self.subTitleLabel.hide()
        toolbarLayout.addLayout(heading, 1)
        toolbarLayout.addWidget(self.runButton, 0, Qt.AlignTop)

        self.taskStrip.setObjectName("taskStrip")
        self.taskGrid.setContentsMargins(12, 12, 12, 12)
        self.taskGrid.setHorizontalSpacing(10)
        self.taskGrid.setVerticalSpacing(10)

        self.pageLayout.addWidget(toolbar)
        self.pageLayout.addWidget(self.taskStrip)
        self.pageLayout.addWidget(self.panel)
        self.pageLayout.addStretch(1)

        self.runButton.clicked.connect(self._run)
        self.panel.actionRequested.connect(self._handle_action)
        self._sync_page_background()
        self._refresh_pending()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_page_background()
        if not self.has_results and not self.is_running:
            self._refresh_pending()

    def _sync_page_background(self):
        palette = app_palette()
        self.setStyleSheet(f"QScrollArea {{ border: none; background: {palette.bg}; }}")
        self.scrollWidget.setStyleSheet(_page_styles(palette))

    def _refresh_task_strip(self, checks: list[Check] | None = None):
        _clear_layout(self.taskGrid)
        chips = _task_chips(self.tr, checks)
        columns = max(1, min(5, len(chips)))
        for index, chip in enumerate(chips):
            widget = TaskChip(chip, self.taskStrip)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.taskGrid.addWidget(widget, index // columns, index % columns)

    def _refresh_pending(self):
        self.has_results = False
        self.is_running = False
        self.runButton.setEnabled(True)
        self.runButton.setText(self.tr("运行诊断"))
        self._refresh_task_strip()
        self.panel.setItems(_pending_items(self.tr))

    def _run(self):
        if self.is_running or (self._doctor_thread and self._doctor_thread.isRunning()):
            return
        self.has_results = False
        self.is_running = True
        self.runButton.setEnabled(False)
        self.runButton.setText(self.tr("诊断中"))
        self.panel.setItems(
            _with_status(_base_items(self.tr), ItemStatus.CHECKING),
            actions_enabled=False,
        )
        self._doctor_thread = DoctorThread()
        self._doctor_thread.finished.connect(self._on_finished)
        self._doctor_thread.error.connect(self._on_error)
        self._doctor_thread.start()

    def closeEvent(self, event):
        # 退出时停诊断网络线程：main_window.closeEvent 会 close() 本页，running
        # QThread 被销毁会触发 qFatal。只读网络线程，terminate 安全。
        if self._doctor_thread is not None and self._doctor_thread.isRunning():
            self._doctor_thread.terminate()
            self._doctor_thread.wait(1000)
        super().closeEvent(event)

    def _on_finished(self, checks: list[Check]):
        self.has_results = True
        self.is_running = False
        self.runButton.setEnabled(True)
        self.runButton.setText(self.tr("重新诊断"))
        self._refresh_task_strip(checks)
        items = _items_from_checks(checks, self.tr)
        self.panel.setItems(items, finished=True)
        errors = sum(item.status == ItemStatus.ERROR for item in items)
        warnings = sum(item.status == ItemStatus.WARNING for item in items)
        if errors:
            InfoBar.error(
                self.tr("诊断完成"),
                self.tr("发现 {count} 项需要处理").format(count=errors),
                duration=INFOBAR_DURATION_ERROR,
                parent=self,
            )
        elif warnings:
            InfoBar.warning(
                self.tr("诊断完成"),
                self.tr("有 {count} 项可选项需注意（不影响主要流程）").format(count=warnings),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )
        else:
            InfoBar.success(
                self.tr("诊断完成"),
                self.tr("当前检查项全部通过"),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )

    def _on_error(self, message: str):
        self.is_running = False
        self.runButton.setEnabled(True)
        self.runButton.setText(self.tr("重新诊断"))
        self.panel.setItems(_pending_items(self.tr))
        InfoBar.error(self.tr("诊断失败"), message, duration=INFOBAR_DURATION_ERROR, parent=self)

    def _handle_action(self, action: ItemAction):
        if action == ItemAction.DOWNLOAD_HELP:
            InfoBar.info(
                self.tr("视频下载"),
                self.tr(
                    "YouTube 需要可用的系统代理；哔哩哔哩提示风控（412）时稍等几分钟重试，"
                    "或在浏览器登录后导出 cookies.txt 放到应用数据目录。"
                ),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )
            return
        if action == ItemAction.TOOL_HELP:
            InfoBar.info(
                self.tr("FFmpeg"),
                self.tr("ASS 硬字幕需要带 libass 的完整 FFmpeg。macOS 可安装 ffmpeg-full；也可以先切换为圆角背景。"),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )
            return
        if action == ItemAction.DOWNLOAD_DEPENDENCIES:
            self._open_dependency_dialog()
            return
        page_key = _settings_page_for_action(action)
        if page_key:
            self._open_settings_page(page_key)

    def _open_dependency_dialog(self):
        from videocaptioner.ui.components.dependency_download_dialog import (
            DependencyDownloadDialog,
        )

        dialog = DependencyDownloadDialog(parent=self)
        # 装好任意依赖后自动重跑诊断，卡片状态即时刷新
        dialog.depsChanged.connect(self._run)
        dialog.exec()

    def _open_settings_page(self, page_key: str):
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            if window.openSettingsPage(page_key) is False:  # type: ignore[attr-defined]
                InfoBar.error(
                    self.tr("跳转失败"),
                    self.tr("没有找到对应的设置页。"),
                    duration=INFOBAR_DURATION_ERROR,
                    parent=self,
                )


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if widget := item.widget():
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def _status_text(status: ItemStatus) -> str:
    return {
        ItemStatus.OK: "正常",
        ItemStatus.WARNING: "需注意",
        ItemStatus.ERROR: "未通过",
        ItemStatus.CHECKING: "检查中",
        ItemStatus.PENDING: "待检查",
    }[status]


def _status_level(status: ItemStatus) -> str:
    return {
        ItemStatus.OK: "success",
        ItemStatus.WARNING: "warning",
        ItemStatus.ERROR: "danger",
        ItemStatus.CHECKING: "neutral",
        ItemStatus.PENDING: "neutral",
    }[status]


def _with_status(items: list[DiagnosticItem], status: ItemStatus) -> list[DiagnosticItem]:
    return [
        DiagnosticItem(
            key=item.key,
            title=item.title,
            description=item.description,
            action=item.action,
            button_text=item.button_text,
            status=status,
        )
        for item in items
    ]


def _pending_items(tr: Translator) -> list[DiagnosticItem]:
    return _base_items(tr)


def _base_items(tr: Translator) -> list[DiagnosticItem]:
    items = [
        DiagnosticItem(
            key="ffmpeg",
            title="FFmpeg / FFprobe",
            description=tr("生成视频、压入字幕、合入配音都需要它。"),
            action=ItemAction.TOOL_HELP,
            button_text=tr("安装工具"),
        ),
        DiagnosticItem(
            key="transcribe",
            title=tr("转录服务"),
            description=_transcribe_description(tr),
            action=ItemAction.TRANSCRIBE_SETTINGS,
            button_text=tr("转录配置"),
        ),
        DiagnosticItem(
            key="download",
            title=tr("视频下载"),
            description=tr("解析 YouTube 与哔哩哔哩链接，验证在线视频能否下载。"),
            action=ItemAction.DOWNLOAD_HELP,
            button_text=tr("使用说明"),
        ),
    ]
    if _needs_llm():
        items.append(
            DiagnosticItem(
                key="llm",
                title=_llm_item_title(tr),
                description=_llm_description(tr),
                action=ItemAction.LLM_SETTINGS,
                button_text=tr("大模型配置"),
            )
        )
    if cfg.need_translate.value:
        items.append(
            DiagnosticItem(
                key="translate",
                title=tr("翻译服务"),
                description=_translate_description(tr),
                action=ItemAction.TRANSLATE_SETTINGS,
                button_text=tr("翻译配置"),
            )
        )
    items.append(
        DiagnosticItem(
            key="dubbing",
            title=tr("配音服务"),
            description=_dubbing_description(tr),
            action=ItemAction.DUBBING_SETTINGS,
            button_text=tr("配音配置"),
        )
    )
    items.append(
        DiagnosticItem(
            key="live_caption",
            title=tr("实时字幕"),
            description=tr("实时转录需要本机 voxgate 转录程序，或一个外部实时服务。"),
            action=ItemAction.LIVE_CAPTION_SETTINGS,
            button_text=tr("实时字幕配置"),
        )
    )
    return items


def _items_from_checks(checks: list[Check], tr: Translator) -> list[DiagnosticItem]:
    checks_by_name = {check.name: check for check in checks}
    items: list[DiagnosticItem] = []

    ffmpeg_ass_check = checks_by_name.get("ffmpeg.ass_filter")
    ffmpeg_status = _combined_status([checks_by_name.get("ffmpeg"), checks_by_name.get("ffprobe"), ffmpeg_ass_check])
    ffmpeg_ass_failed = _check_status(ffmpeg_ass_check) == ItemStatus.ERROR
    # 缺二进制 → 直接下载安装；ASS 滤镜不全是构建变体问题 → 仍给文字处理建议
    ffmpeg_missing = _is_problem(ffmpeg_status) and not ffmpeg_ass_failed
    items.append(
        DiagnosticItem(
            key="ffmpeg",
            title=(
                tr("FFmpeg 不支持 ASS 硬字幕")
                if ffmpeg_ass_failed
                else tr("缺少 FFmpeg / FFprobe")
                if _is_problem(ffmpeg_status)
                else "FFmpeg / FFprobe"
            ),
            description=(
                tr("当前 FFmpeg 缺少 ASS 字幕滤镜。请安装完整版本，或把字幕渲染模式切换为圆角背景。")
                if ffmpeg_ass_failed
                else tr("缺少后无法生成视频、压入字幕或合入配音。")
                if _is_problem(ffmpeg_status)
                else tr("工具完整，可生成视频和配音视频。")
            ),
            action=ItemAction.DOWNLOAD_DEPENDENCIES if ffmpeg_missing else ItemAction.TOOL_HELP,
            button_text=(
                tr("下载安装")
                if ffmpeg_missing
                else tr("处理方式")
                if ffmpeg_ass_failed
                else tr("安装工具")
            ),
            status=ffmpeg_status,
        )
    )

    transcribe_checks = _checks_with_prefix(
        checks, ("transcribe", "whisper", "whisper-cpp", "faster-whisper")
    )
    transcribe_status = _combined_status(transcribe_checks)
    items.append(
        DiagnosticItem(
            key="transcribe",
            title=tr("转录服务"),
            description=(
                tr("当前转录方式不可用，请检查网络、Key 或本地模型。")
                if _is_problem(transcribe_status)
                else tr("当前转录方式可用，可生成原文字幕。")
            ),
            action=ItemAction.TRANSCRIBE_SETTINGS,
            button_text=tr("转录配置"),
            status=transcribe_status,
        )
    )

    download_checks = _checks_with_prefix(checks, ("api.download",))
    if download_checks:
        failed = [check for check in download_checks if check.status != "ok"]
        if failed:
            # 检查与真实下载共用同一条回退链路（含浏览器登录态），
            # 走到这里说明兜底也被拒绝，是真不可用。
            detail = "；".join(f"{check.message}" for check in failed)
            description = tr("站点当前不可用（浏览器登录态兜底也已尝试）：{}").format(detail)
        elif any("登录态" in check.message for check in download_checks):
            description = tr("YouTube 与哔哩哔哩解析正常（部分站点通过浏览器登录态），可直接粘贴链接下载。")
        else:
            description = tr("YouTube 与哔哩哔哩解析正常，可直接粘贴链接下载。")
        items.append(
            DiagnosticItem(
                key="download",
                title=tr("视频下载"),
                description=description,
                action=ItemAction.DOWNLOAD_HELP,
                button_text=tr("使用说明"),
                status=_combined_status(download_checks),
            )
        )

    if _needs_llm():
        llm_checks = _checks_with_prefix(checks, ("llm",))
        llm_status = _combined_status(llm_checks)
        items.append(
            DiagnosticItem(
                key="llm",
                title=tr("大模型配置不可用") if _is_problem(llm_status) else _llm_item_title(tr),
                description=(
                    tr("字幕校正、术语修正和智能断句需要可用 Key。")
                    if _is_problem(llm_status)
                    else tr("大模型配置可用，可用于字幕增强。")
                ),
                action=ItemAction.LLM_SETTINGS,
                button_text=tr("大模型配置"),
                status=llm_status,
            )
        )

    if cfg.need_translate.value:
        items.append(
            DiagnosticItem(
                key="translate",
                title=tr("翻译服务"),
                description=(
                    tr("大模型翻译会复用 LLM Key。")
                    if _translate_uses_llm()
                    else tr("翻译服务可用，可生成目标语言字幕。")
                ),
                action=ItemAction.TRANSLATE_SETTINGS,
                button_text=tr("翻译配置"),
                status=ItemStatus.OK,
            )
        )

    dubbing_checks = _checks_with_prefix(checks, ("dubbing", "api.dubbing"))
    dubbing_status = _combined_status(dubbing_checks)
    items.append(
        DiagnosticItem(
            key="dubbing",
            title=tr("配音服务"),
            description=(
                tr("Gemini / SiliconFlow 需要配音 Key；Edge 可免 Key。")
                if _is_problem(dubbing_status)
                else tr("当前配音配置可用，可继续生成配音。")
            ),
            action=ItemAction.DUBBING_SETTINGS,
            button_text=tr("配音配置"),
            status=dubbing_status,
        )
    )

    live_caption_checks = _checks_with_prefix(checks, ("live_caption",))
    live_caption_status = _combined_status(live_caption_checks)
    # 只有「缺 voxgate 本地程序」才走下载；fun-asr 缺 Key / 远程服务问题 → 去设置
    lc_needs_download = _is_problem(live_caption_status) and any(
        c.name == "live_caption.voxgate" for c in live_caption_checks
    )
    lc_is_funasr = any(c.name == "live_caption.funasr" for c in live_caption_checks)
    if _is_problem(live_caption_status):
        lc_desc = (
            tr("Fun-ASR 实时缺少百炼 API Key，去设置里填写即可。")
            if lc_is_funasr
            else tr("可选功能：未找到 voxgate 转录程序或外部实时服务，需要时再配置即可。")
        )
    else:
        lc_desc = tr("实时字幕后端就绪，可开始实时转录与翻译。")
    items.append(
        DiagnosticItem(
            key="live_caption",
            title=tr("实时字幕"),
            description=lc_desc,
            action=ItemAction.DOWNLOAD_DEPENDENCIES if lc_needs_download else ItemAction.LIVE_CAPTION_SETTINGS,
            button_text=tr("下载 voxgate") if lc_needs_download else tr("实时字幕配置"),
            status=live_caption_status,
        )
    )
    return items


def _is_problem(status: ItemStatus) -> bool:
    """需要用户关注的状态（红错误或琥珀警告），用于选「问题」文案而非「就绪」文案。"""
    return status in (ItemStatus.ERROR, ItemStatus.WARNING)


def _checks_with_prefix(checks: list[Check], prefixes: tuple[str, ...]) -> list[Check]:
    return [check for check in checks if check.name.startswith(prefixes)]


def _combined_status(checks: list[Check | None]) -> ItemStatus:
    present = [check for check in checks if check is not None]
    if not present:
        return ItemStatus.OK
    # error 红、warn 琥珀（可选项缺失），两者区分：error 才算"未通过"
    if any(check.status == "error" for check in present):
        return ItemStatus.ERROR
    if any(check.status == "warn" for check in present):
        return ItemStatus.WARNING
    if any(check.status == "checking" for check in present):
        return ItemStatus.CHECKING
    return ItemStatus.OK


def _check_status(check: Check | None) -> ItemStatus:
    if check is None:
        return ItemStatus.OK
    if check.status == "error":
        return ItemStatus.ERROR
    if check.status == "warn":
        return ItemStatus.WARNING
    if check.status == "checking":
        return ItemStatus.CHECKING
    if check.status == "pending":
        return ItemStatus.PENDING
    return ItemStatus.OK


def _task_chips(tr: Translator, checks: list[Check] | None = None) -> list[TaskChipData]:
    chips = [
        TaskChipData(tr("转录"), _transcribe_label()),
    ]
    if cfg.need_optimize.value or cfg.need_split.value:
        chips.append(TaskChipData(tr("字幕处理"), _subtitle_processing_label(tr)))
    if cfg.need_translate.value:
        chips.append(TaskChipData(tr("翻译"), cfg.translator_service.value.value))
    chips.append(TaskChipData(tr("配音"), _dubbing_label(tr)))
    chips.append(TaskChipData(tr("导出"), _export_label(tr)))
    return chips


def _transcribe_label() -> str:
    return getattr(cfg.transcribe_model.value, "value", str(cfg.transcribe_model.value))


def _subtitle_processing_label(tr: Translator) -> str:
    parts = []
    if cfg.need_optimize.value:
        parts.append(tr("校正"))
    if cfg.need_split.value:
        parts.append(tr("智能断句"))
    return " + ".join(parts) or tr("未启用")


def _dubbing_label(tr: Translator) -> str:
    return tr(get_provider_option(cfg.dubbing_provider.value).title)


def _export_label(tr: Translator) -> str:
    pieces = [tr("字幕")]
    if cfg.need_video.value:
        pieces.insert(0, tr("视频"))
    if cfg.dubbing_enabled.value:
        pieces.append(tr("配音"))
    if not cfg.need_video.value and not cfg.dubbing_enabled.value:
        return tr("字幕文件")
    return " + ".join(pieces)


def _needs_llm() -> bool:
    return bool(cfg.need_optimize.value or cfg.need_split.value or _translate_uses_llm())


def _translate_uses_llm() -> bool:
    return cfg.need_translate.value and cfg.translator_service.value == TranslatorServiceEnum.OPENAI


def _llm_item_title(tr: Translator) -> str:
    if cfg.need_optimize.value and cfg.need_split.value:
        return tr("字幕校正与智能断句")
    if cfg.need_optimize.value:
        return tr("字幕校正")
    if cfg.need_split.value:
        return tr("智能断句")
    return tr("大模型翻译")


def _llm_description(tr: Translator) -> str:
    if _translate_uses_llm() and not (cfg.need_optimize.value or cfg.need_split.value):
        return tr("当前翻译会调用大模型，需要可用 Key。")
    return tr("校正、术语修正、智能断句需要可用 Key。")


def _transcribe_description(tr: Translator) -> str:
    if cfg.transcribe_model.value.name in {"BIJIAN", "JIANYING"}:
        return tr("把视频或音频转成原文字幕，免费接口需要网络。")
    if cfg.transcribe_model.value.name == "WHISPER_API":
        return tr("把视频或音频转成原文字幕，需要 Whisper Key。")
    return tr("把视频或音频转成原文字幕，需要本地模型。")


def _translate_description(tr: Translator) -> str:
    if _translate_uses_llm():
        return tr("生成目标语言字幕，大模型翻译会复用 LLM Key。")
    return tr("生成目标语言字幕，失败只影响译文。")


def _dubbing_description(tr: Translator) -> str:
    return tr("按当前提供商和音色生成配音；部分服务需要 Key。")


def _settings_page_for_action(action: ItemAction) -> str | None:
    return {
        ItemAction.TRANSCRIBE_SETTINGS: "transcribe",
        ItemAction.LLM_SETTINGS: "llm",
        ItemAction.TRANSLATE_SETTINGS: "translate-service",
        ItemAction.DUBBING_SETTINGS: "dubbing",
        ItemAction.LIVE_CAPTION_SETTINGS: "live-caption",
    }.get(action)


def _page_styles(palette: AppPalette) -> str:
    return f"""
QWidget#scrollWidget {{
    background: {palette.bg};
}}
QFrame#taskStrip {{
    background: {palette.panel};
    border: 1px solid {palette.line};
    border-radius: 16px;
}}
QFrame#taskChip {{
    background: transparent;
    border: none;
}}
QLabel#diagnosticPanelTitle {{
    color: {palette.text};
    background: transparent;
}}
QLabel#taskChipCategory {{
    color: {palette.subtle};
}}
QLabel#taskChipTitle {{
    color: {palette.text};
}}
QFrame#diagnosticPanel {{
    background: {palette.panel};
    border: 1px solid {palette.line};
    border-radius: 14px;
}}
QFrame#diagnosticHeader {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {palette.line_soft};
}}
QFrame#rowsFrame {{
    background: transparent;
    border: none;
}}
QFrame#diagnosticRow {{
    background: {palette.panel};
    border-bottom: 1px solid {palette.line_soft};
}}
QFrame#diagnosticRow[last="true"] {{
    border-bottom: none;
}}
QFrame#diagnosticRow[status="error"] {{
    background: {rgba(palette.danger, 0.08)};
    border-left: 3px solid {palette.danger};
}}
QFrame#diagnosticRow[status="warning"] {{
    background: {rgba(palette.warn, 0.08)};
    border-left: 3px solid {palette.warn};
}}
QLabel#rowTitle {{
    color: {palette.text};
}}
QLabel#rowDescription {{
    color: {palette.muted};
}}
"""


def _build_doctor_config() -> dict:
    provider = cfg.dubbing_provider.value
    asr_name = cfg.transcribe_model.value.name.lower().replace("_", "-")
    if cfg.transcribe_model.value == TranscribeModelEnum.BAILIAN_FUN_ASR:
        asr_name = "fun-asr"
    return {
        "llm": {
            "api_key": _current_llm_api_key(),
            "api_base": _current_llm_api_base(),
            "model": _current_llm_model(),
        },
        "whisper_api": {
            "api_key": str(cfg.whisper_api_key.value or "").strip(),
            "api_base": str(cfg.whisper_api_base.value or "").strip(),
            "model": str(cfg.whisper_api_model.value or "whisper-1").strip(),
        },
        "fun_asr": {
            "api_key": str(cfg.fun_asr_api_key.value or "").strip(),
            "api_base": str(cfg.fun_asr_api_base.value or "").strip(),
            "model": str(cfg.fun_asr_model.value or "fun-asr").strip(),
        },
        "transcribe": {
            "asr": asr_name,
            "whisper_cpp": {
                "model": getattr(cfg.whisper_model.value, "value", str(cfg.whisper_model.value)),
            },
            "faster_whisper": {
                "model": getattr(
                    cfg.faster_whisper_model.value, "value", str(cfg.faster_whisper_model.value)
                ),
            },
        },
        "subtitle": {
            "optimize": cfg.need_optimize.value,
            "split": cfg.need_split.value,
            "translate": cfg.need_translate.value,
            "render_mode": cfg.subtitle_render_mode.value.value,
        },
        "translate": {
            "service": "llm" if cfg.translator_service.value == TranslatorServiceEnum.OPENAI else cfg.translator_service.value.name.lower(),
        },
        "dubbing": {
            "provider": provider,
            "preset": cfg.dubbing_preset.value,
            "api_key": str(cfg.dubbing_api_key.value or "").strip(),
            "api_base": str(cfg.dubbing_api_base.value or "").strip(),
            "model": str(cfg.dubbing_model.value or "").strip(),
            "voice": str(cfg.dubbing_voice.value or "").strip(),
            "timing": "balanced",
            "audio_mode": "replace",
        },
        "live_caption": {
            "provider": cfg.live_caption_provider.value,
            "voxgate_binary": str(cfg.live_caption_voxgate_binary.value or "").strip(),
            "api_key": str(cfg.fun_asr_api_key.value or "").strip(),
        },
    }


def _current_llm_api_key() -> str:
    service = cfg.llm_service.value
    value = {
        "OPENAI": cfg.openai_api_key.value,
        "SILICON_CLOUD": cfg.silicon_cloud_api_key.value,
        "DEEPSEEK": cfg.deepseek_api_key.value,
        "OLLAMA": cfg.ollama_api_key.value,
        "LM_STUDIO": cfg.lm_studio_api_key.value,
        "GEMINI": cfg.gemini_api_key.value,
        "CHATGLM": cfg.chatglm_api_key.value,
    }.get(service.name, "")
    return str(value or "").strip()


def _current_llm_api_base() -> str:
    service = cfg.llm_service.value
    value = {
        "OPENAI": cfg.openai_api_base.value,
        "SILICON_CLOUD": cfg.silicon_cloud_api_base.value,
        "DEEPSEEK": cfg.deepseek_api_base.value,
        "OLLAMA": cfg.ollama_api_base.value,
        "LM_STUDIO": cfg.lm_studio_api_base.value,
        "GEMINI": cfg.gemini_api_base.value,
        "CHATGLM": cfg.chatglm_api_base.value,
    }.get(service.name, "")
    return str(value or "").strip()


def _current_llm_model() -> str:
    service = cfg.llm_service.value
    value = {
        "OPENAI": cfg.openai_model.value,
        "SILICON_CLOUD": cfg.silicon_cloud_model.value,
        "DEEPSEEK": cfg.deepseek_model.value,
        "OLLAMA": cfg.ollama_model.value,
        "LM_STUDIO": cfg.lm_studio_model.value,
        "GEMINI": cfg.gemini_model.value,
        "CHATGLM": cfg.chatglm_model.value,
    }.get(service.name, "")
    return str(value or "").strip()
