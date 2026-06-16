"""字幕预览内容寻址缓存：同输入只渲染一次，按数量上限滚动清理。

预览渲染是输入的纯函数；ASS 走 ffmpeg（~250ms）、圆角走 PIL（~70ms），来回切换
或重复编辑同一组样式时命中缓存（~1ms）。这里用圆角渲染器（不依赖 ffmpeg）验证缓存
命中不重渲染，并单测路径确定性与清理上限。
"""

import videocaptioner.core.subtitle.preview_cache as pc
from videocaptioner.core.subtitle import render_preview
from videocaptioner.core.subtitle.styles import RoundedBgStyle


def test_preview_path_is_deterministic_and_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_PREVIEW_DIR", tmp_path)
    assert pc.preview_path("abc") == pc.preview_path("abc")
    assert pc.preview_path("abc") != pc.preview_path("xyz")
    assert pc.preview_path("abc").parent == tmp_path


def test_prune_keeps_only_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_PREVIEW_DIR", tmp_path)
    for i in range(30):
        (tmp_path / f"{i:02d}.png").write_bytes(b"x")
    pc.prune(keep=24)
    assert len(list(tmp_path.glob("*.png"))) == 24


def test_render_preview_hits_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_PREVIEW_DIR", tmp_path)
    style = RoundedBgStyle(font_name="Noto Sans SC", font_size=52)
    kwargs = dict(primary_text="Hello", secondary_text="你好", style=style, bg_image_path=None)

    first = render_preview(**kwargs)
    assert "subtitle_preview" not in first  # 已被 monkeypatch 到 tmp_path
    assert first.endswith(".png")
    mtime = (tmp_path / first.split("/")[-1]).stat().st_mtime_ns

    # 同输入再渲染：返回同一路径，且文件未被重写（命中缓存，未重渲染）
    second = render_preview(**kwargs)
    assert second == first
    assert (tmp_path / second.split("/")[-1]).stat().st_mtime_ns == mtime

    # 改一个参数：另一个缓存文件
    third = render_preview(**{**kwargs, "primary_text": "World"})
    assert third != first
    assert len(list(tmp_path.glob("*.png"))) == 2
