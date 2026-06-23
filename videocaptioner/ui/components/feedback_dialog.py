"""意见反馈弹窗：分类 + 可粘贴截图的描述编辑器 + 联系方式 → 后台 multipart 提交。

复用 AppDialog 外壳 + workbench 控件（AppTextEdit/AppLineEdit/PillSelect/RoundIconButton）。
截图由用户提供：编辑器里 Ctrl+V 直接粘贴、或拖入、或「添加图片」选文件；缩略图可删。
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
    QWidget,
)

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
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.app_dialog import AppDialog
from videocaptioner.ui.components.workbench import (
    AppLineEdit,
    AppTextEdit,
    CompactButton,
    PillSelect,
    RoundIconButton,
    apply_font,
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
    """64×64 圆角截图缩略图，右上角悬浮删除钮。"""

    removed = pyqtSignal(object)

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._pixmap = pixmap
        self._remove = RoundIconButton(AppIcon.CLOSE, diameter=20, parent=self)
        self._remove.clicked.connect(lambda: self.removed.emit(self))
        self._remove.move(self.width() - 20, 0)

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


class FeedbackDialog(AppDialog):
    """意见反馈表单弹窗。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(tr("feedback.title"), icon=AppIcon.MESSAGE, parent=parent, width=540)
        self._state = "form"  # form | submitting | done
        self._attachments: list[tuple[FeedbackAttachment, _AttachmentThumb]] = []
        self._thread: FeedbackSubmitThread | None = None
        self._categories = [(value, tr(f"feedback.category.{value}")) for value in CATEGORIES]

        # 类型
        cat_row = QHBoxLayout()
        cat_row.setSpacing(10)
        cat_label = self._field_label(tr("feedback.category.label"))
        cat_label.setFixedWidth(48)
        cat_row.addWidget(cat_label)
        self.categorySelect = PillSelect(self.widget)
        self.categorySelect.setItems([label for _, label in self._categories], current=self._categories[0][1])
        cat_row.addWidget(self.categorySelect)
        cat_row.addStretch(1)
        self.bodyLayout.addLayout(cat_row)

        # 描述编辑器（支持粘贴/拖入截图）
        self.editor = _PasteTextEdit(parent=self.widget, min_height=128)
        self.editor.setPlaceholderText(tr("feedback.message.placeholder"))
        self.editor.imagePasted.connect(self._add_image_qimage)
        self.editor.imageFilePasted.connect(self._add_image_file)
        self.bodyLayout.addWidget(self.editor)

        # 截图行：缩略图 + 添加按钮 + 计数
        attach_row = QHBoxLayout()
        attach_row.setSpacing(8)
        self.thumbStrip = QHBoxLayout()
        self.thumbStrip.setSpacing(8)
        self.thumbStrip.setContentsMargins(0, 0, 0, 0)
        attach_row.addLayout(self.thumbStrip)
        self.addImageButton = CompactButton(tr("feedback.add_image"), AppIcon.PHOTO, self.widget)
        self.addImageButton.clicked.connect(self._pick_images)
        attach_row.addWidget(self.addImageButton)
        attach_row.addStretch(1)
        self.countLabel = self._hint_label("")
        attach_row.addWidget(self.countLabel)
        self.bodyLayout.addLayout(attach_row)

        # 联系方式
        self.contactEdit = AppLineEdit("", self.widget)
        self.contactEdit.setPlaceholderText(tr("feedback.contact.placeholder"))
        self.bodyLayout.addWidget(self.contactEdit)

        # 诊断附带说明 + 提交状态
        self.diagHint = self._hint_label(tr("feedback.diagnostics_hint"))
        self.bodyLayout.addWidget(self.diagHint)
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
    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text, self.widget)
        apply_font(label, 13, 720)
        label.setStyleSheet(f"color: {app_palette().subtle}; background: transparent;")
        return label

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
        self.addImageButton.setEnabled(self._state == "form" and len(self._attachments) < MAX_FILES)

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
        self.addImageButton.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.closeButton.setEnabled(False)
        self.setClosableOnMaskClicked(False)
        self.submitButton.setEnabled(False)
        self.submitButton.setText(tr("feedback.submitting"))
        self._show_status(tr("feedback.submitting"), error=False)

    def _on_succeeded(self, feedback_id: str) -> None:
        self._state = "done"
        text = tr("feedback.success", id=feedback_id) if feedback_id else tr("feedback.success_noid")
        self._show_status(text, error=False)
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
