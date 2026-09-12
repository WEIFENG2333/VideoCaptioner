#!/usr/bin/env python3
"""把字幕视频合成页驱动到设计稿 A 的 7 个状态并逐一截图。

用法：
    .venv/bin/python scripts/synthesis_state_shots.py /tmp/vc-syn-shots \
        [--compare /tmp/vc-syn-design] [--theme light]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vc-syn-shots")
COMPARE_DIR = (
    Path(sys.argv[sys.argv.index("--compare") + 1]) if "--compare" in sys.argv else None
)
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "dark"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "VIDEOCAPTIONER_CONFIG_FILE", str(OUT_DIR / "state-shots-config.toml")
)

STATES = ["v1a", "v1b", "v1c", "v1d", "v1e", "v1f", "v1g"]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ["VIDEOCAPTIONER_CONFIG_FILE"])
    if config.exists():
        config.unlink()

    from PyQt5.QtWidgets import QApplication

    app = QApplication([])

    from qfluentwidgets import Theme, setTheme

    import videocaptioner.ui.view.video_synthesis_interface as synthesis_module
    from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
    from videocaptioner.ui.common.config import ThemeMode, cfg
    from videocaptioner.ui.view.video_synthesis_interface import VideoSynthesisInterface

    cfg.set(
        cfg.themeMode,
        ThemeMode.LIGHT if THEME == "light" else ThemeMode.DARK,
        save=False,
    )
    setTheme(Theme.LIGHT if THEME == "light" else Theme.DARK)
    # 截图时不真正打开访达
    synthesis_module.open_folder = lambda _path: None

    assets = OUT_DIR / "assets"
    assets.mkdir(exist_ok=True)
    srt_path = assets / "线性代数基础 p01-译文在上.srt"
    ASRData([ASRDataSeg("示例字幕", 0, 2000)]).to_srt(save_path=str(srt_path))
    video_path = assets / "linear-algebra-demo.mp4"
    video_path.write_bytes(b"\0" * 1024)

    page = VideoSynthesisInterface()
    page.layout().setContentsMargins(0, 24, 0, 0)
    page.resize(1278, 717)
    page.show()

    def settle():
        for _ in range(10):
            app.processEvents()

    def grab(name: str):
        settle()
        page.resize(1278, 717)
        settle()
        page.grab().save(str(OUT_DIR / f"{name}.png"))
        print(f"shot={OUT_DIR / f'{name}.png'}")

    # A 空态：默认字幕视频开
    cfg.set(cfg.need_video, True, save=False)
    cfg.set(cfg.dubbing_enabled, False, save=False)
    page._refresh()
    grab("v1a")

    # B 字幕视频缺视频
    page.set_subtitle_file(str(srt_path))
    grab("v1b")

    # C 只生成配音音频（Edge 免 Key）
    cfg.set(cfg.dubbing_provider, "edge", save=False)
    cfg.set(cfg.need_video, False, save=False)
    cfg.set(cfg.dubbing_enabled, True, save=False)
    grab("v1c")

    # D 全流程就绪
    cfg.set(cfg.need_video, True, save=False)
    page.set_video_file(str(video_path))
    grab("v1d")

    # E 运行中（配音 38%）
    page._enter_running()
    page._on_progress(38, "生成配音")
    grab("v1e")

    # F 完成
    wav_path = assets / "【配音音频】线性代数基础 p01-译文在上.wav"
    wav_path.write_bytes(b"\0" * 2048)
    page._on_completed([("字幕视频", str(video_path)), ("配音音频", str(wav_path))])
    grab("v1f")

    # G 配置缺失（SiliconFlow 无 Key）
    page.state = synthesis_module.PageState.IDLE
    cfg.set(cfg.dubbing_provider, "siliconflow", save=False)
    cfg.set(cfg.dubbing_api_key, "", save=False)
    page._refresh()
    grab("v1g")

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
