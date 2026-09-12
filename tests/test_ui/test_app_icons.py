"""应用图标规范测试。

主题上色管线（app_icons.render_svg_pixmap）靠把 SVG 里的 currentColor
占位符替换成主题色；硬编码颜色的图标会以原始颜色渲染、主题失效
（曾导致“等待字幕”按钮图标在深色主题下渲染成黑色）。
此测试强制 resource/assets/icons 下所有 SVG 遵守占位符约定。
"""

import re
from pathlib import Path

import pytest

ICON_DIR = Path(__file__).resolve().parents[2] / "resource" / "assets" / "icons"

# fill/stroke 只允许 currentColor 或 none
_HARDCODED_PAINT = re.compile(r'(?:fill|stroke)="(?!currentColor|none)[^"]+"')


def _icon_files() -> list[Path]:
    files = sorted(ICON_DIR.glob("*.svg"))
    assert files, f"icon directory missing or empty: {ICON_DIR}"
    return files


@pytest.mark.parametrize("svg_path", _icon_files(), ids=lambda p: p.name)
def test_icon_uses_current_color_placeholder(svg_path: Path):
    content = svg_path.read_text(encoding="utf-8")
    assert "currentColor" in content, (
        f"{svg_path.name} 缺少 currentColor 占位符，主题上色会失效"
    )
    hardcoded = _HARDCODED_PAINT.findall(content)
    assert not hardcoded, (
        f"{svg_path.name} 存在硬编码颜色 {hardcoded}，请改为 currentColor / none"
    )
