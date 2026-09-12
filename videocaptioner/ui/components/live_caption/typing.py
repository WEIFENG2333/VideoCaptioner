# -*- coding: utf-8 -*-
"""实时字幕「打字机」逐字步进的共享逻辑（页内转录条 + 浮窗共用，避免两处漂移）。

译文每次重译多为前缀相同、后缀改写。关键契约：可见字数只增不减——尾字在原位被新值覆盖而非先删
再打，避免行数先塌再涨的抖动；只有整句重译变短（少见）才对齐到更短目标。
"""

from __future__ import annotations

# 打字/删除节奏：~25 字/秒，逐字流畅但不过快。
TYPE_INTERVAL_MS = 40


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def next_visible(visible: str, full: str) -> str:
    """
    把 ``visible`` 朝 ``full`` 推进一步并返回新的可见串。

    可见长度单调不减：取 ``full`` 的「当前长度 + 一步」前缀，尾字原位覆盖而非先删再打（防抖），
    大段改写按比例加速补。目标比当前可见还短时（少见）直接对齐到更短目标。
    """
    if visible == full:
        return full
    n = len(visible)
    if n >= len(full):
        return full  # 目标不长于当前可见：直接对齐（同长=原位改写，更短=截断）
    rem = len(full) - n
    add = max(1, rem // 5) if rem > 24 else 1
    return full[: n + add]
