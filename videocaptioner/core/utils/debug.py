from __future__ import annotations

import os
from typing import Optional

_ENV = "VC_DEBUG"
_OFF = {"", "0", "false", "no", "off"}
_ALL = {"1", "true", "yes", "on", "all"}


def debug_enabled(subsystem: Optional[str] = None) -> bool:
    """VC_DEBUG 是否为 ``subsystem`` 开启调试；不传则只看总开关。"""
    val = os.environ.get(_ENV, "").strip().lower()
    if val in _OFF:
        return False
    if val in _ALL or subsystem is None:
        return True
    selected = {s.strip() for s in val.split(",") if s.strip()}
    return subsystem.strip().lower() in selected
