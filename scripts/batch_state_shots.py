#!/usr/bin/env python3
"""把批量处理页驱动到设计稿 A 的 4 个状态并逐一截图。

用法：
    .venv/bin/python scripts/batch_state_shots.py /tmp/vc-batch-shots \
        [--compare /tmp/vc-batch-design] [--theme light]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vc-batch-shots")
COMPARE_DIR = (
    Path(sys.argv[sys.argv.index("--compare") + 1]) if "--compare" in sys.argv else None
)
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "dark"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "VIDEOCAPTIONER_CONFIG_FILE", str(OUT_DIR / "state-shots-config.toml")
)

STATES = ["v1a", "v1b", "v1c", "v1d"]

# 设计稿状态 B/C/D 用到的演示文件清单
DEMO_FILES = [
    ("Courses/linear-algebra", "线性代数基础 p01.mp4"),
    ("Courses/linear-algebra", "线性代数基础 p02.mp4"),
    ("Courses/audio", "linear-algebra-review.m4a"),
    ("Courses/matrix", "矩阵专题讲义.mp4"),
    ("Courses/vector-space", "向量空间例题 p03.mp4"),
    ("Courses/audio", "basis-and-rank.m4a"),
    ("Courses/eigen", "特征值专题 p01.mp4"),
    ("Courses/qa", "课程答疑合集.mov"),
    ("Courses/audio", "矩阵分解复习.wav"),
    ("Courses/final-review", "期末串讲 p02.mp4"),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ["VIDEOCAPTIONER_CONFIG_FILE"])
    if config.exists():
        config.unlink()

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme

    from videocaptioner.ui.common.config import ThemeMode, cfg
    from videocaptioner.ui.view.batch_process_interface import (
        BatchProcessInterface,
        JobStatus,
    )

    cfg.set(
        cfg.themeMode,
        ThemeMode.LIGHT if THEME == "light" else ThemeMode.DARK,
        save=False,
    )
    setTheme(Theme.LIGHT if THEME == "light" else Theme.DARK)

    assets = OUT_DIR / "assets"
    paths = []
    for folder, name in DEMO_FILES:
        target = assets / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\0" * 1024)
        paths.append(str(target))

    page = BatchProcessInterface()
    page.resize(1322, 820)
    page.show()

    def settle():
        for _ in range(10):
            app.processEvents()

    def grab(name: str):
        settle()
        page.resize(1322, 820)
        settle()
        page.grab().save(str(OUT_DIR / f"{name}.png"))
        print(f"shot={OUT_DIR / f'{name}.png'}")

    # A 空队列（全流程模式）
    cfg.set(cfg.batch_mode, "full", save=False)
    cfg.set(cfg.dubbing_enabled, True, save=False)
    page._switch_mode("full")
    grab("v1a")

    # B 队列已就绪：10 个文件
    page.controller.add_paths(paths)
    grab("v1b")

    # C 处理中：首个任务字幕处理 48%，其余等待
    jobs = page.controller.jobs
    page._batch_ran = False
    page.controller._dispatch_enabled = True
    page.controller._stages = ["transcribe", "subtitle", "dubbing", "synthesis"]
    jobs[0].status = JobStatus.RUNNING
    jobs[0].progress = 48
    jobs[0].note = "字幕处理 · 第 57 / 124 条"
    jobs[0].stage = "subtitle"
    jobs[1].note = "等待上一个任务完成"

    class _FakeRunner:  # 只为 active_stages/is_active 查询提供 job 映射
        pass

    page.controller._runners = {_FakeRunner(): jobs[0]}
    for index in range(len(jobs)):
        page.controller.jobChanged.emit(index)
    grab("v1c")

    # D 完成与失败恢复：7 完成 1 失败（移除 2 个，剩 8 个任务）
    page.controller._runners = {}
    page.controller._dispatch_enabled = False
    for job in (jobs[8], jobs[9]):
        page.controller.jobs.remove(job)
    page.controller.queueChanged.emit()
    jobs = page.controller.jobs
    for index, job in enumerate(jobs):
        job.stage = ""
        if job.name == "矩阵专题讲义.mp4":
            job.status = JobStatus.FAILED
            job.progress = 18
            job.note = "LLM API Key 缺失"
            job.error = "字幕处理：LLM API Key 缺失"
        else:
            job.status = JobStatus.COMPLETED
            job.progress = 100
            suffix = Path(job.name).suffix
            job.note = (
                "已输出原始字幕"
                if suffix in (".m4a", ".wav")
                else f"已输出 【卡卡】{Path(job.name).stem}.mp4"
            )
        page.controller.jobChanged.emit(index)
    page._batch_ran = True
    page._refresh()
    grab("v1d")

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
