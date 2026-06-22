"""软件更新 + 公告：拉取 GitHub Release 的 latest.json，选当前平台资产、判断新版、取公告。

manifest 由 CI 在发版时生成并挂到同一个 Release（与资产同源、可回滚）。公告字段可在发版
后随时 `gh release upload latest.json --clobber` 覆盖更新（零服务器、可实时改）。结构：

    {
      "version": "1.5.0",
      "notes": "更新内容…",
      "mandatory": false,            # 强制更新（一刀切）
      "min_supported": "1.0.0",      # 低于此版本视为必须更新（可选）
      "pub_date": "2026-06-22",
      "platforms": {
        "macos-arm64": {"url": "...", "sha256": "...", "size": 123, "kind": "app-zip"},
        "macos-x64":   {"url": "...", "sha256": "...", "size": 123, "kind": "app-zip"},
        "windows-x64": {"url": "...", "sha256": "...", "size": 123, "kind": "onedir-zip"}
      },
      "announcement": {              # 可选，实时公告
        "enabled": true,
        "id": "2026-summer",         # 去重键（客户端按 id 只弹一次）；缺省用 content 哈希
        "title": "标题",             # 可选
        "content": "公告内容…",
        "start_date": "2026-06-01",  # 可选，生效起（含）
        "end_date": "2026-07-01",    # 可选，生效止（含）
        "min_version": "",           # 可选，只给 >= 此版本的用户看
        "max_version": ""            # 可选，只给 <= 此版本的用户看（版本定向）
      }
    }

只读纯逻辑，无 PyQt 依赖（UI 通过 ui/thread/update_thread.py 接入）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256 as _sha256
from typing import Optional

import requests

from videocaptioner.core.download.dependencies import current_platform
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("update_manifest")

# 与 dependencies 同策略：ghproxy 镜像优先（国内可达），GitHub 直连兜底。
_GH_MIRRORS = ("https://ghproxy.com/", "https://mirror.ghproxy.com/")


@dataclass(frozen=True)
class UpdateAsset:
    url: str
    sha256: str
    size: int
    kind: str  # "onedir-zip"(Windows 目录包) | "app-zip"(macOS .app)


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    mandatory: bool
    asset: UpdateAsset

    @property
    def urls(self) -> tuple[str, ...]:
        """资产下载地址：镜像优先 + 直连兜底。"""
        return _mirror_urls(self.asset.url)


@dataclass(frozen=True)
class Announcement:
    id: str       # 去重键，客户端按它只弹一次
    title: str
    content: str


@dataclass(frozen=True)
class RemoteManifest:
    """一次拉取的结果：可能有新版、可能有公告，两者互相独立。"""

    update: Optional[UpdateInfo]
    announcement: Optional[Announcement]


def _mirror_urls(url: str) -> tuple[str, ...]:
    return tuple(m + url for m in _GH_MIRRORS) + (url,)


def parse_version(value: str) -> tuple[int, ...]:
    """'v1.5.0' / '1.5.0' → (1,5,0)；非法/dev 返回 (0,)。"""
    raw = (value or "").lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for piece in raw.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) or (0,)


def _padded(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """把两个版本元组补零到等长再比，避免 (1,5) < (1,5,0) 这类长度差导致的误判。"""
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def is_newer(latest: str, current: str) -> bool:
    a, b = _padded(parse_version(latest), parse_version(current))
    return a > b


def select_asset(platforms: dict) -> Optional[dict]:
    """按当前 os-arch 选资产；macOS arm64 无原生包时回落 x64（Rosetta）。"""
    os_key, arch = current_platform()
    for key in (f"{os_key}-{arch}", f"{os_key}-x64" if os_key == "macos" else None):
        if key and key in platforms:
            return platforms[key]
    return None


def _within_window(start: str, end: str, today: date) -> bool:
    """今天是否落在 [start, end] 内（含端点）。任一端缺省即该侧无限制。"""
    try:
        if start and today < date.fromisoformat(start):
            return False
        if end and today > date.fromisoformat(end):
            return False
    except ValueError:
        return False  # 日期格式错 → 不展示，避免误推
    return True


def select_announcement(
    ann: dict,
    current_version: str,
    *,
    today: Optional[date] = None,
) -> Optional[Announcement]:
    """从 manifest 的 announcement 块选出当前应展示的公告，否则 None。

    生效条件：``enabled`` 且 ``content`` 非空、今天在 ``start_date~end_date`` 时间窗内、
    当前版本落在 ``min_version~max_version`` 区间内（版本定向）。"只弹一次"的去重由 UI
    按返回的 ``id`` 处理，本函数不读写状态。
    """
    if not ann or not ann.get("enabled", False):
        return None
    content = str(ann.get("content", "")).strip()
    if not content:
        return None
    if not _within_window(str(ann.get("start_date", "")), str(ann.get("end_date", "")), today or date.today()):
        return None
    cur = parse_version(current_version)
    min_v = str(ann.get("min_version", "")).strip()
    max_v = str(ann.get("max_version", "")).strip()
    if min_v:
        a, b = _padded(cur, parse_version(min_v))
        if a < b:
            return None
    if max_v:
        a, b = _padded(cur, parse_version(max_v))
        if a > b:
            return None
    ann_id = str(ann.get("id", "")).strip() or _sha256(content.encode("utf-8")).hexdigest()[:16]
    return Announcement(id=ann_id, title=str(ann.get("title", "")).strip(), content=content)


def _select_update(data: dict, current_version: str) -> Optional[UpdateInfo]:
    """从 manifest 选当前平台的可用新版；无新版/无本平台资产返回 None。"""
    latest = str(data.get("version", "")).strip()
    if not latest or not is_newer(latest, current_version):
        return None
    raw = select_asset(data.get("platforms", {}) or {})
    if not raw or not raw.get("url"):
        logger.info("manifest 无当前平台资产：%s", current_platform())
        return None
    mandatory = bool(data.get("mandatory", False))
    min_supported = str(data.get("min_supported", "")).strip()
    if min_supported and parse_version(current_version) < parse_version(min_supported):
        mandatory = True
    return UpdateInfo(
        version=latest,
        notes=str(data.get("notes", "")),
        mandatory=mandatory,
        asset=UpdateAsset(
            url=str(raw["url"]),
            sha256=str(raw.get("sha256", "")),
            size=int(raw.get("size", 0) or 0),
            kind=str(raw.get("kind", "")),
        ),
    )


def _fetch_json(
    current_version: str,
    manifest_urls: tuple[str, ...],
    session: Optional[requests.Session],
    timeout: int,
) -> Optional[dict]:
    """按镜像顺序拉 manifest JSON；全部失败返回 None（静默，调用方记日志）。"""
    http = session or requests.Session()
    errors = []
    for url in _mirror_urls(manifest_urls[0]) if len(manifest_urls) == 1 else manifest_urls:
        try:
            resp = http.get(url, timeout=timeout, headers={"app_version": current_version})
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
    logger.info("update manifest 不可达：%s", "; ".join(errors))
    return None


def fetch_manifest(
    current_version: str,
    manifest_urls: tuple[str, ...],
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> Optional[RemoteManifest]:
    """一次拉取 manifest，返回（可用新版, 公告）。网络/解析失败返回 None；不抛给 UI。"""
    data = _fetch_json(current_version, manifest_urls, session, timeout)
    if data is None:
        return None
    return RemoteManifest(
        update=_select_update(data, current_version),
        announcement=select_announcement(data.get("announcement", {}) or {}, current_version),
    )


def fetch_update(
    current_version: str,
    manifest_urls: tuple[str, ...],
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> Optional[UpdateInfo]:
    """拉 manifest、选平台资产、比较版本。有新版返回 UpdateInfo，否则 None。"""
    manifest = fetch_manifest(current_version, manifest_urls, session=session, timeout=timeout)
    return manifest.update if manifest else None
