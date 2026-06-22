"""软件自动更新：拉 manifest → 后台下载（校验）→ 退出后替换重启。无 PyQt 依赖。"""

from videocaptioner.core.update.installer import (
    apply_update,
    can_self_update,
    download_update,
    install_root,
    is_frozen,
)
from videocaptioner.core.update.manifest import (
    Announcement,
    RemoteManifest,
    UpdateAsset,
    UpdateInfo,
    fetch_manifest,
    fetch_update,
    is_newer,
    parse_version,
    select_announcement,
)

__all__ = [
    "UpdateInfo",
    "UpdateAsset",
    "Announcement",
    "RemoteManifest",
    "fetch_update",
    "fetch_manifest",
    "select_announcement",
    "is_newer",
    "parse_version",
    "download_update",
    "apply_update",
    "install_root",
    "can_self_update",
    "is_frozen",
]
