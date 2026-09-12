import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtMultimedia import (
    QAudioEncoderSettings,
    QAudioRecorder,
    QMediaContent,
    QMediaPlayer,
    QMediaRecorder,
    QMultimedia,
)
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    InfoBar,
)

from videocaptioner.config import CACHE_PATH
from videocaptioner.core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from videocaptioner.core.dubbing import get_dubbing_preset
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.dubbing_options import (
    DUBBING_PROVIDERS,
    DubbingVoiceOption,
    get_provider_option,
    get_provider_voices,
    provider_desc,
    provider_title,
    tag_label,
    voice_desc,
)
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.workbench import (
    AppScrollArea,
    AppTextEdit,
    ClickableFrame,
    CompactButton,
    DangerButton,
    FilterTabs,
    SelectableCard,
    StatusPill,
    WorkbenchButton,
    apply_font,
    draw_rounded_surface,
)
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.voice_preview_thread import (
    VoicePreviewThread,
    bundled_voice_preview,
    playable_voice_preview,
)

CONTROL_RADIUS = 9   # 与 workbench CompactButton 一致
PANEL_RADIUS = 18  # 面板圆角（更圆润）
PAGE_MARGIN_X = 26  # 与批量/诊断等独立 nav 页根边距统一为 (26,20,26,22)
SECTION_GAP = 14
BODY_GAP = 18
PROVIDER_HEIGHT = 88
TABLE_HEADER_HEIGHT = 52
VOICE_ROW_HEIGHT = 92  # 容纳 标题 + 描述 + 标签三行
VOICE_LIST_PADDING = 12  # 音色列表内边距
VOICE_ROW_GAP = 8  # 音色卡片之间的留白
VOICE_ROW_RADIUS = 14  # 音色卡片圆角（圆角卡片，非直角行）
AUDITION_BUTTON_WIDTH = 92


def _tag_chip(text: str, parent=None) -> QLabel:
    """音色标签小药丸：色值由页面 QSS 统一着色。"""
    chip = QLabel(text, parent)
    chip.setObjectName("voiceTag")
    apply_font(chip, 11, 760)
    return chip


def _provider_badge(option) -> tuple[str, str]:
    """提供商卡右侧状态胶囊：
    免 Key（Edge）/ 可克隆（SiliconFlow）为 ok，其余需 Key 为 neutral。"""
    if not option.needs_api_key:
        return tr("dubbing.badge.no_key"), "ok"
    if option.supports_clone:
        return tr("dubbing.badge.clone"), "ok"
    return tr("dubbing.badge.need_key"), "neutral"

# 提供商卡左侧图标（与批量处理页模式卡同款图标盒）：均为音频族图标，
# edge=扬声器、gemini=音符、siliconflow=麦克风（克隆录音语义贴切）。
_PROVIDER_ICONS = {
    "edge": AppIcon.VOLUME,
    "gemini": AppIcon.MUSIC,
    "siliconflow": AppIcon.MICROPHONE,
}
PREVIEW_PANEL_WIDTH = 376
GENDER_FILTER_TAGS = {"女声", "男声"}


def _blend_color(foreground: str, background: str, alpha: float) -> QColor:
    # foreground/background 恒为 app_palette() 的有效色，无须无效兜底——
    # 写死兜底色在自定义主题下反而是错的。
    fg = QColor(foreground)
    bg = QColor(background)
    alpha = max(0.0, min(1.0, alpha))
    return QColor(
        int(fg.red() * alpha + bg.red() * (1 - alpha)),
        int(fg.green() * alpha + bg.green() * (1 - alpha)),
        int(fg.blue() * alpha + bg.blue() * (1 - alpha)),
    )


