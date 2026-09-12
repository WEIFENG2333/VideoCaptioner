"""软件自动更新：调后端检查 → 后台下载（校验）→ 退出后替换重启。无 PyQt 依赖。"""

from videocaptioner.core.update.client import (
    Announcement,
    CheckResult,
    UpdateInfo,
    app_channel,
    check_update,
)
from videocaptioner.core.update.installer import (
    apply_update,
    can_self_update,
    download_update,
    install_root,
    is_frozen,
)

__all__ = [
    "UpdateInfo",
    "Announcement",
    "CheckResult",
    "check_update",
    "app_channel",
    "download_update",
    "apply_update",
    "install_root",
    "can_self_update",
    "is_frozen",
]
