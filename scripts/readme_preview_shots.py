#!/usr/bin/env python3
"""生成 README 的界面预览图（docs/images/preview-*.png）。

每张图都驱动到「真实任务处理中」的有内容状态，而不是空态：

- preview-home.png          首页（任务创建 tab，链接解析后正在下载 36%）
- preview-transcription.png 语音转录（转录完成：字幕表 + 视频封面 + 结果面板）
- preview-subtitle.png      字幕优化与翻译（翻译进行中 46%，第 57/124 条）
- preview-batch.png         批量处理（队列处理中，首个任务 48%）
- preview-dubbing.png       配音（音色库 + 试听文案）

用法：
    .venv/bin/python scripts/readme_preview_shots.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "images"
ASSETS = Path(tempfile.mkdtemp(prefix="vc-readme-shots-"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", str(ASSETS / "config.toml"))

SIZE = (1322, 804)

SEGMENTS = [
    (1120, 3400, "大家好，欢迎来到这一节课。"),
    (3520, 6200, "我们今天讲矩阵和向量空间。"),
    (6360, 8900, "先从最基本的概念开始。"),
    (9100, 12000, "后面会用几个例子来说明。"),
    (12240, 15640, "我们先看一下矩阵的形式。"),
    (15900, 18200, "它由若干行和若干列组成。"),
]

ROWS = [
    (1120, 3400, "大家好，欢迎来到这一节课。", "Hello, welcome to this lesson."),
    (3520, 6200, "我们今天讲矩阵和向量空间。", "Today we will talk about matrices and vector spaces."),
    (6360, 8900, "先从最基本的概念开始。", "Let's start with the most basic concepts."),
    (9100, 12000, "后面会用几个例子来说明。", "We will explain it with examples later."),
    (12240, 15640, "我们先看一下矩阵的形式。", "Let's look at the form of a matrix."),
    (15900, 18200, "它由若干行和若干列组成。", ""),
]

BATCH_FILES = [
    ("Courses/linear-algebra", "线性代数基础 p01.mp4"),
    ("Courses/linear-algebra", "线性代数基础 p02.mp4"),
    ("Courses/audio", "linear-algebra-review.m4a"),
    ("Courses/matrix", "矩阵专题讲义.mp4"),
    ("Courses/vector-space", "向量空间例题 p03.mp4"),
    ("Courses/audio", "basis-and-rank.m4a"),
    ("Courses/eigen", "特征值专题 p01.mp4"),
    ("Courses/qa", "课程答疑合集.mov"),
]


def make_cover(path: Path) -> None:
    """画一张讲义风格的视频封面（渐变底 + 标题），供缩略图展示。"""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 640, 360
    image = Image.new("RGB", (width, height))
    top, bottom = (16, 42, 34), (4, 12, 10)
    for y in range(height):
        t = y / height
        image.paste(
            tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)),
            (0, y, width, y + 1),
        )
    draw = ImageDraw.Draw(image)
    accent = (62, 230, 145)
    draw.rounded_rectangle((40, 96, 96, 104), 4, fill=accent)
    font_path = ROOT / "resource" / "fonts" / "LXGWWenKai-Regular.ttf"
    title_font = ImageFont.truetype(str(font_path), 44)
    sub_font = ImageFont.truetype(str(font_path), 22)
    draw.text((40, 128), "线性代数基础", font=title_font, fill=(238, 244, 240))
    draw.text((40, 188), "第 1 讲 · 矩阵与向量空间", font=sub_font, fill=(150, 168, 158))
    draw.text((40, 296), "p01 · 10:24", font=sub_font, fill=accent)
    image.save(path)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme, setThemeColor

    from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
    from videocaptioner.core.entities import (
        AudioStreamInfo,
        TranscribeModelEnum,
        VideoInfo,
    )
    from videocaptioner.ui.common.config import DEFAULT_THEME_COLOR, ThemeMode, cfg

    cfg.set(cfg.themeMode, ThemeMode.DARK, save=False)
    setTheme(Theme.DARK)
    setThemeColor(DEFAULT_THEME_COLOR)

    def settle(widget, n: int = 12):
        for _ in range(n):
            app.processEvents()

    def grab(widget, name: str):
        settle(widget)
        widget.grab().save(str(OUT_DIR / name))
        print(f"shot={OUT_DIR / name}")

    cover = ASSETS / "cover.png"
    make_cover(cover)

    # ---------------------------------------------------------- 首页（下载中）
    from videocaptioner.ui.view.home_interface import HomeInterface
    from videocaptioner.ui.view.task_creation_interface import PageState as TaskState

    home = HomeInterface()
    home.resize(*SIZE)
    home.show()
    settle(home)
    task = home.task_creation_interface
    task.inputField.edit.setText("https://www.bilibili.com/video/BV1Et421E7jk")
    task.state = TaskState.DOWNLOADING
    task._refresh()
    task.downloadPanel.setMedia(
        {
            "title": "线性代数基础与解法全集｜长期更新｜从零开始",
            "uploader": "数学老师",
            "duration": "10:24",
            "site": "BiliBili",
        }
    )
    task._on_download_progress(36, "正在下载媒体")
    task.downloadPanel.setStats("4.6 MB/s", "剩余 01:18")
    grab(home, "preview-home.png")
    home.close()

    # ----------------------------------------------- 语音转录（完成 + 字幕表）
    from videocaptioner.ui.view.transcription_interface import (
        PageState as TransState,
    )
    from videocaptioner.ui.view.transcription_interface import (
        TranscriptionInterface,
    )

    cfg.set(cfg.transcribe_model, TranscribeModelEnum.BIJIAN, save=False)
    video_path = ASSETS / "线性代数基础与解法全集 p01.mp4"
    video_path.write_bytes(b"\0" * 1024)
    trans = TranscriptionInterface()
    trans.resize(*SIZE)
    trans.show()
    settle(trans)
    trans._media_path = str(video_path)
    trans.media_info = VideoInfo(
        file_name="线性代数基础与解法全集 p01.mp4",
        file_path=str(video_path),
        width=1920,
        height=1080,
        fps=30.0,
        duration_seconds=624,
        bitrate_kbps=4000,
        video_codec="h264",
        audio_codec="aac",
        audio_sampling_rate=44100,
        thumbnail_path=str(cover),
        audio_streams=[AudioStreamInfo(index=0, codec="aac", language="zh")],
    )
    segments = (SEGMENTS * 37)[:220]
    trans.subtitlePreview.setSegments(segments)
    trans.subtitlePreview.setActiveRow(1)
    trans.resultPanel.thumb.setMedia(str(cover), False)
    trans.resultPanel.setResult(
        title="线性代数基础与解法全集 p01",
        chips=["B 接口", "10:24", "SRT"],
        file_name="【原始字幕】线性代数基础-B接口.srt",
    )
    trans._apply_state(TransState.DONE)
    grab(trans, "preview-transcription.png")
    trans.close()

    # ------------------------------------------- 字幕优化与翻译（翻译中 46%）
    from videocaptioner.ui.view.subtitle_interface import PageState as SubState
    from videocaptioner.ui.view.subtitle_interface import SubtitleInterface

    cfg.set(cfg.need_optimize, True, save=False)
    cfg.set(cfg.need_translate, True, save=False)
    srt_path = ASSETS / "线性代数基础 p01.srt"
    srt_segments = []
    for index in range(124):
        start, end, text, _ = ROWS[index % len(ROWS)]
        offset = (index // len(ROWS)) * 20000
        srt_segments.append(ASRDataSeg(text, start + offset, end + offset))
    ASRData(srt_segments).to_srt(save_path=str(srt_path))

    subtitle = SubtitleInterface()
    subtitle.resize(*SIZE)
    subtitle.show()
    settle(subtitle)
    subtitle.load_subtitle_file(str(srt_path))
    keys = list(subtitle.model.raw().keys())
    translations = {
        keys[index]: ROWS[index % len(ROWS)][3]
        for index in range(5)
        if ROWS[index % len(ROWS)][3]
    }
    translations[keys[5]] = "正在翻译..."
    subtitle.model.merge_translations(translations)
    subtitle._apply_state(SubState.RUNNING)
    subtitle._translated_count = 57
    subtitle.model.set_dim_from(6)
    subtitle.tablePanel.bottomBar.showRunning("字幕翻译", 46, 57, 124)
    subtitle.tablePanel.table.selectRow(2)
    grab(subtitle, "preview-subtitle.png")
    subtitle.close()

    # ------------------------------------------------- 批量处理（处理中 48%）
    from videocaptioner.ui.view.batch_process_interface import (
        BatchProcessInterface,
        JobStatus,
    )

    cfg.set(cfg.batch_mode, "full", save=False)
    cfg.set(cfg.dubbing_enabled, True, save=False)
    # 批量行会展示文件所在目录，用干净的演示路径（而不是 /var/folders 临时目录）
    batch_root = Path("/tmp/课程素材")
    paths = []
    for folder, name in BATCH_FILES:
        target = batch_root / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\0" * 1024)
        paths.append(str(target))
    batch = BatchProcessInterface()
    batch.resize(*SIZE)
    batch.show()
    settle(batch)
    batch._switch_mode("full")
    batch.controller.add_paths(paths)
    jobs = batch.controller.jobs
    batch.controller._dispatch_enabled = True
    batch.controller._stages = ["transcribe", "subtitle", "dubbing", "synthesis"]
    jobs[0].status = JobStatus.RUNNING
    jobs[0].progress = 48
    jobs[0].note = "字幕处理 · 第 57 / 124 条"
    jobs[0].stage = "subtitle"
    jobs[1].note = "等待上一个任务完成"

    class _FakeRunner:
        pass

    batch.controller._runners = {_FakeRunner(): jobs[0]}
    for index in range(len(jobs)):
        batch.controller.jobChanged.emit(index)
    grab(batch, "preview-batch.png")
    batch.controller._runners = {}  # 假 runner 不参与关闭收尾
    batch.close()

    # ----------------------------------------------------------------- 配音
    from videocaptioner.ui.view.dubbing_interface import DubbingInterface

    dubbing = DubbingInterface()
    dubbing.resize(*SIZE)
    dubbing.show()
    grab(dubbing, "preview-dubbing.png")
    dubbing.close()

    print("readme-previews=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
