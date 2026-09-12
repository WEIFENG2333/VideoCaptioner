"""更新检查：调后端 ``/api/update/check``，拿 block / update / announcement。无 PyQt。

后端（自建，飞书多维表格驱动）决定一切：版本封禁、选最新版、公告时间窗。客户端只渲染。
二进制仍在 GitHub Release，响应给直链；下载时套国内镜像兜底 + sha256 校验（见 installer）。

请求头带匿名设备信息（与反馈复用同一个 client_id）供后端统计。任何失败返回 None，
调用方静默忽略、不阻断启动。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from videocaptioner.config import APP_NAME, VERSION
from videocaptioner.core.download.downloader import gh_mirror_urls
from videocaptioner.core.feedback.diagnostics import get_or_create_client_id, platform_tag
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("update_check")


def app_channel() -> str:
    """渠道：desktop=打包版 / dev=源码或 editable 安装 / pip=正式 wheel 安装。

    后端据此决定是否下发自更新：dev 能看到更新与公告（便于调试），pip 交给 pip 自己升级、
    后端不下发 update。frozen 用 sys.frozen 判；非 frozen 时按包是否在 site-packages 区分
    （源码/editable 在仓库目录 = dev，wheel 装进 site-packages = pip）——比版本号可靠，
    因为 editable 安装的源码运行也报真实版本号而非 0.0.0。
    """
    if bool(getattr(sys, "frozen", False)):
        return "desktop"
    if VERSION.startswith("0.0.0"):
        return "dev"
    parts = Path(__file__).resolve().parts
    return "pip" if ("site-packages" in parts or "dist-packages" in parts) else "dev"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str
    size: int

    @property
    def urls(self) -> tuple[str, ...]:
        """资产下载地址：镜像优先 + 直连兜底。"""
        return gh_mirror_urls(self.url)


@dataclass(frozen=True)
class Announcement:
    id: str
    title: str
    content: str


@dataclass(frozen=True)
class CheckResult:
    """一次检查的结果，三者互相独立、都可为空。"""

    block: Optional[str]  # 非空=当前版本被封禁，文案直接展示给用户
    update: Optional[UpdateInfo]
    announcement: Optional[Announcement]


def _parse_update(data: object) -> Optional[UpdateInfo]:
    if not isinstance(data, dict):
        return None
    url = str(data.get("url") or "").strip()
    version = str(data.get("version") or "").strip()
    if not url or not version:  # 缺关键字段视为无更新，不冒进
        return None
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return UpdateInfo(
        version=version,
        notes=str(data.get("notes") or ""),
        url=url,
        sha256=str(data.get("sha256") or "").strip(),
        size=size,
    )


def _parse_announcement(data: object) -> Optional[Announcement]:
    if not isinstance(data, dict):
        return None
    ann_id = str(data.get("id") or "").strip()
    content = str(data.get("content") or "").strip()
    if not ann_id or not content:  # 无 id（无法去重）或无正文 → 不弹
        return None
    return Announcement(id=ann_id, title=str(data.get("title") or "").strip(), content=content)


def check_update(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> Optional[CheckResult]:
    """调后端更新检查。网络/解析/错误响应一律返回 None（调用方静默忽略，不阻断启动）。"""
    http = session or requests.Session()
    plat = platform_tag()
    channel = app_channel()
    headers = {
        "X-App-Version": VERSION,
        "X-App-Platform": plat,
        "X-App-Channel": channel,
        "X-Client-Id": get_or_create_client_id(),
        "User-Agent": f"{APP_NAME}/{VERSION} ({plat})",
    }
    try:
        resp = http.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.info("更新检查不可达：%s", exc)
        return None
    if not isinstance(data, dict) or data.get("ok") is False:
        logger.info("更新检查返回错误：%s", str(data)[:200])
        return None

    raw_block = data.get("block")
    block = str(raw_block).strip() if isinstance(raw_block, str) and raw_block.strip() else None
    result = CheckResult(
        block=block,
        update=_parse_update(data.get("update")),
        announcement=_parse_announcement(data.get("announcement")),
    )
    logger.info(
        "更新检查：channel=%s blocked=%s update=%s announcement=%s",
        channel,
        bool(result.block),
        result.update.version if result.update else None,
        result.announcement.id if result.announcement else None,
    )
    return result
