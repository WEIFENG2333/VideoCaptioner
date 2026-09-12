#!/usr/bin/env python3
"""把任务创建页驱动到设计稿 A 的 4 个状态并逐一截图。

用法：
    .venv/bin/python scripts/task_state_shots.py /tmp/vc-task-shots \
        [--compare /tmp/vc-task-design] [--theme light]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vc-task-shots")
COMPARE_DIR = (
    Path(sys.argv[sys.argv.index("--compare") + 1]) if "--compare" in sys.argv else None
)
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "dark"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "VIDEOCAPTIONER_CONFIG_FILE", str(OUT_DIR / "state-shots-config.toml")
)

STATES = ["v1a", "v1b", "v1c", "v1d"]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ["VIDEOCAPTIONER_CONFIG_FILE"])
    if config.exists():
        config.unlink()

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme

    from videocaptioner.ui.common.config import ThemeMode, cfg
    from videocaptioner.ui.view.task_creation_interface import (
        PageState,
        TaskCreationInterface,
    )

    cfg.set(
        cfg.themeMode,
        ThemeMode.LIGHT if THEME == "light" else ThemeMode.DARK,
        save=False,
    )
    setTheme(Theme.LIGHT if THEME == "light" else Theme.DARK)

    assets = OUT_DIR / "assets" / "课程素材"
    assets.mkdir(parents=True, exist_ok=True)
    video = assets / "线性代数基础与解法全集 p01.mp4"
    video.write_bytes(b"\0" * (128 * 1024))

    page = TaskCreationInterface()
    page.resize(1322, 804)
    page.show()

    def settle():
        for _ in range(10):
            app.processEvents()

    def grab(name: str):
        settle()
        page.grab().save(str(OUT_DIR / f"{name}.png"))
        print(f"shot={OUT_DIR / f'{name}.png'}")

    # A 空态
    grab("v1a")

    # B 本地文件已就绪
    page.inputField.edit.setText(str(video))
    grab("v1b")

    # C 链接下载中（36%）
    page.inputField.edit.setText("https://www.bilibili.com/video/BV1Et421E7jk")
    page.state = PageState.DOWNLOADING
    page._refresh()
    page.downloadPanel.setMedia(
        {
            "title": "线性代数基础与解法全集｜长期更新｜从零开始",
            "uploader": "数学老师",
            "duration": "10:24",
            "site": "BiliBili",
        }
    )
    page._on_download_progress(36, "正在下载媒体")
    page.downloadPanel.setStats("4.6 MB/s", "剩余 01:18")
    grab("v1c")

    # D 输入错误
    page.state = PageState.INPUT
    page.inputField.edit.setText("not-a-video")
    grab("v1d")

    # E 下载前确认（解析完成，选择清晰度）
    page.inputField.edit.setText("https://www.bilibili.com/video/BV1Et421E7jk")
    page.state = PageState.PROBING
    page._on_probed(
        {
            "title": "线性代数基础与解法全集｜长期更新｜从零开始",
            "site": "BiliBili",
            "uploader": "数学老师",
            "duration": "10:24",
            "qualities": [1080, 720, 480, 360],
            "has_subtitle": True,
        }
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
