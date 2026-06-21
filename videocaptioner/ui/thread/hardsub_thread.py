"""硬字幕提取的 QThread 薄壳：core 耗时操作搬离 GUI 线程，结果经 Qt 信号回传。

- :class:`RegionDetectThread` → ``detected(RegionResult|None)``；
- :class:`HardsubExtractThread` → ``cue_ready`` 流式 + ``finished(ASRData)``。
core 回调在工作线程，只能经 Qt 信号（queued）回 GUI 线程碰控件；取消保留已识别结果。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.hardsub.config import HardsubConfig
from videocaptioner.core.ocr.base import OcrEngine
from videocaptioner.ui.thread.worker import WorkerThread


class PrepareThread(WorkerThread):
    """载入视频的耗时探测放后台：ffprobe 取尺寸/时长 + 抽首帧，避免拖入时 GUI 卡死。"""

    ready = pyqtSignal(int, int, float, object)  # width, height, duration, first_frame_rgb|None

    def __init__(self, video_path: str, parent=None) -> None:
        super().__init__(parent)
        self._video_path = video_path

    def _work(self) -> None:
        from videocaptioner.core.hardsub.frames import grab_frame, probe_dimensions

        dims = probe_dimensions(self._video_path)
        self.checkpoint()
        if dims is None:
            self.error.emit("无法读取该视频")
            return
        width, height, _, duration = dims
        frame = grab_frame(self._video_path, max(0.5, duration * 0.1), max_width=1280)
        self.checkpoint()
        self.ready.emit(width, height, duration, frame)


class RegionDetectThread(WorkerThread):
    """自动检测字幕区域（采样若干帧跑文本检测 + 时间稳定性投票）。"""

    detected = pyqtSignal(object)  # RegionResult(roi, font_height) 或 None

    def __init__(
        self, video_path: str, engine: OcrEngine, sample_count: int = 20, parent=None
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._engine = engine
        self._sample_count = sample_count

    def _work(self) -> None:
        from videocaptioner.core.hardsub.region import detect_subtitle_region

        self.progress.emit(0, "识别字幕区域")
        result = detect_subtitle_region(
            self._video_path, self._engine, self._sample_count,
            on_progress=lambda p: self.progress.emit(p, "识别字幕区域"),
        )
        self.checkpoint()
        self.detected.emit(result)


class HardsubExtractThread(WorkerThread):
    """提取硬字幕：流式产出每条字幕，结束发出完整 :class:`ASRData`。"""

    cue_ready = pyqtSignal(object)  # HardsubCue
    finished = pyqtSignal(object)   # ASRData（取消时为已识别的部分结果）

    def __init__(self, config: HardsubConfig, engine: OcrEngine, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._engine = engine

    def _work(self) -> None:
        from videocaptioner.core.hardsub.pipeline import extract_hardsub

        data = extract_hardsub(
            self._config,
            self._engine,
            on_cue=lambda cue: self.cue_ready.emit(cue),
            on_progress=lambda p: self.progress.emit(p.percent, f"识别中 {p.cue_count} 条"),
            should_cancel=self.is_cancel_requested,
        )
        # 取消也照常发 finished：已识别的部分保留给用户，不丢弃。
        self.finished.emit(data)


def make_engine(config: HardsubConfig, det_limit_side_len: int = 960) -> OcrEngine:
    """按配置构造 OCR 引擎（廉价，模型在引擎首次推理时才加载——放到线程里）。"""
    from videocaptioner.core.ocr.rapid import create_rapidocr

    return create_rapidocr(
        lang=config.lang, ocr_version=config.ocr_version, model_type=config.model_type,
        det_limit_side_len=det_limit_side_len,
    )


def ocr_ready() -> Optional[str]:
    """OCR 依赖是否就绪；就绪返回 None，否则返回缺失原因。"""
    from videocaptioner.core.ocr.rapid import ocr_dependency_ready

    return ocr_dependency_ready()
