"""发版时把新版本登记到更新后端（POST /api/admin/release）。

取代旧的「生成 latest.json 挂 Release」：后端（飞书多维表格驱动）据此在「版本」表建/改一行，
客户端启动调 /api/update/check 即可拿到。二进制仍在 GitHub Release，这里只上报下载地址 +
sha256 + size。资产名由 scripts/build_desktop.py 决定：

    VideoCaptioner-{version}-windows-x64.zip       Windows onedir 目录包
    VideoCaptioner-{version}-macos-x64-app.zip     macOS .app 包
    VideoCaptioner-{version}-macos-arm64-app.zip   macOS .app 包
    （macOS 非 -app 的裸 onedir 包不参与更新，跳过）

用法（CI）：
    CI_RELEASE_TOKEN=xxx python scripts/register_release.py \
        --tag v2.3.0 --repo WEIFENG2333/VideoCaptioner \
        --artifacts ./artifacts [--notes "本次更新…"] \
        [--endpoint https://backend.videocaptioner.cn/api/admin/release]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import requests

_DEFAULT_ENDPOINT = "https://backend.videocaptioner.cn/api/admin/release"
_NAME = re.compile(r"^VideoCaptioner-(?P<ver>.+?)-(?P<os>windows|macos)-(?P<arch>[a-z0-9]+)(?P<app>-app)?\.zip$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _platform_key(name: str) -> str | None:
    """资产名 → 平台键；不参与更新的资产返回 None。"""
    m = _NAME.match(name)
    if not m:
        return None
    if m["os"] == "macos":
        return f"macos-{m['arch']}" if m["app"] else None  # 仅 .app 参与更新
    return f"windows-{m['arch']}"


def build_platforms(artifacts: Path, repo: str, tag: str) -> dict:
    platforms: dict[str, dict] = {}
    for zip_path in sorted(artifacts.rglob("VideoCaptioner-*.zip")):
        key = _platform_key(zip_path.name)
        if not key:
            continue
        platforms[key] = {
            "url": f"https://github.com/{repo}/releases/download/{tag}/{zip_path.name}",
            "sha256": _sha256(zip_path),
            "size": zip_path.stat().st_size,
        }
    return platforms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True, help="Release tag，如 v2.3.0")
    parser.add_argument("--repo", required=True, help="owner/name，如 WEIFENG2333/VideoCaptioner")
    parser.add_argument("--artifacts", required=True, type=Path, help="含 zip 资产的目录（递归扫描）")
    parser.add_argument("--notes", default="", help="更新说明")
    parser.add_argument("--endpoint", default=_DEFAULT_ENDPOINT, help="登记端点 URL")
    args = parser.parse_args()

    token = os.environ.get("CI_RELEASE_TOKEN", "").strip()
    if not token:
        print("✗ 缺少环境变量 CI_RELEASE_TOKEN", file=sys.stderr)
        return 1

    version = args.tag.lstrip("vV")
    platforms = build_platforms(args.artifacts, args.repo, args.tag)
    if not platforms:
        print(f"✗ 未在 {args.artifacts} 找到可发布资产（VideoCaptioner-*-{{windows,macos}}-*.zip）", file=sys.stderr)
        return 1

    payload = {"version": version, "notes": args.notes, "platforms": platforms}
    resp = requests.post(
        args.endpoint,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=30,
    )
    print(f"POST {args.endpoint} → {resp.status_code}")
    print(resp.text[:500])
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        print(f"✗ 后端登记失败：{body}", file=sys.stderr)
        return 1
    print(f"✓ 已登记 {version}（{len(platforms)} 个平台：{', '.join(platforms)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