class ThemedSimpleCard(QFrame):
    """项目自绘卡：palette 颜色 + 可选选中态描边，不依赖 qfluent SimpleCardWidget
    （它本就完全覆盖 paintEvent，qfluent 基类的视觉从未被用到）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_visual = False
        self._radius = PANEL_RADIUS

    def setBorderRadius(self, radius: int):
        self._radius = radius

    def setSelectedVisual(self, selected: bool):
        self._selected_visual = selected
        self.update()

    def paintEvent(self, event):  # noqa: N802
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        background = (
            _blend_color(palette.accent, palette.panel, 0.14)
            if self._selected_visual
            else QColor(palette.panel)
        )
        border = QColor(palette.accent if self._selected_visual else palette.line)
        painter.setPen(border)
        painter.setBrush(background)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self._radius, self._radius)


class _RoundedPanel(QFrame):
    """自绘抗锯齿圆角面板：bg/border 按主题实时取色，半径固定。

    替代 QSS ``border-radius``（QSS 圆角不做抗锯齿，边缘有锯齿/不流畅）。
    """

    def __init__(self, radius, bg_fn, border_fn, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._bg_fn = bg_fn  # callable(palette) -> str
        self._border_fn = border_fn  # callable(palette) -> str

    def paintEvent(self, event):  # noqa: N802
        palette = app_palette()
        draw_rounded_surface(self, self._bg_fn(palette), self._border_fn(palette), self._radius)


class AuditionButton(ClickableFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("auditionButton")
        self.setFixedSize(AUDITION_BUTTON_WIDTH, 36)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(text, self)
        self.label.setObjectName("auditionButtonLabel")
        self.label.setAlignment(Qt.AlignCenter)  # type: ignore
        apply_font(self.label, 13, 750)
        layout.addWidget(self.label, 0, 0, Qt.AlignCenter)  # type: ignore
        self._sync_style()

    def setText(self, text: str):
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._sync_style()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:  # type: ignore
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def _sync_style(self):
        palette = app_palette()
        if not self.isEnabled():
            bg, fg, border = palette.disabled, palette.subtle, palette.line
        else:
            bg, fg, border = palette.field, palette.text, palette.line
        self.setStyleSheet(
            f"""
            QFrame#auditionButton {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {CONTROL_RADIUS}px;
            }}
            QLabel#auditionButtonLabel {{
                color: {fg};
                background: transparent;
                border: none;
            }}
            """
        )


class VoiceRow(QFrame):
    previewRequested = pyqtSignal(str, object)
    selectedRequested = pyqtSignal(str)

    def __init__(self, voice: DubbingVoiceOption, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.setObjectName("voiceRow")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore  圆角卡片需自绘样式背景
        self.setFixedHeight(VOICE_ROW_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore

        layout = QGridLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(0, 1)
        layout.setColumnMinimumWidth(1, AUDITION_BUTTON_WIDTH)

        titleWidget = QWidget(self)
        titleBox = QVBoxLayout(titleWidget)
        titleBox.setContentsMargins(0, 0, 0, 0)
        titleBox.setSpacing(5)
        self.titleLabel = QLabel(voice.title, self)
        apply_font(self.titleLabel, 16, 760)
        self.descLabel = QLabel(voice_desc(voice), self)
        self.descLabel.setObjectName("dubCaption")
        apply_font(self.descLabel, 13, 500)
        self.descLabel.setWordWrap(False)
        titleBox.addWidget(self.titleLabel)
        titleBox.addWidget(self.descLabel)
        if voice.tags:
            tagsRow = QHBoxLayout()
            tagsRow.setContentsMargins(0, 1, 0, 0)
            tagsRow.setSpacing(6)
            for tag in voice.tags:
                tagsRow.addWidget(_tag_chip(tag_label(tag), self))
            tagsRow.addStretch(1)
            titleBox.addLayout(tagsRow)
        layout.addWidget(titleWidget, 0, 0, Qt.AlignVCenter)  # type: ignore

        self.previewButton = AuditionButton(tr("dubbing.btn.audition"), self)
        layout.addWidget(self.previewButton, 0, 1, Qt.AlignRight | Qt.AlignVCenter)  # type: ignore
        self.previewButton.clicked.connect(lambda: self.previewRequested.emit(self.voice.preset, self.previewButton))

    def setSelected(self, selected: bool):
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore
            self.selectedRequested.emit(self.voice.preset)
            event.accept()
            return
        super().mousePressEvent(event)


class VoiceTable(QFrame):
    previewRequested = pyqtSignal(str, object)
    selectedRequested = pyqtSignal(str)
    filterChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("voiceTable")
        self.rows: list[VoiceRow] = []
        self.filterTabs: FilterTabs | None = None
        self._filter_keys: tuple[str, ...] = ()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self._add_header()  # 表头固定在顶部
        # 音色卡列表区：内边距 + 卡间留白，每个音色是独立圆角卡片。
        # 放进内部 QScrollArea：表头不动，只有这块在长列表时滚动。
        self.listArea = QWidget()
        self.listArea.setObjectName("voiceListArea")
        self.listLayout = QVBoxLayout(self.listArea)
        self.listLayout.setContentsMargins(
            VOICE_LIST_PADDING, VOICE_LIST_PADDING, VOICE_LIST_PADDING, VOICE_LIST_PADDING
        )
        self.listLayout.setSpacing(VOICE_ROW_GAP)
        self.listScroll = QScrollArea(self)
        self.listScroll.setObjectName("voiceScroll")
        self.listScroll.setWidget(self.listArea)
        self.listScroll.setWidgetResizable(True)
        self.listScroll.setFrameShape(QFrame.NoFrame)  # type: ignore[attr-defined]
        self.listScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[attr-defined]
        self.listScroll.viewport().setAutoFillBackground(False)
        self.layout.addWidget(self.listScroll, 1)  # 填满表头下方剩余高度

    def _add_header(self):
        """表头：左「音色库 / 中文音色」标题 + 右分段筛选。"""
        self.header = QFrame(self)
        self.header.setObjectName("voiceHeader")
        self.header.setFixedHeight(TABLE_HEADER_HEIGHT)
        self._headerLayout = QHBoxLayout(self.header)
        self._headerLayout.setContentsMargins(16, 0, 10, 0)
        self._headerLayout.setSpacing(10)
        self.headingLabel = QLabel(tr("dubbing.voice.library"), self.header)
        self.headingLabel.setObjectName("voiceHeading")
        apply_font(self.headingLabel, 19, 820)
        self._headerLayout.addWidget(self.headingLabel)
        self._headerLayout.addStretch(1)
        self._build_filter(
            [
                ("全部", tr("dubbing.filter.all")),
                ("女声", tr("dubbing.filter.female")),
                ("男声", tr("dubbing.filter.male")),
            ]
        )
        self.layout.addWidget(self.header)

    def _build_filter(self, items: list[tuple[str, str]]):
        keys = tuple(k for k, _ in items)
        if keys == self._filter_keys and self.filterTabs is not None:
            return
        self._filter_keys = keys
        if self.filterTabs is not None:
            self._headerLayout.removeWidget(self.filterTabs)
            # setParent(None) 立即从表头移除并停止绘制；只 deleteLater 会留下残影旧分段
            self.filterTabs.setParent(None)
            self.filterTabs.deleteLater()
        self.filterTabs = FilterTabs(items, self.header)
        self.filterTabs.changed.connect(self.filterChanged)
        self._headerLayout.addWidget(self.filterTabs)

    def configure(self, heading: str, *, show_gender: bool, show_clone: bool):
        """按提供商配置表头：标题文案 + 筛选项（性别/克隆按需出现）。"""
        self.headingLabel.setText(heading)
        items = [("全部", tr("dubbing.filter.all"))]
        if show_gender:
            items += [("女声", tr("dubbing.filter.female")), ("男声", tr("dubbing.filter.male"))]
        if show_clone:
            items += [("克隆", tr("dubbing.filter.clone"))]
        self._build_filter(items)

    def setFilter(self, key: str):
        if self.filterTabs is not None:
            self.filterTabs.setCurrent(key)

    def setVoices(self, voices: list[DubbingVoiceOption], current: str):
        # 清空旧行与尾部弹簧（弹簧不在 self.rows 里，必须连同清掉）
        while self.listLayout.count():
            item = self.listLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.rows = []
        for voice in voices:
            row = VoiceRow(voice, self.listArea)
            row.setSelected(voice.preset == current)
            row.previewRequested.connect(self.previewRequested)
            row.selectedRequested.connect(self.selectedRequested)
            self.listLayout.addWidget(row)
            self.rows.append(row)
        self.listLayout.addStretch(1)  # 行少时顶部对齐；行多时由 listScroll 滚动，不再固定整表高度


class PreviewPanel(ThemedSimpleCard):
    layoutChanged = pyqtSignal()
    customPreviewRequested = pyqtSignal()
    chooseAudioRequested = pyqtSignal()
    playAudioRequested = pyqtSignal()
    recordRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    cloneTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore
        self.setBorderRadius(PANEL_RADIUS)
        self.setFixedWidth(PREVIEW_PANEL_WIDTH)
        self._clone_available = True
        self._clone_audio_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(9)

        # 标题 + 描述在左，当前音色 pill 在右。
        # 用透明容器而非带边框的子卡——子卡圆角(15)和外层面板圆角(18)在顶部只差 ~16px，
        # 会出现「两个圆角嵌套重叠」的观感。标题直接贴面板内边距即可，干净不重复。
        self.selectedCard = QFrame(self)
        self.selectedCard.setObjectName("selectedCard")
        header = QHBoxLayout(self.selectedCard)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        headText = QVBoxLayout()
        headText.setContentsMargins(0, 0, 0, 0)
        headText.setSpacing(3)
        self.titleLabel = QLabel(tr("dubbing.preview.title"), self.selectedCard)
        apply_font(self.titleLabel, 19, 700)
        self.descLabel = QLabel(tr("dubbing.preview.desc"), self.selectedCard)
        self.descLabel.setObjectName("dubCaption")
        self.descLabel.setWordWrap(True)
        apply_font(self.descLabel, 13, 500)
        headText.addWidget(self.titleLabel)
        headText.addWidget(self.descLabel)
        self.voicePill = StatusPill("", "ok", self.selectedCard)  # 当前音色
        self.voicePill.hide()
        header.addLayout(headText, 1)
        header.addWidget(self.voicePill, 0, Qt.AlignTop)

        self.previewInput = AppTextEdit(parent=self, min_height=104, radius=15)
        self.previewInput.setObjectName("previewInput")
        self.previewInput.setPlaceholderText(tr("dubbing.preview.input_placeholder"))
        self.previewInput.setFixedHeight(104)
        self.previewInput.setPlainText(tr("dubbing.preview.sample_text"))
        apply_font(self.previewInput, 13, 700)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(8)
        self.countLabel = QLabel("", self)
        self.countLabel.setObjectName("sampleMetaLabel")
        self.countLabel.setMinimumWidth(50)
        self.countLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore
        apply_font(self.countLabel, 11, 400)
        meta.addStretch(1)
        meta.addWidget(self.countLabel)

        self.customPreviewButton = WorkbenchButton(
            tr("dubbing.btn.generate_preview"), AppIcon.PLAY, primary=True, height=40, parent=self
        )

        # 自绘抗锯齿圆角（绿调克隆框）；QSS border-radius 会有锯齿
        self.cloneSection = _RoundedPanel(
            15,
            lambda p: rgba(p.accent, 0.07),
            lambda p: rgba(p.accent, 0.38),
            self,
        )
        self.cloneSection.setObjectName("cloneSection")
        cloneLayout = QVBoxLayout(self.cloneSection)
        cloneLayout.setContentsMargins(12, 12, 12, 12)
        cloneLayout.setSpacing(8)

        cloneHeader = QHBoxLayout()
        cloneTitle = QLabel(tr("dubbing.clone.title"), self.cloneSection)
        apply_font(cloneTitle, 15, 700)
        cloneHeader.addWidget(cloneTitle)
        cloneHeader.addStretch(1)

        self.fileBox = QFrame(self.cloneSection)
        self.fileBox.setObjectName("cloneFileBox")
        self.fileBox.setFixedHeight(38)
        fileLayout = QHBoxLayout(self.fileBox)
        fileLayout.setContentsMargins(12, 0, 10, 0)
        fileLayout.setSpacing(8)
        self.fileLabel = QLabel(tr("dubbing.clone.no_audio"), self.fileBox)
        self.fileLabel.setObjectName("dubCaption")
        apply_font(self.fileLabel, 12, 600)
        self.fileLabel.setWordWrap(False)
        self.fileStatusPill = StatusPill(tr("dubbing.clone.uploaded"), "ok", self.fileBox)
        self.fileStatusPill.hide()
        fileLayout.addWidget(self.fileLabel, 1)
        fileLayout.addWidget(self.fileStatusPill, 0, Qt.AlignVCenter)

        # 操作按钮统一 workbench 紧凑按钮，自适应宽度不挤压
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.chooseButton = CompactButton(tr("dubbing.clone.upload"), AppIcon.FOLDER_ADD, self.cloneSection)
        self.playButton = CompactButton(tr("dubbing.btn.audition"), AppIcon.PLAY, self.cloneSection)
        self.recordButton = CompactButton(tr("dubbing.clone.record"), AppIcon.MICROPHONE, self.cloneSection)
        self.clearButton = DangerButton(tr("dubbing.clone.clear"), AppIcon.DELETE, self.cloneSection)
        actions.addWidget(self.chooseButton)
        actions.addWidget(self.playButton)
        actions.addWidget(self.recordButton)
        actions.addWidget(self.clearButton)
        actions.addStretch(1)

        self.cloneTextLabel = QLabel(tr("dubbing.clone.ref_text"), self.cloneSection)
        self.cloneTextLabel.setObjectName("sampleMetaLabel")
        apply_font(self.cloneTextLabel, 12, 600)
        self.cloneTextInput = AppTextEdit(parent=self.cloneSection, min_height=48, radius=12)
        self.cloneTextInput.setObjectName("cloneTextInput")
        self.cloneTextInput.setPlaceholderText(tr("dubbing.clone.ref_text_placeholder"))
        self.cloneTextInput.setFixedHeight(48)
        apply_font(self.cloneTextInput, 12, 650)

        self.cloneHintLabel = QLabel(tr("dubbing.clone.hint"), self.cloneSection)
        self.cloneHintLabel.setObjectName("sampleMetaLabel")
        apply_font(self.cloneHintLabel, 11, 400)
        self.cloneHintLabel.setWordWrap(True)
        self.cloneHintLabel.hide()

        cloneLayout.addLayout(cloneHeader)
        cloneLayout.addWidget(self.fileBox)
        cloneLayout.addLayout(actions)
        cloneLayout.addWidget(self.cloneTextLabel)
        cloneLayout.addWidget(self.cloneTextInput)
        cloneLayout.addWidget(self.cloneHintLabel)

        # 非克隆提供商：用「当前音色 / 生成类型」摘要替代克隆区
        self.formList = _RoundedPanel(
            14, lambda p: p.field, lambda p: p.line_soft, self
        )
        self.formList.setObjectName("formList")
        formLayout = QVBoxLayout(self.formList)
        formLayout.setContentsMargins(14, 10, 14, 10)
        formLayout.setSpacing(8)
        self.formVoiceValue = QLabel("", self.formList)
        self.formTypeValue = QLabel(tr("dubbing.form.type_preview"), self.formList)
        formLayout.addLayout(self._form_row(tr("dubbing.form.current_voice"), self.formVoiceValue))
        formLayout.addLayout(self._form_row(tr("dubbing.form.gen_type"), self.formTypeValue))

        layout.addWidget(self.selectedCard)
        layout.addWidget(self.cloneSection)
        layout.addWidget(self.previewInput)
        layout.addLayout(meta)
        layout.addWidget(self.formList)
        layout.addWidget(self.customPreviewButton)

        self.previewInput.textChanged.connect(self._update_count)
        self.customPreviewButton.clicked.connect(self.customPreviewRequested)
        self.chooseButton.clicked.connect(self.chooseAudioRequested)
        self.playButton.clicked.connect(self.playAudioRequested)
        self.recordButton.clicked.connect(self.recordRequested)
        self.clearButton.clicked.connect(self.clearRequested)
        self.cloneTextInput.textChanged.connect(
            lambda: self.cloneTextChanged.emit(self.cloneTextInput.toPlainText().strip())
        )
        self._update_count()

    def _form_row(self, label_text: str, value_label: QLabel) -> QHBoxLayout:
        """form-list 一行：左键名 + 右值。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        key = QLabel(label_text, self.formList)
        key.setObjectName("formKey")
        apply_font(key, 12, 600)
        apply_font(value_label, 13, 700)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # type: ignore
        row.addWidget(key)
        row.addStretch(1)
        row.addWidget(value_label)
        return row

    def text(self) -> str:
        return self.previewInput.toPlainText().strip()

    def customButtonLabel(self) -> str:
        """主按钮应显示的文案：有参考音频的克隆态用「生成克隆音频」，否则「生成试听音频」。"""
        if self._clone_available and bool(self._clone_audio_path):
            return tr("dubbing.btn.generate_clone")
        return tr("dubbing.btn.generate_preview")

    def setCurrentVoice(self, name: str):
        """右栏「配音文案」标题旁显示当前音色名。"""
        if name:
            self.voicePill.setState(name, "ok")
            self.voicePill.show()
        else:
            self.voicePill.hide()
        self.formVoiceValue.setText(name or tr("dubbing.form.not_selected"))

    def setCloneAvailable(self, available: bool):
        self._clone_available = available
        self.cloneSection.setVisible(available)
        self.formList.setVisible(not available)
        if not available:
            self.customPreviewButton.setText(tr("dubbing.btn.generate_preview"))
            self.descLabel.setText(tr("dubbing.preview.desc"))
            self.layoutChanged.emit()
        else:
            self.descLabel.setText(tr("dubbing.preview.desc_clone"))
            self._sync_clone_state()
        self.updateGeometry()

    def setAudioPath(self, path: str):
        self._clone_audio_path = path.strip()
        self.fileLabel.setText(self._format_file_line(self._clone_audio_path))
        self.fileStatusPill.setVisible(self._clone_audio_exists())
        if not self._clone_available:
            self.playButton.setEnabled(False)
            self.clearButton.setEnabled(False)
            self.updateGeometry()
            self.layoutChanged.emit()
            return
        self._sync_clone_state()

    def setCloneText(self, text: str):
        if self.cloneTextInput.toPlainText() == text:
            return
        self.cloneTextInput.blockSignals(True)
        self.cloneTextInput.setPlainText(text)
        self.cloneTextInput.blockSignals(False)

    def setRecording(self, recording: bool):
        self.recordButton.setText(tr("dubbing.btn.stop") if recording else tr("dubbing.clone.record"))
        self.chooseButton.setEnabled(not recording)
        self.playButton.setEnabled(False if recording else self._clone_audio_exists())
        self.clearButton.setEnabled(False if recording else bool(self._clone_audio_path))

    def syncStyle(self):
        self.customPreviewButton.syncStyle()
        self.chooseButton.syncStyle()
        self.playButton.syncStyle()
        self.recordButton.syncStyle()
        self.clearButton.syncStyle()

    def _update_clone_hint(self, path: str):
        if path:
            if Path(path).exists():
                self.cloneHintLabel.clear()
            else:
                self.cloneHintLabel.setText(tr("dubbing.clone.missing_file"))
        else:
            self.cloneHintLabel.clear()

    def _sync_clone_state(self):
        if not self._clone_available:
            self.cloneSection.hide()
            self.updateGeometry()
            return
        has_audio = bool(self._clone_audio_path)
        self.customPreviewButton.setText(
            tr("dubbing.btn.generate_clone") if has_audio else tr("dubbing.btn.generate_preview")
        )
        self._update_clone_hint(self._clone_audio_path)
        self.cloneTextLabel.setVisible(has_audio)
        self.cloneTextInput.setVisible(has_audio)
        self.cloneHintLabel.setVisible(bool(self.cloneHintLabel.text()))
        self.playButton.setEnabled(self._clone_audio_exists())
        self.clearButton.setEnabled(has_audio)
        self.cloneSection.updateGeometry()
        self.updateGeometry()
        self.layoutChanged.emit()

    def _clone_audio_exists(self) -> bool:
        return bool(self._clone_audio_path) and Path(self._clone_audio_path).exists()

    def _format_file_line(self, path: str) -> str:
        """file-line 文案：「文件名 · 时长s」。"""
        if not path:
            return tr("dubbing.clone.no_audio")
        name = Path(path).name
        seconds = self._audio_seconds(path)
        return f"{name} · {seconds}s" if seconds else name

    @staticmethod
    def _audio_seconds(path: str) -> int:
        if not path or not Path(path).exists():
            return 0
        try:
            from videocaptioner.core.dubbing.audio import get_audio_duration_ms

            return round(get_audio_duration_ms(path) / 1000)
        except Exception:
            return 0

    def _update_count(self):
        self.countLabel.setText(tr("dubbing.preview.char_count", count=len(self.text())))


