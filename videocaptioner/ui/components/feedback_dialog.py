"""意见反馈弹窗：分类 + 可粘贴截图的描述编辑器 + 联系方式 → 后台 multipart 提交。

复用 AppDialog 外壳 + workbench 控件；类型用整宽 _SelectField、添加截图用与缩略图等大的 _AddImageTile，
让所有控件成一套视觉。截图由用户提供：编辑器里 Ctrl+V 粘贴、拖入，或点 + 块选文件；缩略图可删。
诊断信息默认随提交附带（无开关），但绝不含密钥（见 core/feedback/diagnostics）。
"""

from __future__ import annotations

from PyQt5.QtCore import QBuffer, QByteArray, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Action, RoundMenu

from videocaptioner.core.feedback import (
    CATEGORIES,
    MAX_FILE_BYTES,
    MAX_FILES,
    FeedbackAttachment,
    FeedbackReport,
    FeedbackValidationError,
    gather_diagnostics,
)
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette, rgba
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import (
    AppLineEdit,
    AppTextEdit,
    RoundIconButton,
    SectionLabel,
    apply_font,
    draw_rounded_surface,
    icon_pixmap,
)
from videocaptioner.ui.i18n import N_, tr
from videocaptioner.ui.thread.feedback_thread import FeedbackSubmitThread

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

# 动态拼接的 key（tr(f"feedback.category.{...}") / tr(f"feedback.err.{...}")）pybabel 抽不到，
# 在此用 N_ 显式登记，让 extract 收进 .pot（运行时仍走上面的 f-string tr）。
_REGISTER_I18N = (
    N_("feedback.category.bug"),
    N_("feedback.category.feature"),
    N_("feedback.category.question"),
    N_("feedback.category.other"),
    N_("feedback.err.message_required"),
    N_("feedback.err.message_too_long"),
    N_("feedback.err.contact_too_long"),
    N_("feedback.err.too_many_files"),
    N_("feedback.err.file_type"),
    N_("feedback.err.file_too_large"),
    N_("feedback.err.total_too_large"),
    N_("feedback.err.category_invalid"),
    N_("feedback.err.network"),
    N_("feedback.err.unauthorized"),
    N_("feedback.err.too_large"),
    N_("feedback.err.invalid_request"),
    N_("feedback.err.server"),
)


def _qimage_to_png(image: QImage) -> bytes:
    # QByteArray 必须用局部变量持有：内联传给 QBuffer 的临时对象会被回收，写入即野指针（bus error）。
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.WriteOnly)  # type: ignore[attr-defined]
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


class _PasteTextEdit(AppTextEdit):
    """描述编辑器：拦截粘贴/拖入的图片，转交给弹窗当作截图；文本照常粘贴。"""

    imagePasted = pyqtSignal(QImage)
    imageFilePasted = pyqtSignal(str)

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self.imagePasted.emit(image)
                return
        if source.hasUrls():
            paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            images = [p for p in paths if p.lower().endswith(_IMAGE_SUFFIXES)]
            if images:
                for path in images:
                    self.imageFilePasted.emit(path)
                return
        super().insertFromMimeData(source)


class _AttachmentThumb(QFrame):
    """56×56 圆角截图缩略图，右上角悬浮删除钮。"""

    removed = pyqtSignal(object)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self._pixmap = pixmap
        self._remove = RoundIconButton(AppIcon.CLOSE, diameter=18, parent=self)
        self._remove.clicked.connect(lambda: self.removed.emit(self))
        self._remove.move(self.width() - 18, 0)

    def paintEvent(self, event):
        palette = app_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 9, 9)
        painter.setClipPath(clip)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,  # type: ignore[attr-defined]
                Qt.SmoothTransformation,  # type: ignore[attr-defined]
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        painter.setClipping(False)
        painter.setPen(QColor(palette.line_soft))
        painter.setBrush(Qt.NoBrush)  # type: ignore[attr-defined]
        painter.drawRoundedRect(rect, 9, 9)


