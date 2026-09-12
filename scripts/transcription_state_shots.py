#!/usr/bin/env python3
"""把语音转录页驱动到设计稿的 6 个状态并逐一截图。

数据与 docs/dev/design-transcription.html 设计稿保持一致（文件名、
进度 62%、失败文案、字幕条目等），截图尺寸 1268x702 与
scripts/design_reference_shots.py 产出的 *-split.png 完全对应，可直接对比。

用法：
    .venv/bin/python scripts/transcription_state_shots.py /tmp/vc-app-shots

可选 --compare /tmp/vc-design-shots：生成 design|app 并排对比图。
可选 --theme light：浅色主题（默认 dark）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vc-app-shots")
COMPARE_DIR = (
    Path(sys.argv[sys.argv.index("--compare") + 1])
    if "--compare" in sys.argv
    else None
)
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "dark"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "VIDEOCAPTIONER_CONFIG_FILE", str(OUT_DIR / "state-shots-config.toml")
)

# 设计稿状态 id -> 截图文件名
STATES = ["v1a", "v1b", "v1c", "v1d", "v1e", "v1f"]

DESIGN_SEGMENTS = [
    (1120, 3400, "大家好，欢迎来到这一节课。"),
    (3520, 6200, "我们今天讲矩阵和向量空间。"),
    (6360, 8900, "先从最基本的概念开始。"),
    (9100, 12000, "后面会用几个例子来说明。"),
    (12240, 15640, "我们先看一下这个矩阵的形式。"),
    (15900, 18200, "它由若干行和若干列组成。"),
]

DESIGN_TEXT = "\n".join(
    ["大家好，欢迎来到这一节课。", "我们今天讲矩阵和向量空间。", "先从最基本的概念开始。", "后面会用几个例子来说明。"]
)


def make_sparse_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.seek(size - 1)
        handle.write(b"\0")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ["VIDEOCAPTIONER_CONFIG_FILE"])
    if config.exists():
        config.unlink()

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme

    from videocaptioner.core.entities import (
        AudioStreamInfo,
        TranscribeModelEnum,
        VideoInfo,
    )
    from videocaptioner.ui.common.config import ThemeMode, cfg
    from videocaptioner.ui.view.transcription_interface import (
        PageState,
        TranscriptionInterface,
    )

    cfg.set(
        cfg.themeMode,
        ThemeMode.LIGHT if THEME == "light" else ThemeMode.DARK,
        save=False,
    )
    setTheme(Theme.LIGHT if THEME == "light" else Theme.DARK)

    # 与设计稿一致的参数：Fun-ASR / paraformer-v2 / 自动检测 / SRT / 词时间戳开。
    cfg.set(cfg.transcribe_model, TranscribeModelEnum.BAILIAN_FUN_ASR, save=False)
    cfg.set(cfg.fun_asr_model, "paraformer-v2", save=False)
    cfg.set(cfg.transcribe_word_timestamp, True, save=False)  # 设计稿开关为开

    video_path = OUT_DIR / "assets" / "线性代数基础与解法全集｜从零开始 p01.mp4"
    audio_path = OUT_DIR / "assets" / "lecture-audio.wav"
    make_sparse_file(video_path, 1024)
    make_sparse_file(audio_path, 48 * 1024 * 1024)

    video_info = VideoInfo(
        file_name="线性代数基础与解法全集｜从零开始 p01.mp4",
        file_path=str(video_path),
        width=1920,
        height=1080,
        fps=30.0,
        duration_seconds=624,
        bitrate_kbps=4000,
        video_codec="h264",
        audio_codec="aac",
        audio_sampling_rate=44100,
        thumbnail_path="",
        audio_streams=[AudioStreamInfo(index=0, codec="aac", language="zh")],
    )
    audio_info = VideoInfo(
        file_name="lecture-audio.wav",
        file_path=str(audio_path),
        width=0,
        height=0,
        fps=0.0,
        duration_seconds=372,
        bitrate_kbps=0,
        video_codec="",
        audio_codec="pcm_s16le",
        audio_sampling_rate=16000,
        thumbnail_path="",
        audio_streams=[AudioStreamInfo(index=0, codec="pcm_s16le")],
    )

    page = TranscriptionInterface()
    page.layout().setContentsMargins(0, 0, 0, 0)
    page.resize(1268, 702)
    page.show()

    def settle():
        for _ in range(10):
            app.processEvents()

    def grab(name: str):
        settle()
        pixmap = page.grab()
        path = OUT_DIR / f"{name}.png"
        pixmap.save(str(path))
        print(f"shot={path}")

    # A 未选择文件
    grab("v1a")

    # B 文件就绪（视频）
    page._media_path = str(video_path)
    page._apply_state(PageState.READY)
    page._on_media_loaded(video_info)
    grab("v1b")

    # C 转录中（音频，62%）
    page._media_path = str(audio_path)
    page.media_info = audio_info
    page.mediaCard.setTitle(audio_info.file_name)
    page.mediaCard.thumb.setMedia(None, True)
    page._apply_state(PageState.RUNNING)
    page.progressCard.setProgress(62)
    grab("v1c")

    # D 失败恢复（视频 + Whisper API，模型未配置时显示服务名，与设计稿一致）
    cfg.set(cfg.transcribe_model, TranscribeModelEnum.WHISPER_API, save=False)
    cfg.set(cfg.whisper_api_model, "", save=False)
    page._media_path = str(video_path)
    page.media_info = video_info
    page.mediaCard.setTitle("线性代数基础 p01.mp4")
    page.mediaCard.thumb.setMedia(None, False)
    page.errorBanner.setMessage("Whisper API Key 不可用，或网络连接失败。")
    page._apply_state(PageState.FAILED)
    grab("v1d")

    # E SRT 结果
    cfg.set(cfg.transcribe_model, TranscribeModelEnum.BIJIAN, save=False)
    segments = (DESIGN_SEGMENTS * 37)[:220]
    page.subtitlePreview.setSegments(segments)
    page.subtitlePreview.setActiveRow(1)
    page.resultPanel.thumb.setMedia(None, False)
    page.resultPanel.setResult(
        title="线性代数基础 p01",
        chips=["B 接口", "10:24", "SRT"],
        file_name="【原始字幕】线性代数基础-B接口.srt",
    )
    page._apply_state(PageState.DONE)
    grab("v1e")

    # F 纯文本结果
    page.textPreview.setContent(DESIGN_TEXT)
    page.resultPanel.setResult(
        title="线性代数基础 p01",
        chips=["B 接口", "10:24", "TXT"],
        file_name="linear-algebra-demo.txt",
    )
    page._apply_state(PageState.DONE, preview_text=True)
    grab("v1f")

    page.close()

    if COMPARE_DIR is not None:
        _build_comparison(COMPARE_DIR)
    print("state-shots=ok")
    return 0


def _build_comparison(design_dir: Path) -> None:
    """每个状态输出 design(上) / app(下) 的对比图。"""
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