class DubbingInterface(AppScrollArea):
    """配音音色库与试听页。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(tr("dubbing.title"))
        self.preview_thread: VoicePreviewThread | None = None
        self.player = QMediaPlayer(self)
        self.player.stateChanged.connect(self._on_player_state_changed)
        self.player.error.connect(self._on_player_error)
        self.recorder = QAudioRecorder(self)
        self._recording_output_path: Path | None = None
        self.scrollWidget = QWidget()
        self.contentLayout = QVBoxLayout(self.scrollWidget)
        self.providerCards: dict[str, SelectableCard] = {}
        self.genderFilter = "全部"
        self._active_preview_button: QWidget | None = None  # 合成中的按钮
        self._playing_button: QWidget | None = None  # 播放中的按钮（可点停止）
        self._playing_path = ""
        self._fallback_player_process: subprocess.Popen | None = None
        self._active_preview_cache_key: tuple[str, ...] | None = None
        self._preview_cache: dict[tuple[str, ...], str] = {}

        self._init_ui()
        self._connect_signals()
        self._setup_recorder()
        self._on_provider_changed(cfg.dubbing_provider.value)

    def _init_ui(self):
        self.resize(1200, 820)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("dubbingInterface")
        self.scrollWidget.setObjectName("scrollWidget")

        # 页头：标题 + 描述，随内容滚动（与批量处理页 pageTitle/pageSubtitle
        # 同款）；不再用浮动绝对定位 + viewport 顶边距的旧写法。
        self.headerWidget = QWidget(self.scrollWidget)
        headRow = QHBoxLayout(self.headerWidget)
        headRow.setContentsMargins(0, 0, 0, 0)
        headRow.setSpacing(12)
        headText = QVBoxLayout()
        headText.setContentsMargins(0, 0, 0, 0)
        headText.setSpacing(3)
        self.titleLabel = QLabel(tr("dubbing.title"), self.headerWidget)
        self.titleLabel.setObjectName("pageTitle")
        apply_font(self.titleLabel, 26, 860)
        self.subtitleLabel = QLabel(
            tr("dubbing.subtitle"), self.headerWidget
        )
        self.subtitleLabel.setObjectName("pageSubtitle")
        apply_font(self.subtitleLabel, 13, 720)
        headText.addWidget(self.titleLabel)
        headText.addWidget(self.subtitleLabel)
        headRow.addLayout(headText, 1)
        # 右侧：配音配置入口 + 当前提供商就绪状态
        self.configButton = CompactButton(tr("dubbing.btn.config"), AppIcon.SETTING, self.headerWidget)
        self.configButton.clicked.connect(self._open_dubbing_config)
        self.readyPill = StatusPill("", "neutral", self.headerWidget)
        headRow.addWidget(self.configButton, 0, Qt.AlignBottom)  # type: ignore[arg-type]
        headRow.addWidget(self.readyPill, 0, Qt.AlignBottom)  # type: ignore[arg-type]

        self.providerPanel = QWidget(self.scrollWidget)
        self.providerPanel.setFixedHeight(PROVIDER_HEIGHT)
        providerLayout = QHBoxLayout(self.providerPanel)
        providerLayout.setContentsMargins(0, 0, 0, 0)
        providerLayout.setSpacing(12)
        for option in DUBBING_PROVIDERS:
            card = SelectableCard(
                option.key,
                provider_title(option),
                provider_desc(option),
                _PROVIDER_ICONS.get(option.key),
                self.providerPanel,
            )
            text, level = _provider_badge(option)
            card.setBadge(text, level)
            card.clicked.connect(self._on_provider_changed)
            providerLayout.addWidget(card, 1)
            self.providerCards[option.key] = card

        self.bodyPanel = QWidget(self.scrollWidget)
        bodyLayout = QHBoxLayout(self.bodyPanel)
        bodyLayout.setContentsMargins(0, 0, 0, 0)
        bodyLayout.setSpacing(BODY_GAP)
        # 左侧音色库独立滚动：表头(音色库+筛选)固定，只有音色行在内部滚动；右侧预览面板固定不动。
        self.voiceTable = VoiceTable(self.bodyPanel)
        self.sidePanel = QWidget(self.bodyPanel)
        sideLayout = QVBoxLayout(self.sidePanel)
        sideLayout.setContentsMargins(0, 0, 0, 0)
        sideLayout.setSpacing(SECTION_GAP)
        self.previewPanel = PreviewPanel(self.sidePanel)
        sideLayout.addWidget(self.previewPanel)
        sideLayout.addStretch(1)
        bodyLayout.addWidget(self.voiceTable, 1)
        bodyLayout.addWidget(self.sidePanel, 0, Qt.AlignTop)  # type: ignore

        self.contentLayout.setSpacing(SECTION_GAP)
        self.contentLayout.setContentsMargins(PAGE_MARGIN_X, 20, PAGE_MARGIN_X, 22)
        self.contentLayout.addWidget(self.headerWidget)
        self.contentLayout.addWidget(self.providerPanel)
        self.contentLayout.addWidget(self.bodyPanel, 1)  # 占满剩余高度；内部 voiceScroll 滚动

    def _connect_signals(self):
        self.voiceTable.filterChanged.connect(self._on_gender_filter)
        self.voiceTable.previewRequested.connect(self._preview)
        self.voiceTable.selectedRequested.connect(self._apply_preset)
        self.previewPanel.customPreviewRequested.connect(self._preview_custom_text)
        self.previewPanel.chooseAudioRequested.connect(self._choose_clone_audio)
        self.previewPanel.playAudioRequested.connect(self._play_clone_audio)
        self.previewPanel.recordRequested.connect(self._toggle_clone_recording)
        self.previewPanel.clearRequested.connect(self._clear_clone_audio)
        self.previewPanel.layoutChanged.connect(self._refresh_body_layout)
        self.previewPanel.cloneTextChanged.connect(
            lambda text: cfg.set(cfg.dubbing_clone_text, text, save=False)
        )

    def _setup_recorder(self):
        settings = QAudioEncoderSettings()
        settings.setCodec("audio/pcm")
        settings.setSampleRate(16000)
        settings.setChannelCount(1)
        settings.setQuality(QMultimedia.NormalQuality)
        self.recorder.setEncodingSettings(settings)
        self.recorder.stateChanged.connect(self._on_recording_state_changed)

    def closeEvent(self, event):
        # 退出/切走时停掉试听网络线程、播放器与录音：main_window.closeEvent 会 close()
        # 本页，若 preview_thread 仍在跑，销毁 running QThread 会触发 qFatal。
        # 这是只读网络线程，terminate 安全。
        if self.preview_thread is not None and self.preview_thread.isRunning():
            self.preview_thread.terminate()
            self.preview_thread.wait(1000)
        self.player.stop()
        if self.recorder.state() == QMediaRecorder.RecordingState:
            self.recorder.stop()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_page_background()
        self._on_provider_changed(cfg.dubbing_provider.value)

    def _sync_page_background(self):
        palette = app_palette()
        style = f"""
            QScrollArea {{
                border: none;
                background: {palette.bg};
            }}
            QWidget#scrollWidget {{
                background: {palette.bg};
            }}
            QFrame#voiceTable {{
                background: {palette.panel};
                border: 1px solid {palette.line_soft};
                border-radius: 18px;
            }}
            QFrame#voiceHeader {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {palette.line_soft};
            }}
            QWidget#voiceListArea {{ background: transparent; }}
            QScrollArea#voiceScroll {{ background: transparent; border: none; }}
            QScrollArea#voiceScroll QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px; border: none;
            }}
            QScrollArea#voiceScroll QScrollBar::handle:vertical {{
                background: {palette.line}; border-radius: 4px; min-height: 36px;
            }}
            QScrollArea#voiceScroll QScrollBar::add-line:vertical,
            QScrollArea#voiceScroll QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
            QFrame#voiceRow {{
                background: {palette.card_surface};
                border: 1px solid {palette.line_soft};
                border-radius: {VOICE_ROW_RADIUS}px;
            }}
            QFrame#voiceRow:hover {{
                background: {palette.card_surface_hover};
            }}
            QFrame#voiceRow[selected="true"] {{
                background: {palette.selected};
                border: 1px solid {palette.accent_border};
            }}
            QFrame#cloneFileBox {{
                background: transparent;
                border: 1px dashed {rgba(palette.muted, 0.34)};
                border-radius: 12px;
            }}
            QFrame#selectedCard {{ background: transparent; border: none; }}
            QLabel#formKey {{ color: {palette.muted}; background: transparent; }}
            QLabel {{
                color: {palette.text};
                background: transparent;
            }}
            QLabel#pageTitle {{ color: {palette.text}; background: transparent; }}
            QLabel#pageSubtitle {{ color: {palette.muted}; background: transparent; }}
            QLabel#dubCaption {{
                color: {palette.muted};
            }}
            QLabel#sampleMetaLabel {{
                color: {palette.subtle};
            }}
            QLabel#voiceHeading {{ color: {palette.text}; background: transparent; }}
            QLabel#voiceTag {{
                color: {palette.subtle};
                background: {palette.card_surface};
                border: 1px solid {palette.line_soft};
                border-radius: 7px;
                padding: 1px 8px;
            }}
        """
        self.setStyleSheet(style)
        self.scrollWidget.setStyleSheet(f"QWidget#scrollWidget {{ background: {palette.bg}; }}")
        self.previewPanel.syncStyle()

    def _open_dubbing_config(self):
        """跳到设置页的「配音配置」（提供商 Key / 模型等）。"""
        window = self.window()
        if hasattr(window, "openSettingsPage"):
            window.openSettingsPage("dubbing")

    def _on_provider_changed(self, provider: str):
        # 切换提供商会重建音色/模型上下文：先彻底停掉进行中的试听播放、合成与录制。
        # 否则旧按钮仍指向播放中的音频，而下面 setCloneAvailable 会重置其文案 → 标签与行为相反。
        self._abort_preview()
        if self.recorder.state() == QMediaRecorder.RecordingState:
            self.recorder.stop()
        cfg.set(cfg.dubbing_provider, provider)
        option = get_provider_option(provider)
        ready = {
            "edge": (tr("dubbing.ready.no_key"), "ok"),
            "gemini": (tr("dubbing.ready.need_key"), "neutral"),
            "siliconflow": (tr("dubbing.ready.clone"), "ok"),
        }.get(provider, (tr("dubbing.ready.default"), "ok"))
        self.readyPill.setState(*ready)
        if option.models and not cfg.dubbing_model.value:
            cfg.set(cfg.dubbing_model, option.models[0])
        self.previewPanel.setCloneAvailable(option.supports_clone)
        self.previewPanel.setAudioPath(cfg.dubbing_clone_audio.value)
        self.previewPanel.setCloneText(cfg.dubbing_clone_text.value)

        presets = get_provider_voices(provider)
        current = cfg.dubbing_preset.value
        if current not in {voice.preset for voice in presets}:
            preset = get_dubbing_preset(presets[0].preset)
            cfg.set(cfg.dubbing_preset, presets[0].preset)
            cfg.set(cfg.dubbing_voice, preset.voice)
            cfg.set(cfg.dubbing_model, preset.model)

        for key, card in self.providerCards.items():
            card.setActive(key == provider)
        self._sync_filter_visibility(provider, presets)
        self._render_voice_table()
        self.contentLayout.update()

    def _sync_filter_visibility(self, provider: str, voices: tuple[DubbingVoiceOption, ...]):
        supports_gender = any(GENDER_FILTER_TAGS.intersection(voice.tags) for voice in voices)
        supports_clone = any("克隆" in voice.tags for voice in voices)
        heading = tr("dubbing.voice.library_zh") if provider == "siliconflow" else tr("dubbing.voice.library")
        # 切换提供商时筛选项可能变化（如克隆 tab 出现/消失），统一回到「全部」
        self.genderFilter = "全部"
        self.voiceTable.configure(heading, show_gender=supports_gender, show_clone=supports_clone)
        self.voiceTable.setFilter("全部")

    def _on_gender_filter(self, value: str):
        self.genderFilter = value
        self._render_voice_table()

    def _filtered_voices(self) -> list[DubbingVoiceOption]:
        voices = list(get_provider_voices(cfg.dubbing_provider.value))
        if self.genderFilter != "全部":
            voices = [voice for voice in voices if self.genderFilter in voice.tags]
        return voices

    def _render_voice_table(self):
        # 行控件即将重建：先释放对旧行试听按钮的引用，避免悬挂指针
        if isinstance(self._playing_button, AuditionButton):
            self._stop_playback()
        if isinstance(self._active_preview_button, AuditionButton):
            self._active_preview_button = None
        voices = self._filtered_voices()
        self.voiceTable.setVoices(voices, cfg.dubbing_preset.value)
        self.previewPanel.setCurrentVoice(self._current_voice_title())
        self._refresh_body_layout()

    def _current_voice_title(self) -> str:
        """当前选中音色的展示名（用于右栏「配音文案」标题旁的 pill）。"""
        current = cfg.dubbing_preset.value
        for voice in get_provider_voices(cfg.dubbing_provider.value):
            if voice.preset == current:
                return voice.title
        return ""

    def _refresh_body_layout(self):
        # 音色表高度由内容决定，在 voiceScroll 内滚动；bodyPanel 由布局拉伸占满视口，
        # 不再固定整页高度（否则整页一起滚、右栏跟着滚走）。
        self.viewport().update()

    def _choose_clone_audio(self):
        if not get_provider_option(cfg.dubbing_provider.value).supports_clone:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dubbing.dialog.choose_audio"),
            "",
            tr("dubbing.dialog.audio_filter"),
        )
        if not path:
            return
        cfg.set(cfg.dubbing_clone_audio, path, save=False)
        self.previewPanel.setAudioPath(path)
        self._discard_clone_preview_cache()
        self._refresh_body_layout()

    def _toggle_clone_recording(self):
        if not get_provider_option(cfg.dubbing_provider.value).supports_clone:
            return
        if self.recorder.state() == QMediaRecorder.RecordingState:
            self.recorder.stop()
            return

        output_dir = CACHE_PATH / "dubbing-clone"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._recording_output_path = output_dir / "reference.wav"
        if self._recording_output_path.exists():
            self._recording_output_path.unlink()
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self._recording_output_path)))
        self.recorder.record()
        self.previewPanel.setRecording(True)

    def _on_recording_state_changed(self, state: QMediaRecorder.State):
        recording = state == QMediaRecorder.RecordingState
        self.previewPanel.setRecording(recording)
        if recording or not self._recording_output_path:
            return
        if self._recording_output_path.exists() and self._recording_output_path.stat().st_size > 0:
            path = str(self._recording_output_path)
            cfg.set(cfg.dubbing_clone_audio, path, save=False)
            self.previewPanel.setAudioPath(path)
            self._discard_clone_preview_cache()
            self._refresh_body_layout()
            InfoBar.success(
                tr("dubbing.toast.record_done"),
                tr("dubbing.toast.record_done_body"),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self,
            )
        self._recording_output_path = None

    def _clear_clone_audio(self):
        if self.recorder.state() == QMediaRecorder.RecordingState:
            self.recorder.stop()
        cfg.set(cfg.dubbing_clone_audio, "", save=False)
        cfg.set(cfg.dubbing_clone_text, "", save=False)
        self.previewPanel.setAudioPath("")
        self.previewPanel.setCloneText("")
        self._discard_clone_preview_cache()
        self._refresh_body_layout()

    def _play_clone_audio(self):
        path = cfg.dubbing_clone_audio.value.strip()
        if not path or not Path(path).exists():
            InfoBar.warning(
                tr("dubbing.toast.audio_missing"),
                tr("dubbing.toast.audio_missing_body"),
                duration=3000,
                parent=self,
            )
            self.previewPanel.setAudioPath("")
            cfg.set(cfg.dubbing_clone_audio, "", save=False)
            self._refresh_body_layout()
            return
        if self.previewPanel.playButton is self._playing_button:
            self._stop_playback()
            return
        self._play_audio_file(path, self.previewPanel.playButton)

    def _apply_preset(self, preset_name: str):
        preset = get_dubbing_preset(preset_name)
        cfg.set(cfg.dubbing_provider, preset.provider)
        cfg.set(cfg.dubbing_preset, preset_name)
        cfg.set(cfg.dubbing_voice, preset.voice)
        cfg.set(cfg.dubbing_model, preset.model)
        if preset.api_base and not cfg.dubbing_api_base.value:
            cfg.set(cfg.dubbing_api_base, preset.api_base)
        self._on_provider_changed(preset.provider)

    def _preview_custom_text(self):
        text = self.previewPanel.text()
        if not text:
            InfoBar.warning(
                tr("dubbing.toast.empty_text"),
                tr("dubbing.toast.empty_text_body"),
                duration=3000,
                parent=self,
            )
            return
        option = get_provider_option(cfg.dubbing_provider.value)
        clone_audio_path = cfg.dubbing_clone_audio.value.strip() if option.supports_clone else ""
        clone_audio_text = cfg.dubbing_clone_text.value.strip() if clone_audio_path else ""
        if clone_audio_path and not clone_audio_text:
            InfoBar.warning(
                tr("dubbing.toast.missing_ref_text"),
                tr("dubbing.toast.missing_ref_text_body"),
                duration=3500,
                parent=self,
            )
            return
        self._preview(
            cfg.dubbing_preset.value,
            self.previewPanel.customPreviewButton,
            text=text,
            clone_audio_path=clone_audio_path,
            clone_audio_text=clone_audio_text,
        )

    # ------------------------------------------------- 试听按钮状态机
    # idle（试听）→ loading（合成中…，禁用）→ playing（停止，可点）→ idle。
    # 同一时刻只有一个按钮处于 loading 或 playing；点击播放中的按钮即停止。

    def _preview_idle_text(self, button: QWidget) -> str:
        # 自定义试听按钮播完后要复原成「生成试听音频 / 生成克隆音频」（随克隆态变），
        # 而非旧文案「试听这句话」，否则按钮标签会与右栏当前模式不一致。
        if button is self.previewPanel.customPreviewButton:
            return self.previewPanel.customButtonLabel()
        return tr("dubbing.btn.audition")

    def _set_preview_button(self, button: QWidget | None, state: str):
        if button is None:
            return
        if state == "loading":
            button.setEnabled(False)
            if hasattr(button, "setText"):
                button.setText(tr("dubbing.btn.synthesizing"))
        elif state == "playing":
            button.setEnabled(True)
            if hasattr(button, "setText"):
                button.setText(tr("dubbing.btn.stop"))
            if hasattr(button, "setIcon"):
                button.setIcon(AppIcon.CANCEL)
        else:
            button.setEnabled(True)
            if hasattr(button, "setText"):
                button.setText(self._preview_idle_text(button))
            if hasattr(button, "setIcon"):
                button.setIcon(AppIcon.PLAY)

    def _abort_preview(self):
        """彻底中止任何进行中的试听：停止播放、终止合成线程、复位 loading 按钮。

        切换提供商/页面销毁时调用。终止 running QThread 与 closeEvent 同一处理方式，
        避免合成完成后回调用旧音色播放、或 loading 按钮卡在「合成中…」。
        """
        self._stop_playback()
        if self.preview_thread is not None and self.preview_thread.isRunning():
            self.preview_thread.terminate()
            self.preview_thread.wait(1000)
        self._set_preview_button(self._active_preview_button, "idle")
        self._active_preview_button = None
        self._active_preview_cache_key = None

    def _stop_playback(self):
        if self._playing_button is not None:
            self._set_preview_button(self._playing_button, "idle")
            self._playing_button = None
        self._playing_path = ""
        self.player.stop()
        self._stop_fallback_player()

    def _on_player_state_changed(self, state):
        # 自然播完（或外部停止）：把"停止"复原成"试听"
        if state == QMediaPlayer.StoppedState and self._playing_button is not None:
            self._set_preview_button(self._playing_button, "idle")
            self._playing_button = None
            self._playing_path = ""

    def _on_player_error(self, error):
        if not self._playing_path or error == QMediaPlayer.NoError:
            return
        button = self._playing_button
        path = self._playing_path
        self.player.stop()
        if self._play_audio_with_external_player(path, button):
            return
        self._set_preview_button(button, "idle")
        self._playing_button = None
        self._playing_path = ""
        InfoBar.error(
            tr("dubbing.toast.play_failed"),
            tr("dubbing.toast.play_failed_body"),
            duration=INFOBAR_DURATION_ERROR,
            parent=self,
        )

    def _preview(
        self,
        preset_name: str,
        button: QWidget | None = None,
        *,
        text: str = "",
        clone_audio_path: str = "",
        clone_audio_text: str = "",
    ):
        if button is not None and button is self._playing_button:
            # 播放中点同一按钮 = 停止
            self._stop_playback()
            return
        if self.preview_thread and self.preview_thread.isRunning():
            InfoBar.info(
                tr("dubbing.toast.please_wait"),
                tr("dubbing.toast.please_wait_body"),
                duration=2000,
                parent=self,
            )
            return
        preset = get_dubbing_preset(preset_name)
        requires_api = text or clone_audio_path or clone_audio_text or not bundled_voice_preview(preset_name)
        if preset.provider != "edge" and not cfg.dubbing_api_key.value.strip() and requires_api:
            InfoBar.warning(
                tr("dubbing.toast.need_api_key"),
                tr("dubbing.toast.need_api_key_body"),
                duration=3500,
                parent=self,
            )
            return
        cache_key = self._preview_cache_key(
            preset_name,
            text=text,
            clone_audio_path=clone_audio_path,
            clone_audio_text=clone_audio_text,
        )
        cached_path = self._preview_cache.get(cache_key, "")
        if cached_path and Path(cached_path).exists():
            self._play_audio_file(cached_path, button)
            return
        self._active_preview_button = button
        self._active_preview_cache_key = cache_key
        self._set_preview_button(button, "loading")
        self.preview_thread = VoicePreviewThread(
            preset_name,
            text=text,
            clone_audio_path=clone_audio_path,
            clone_audio_text=clone_audio_text,
        )
        self.preview_thread.finished.connect(self._on_preview_finished)
        self.preview_thread.error.connect(self._on_preview_error)
        self.preview_thread.start()

    def _on_preview_finished(self, path: str):
        if self._active_preview_cache_key:
            self._preview_cache[self._active_preview_cache_key] = path
            self._active_preview_cache_key = None
        button = self._active_preview_button
        self._active_preview_button = None
        self._set_preview_button(button, "idle")
        # 播放状态由 _play_audio_file 接管（按钮翻成"停止"），不再弹成功通知
        self._play_audio_file(path, button)

    def _on_preview_error(self, message: str):
        self._active_preview_cache_key = None
        self._set_preview_button(self._active_preview_button, "idle")
        self._active_preview_button = None
        InfoBar.error(
            tr("dubbing.toast.preview_failed"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            parent=self,
        )

    def _play_audio_file(self, path: str, button: QWidget | None = None):
        playable_path = playable_voice_preview(Path(path))
        self._stop_playback()
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(playable_path))))
        self._playing_button = button
        self._playing_path = str(playable_path)
        self._set_preview_button(button, "playing")
        self.player.play()

    def _play_audio_with_external_player(self, path: str, button: QWidget | None = None) -> bool:
        ffplay = shutil.which("ffplay")
        if ffplay:
            command = [
                ffplay,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                path,
            ]
        else:
            paplay = shutil.which("paplay")
            if not paplay:
                return False
            command = [paplay, path]
        self._stop_fallback_player()
        try:
            self._fallback_player_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._fallback_player_process = None
            return False
        self._playing_button = button
        self._playing_path = path
        self._set_preview_button(button, "playing")
        QTimer.singleShot(300, self._poll_fallback_player)
        return True

    def _poll_fallback_player(self):
        process = self._fallback_player_process
        if process is None:
            return
        if process.poll() is None:
            QTimer.singleShot(300, self._poll_fallback_player)
            return
        self._fallback_player_process = None
        if self._playing_button is not None:
            self._set_preview_button(self._playing_button, "idle")
        self._playing_button = None
        self._playing_path = ""

    def _stop_fallback_player(self):
        process = self._fallback_player_process
        self._fallback_player_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()

    def _preview_cache_key(
        self,
        preset_name: str,
        *,
        text: str = "",
        clone_audio_path: str = "",
        clone_audio_text: str = "",
    ) -> tuple[str, ...]:
        audio_signature = ""
        if clone_audio_path:
            audio_file = Path(clone_audio_path)
            if audio_file.exists():
                stat = audio_file.stat()
                audio_signature = f"{audio_file.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
            else:
                audio_signature = clone_audio_path
        return (
            preset_name,
            cfg.dubbing_provider.value.strip(),
            cfg.dubbing_model.value.strip(),
            cfg.dubbing_voice.value.strip(),
            text.strip(),
            audio_signature,
            clone_audio_text.strip(),
        )

    def _discard_clone_preview_cache(self):
        self._preview_cache.clear()
