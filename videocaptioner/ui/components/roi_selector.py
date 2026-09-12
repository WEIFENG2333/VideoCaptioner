"""视频字幕区域框选控件：静止帧背景上自绘可拖拽/缩放的矩形选框 + 底部换帧 scrubber。

为什么用静止帧而不在 QVideoWidget 上叠层：QVideoWidget 在 mac/Win 是原生子窗口，叠的选框会
被视频画面盖住 / 透明失效。框选字幕区根本不需要播放——用 ffmpeg 抽某一时刻的帧当背景，在普通
QWidget 上自绘选框，坐标系最干净。拖 scrubber 换看不同时刻的帧，便于把框对准稳定的字幕带。

坐标：选框对外一律用「视频原始分辨率像素」(roi_src)，控件像素经 letterbox(居中黑边)反算。
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.workbench import apply_font, icon_pixmap, to_qcolor
from videocaptioner.ui.i18n import tr

# 边缘掩码（位运算，与 caption_overlay 的拖拽/缩放同风格）
_L, _R, _T, _B = 1, 2, 4, 8
_HANDLE = 9   # 手柄命中半径（px）
_BAR_H = 56   # 底部控制条高度


def ndarray_to_qpixmap(arr: np.ndarray) -> QPixmap:
    """RGB ndarray (H,W,3) → QPixmap。必须 ascontiguous + 传 strides + copy()，
    否则 QImage 零拷贝引用 numpy buffer，buffer 被 GC 后会花屏/崩溃。"""
    arr = np.ascontiguousarray(arr)
    h, w, _ = arr.shape
    qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class _ScrubBar(QWidget):
    """底部换帧条：进度条 + 时间码 + 文件名 + 提示。点击/拖动发出 seek(比例)。"""

    seeked = pyqtSignal(float)  # 0.0 - 1.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_BAR_H)
        self._fraction = 0.0
        self._duration = 0.0
        self._clip_name = ""
        self._dragging = False
        self.setCursor(Qt.PointingHandCursor)  # type: ignore[arg-type]

    def set_clip(self, name: str, duration: float) -> None:
        self._clip_name = name
        self._duration = duration
        self.update()

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def _track_rect(self) -> QRect:
        return QRect(14, 12, self.width() - 28, 6)

    def _seek_to(self, x: int) -> None:
        track = self._track_rect()
        frac = (x - track.left()) / max(1, track.width())
        self.set_fraction(frac)
        self.seeked.emit(self._fraction)

    def mousePressEvent(self, event):
        # 只在轨道/滑块区起拖；点到下面的时间/提示文字不跳帧（否则像"突然播放"）。
        if (
            event.button() == Qt.LeftButton  # type: ignore[attr-defined]
            and event.pos().y() <= self._track_rect().bottom() + 8
        ):
            self._dragging = True
            self._seek_to(event.pos().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek_to(event.pos().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def paintEvent(self, _event):
        palette = app_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 半透明深色底（叠在帧上）
        p.setPen(Qt.NoPen)  # type: ignore[arg-type]
        p.setBrush(QColor(10, 17, 15, 184))
        p.drawRoundedRect(self.rect(), 12, 12)
        # 轨道 + 已播部分 + 滑块
        track = self._track_rect()
        p.setBrush(QColor(197, 215, 209, 56))
        p.drawRoundedRect(track, 3, 3)
        fill_w = int(track.width() * self._fraction)
        if fill_w > 0:
            p.setBrush(QColor(palette.accent))
            p.drawRoundedRect(QRect(track.left(), track.top(), fill_w, track.height()), 3, 3)
        thumb_x = track.left() + fill_w
        p.setBrush(QColor(palette.accent))
        p.drawEllipse(QPoint(thumb_x, track.center().y()), 7, 7)
        # 时间码 + 文件名（左）/ 提示（右）
        cur = self._fraction * self._duration
        p.setPen(QColor("#f5fbf8"))
        apply_font(self, 12, 800)
        p.setFont(self.font())
        # 左：时间码；右：提示。不再画文件名——它与面板头标题重复。
        text_y = track.bottom() + 6
        p.drawText(QRect(14, text_y, 200, 22), Qt.AlignVCenter | Qt.AlignLeft,  # type: ignore[arg-type]
                   f"{self._fmt(cur)} / {self._fmt(self._duration)}")
        p.setPen(QColor(palette.subtle))
        p.drawText(QRect(self.width() - 180, text_y, 166, 22),
                   Qt.AlignVCenter | Qt.AlignRight, tr("roi.scrub.hint"))  # type: ignore[arg-type]


class RoiSelector(QWidget):
    """静止帧 + 可编辑字幕区选框。``frame_provider(t)`` 由页面提供，按秒抽帧返回 RGB ndarray。"""

    roi_changed = pyqtSignal(object)  # (x, y, w, h) 原始分辨率，或 None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("roiSelector")
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self._pix: Optional[QPixmap] = None
        self._src_size = QSize(1, 1)
        self._duration = 0.0
        self._frame_provider: Optional[Callable[[float], Optional[np.ndarray]]] = None
        # ROI 以「原始分辨率坐标」为唯一真相；_roi 是它在当前布局下派生的控件矩形（绘制/命中用）。
        # 这样窗口 resize / 换帧时框始终贴住同一画面区域，不漂移。
        self._roi_src: Optional[tuple] = None
        self._roi = QRect()          # 控件坐标（从 _roi_src 派生）
        self._mode: Optional[str] = None
        self._edge = 0
        self._press = QPoint()
        self._roi_at_press = QRect()
        self._scale = 1.0
        self._off = QPoint(0, 0)
        self._new_dragging = False   # 新建框是否已拖动（区分单击空白 vs 拖框）
        self._busy_text: Optional[str] = None

        self._bar = _ScrubBar(self)
        self._bar.seeked.connect(self._on_seek)
        self._bar.hide()

    # ----- 对外 -----

    def set_video(
        self,
        frame_provider: Callable[[float], Optional[np.ndarray]],
        src_size: QSize,
        duration: float,
        clip_name: str,
        first_frame: Optional[np.ndarray] = None,
    ) -> None:
        """绑定抽帧回调与视频尺寸/时长并显示首帧。``first_frame`` 由上层后台预抽好直接用，
        避免在 GUI 线程再抽一次（拖入卡顿）。坐标系恒为 ``src_size`` 原始分辨率。"""
        self._frame_provider = frame_provider
        self._src_size = src_size
        self._duration = duration
        self._busy_text = None
        self._bar.set_clip(clip_name, duration)
        self._bar.set_fraction(0.1)
        self._bar.show()
        if first_frame is not None:
            self._pix = ndarray_to_qpixmap(first_frame)
            self._recompute_layout()
            self.update()
        else:
            self._show_frame_at(max(0.5, duration * 0.1))

    def set_roi_src(self, roi: Optional[tuple]) -> None:
        """从原始分辨率 ROI 设置选框（自动检测结果回填）。None 清空；越界先 clamp 到画面内。"""
        if roi is None:
            self._roi_src = None
        else:
            sw, sh = self._src_size.width(), self._src_size.height()
            x = max(0, min(int(roi[0]), sw - 1))
            y = max(0, min(int(roi[1]), sh - 1))
            w = max(1, min(int(roi[2]), sw - x))
            h = max(1, min(int(roi[3]), sh - y))
            self._roi_src = (x, y, w, h)
        self._sync_roi_from_src()
        self.update()

    def set_busy(self, text: Optional[str]) -> None:
        """显示/清除居中「正在进行」遮罩（如「识别字幕区域中…」）。"""
        self._busy_text = text
        self.update()

    def roi_src(self) -> Optional[tuple]:
        return self._roi_src

    def seek_to(self, seconds: float) -> None:
        """跳到某一时刻并显示该帧（结果表点行「定位到此画面」用：让用户核对该条字幕的真实画面）。"""
        if self._frame_provider is None:
            return
        seconds = max(0.0, min(seconds, self._duration))
        if self._duration > 0:
            self._bar.set_fraction(seconds / self._duration)
        self._show_frame_at(seconds)

    def _sync_roi_from_src(self) -> None:
        """按当前布局把 _roi_src（原始坐标）派生成 _roi（控件坐标），并 clamp 到画面显示区。"""
        if self._roi_src is None:
            self._roi = QRect()
            return
        x, y, w, h = self._roi_src
        tl = self._src_to_widget(x, y)
        br = self._src_to_widget(x + w, y + h)
        self._roi = QRect(tl, br).normalized()
        self._clamp_to_image()

    def _commit_roi_to_src(self) -> None:
        """编辑（拖/拉/新建）结束后把控件坐标的 _roi 写回 _roi_src。"""
        if not self._roi.isValid() or self._roi.width() < 4 or self._roi.height() < 4:
            self._roi_src = None
            return
        tl = self._widget_to_src(self._roi.left(), self._roi.top())
        br = self._widget_to_src(self._roi.right(), self._roi.bottom())
        # round 而非 int：_src_to_widget 与这里都向下取整会让每次微调框左上角往原点漂 3-4px、
        # 多次编辑后累积偏移，round 让往返映射近似无损。
        self._roi_src = (round(tl[0]), round(tl[1]), round(br[0] - tl[0]), round(br[1] - tl[1]))

    def clear(self) -> None:
        self._pix = None
        self._roi_src = None
        self._roi = QRect()
        self._bar.hide()
        self.update()

    # ----- 帧 / 布局 -----

    def _show_frame_at(self, t: float) -> None:
        if self._frame_provider is None:
            return
        arr = self._frame_provider(t)
        if arr is None:
            return
        # 抽帧可能为提速被缩小，但坐标系始终用原始分辨率（_src_size 由 set_video 设定，不被覆盖）：
        # 否则 ROI 的原始坐标会被当成缩放坐标，框就错位/超界。pixmap 画进 image_rect 时自然缩放。
        self._pix = ndarray_to_qpixmap(arr)
        self._recompute_layout()
        self.update()

    def _on_seek(self, fraction: float) -> None:
        # 换帧只换背景图；ROI 是原始坐标，_sync_roi_from_src 会重画，位置不变。
        self._show_frame_at(fraction * self._duration)

    def _recompute_layout(self) -> None:
        sw, sh = self._src_size.width(), self._src_size.height()
        # 底部 scrubber 覆盖在帧上：帧避开它，避免字幕区被遮且坐标更直观。
        avail_h = max(1, self.height() - _BAR_H - 14)
        scale = min(self.width() / max(1, sw), avail_h / max(1, sh))
        self._scale = scale
        dw, dh = sw * scale, sh * scale
        self._off = QPoint(int((self.width() - dw) / 2), int((avail_h - dh) / 2))
        self._sync_roi_from_src()

    def resizeEvent(self, event):
        self._recompute_layout()
        self._bar.setGeometry(16, self.height() - _BAR_H - 14, self.width() - 32, _BAR_H)
        super().resizeEvent(event)

    # ----- 坐标映射 -----

    def _widget_to_src(self, px: float, py: float) -> tuple:
        s = self._scale or 1.0
        return ((px - self._off.x()) / s, (py - self._off.y()) / s)

    def _src_to_widget(self, sx: float, sy: float) -> QPoint:
        return QPoint(
            round(sx * self._scale + self._off.x()), round(sy * self._scale + self._off.y())
        )

    def _image_rect(self) -> QRect:
        return QRect(
            self._off.x(), self._off.y(),
            int(self._src_size.width() * self._scale),
            int(self._src_size.height() * self._scale),
        )

    # ----- 选框手柄 -----

    def _handles(self) -> dict:
        r = self._roi
        cx, cy = r.center().x(), r.center().y()
        pts = {
            _T | _L: r.topLeft(), _T: QPoint(cx, r.top()), _T | _R: r.topRight(),
            _L: QPoint(r.left(), cy), _R: QPoint(r.right(), cy),
            _B | _L: r.bottomLeft(), _B: QPoint(cx, r.bottom()), _B | _R: r.bottomRight(),
        }
        return {edge: QRect(p.x() - _HANDLE, p.y() - _HANDLE, 2 * _HANDLE, 2 * _HANDLE)
                for edge, p in pts.items()}

    def _hit(self, pos: QPoint) -> tuple:
        if self._roi.isValid():
            for edge, rect in self._handles().items():
                if rect.contains(pos):
                    return "resize", edge
            if self._roi.contains(pos):
                return "move", 0
        return "new", 0

    @staticmethod
    def _cursor_for(edge: int):
        if edge in (_T | _L, _B | _R):
            return Qt.SizeFDiagCursor
        if edge in (_T | _R, _B | _L):
            return Qt.SizeBDiagCursor
        if edge in (_L, _R):
            return Qt.SizeHorCursor
        if edge in (_T, _B):
            return Qt.SizeVerCursor
        return Qt.SizeAllCursor

    # ----- 鼠标 -----

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._pix is None:  # type: ignore[attr-defined]
            return
        if not self._image_rect().contains(event.pos()):
            return
        self._press = event.pos()
        self._roi_at_press = QRect(self._roi)
        self._mode, self._edge = self._hit(event.pos())
        # 新建框先不动旧框，等真正拖动了再开画——单击空白不应把已有框清成一个点。
        self._new_dragging = False
        self.update()

    def mouseMoveEvent(self, event):
        if self._mode is None:
            if self._pix is not None and self._image_rect().contains(event.pos()):
                mode, edge = self._hit(event.pos())
                self.setCursor(
                    self._cursor_for(edge) if mode == "resize"
                    else (Qt.SizeAllCursor if mode == "move" else Qt.CrossCursor)
                )
            else:
                self.unsetCursor()
            return
        delta = event.pos() - self._press
        if self._mode == "new":
            # 拖动超过阈值才开始画新框；否则保持旧框（避免单击空白误清）。
            if not self._new_dragging and delta.manhattanLength() < 6:
                return
            self._new_dragging = True
            self._roi = QRect(self._press, event.pos()).normalized()
        elif self._mode == "move":
            self._roi = self._roi_at_press.translated(delta)
        elif self._mode == "resize":
            r = QRect(self._roi_at_press)
            if self._edge & _L:
                r.setLeft(r.left() + delta.x())
            if self._edge & _R:
                r.setRight(r.right() + delta.x())
            if self._edge & _T:
                r.setTop(r.top() + delta.y())
            if self._edge & _B:
                r.setBottom(r.bottom() + delta.y())
            self._roi = r.normalized()
        self._clamp_to_image()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._mode is None:
            return
        was_new = self._mode == "new"
        self._mode = None
        self._edge = 0
        if was_new and not self._new_dragging:
            # 单击空白没拖动：保持原框不变，不提交（不清掉已有框）。
            self._roi = QRect(self._roi_at_press)
            self.update()
            return
        self._commit_roi_to_src()
        self.update()
        self.roi_changed.emit(self.roi_src())

    def _clamp_to_image(self) -> None:
        img = self._image_rect()
        r = self._roi
        r.setLeft(max(img.left(), r.left()))
        r.setTop(max(img.top(), r.top()))
        r.setRight(min(img.right(), r.right()))
        r.setBottom(min(img.bottom(), r.bottom()))
        self._roi = r

    # ----- 绘制 -----

    def paintEvent(self, _event):
        palette = app_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)  # 帧图缩放不锯齿
        p.fillRect(self.rect(), QColor("#10100f"))  # 帧外黑边
        if self._pix is None:
            if self._busy_text:
                self._paint_busy(p)
            return
        img = self._image_rect()
        # 圆角裁剪帧，和面板/卡片的圆润风格一致（直角硬边显得突兀）。
        frame_path = QPainterPath()
        frame_path.addRoundedRect(QRectF(img), 12, 12)
        p.save()
        p.setClipPath(frame_path)
        p.drawPixmap(img, self._pix)
        p.restore()
        roi = self._roi.intersected(img)
        if roi.width() > 2 and roi.height() > 2:
            # 只压暗 ROI 之外的画面（even-odd：整幅画面矩形「减去」ROI 矩形），ROI 内透出原画面。
            # 不能用 CompositionMode_Clear——那会把已画的视频帧一起擦成透明、露出底色（之前的白块）。
            mask = QPainterPath()
            mask.addRect(QRectF(img))
            mask.addRect(QRectF(roi))
            mask.setFillRule(Qt.OddEvenFill)  # type: ignore[arg-type]
            p.fillPath(mask, QColor(0, 0, 0, 96))
            # 选框 + 8 手柄（主题色边、白色实心手柄）
            accent = to_qcolor(palette.accent)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)  # type: ignore[arg-type]
            p.drawRoundedRect(roi, 6, 6)
            p.setPen(Qt.NoPen)  # type: ignore[arg-type]
            p.setBrush(QColor("#ffffff"))
            for hr in self._handles().values():
                p.drawRoundedRect(hr.adjusted(4, 4, -4, -4), 2, 2)
            # 右上角「字幕区域」标签（不越出画面顶部）
            label = tr("roi.tag.caption_area")
            apply_font(self, 11, 850)
            p.setFont(self.font())
            lw = self.fontMetrics().horizontalAdvance(label) + 20
            tag_y = max(img.top() + 2, roi.top() - 28)
            tag = QRect(min(roi.right() - lw, img.right() - lw - 2), tag_y, lw, 22)
            p.setBrush(QColor(11, 23, 19, 235))
            p.setPen(QPen(to_qcolor(palette.accent_border), 1))
            p.drawRoundedRect(tag, 11, 11)
            p.setPen(to_qcolor(palette.accent_text))
            p.drawText(tag, Qt.AlignCenter, label)  # type: ignore[arg-type]
        if self._busy_text:
            self._paint_busy(p)

    def _paint_busy(self, p: QPainter) -> None:
        """识别/载入时的居中遮罩提示，让用户知道「正在进行」。"""
        palette = app_palette()
        p.fillRect(self.rect(), QColor(8, 14, 12, 150))
        apply_font(self, 15, 850)
        p.setFont(self.font())
        p.setPen(to_qcolor(palette.accent_text))
        p.drawText(self.rect(), Qt.AlignCenter, self._busy_text)  # type: ignore[arg-type]


# 让 icon 引用不被 lint 当未使用（页面层用同一套 AppIcon；此处保留以备扩展工具按钮）
_ = (AppIcon, icon_pixmap)
