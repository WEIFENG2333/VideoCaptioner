"""字幕样式预览图的内容寻址缓存。

预览渲染是输入的纯函数（样式 + 文字 + 背景 → 一张图）。ASS 走 ffmpeg/libass
（约 250ms），圆角走 PIL（约 70ms）。来回切换 ASS / 圆角、或反复微调后又调回原值时，
同一组输入会被重复渲染。这里按输入内容做哈希缓存：命中即直接返回已渲染的图（约 1ms），
不再启动 ffmpeg / 重绘。缓存目录按数量上限滚动清理，不会无限增长。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from videocaptioner.config import CACHE_PATH

_PREVIEW_DIR = Path(CACHE_PATH) / "subtitle_preview"
_MAX_FILES = 24  # 够覆盖 ASS/圆角来回切换 + 最近若干次编辑


def preview_path(signature: str) -> Path:
    """内容签名 -> 缓存图路径（不保证文件已存在）。"""
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    return _PREVIEW_DIR / f"{digest}.png"


def prune(keep: int = _MAX_FILES) -> None:
    """按修改时间保留最近 keep 个预览图，清掉更早的。"""
    if not _PREVIEW_DIR.exists():
        return
    files = sorted(
        _PREVIEW_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)
