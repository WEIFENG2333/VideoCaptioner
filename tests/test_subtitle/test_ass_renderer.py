"""Tests for ASS subtitle renderer."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from videocaptioner.core.subtitle import ass_renderer


@pytest.fixture(autouse=True)
def use_qapp():
    """Override the conftest.py fixture — these tests don't touch Qt."""
    yield


MINIMAL_ASS_STYLE = """[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,40,1
Style: Secondary,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,10,10,40,1
"""


def _make_bg(tmp_path: Path) -> Path:
    bg = tmp_path / "bg.png"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(bg)
    return bg


def test_render_ass_preview_quotes_ffmpeg_filter_paths(monkeypatch, tmp_path):
    """Regression for issue #1090: -vf ass=...:fontsdir=... must be single-quoted.

    Without quotes, FFmpeg parses the path's `/` as the start of a new filter
    option and aborts with `No option name near '/Python312/Lib/...'` for any
    install path containing `/`.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ass_renderer.subprocess, "run", fake_run)
    monkeypatch.setattr(ass_renderer, "auto_wrap_ass_file", lambda p, **kw: p)

    ass_renderer.render_ass_preview(
        style_str=MINIMAL_ASS_STYLE,
        preview_text=("hello", None),
        bg_image_path=str(_make_bg(tmp_path)),
    )

    cmd = captured["cmd"]
    vf_index = cmd.index("-vf")
    vf_value = cmd[vf_index + 1]

    assert vf_value.startswith("ass='"), f"ass path is not single-quoted: {vf_value}"
    assert "':fontsdir='" in vf_value, f"fontsdir is not single-quoted: {vf_value}"
    assert vf_value.endswith("'"), f"fontsdir path is not closed: {vf_value}"
