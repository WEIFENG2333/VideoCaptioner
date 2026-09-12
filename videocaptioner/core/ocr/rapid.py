"""RapidOCR(onnxruntime) 引擎：PP-OCR 模型转 ONNX，torch-free、纯 CPU、跨平台一致。

重库 ``rapidocr``/``onnxruntime`` 懒加载（首次推理才 import），不拖慢启动。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from videocaptioner.core.ocr.base import BBox, OcrEngine, OcrError, OcrLine, bbox_of
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("ocr_rapid")


def _silence_rapidocr_logs() -> None:
    """把 RapidOCR 各子模块 logger 压到 ERROR：它每帧刷 INFO/WARNING（File exists / detection result is empty）淹没日志。"""
    for name in list(logging.root.manager.loggerDict):  # type: ignore[attr-defined]
        if "rapidocr" in name.lower():
            logging.getLogger(name).setLevel(logging.ERROR)
    logging.getLogger("RapidOCR").setLevel(logging.ERROR)

# rec 语言 → det 语言。det 只分中/英/多语三套模型；CJK 系（中/繁/日/韩）统一走 multi det
# 召回最稳，纯英文用 en det 更快更准。
_DET_LANG = {"ch": "ch", "en": "en", "chinese_cht": "ch"}


class RapidOcrEngine(OcrEngine):
    """RapidOCR 封装。``lang`` 为识别语言（"ch" 即中英通吃），其余为质量/速度旋钮。"""

    def __init__(
        self,
        lang: str = "ch",
        ocr_version: str = "PP-OCRv4",
        model_type: str = "mobile",
        text_score: float = 0.5,
        det_limit_side_len: int = 960,
        intra_op_num_threads: int = 0,
    ) -> None:
        self._lang = lang or "ch"
        self._ocr_version = ocr_version
        self._model_type = model_type
        self._text_score = text_score
        # 检测输入最长边上限。区域检测需 960（缩放帧上找居中段对分辨率敏感，过小会误并卡片标题进字幕带）；
        # 提取阶段 ROI 已贴字幕、字号大，用 768 更快且质量不降。
        self._det_limit_side_len = det_limit_side_len
        # 0 表示不指定（RapidOCR 默认 -1 = 自动用全部核）；>0 时限制线程数。
        self._threads = intra_op_num_threads
        self._engine = None  # 懒加载

    @property
    def name(self) -> str:
        return f"RapidOCR/{self._ocr_version}/{self._model_type}/{self._lang}"

    def _ensure(self) -> None:
        if self._engine is not None:
            return
        try:
            from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR
        except Exception as exc:  # noqa: BLE001 — 依赖缺失对用户是「功能未就绪」，统一成 OcrError
            raise OcrError(
                "未安装 OCR 引擎依赖（rapidocr / onnxruntime）。硬字幕提取需要它，"
                "请先安装或在诊断页下载。"
            ) from exc
        # RapidOCR 的 params 值必须是其枚举类型，不能是字符串。
        rec_lang = getattr(LangRec, self._lang.upper(), LangRec.CH)
        det_lang = getattr(LangDet, _DET_LANG.get(self._lang, "multi").upper(), LangDet.MULTI)
        version = OCRVersion.PPOCRV5 if "v5" in self._ocr_version.lower() else OCRVersion.PPOCRV4
        model = ModelType.SERVER if self._model_type == "server" else ModelType.MOBILE
        params: dict = {
            "Global.text_score": self._text_score,
            "Det.lang_type": det_lang,
            "Det.ocr_version": version,
            "Det.model_type": model,
            "Det.limit_side_len": self._det_limit_side_len,
            "Rec.lang_type": rec_lang,
            "Rec.ocr_version": version,
            "Rec.model_type": model,
        }
        if self._threads > 0:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = self._threads
        # RapidOCR 在构造里会把自己的 logger 设回 INFO，预先 setLevel 压不住——构造期间全局禁掉
        # INFO 及以下，构造后再把它的 logger 钉到 ERROR（管住后续每帧识别的噪音）。
        logging.disable(logging.INFO)
        try:
            self._engine = RapidOCR(params=params)
        except Exception as exc:  # noqa: BLE001 — 模型下载/初始化失败统一成 OcrError
            raise OcrError(f"OCR 引擎初始化失败（模型下载或加载出错）：{exc}") from exc
        finally:
            logging.disable(logging.NOTSET)
            _silence_rapidocr_logs()

    def warmup(self) -> None:
        self._ensure()

    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        self._ensure()
        assert self._engine is not None
        try:
            # 必须显式传全部 flag：RapidOCR 实例有状态，调过一次 use_rec=False（detect）后，
            # 不显式传就继承上次的 False，导致后续识别返回空。字幕不旋转，跳过 cls 提速。
            result = self._engine(image, use_det=True, use_cls=False, use_rec=True)
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"OCR 识别失败：{exc}") from exc
        lines: list[OcrLine] = []
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or txts is None:
            return lines
        if scores is None:
            scores = [1.0] * len(txts)
        for box, txt, score in zip(boxes, txts, scores):
            text = (txt or "").strip()
            if not text:
                continue
            lines.append(OcrLine(text=text, score=float(score), box=_to_poly(box)))
        return lines

    def detect(self, image: np.ndarray) -> list[BBox]:
        self._ensure()
        assert self._engine is not None
        try:
            result = self._engine(image, use_det=True, use_cls=False, use_rec=False)
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"OCR 文本检测失败：{exc}") from exc
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        return [bbox_of(_to_poly(box)) for box in boxes]


def _to_poly(box) -> tuple[tuple[float, float], ...]:
    """RapidOCR 的 box（np.ndarray (4,2) 或四点列表）→ 纯 Python 四点元组。"""
    pts: list[tuple[float, float]] = []
    for point in box:
        pts.append((float(point[0]), float(point[1])))
    return tuple(pts)


def create_rapidocr(
    lang: str = "ch",
    ocr_version: str = "PP-OCRv4",
    model_type: str = "mobile",
    threads: int = 0,
    det_limit_side_len: int = 960,
) -> RapidOcrEngine:
    """构造 RapidOCR 引擎。``det_limit_side_len``：检测输入最长边上限，区域检测用 960、提取用 768。"""
    return RapidOcrEngine(
        lang=lang, ocr_version=ocr_version, model_type=model_type,
        intra_op_num_threads=threads, det_limit_side_len=det_limit_side_len,
    )


def ocr_dependency_ready() -> Optional[str]:
    """OCR 依赖是否就绪。就绪返回 None"""
    import importlib.util

    missing = [m for m in ("onnxruntime", "rapidocr") if importlib.util.find_spec(m) is None]
    if missing:
        return f"缺少 OCR 引擎依赖：{', '.join(missing)}"
    return None
