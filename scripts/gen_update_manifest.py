"""发版时生成自动更新清单 latest.json，挂到同一个 GitHub Release。

客户端（videocaptioner/core/update）拉它判断新版并取本平台资产。资产名由
scripts/build_desktop.py 决定：

    VideoCaptioner-{version}-windows-x64.zip       Windows onedir 目录包
    VideoCaptioner-{version}-macos-x64.zip         macOS onedir 目录包（不用于更新）
    VideoCaptioner-{version}-macos-x64-app.zip     macOS .app 包（用于更新）

更新走 .app（macOS）/ onedir 目录（Windows）：

- *-app.zip            → kind=app-zip，平台键 macos-<arch>
- *-windows-*.zip      → kind=onedir-zip，平台键 windows-<arch>
- macOS 的非 -app onedir 包跳过（macOS 更新替换 .app，不替换裸目录）

用法：
    python scripts/gen_update_manifest.py \
        --tag v2.1.0 --repo WEIFENG2333/VideoCaptioner \
        --artifacts ./artifacts --out latest.json \
        [--notes "本次更新…"] [--mandatory] [--min-supported 1.0.0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_NAME = re.compile(r"^VideoCaptioner-(?P<ver>.+?)-(?P<os>windows|macos)-(?P<arch>[a-z0-9]+)(?P<app>-app)?\.zip$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _classify(name: str) -> tuple[str, str] | None:
    """资产名 → (平台键, kind)；不参与更新的资产返回 None。"""
    m = _NAME.match(name)
    if not m:
        return None
    os_name, arch, is_app = m["os"], m["arch"], bool(m["app"])
    if os_name == "macos":
        # macOS 更新替换 .app；裸 onedir 包不用于更新
        return (f"macos-{arch}", "app-zip") if is_app else None
    return (f"windows-{arch}", "onedir-zip")


def build_manifest(
    *,
    version: str,
    tag: str,
    repo: str,
    artifacts: Path,
    notes: str,
    mandatory: bool,
    min_supported: str,
) -> dict:
    platforms: dict[str, dict] = {}
    for zip_path in sorted(artifacts.rglob("VideoCaptioner-*.zip")):
        classified = _classify(zip_path.name)
        if not classified:
            continue
        key, kind = classified
        platforms[key] = {
            "url": f"https://github.com/{repo}/releases/download/{tag}/{zip_path.name}",
            "sha256": _sha256(zip_path),
            "size": zip_path.stat().st_size,
            "kind": kind,
        }
    if not platforms:
        raise SystemExit(f"未在 {artifacts} 找到可发布的更新资产（VideoCaptioner-*-{{windows,macos}}-*.zip）")
    manifest: dict = {"version": version, "notes": notes, "mandatory": mandatory, "platforms": platforms}
    if min_supported:
        manifest["min_supported"] = min_supported
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True, help="Release tag，如 v2.1.0")
    parser.add_argument("--repo", required=True, help="owner/name，如 WEIFENG2333/VideoCaptioner")
    parser.add_argument("--artifacts", required=True, type=Path, help="含 zip 资产的目录（递归扫描）")
    parser.add_argument("--out", required=True, type=Path, help="输出 latest.json 路径")
    parser.add_argument("--notes", default="", help="更新说明")
    parser.add_argument("--mandatory", action="store_true", help="标记为强制更新")
    parser.add_argument("--min-supported", default="", help="低于此版本视为必须更新")
    args = parser.parse_args()

    version = args.tag.lstrip("vV")
    manifest = build_manifest(
        version=version,
        tag=args.tag,
        repo=args.repo,
        artifacts=args.artifacts,
        notes=args.notes,
        mandatory=args.mandatory,
        min_supported=args.min_supported,
    )
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 写入 {args.out}（{len(manifest['platforms'])} 个平台：{', '.join(manifest['platforms'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