class _SelectField(QFrame):
    """整宽下拉：外观与 AppLineEdit 一致（同高 36 / 圆角 9 / 同边框），点击弹 RoundMenu 选值。

    取代 PillSelect 的小胶囊，让「类型」与下面的描述框 / 联系方式框是同一套视觉。
    """

    currentTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[str] = []
        self._current = ""
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[attr-defined]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(8)
        self.textLabel = QLabel(self)
        apply_font(self.textLabel, 14, 720)
        self.textLabel.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.textLabel)
        layout.addStretch(1)
        self.chevron = QLabel(self)
        self.chevron.setFixedSize(14, 14)
        self.chevron.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.chevron, 0, Qt.AlignVCenter)  # type: ignore[attr-defined]
        self._sync()

    def setItems(self, items: list[str], current: str | None = None) -> None:
        self._items = list(items)
        self.setCurrentText(current if current is not None else (items[0] if items else ""))

    def currentText(self) -> str:
        return self._current

    def setCurrentText(self, text: str) -> None:
        self._current = text
        self.textLabel.setText(text)
        self.currentTextChanged.emit(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._items:  # type: ignore[attr-defined]
            menu = RoundMenu(parent=self)
            for item in self._items:
                action = Action(item)
                action.triggered.connect(lambda _=False, text=item: self.setCurrentText(text))
                menu.addAction(action)
            menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        border = palette.accent_border if (self.underMouse() and self.isEnabled()) else palette.line_soft
        draw_rounded_surface(self, palette.field, border, 9)
        super().paintEvent(event)

    def _sync(self) -> None:
        palette = app_palette()
        self.chevron.setPixmap(icon_pixmap(AppIcon.CHEVRON_DOWN, palette.subtle, 14))
        self.textLabel.setStyleSheet(f"color: {palette.text}; background: transparent; border: none;")


class _AddImageTile(QFrame):
    """与缩略图等大（56×56）的「添加图片」方块，中心 + 号；和缩略图排成一排等大方块。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[attr-defined]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        palette = app_palette()
        hovered = self.underMouse() and self.isEnabled()
        draw_rounded_surface(
            self,
            rgba(palette.accent, 0.10 if hovered else 0.05),
            rgba(palette.accent, 0.70 if hovered else 0.40),
            9,
        )
        size = 22
        pixmap = icon_pixmap(AppIcon.ADD, palette.accent_text, size)
        painter = QPainter(self)
        painter.drawPixmap((self.width() - size) // 2, (self.height() - size) // 2, pixmap)


class FeedbackDialog(AppDialog):
    """意见反馈表单弹窗。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(tr("feedback.title"), icon=AppIcon.MESSAGE, parent=parent, width=540)
        self._state = "form"  # form | submitting | done
        self._attachments: list[tuple[FeedbackAttachment, _AttachmentThumb]] = []
        self._thread: FeedbackSubmitThread | None = None
        self._categories = [(value, tr(f"feedback.category.{value}")) for value in CATEGORIES]
        self.bodyLayout.setSpacing(15)  # 字段组之间留白（组内由 _add_field 收紧）

        # 顶部说明：让用户知道反馈直达开发者、会被处理
        self.intro = self.addBodyText(tr("feedback.intro"))

        # 类型：整宽下拉，与下面的输入框同款
        self.categorySelect = _SelectField(self.widget)
        self.categorySelect.setItems([label for _, label in self._categories], current=self._categories[0][1])
        self._add_field(tr("feedback.category.label"), self.categorySelect)

        # 问题描述：定高，避免 QPlainTextEdit 的 Expanding 策略把空输入框撑得过高、显空旷（超出滚动）
        self.editor = _PasteTextEdit(parent=self.widget, min_height=112)
        self.editor.setFixedHeight(112)
        self.editor.setPlaceholderText(tr("feedback.message.placeholder"))
        self.editor.imagePasted.connect(self._add_image_qimage)
        self.editor.imageFilePasted.connect(self._add_image_file)
        self._add_field(tr("feedback.section.message"), self.editor)

        # 截图（选填）：计数放小节标题右侧；标题下提示可粘贴；缩略图与「+」添加块排成一排等大方块
        self.countLabel = self._hint_label("")
        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(0, 0, 0, 0)
        attach_row.setSpacing(8)
        self.thumbStrip = QHBoxLayout()
        self.thumbStrip.setSpacing(8)
        self.thumbStrip.setContentsMargins(0, 0, 0, 0)
        attach_row.addLayout(self.thumbStrip)
        self.addTile = _AddImageTile(self.widget)
        self.addTile.clicked.connect(self._pick_images)
        attach_row.addWidget(self.addTile, 0, Qt.AlignVCenter)  # type: ignore[attr-defined]
        attach_row.addStretch(1)
        self._add_field(
            tr("feedback.section.screenshot"), attach_row,
            hint=tr("feedback.screenshot.hint"), header_right=self.countLabel,
        )

        # 联系方式（选填）
        self.contactEdit = AppLineEdit("", self.widget)
        self.contactEdit.setPlaceholderText(tr("feedback.contact.placeholder"))
        self._add_field(tr("feedback.section.contact"), self.contactEdit)

        # 提交状态（默认隐藏）
        self.statusLabel = QLabel("", self.widget)
        self.statusLabel.setWordWrap(True)
        self.statusLabel.setObjectName("feedbackStatus")
        apply_font(self.statusLabel, 13, 640)
        self.statusLabel.setVisible(False)
        self.bodyLayout.addWidget(self.statusLabel)

        # 底栏
        self.addFooterStretch()
        self.cancelButton = self.addFooterButton(tr("common.cancel"))
        self.cancelButton.clicked.connect(lambda: self.done(0))
        self.submitButton = self.addFooterButton(tr("feedback.submit"), kind="accent")
        self.submitButton.clicked.connect(self._on_primary)

        self._refresh_count()
        self.syncStyle()

    # ----------------------------------------------------------- helpers
    def _add_field(self, label_text: str, content, hint: str | None = None, header_right: QWidget | None = None) -> None:
        """一个表单字段：小节标题行（可带右侧元数据）+ 可选提示 + 控件；组内紧凑、组间留白。"""
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(SectionLabel(label_text, self.widget))
        if header_right is not None:
            header.addStretch(1)
            header.addWidget(header_right)
        group.addLayout(header)
        if hint:
            group.addWidget(self._hint_label(hint))
        if isinstance(content, QWidget):
            group.addWidget(content)
        else:
            group.addLayout(content)
        self.bodyLayout.addLayout(group)

    def _hint_label(self, text: str) -> QLabel:
        label = QLabel(text, self.widget)
        apply_font(label, 12, 560)
        label.setStyleSheet(f"color: {app_palette().subtle}; background: transparent;")
        return label

    def extraStyleRules(self, palette) -> str:
        return f"QLabel#feedbackStatus {{ color: {palette.text}; background: transparent; }}"

    # ----------------------------------------------------------- attachments
    def _add_image_qimage(self, image: QImage) -> None:
        if image.isNull():
            return
        data = _qimage_to_png(image)
        self._add_attachment(f"screenshot-{len(self._attachments) + 1}.png", data, "image/png", QPixmap.fromImage(image))

    def _add_image_file(self, path: str) -> None:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "screenshot"
        self._add_attachment(name, data, mime, pixmap)

    def _pick_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("feedback.add_image"), "", "Images (*.png *.jpg *.jpeg)"
        )
        for path in paths:
            self._add_image_file(path)

    def _add_attachment(self, filename: str, data: bytes, mime: str, pixmap: QPixmap) -> None:
        if len(self._attachments) >= MAX_FILES:
            self._show_status(tr("feedback.err.too_many_files"), error=True)
            return
        if len(data) > MAX_FILE_BYTES:
            self._show_status(tr("feedback.err.file_too_large"), error=True)
            return
        attachment = FeedbackAttachment(filename=filename, data=data, mime=mime)
        thumb = _AttachmentThumb(pixmap, self.widget)
        thumb.removed.connect(self._remove_attachment)
        self.thumbStrip.addWidget(thumb)
        self._attachments.append((attachment, thumb))
        self.statusLabel.setVisible(False)
        self._refresh_count()

    def _remove_attachment(self, thumb: _AttachmentThumb) -> None:
        self._attachments = [(a, t) for a, t in self._attachments if t is not thumb]
        self.thumbStrip.removeWidget(thumb)
        thumb.setParent(None)
        thumb.deleteLater()
        self._refresh_count()

    def _refresh_count(self) -> None:
        self.countLabel.setText(tr("feedback.attach_count", count=len(self._attachments), max=MAX_FILES))
        self.addTile.setVisible(len(self._attachments) < MAX_FILES)  # 满 3 张隐藏添加块
        self.addTile.setEnabled(self._state == "form")

    # ----------------------------------------------------------- submit
    def _selected_category(self) -> str:
        current = self.categorySelect.currentText()
        for value, label in self._categories:
            if label == current:
                return value
        return CATEGORIES[0]

    def _on_primary(self) -> None:
        if self._state == "done":
            self.done(1)
            return
        if self._state == "submitting":
            return
        report = FeedbackReport(
            category=self._selected_category(),
            message=self.editor.toPlainText(),
            contact=self.contactEdit.text(),
            attachments=[a for a, _ in self._attachments],
            diagnostics=gather_diagnostics(),
        )
        try:
            report.validate()
        except FeedbackValidationError as exc:
            self._show_status(self._err_text(exc.code), error=True)
            return
        self._set_submitting()
        self._thread = FeedbackSubmitThread(report, self)
        self._thread.succeeded.connect(self._on_succeeded)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _set_submitting(self) -> None:
        self._state = "submitting"
        self.editor.setReadOnly(True)
        self.categorySelect.setEnabled(False)
        self.contactEdit.setEnabled(False)
        self.addTile.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.closeButton.setEnabled(False)
        self.setClosableOnMaskClicked(False)
        self.submitButton.setEnabled(False)
        self.submitButton.setText(tr("feedback.submitting"))
        self._show_status(tr("feedback.submitting"), error=False)

    def _on_succeeded(self, feedback_id: str) -> None:
        # 编号对用户不可查（后端本期无状态查询），不展示；只给"已收到、会处理"的安心反馈。
        self._state = "done"
        self._show_status(tr("feedback.success"), error=False)
        self.cancelButton.setVisible(False)
        self.closeButton.setEnabled(True)
        self.submitButton.setEnabled(True)
        self.submitButton.setText(tr("feedback.done"))

    def _on_failed(self, code: str, error: str) -> None:
        self._state = "form"
        self.editor.setReadOnly(False)
        self.categorySelect.setEnabled(True)
        self.contactEdit.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self.closeButton.setEnabled(True)
        self.setClosableOnMaskClicked(True)
        self.submitButton.setEnabled(True)
        self.submitButton.setText(tr("feedback.submit"))
        self._refresh_count()
        self._show_status(self._err_text(code), error=True)

    def _show_status(self, text: str, *, error: bool) -> None:
        palette = app_palette()
        color = palette.danger if error else palette.accent_text
        self.statusLabel.setStyleSheet(f"color: {color}; background: transparent;")
        self.statusLabel.setText(text)
        self.statusLabel.setVisible(True)

    def _err_text(self, code: str) -> str:
        known = {
            "message_required", "message_too_long", "contact_too_long", "too_many_files",
            "file_type", "file_too_large", "total_too_large", "category_invalid",
            "network", "unauthorized", "too_large", "invalid_request",
        }
        return tr(f"feedback.err.{code}") if code in known else tr("feedback.err.server")

    def done(self, code: int) -> None:
        # 提交进行中不允许关闭（Esc/遮罩/关闭钮）：避免销毁运行中的线程
        if self._state == "submitting":
            return
        super().done(code)
