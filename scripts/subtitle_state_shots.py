#!/usr/bin/env python3
"""把字幕优化页驱动到设计稿 B 的 5 个状态并逐一截图。

数据与 docs/dev/design-subtitle.html 一致（124 条、46%、
第 57 / 124 条、失败文案等），截图尺寸与 design_reference_shots.py 产出的
*-split.png 对应（.work 元素 1278x717，含 24px 顶部留白）。

用法：
    .venv/bin/python scripts/subtitle_state_shots.py /tmp/vc-sub-shots \
        [--compare /tmp/vc-sub-design] [--theme light]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vc-sub-shots")
COMPARE_DIR = (
    Path(sys.argv[sys.argv.index("--compare") + 1]) if "--compare" in sys.argv else None
)
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "dark"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "VIDEOCAPTIONER_CONFIG_FILE", str(OUT_DIR / "state-shots-config.toml")
)

STATES = ["v1a", "v1b", "v1c", "v1d", "v1e"]

DESIGN_ROWS = [
    (1120, 3400, "大家好，欢迎来到这一节课。", "Hello, welcome to this lesson."),
    (3520, 6200, "我们今天讲矩阵和向量空间。", "Today we will talk about matrices and vector spaces."),
    (6360, 8900, "先从最基本的概念开始。", "Let's start with the most basic concepts."),
    (9100, 12000, "后面会用几个例子来说明。", "We will explain it with examples later."),
    (12240, 15640, "我们先看一下矩阵的形式。", ""),
    (15900, 18200, "它由若干行和若干列组成。", ""),
]


def write_design_srt(path: Path, count: int = 124) -> None:
    """按设计稿内容生成 count 条的 SRT 文件。"""
    from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg

    segments = []
    for index in range(count):
        start, end, text, _ = DESIGN_ROWS[index % len(DESIGN_ROWS)]
        offset = (index // len(DESIGN_ROWS)) * 20000
        segments.append(ASRDataSeg(text, start + offset, end + offset))
    path.parent.mkdir(parents=True, exist_ok=True)
    ASRData(segments).to_srt(save_path=str(path))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ["VIDEOCAPTIONER_CONFIG_FILE"])
    if config.exists():
        config.unlink()

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme

    from videocaptioner.ui.common.config import ThemeMode, cfg
    from videocaptioner.ui.view.subtitle_interface import PageState, SubtitleInterface

    cfg.set(
        cfg.themeMode,
        ThemeMode.LIGHT if THEME == "light" else ThemeMode.DARK,
        save=False,
    )
    setTheme(Theme.LIGHT if THEME == "light" else Theme.DARK)
    cfg.set(cfg.need_optimize, True, save=False)
    cfg.set(cfg.need_translate, True, save=False)
    cfg.set(cfg.need_split, False, save=False)

    srt_path = OUT_DIR / "assets" / "线性代数基础 p01.srt"
    write_design_srt(srt_path)

    page = SubtitleInterface()
    # 设计稿 .work 元素含 24px 顶部留白，对齐到相同的截图区域。
    page.layout().setContentsMargins(0, 24, 0, 0)
    page.resize(1278, 717)
    page.show()

    def settle():
        for _ in range(10):
            app.processEvents()

    def grab(name: str):
        settle()
        page.grab().save(str(OUT_DIR / f"{name}.png"))
        print(f"shot={OUT_DIR / f'{name}.png'}")

    # A 未加载字幕
    grab("v1a")

    # B 准备处理（124 条，选中第 2 行）
    page.load_subtitle_file(str(srt_path))
    page.tablePanel.table.selectRow(1)
    grab("v1b")

    # C 处理中（字幕翻译 46%，第 57 / 124 条）
    keys = list(page.model.raw().keys())
    page.model.merge_translations({keys[0]: DESIGN_ROWS[0][3], keys[1]: "正在翻译..."})
    page._apply_state(PageState.RUNNING)
    page._translated_count = 57
    page.model.set_dim_from(2)
    page.tablePanel.bottomBar.showRunning("字幕翻译", 46, 57, 124)
    page.tablePanel.table.selectRow(1)
    grab("v1c")

    # D 完成检查（译文填充，输出文件名带排布后缀）
    translations = {
        keys[index]: DESIGN_ROWS[index % len(DESIGN_ROWS)][3]
        for index in range(4)
        if DESIGN_ROWS[index % len(DESIGN_ROWS)][3]
    }
    page.model.merge_translations(translations)
    page._output_path = str(OUT_DIR / "assets" / "线性代数基础 p01-译文在上.srt")
    page.tablePanel.setFile("线性代数基础 p01-译文在上.srt", loaded=True)
    page._apply_state(PageState.DONE)
    page.tablePanel.table.selectRow(1)
    grab("v1d")

    # E 配置未就绪
    page.tablePanel.setFile("线性代数基础 p01.srt", loaded=True)
    page._output_path = None
    page._apply_state(
        PageState.FAILED, error="需要先配置可用的大模型 API Key、接口地址和模型。"
    )
    grab("v1e")

    page.close()
    if COMPARE_DIR is not None:
        _build_comparison(COMPARE_DIR)
    print("state-shots=ok")
    return 0


def _build_comparison(design_dir: Path) -> None:
    from PIL import Image, ImageDraw

    for state in STATES:
        design = design_dir / f"{state}-split.png"
        ours = OUT_DIR / f"{state}.png"
        if not design.exists() or not ours.exists():
            continue
        top = Image.open(design).convert("RGB")
        bottom = Image.open(ours).convert("RGB")
        width = max(top.width, bottom.width)
        sheet = Image.new("RGB", (width, top.height + bottom.height + 56), (10, 12, 11))
        draw = ImageDraw.Draw(sheet)
        draw.text((12, 6), f"{state}  design (top) vs app (bottom)", fill=(240, 245, 242))
        sheet.paste(top, (0, 28))
        sheet.paste(bottom, (0, top.height + 56))
        path = OUT_DIR / f"compare-{state}.png"
        sheet.save(path)
        print(f"compare={path}")


if __name__ == "__main__":
    raise SystemExit(main())
