"""extract-hardsub command — OCR 提取视频里的硬字幕（烧录字幕）为可编辑字幕。

抽帧 → 字幕区变化检测 → 变化点 OCR → 去重合并 → 导出 SRT/ASS。区域可手动框选（--roi）或
自动检测（默认）。识别引擎 RapidOCR（纯 CPU，中英文质量好）。
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Optional

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.validators import validate_video_input


def _parse_roi(text: str) -> Optional[tuple[int, int, int, int]]:
    """解析 "x,y,w,h" 为整数元组；非法返回 None。"""
    try:
        parts = [int(v.strip()) for v in text.split(",")]
    except ValueError:
        return None
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def run(args: Namespace, config: dict) -> int:
    from videocaptioner.core.hardsub.config import HardsubConfig, RecognizeMode
    from videocaptioner.core.hardsub.pipeline import extract_hardsub
    from videocaptioner.core.ocr.rapid import create_rapidocr, ocr_dependency_ready

    video_path = Path(args.video)
    if not video_path.exists():
        output.error(f"Video file not found: {video_path}")
        return EXIT.FILE_NOT_FOUND
    err = validate_video_input(video_path)
    if err is not None:
        return err

    missing = ocr_dependency_ready()
    if missing is not None:
        output.error(missing)
        output.hint("安装 OCR 依赖： uv pip install rapidocr onnxruntime")
        return EXIT.DEPENDENCY_MISSING

    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)
    lang = getattr(args, "lang", None) or "ch"
    mode = RecognizeMode(getattr(args, "mode", None) or "standard")

    # ROI：显式 --roi 优先；否则自动检测；都没有则 pipeline 回退底部默认带。
    roi = None
    roi_arg = getattr(args, "roi", None)
    if roi_arg:
        roi = _parse_roi(roi_arg)
        if roi is None:
            output.error("--roi 格式应为 x,y,w,h（像素，原始分辨率），例如 96,612,1728,120")
            return EXIT.USAGE_ERROR

    # --roi 显式指定 = 手动区域：提取所见即所得，不套字号/居中过滤。
    cfg = HardsubConfig.from_mode(
        str(video_path), mode=mode, lang=lang, roi=roi, roi_is_manual=bool(roi)
    )
    engine = create_rapidocr(
        lang=cfg.lang, ocr_version=cfg.ocr_version, model_type=cfg.model_type
    )

    if roi is None and not getattr(args, "no_auto_region", False):
        probe = None if quiet else output.ProgressLine("检测字幕区域").start()
        try:
            from videocaptioner.core.hardsub.region import detect_subtitle_region
            detected = detect_subtitle_region(str(video_path), engine, cfg.region_sample_count)
        except Exception as exc:  # noqa: BLE001
            detected = None
            if verbose:
                output.warn(f"自动检测字幕区域失败：{exc}")
        if probe:
            probe.finish(f"字幕区域 {detected.roi}" if detected else "未自动识别，用底部默认带")
        if detected is not None:
            cfg.roi = detected.roi
            cfg.font_height = detected.font_height  # 复用区域检测学到的字号，免再学一遍

    if verbose:
        output.info(f"语言: {lang}   模式: {mode.value}   引擎: {engine.name}")
        output.info(f"字幕区域 ROI: {cfg.roi or '底部默认带'}")

    progress = None if quiet else output.ProgressLine("识别硬字幕").start()

    def on_progress(p) -> None:
        if progress:
            progress.update(p.percent, f"识别中 {p.cue_count} 条")

    # 提取用 768 引擎（比区域检测的 960 快、质量不降）。
    from videocaptioner.core.hardsub.pipeline import EXTRACT_DET_LIMIT
    extract_engine = create_rapidocr(
        lang=cfg.lang, ocr_version=cfg.ocr_version, model_type=cfg.model_type,
        det_limit_side_len=EXTRACT_DET_LIMIT,
    )
    try:
        data = extract_hardsub(cfg, extract_engine, on_progress=on_progress)
    except Exception as exc:  # noqa: BLE001
        msg = output.clean_error(str(exc))
        if progress:
            progress.fail(msg)
        else:
            output.error(msg)
        if verbose:
            import traceback
            traceback.print_exc()
        return EXIT.RUNTIME_ERROR

    if not data.has_data():
        if progress:
            progress.fail("未识别到字幕")
        output.hint("可能字幕区域不对，用 --roi x,y,w,h 手动指定，或换 --mode accurate")
        return EXIT.RUNTIME_ERROR

    # 输出：默认源文件旁 {stem}.hardsub.srt
    if getattr(args, "output", None):
        out_path = Path(args.output)
    else:
        from videocaptioner.core.application import output_paths
        out_path = output_paths.product_path(video_path, output_paths.TAG_HARDSUB, ext=".srt")
    data.save(str(out_path))

    if progress:
        progress.finish(f"完成 -> {out_path}（{len(data)} 条）")
    if quiet:
        print(out_path)
    return EXIT.SUCCESS
