"""软件更新：拉取 GitHub Release 的 latest.json，选当前平台资产，判断是否有新版。

manifest 由 CI 在发版时生成并挂到同一个 Release（与资产同源、可回滚），结构：

    {
      "version": "1.5.0",
      "notes": "更新内容…",
      "mandatory": false,            # 强制更新
      "min_supported": "1.0.0",      # 低于此版本视为必须更新（可选）
      "pub_date": "2026-06-22",
      "platforms": {
        "macos-arm64": {"url": "...", "sha256": "...", "size": 123, "kind": "app-zip"},
        "macos-x64":   {"url": "...", "sha256": "...", "size": 123, "kind": "app-zip"},
        "windows-x64": {"url": "...", "sha256": "...", "size": 123, "kind": "onedir-zip"}
      }
    }

只读纯逻辑，无 PyQt 依赖（UI 通过 ui/thread/update_thread.py 接入）。
"""

from __future__ import annotations

from dataclasses import dataclass
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


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def select_asset(platforms: dict) -> Optional[dict]:
    """按当前 os-arch 选资产；macOS arm64 无原生包时回落 x64（Rosetta）。"""
    os_key, arch = current_platform()
    for key in (f"{os_key}-{arch}", f"{os_key}-x64" if os_key == "macos" else None):
        if key and key in platforms:
            return platforms[key]
    return None


def fetch_update(
    current_version: str,
    manifest_urls: tuple[str, ...],
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> Optional[UpdateInfo]:
    """拉 manifest、选平台资产、比较版本。有新版返回 UpdateInfo，否则 None。

    网络/解析失败返回 None（静默，调用方可记日志）；不抛给 UI。
    """
    http = session or requests.Session()
    data = None
    errors = []
    for url in _mirror_urls(manifest_urls[0]) if len(manifest_urls) == 1 else manifest_urls:
        try:
            resp = http.get(url, timeout=timeout, headers={"app_version": current_version})
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
    if data is None:
        logger.info("update manifest 不可达：%s", "; ".join(errors))
        return None

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
