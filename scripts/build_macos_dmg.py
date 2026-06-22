#!/usr/bin/env python3
"""把 dist/VideoCaptioner.app 打成拖拽安装的 .dmg（仅 macOS）。

无 Apple 证书时尽力而为：先 ad-hoc 签名（`codesign -s -`），避免 Apple Silicon 上未签名包被
判「已损坏，移到废纸篓」的硬拦截 —— 降级成可「右键 → 打开」的软提示。.dmg 只是更顺手的安装
形态，**不能**消除首次打开的 Gatekeeper 提示（那需要付费证书 + 公证）。自动更新换装后的 .app
由 helper 清 quarantine，所以只有首次手动下载需要右键打开一次。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_desktop import ARTIFACT_DIR, DIST_DIR, ROOT, _platform_tag, _version  # noqa: E402


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(map(str, cmd)))
    return subprocess.run(cmd, check=check)


def build_dmg() -> Path:
    if platform.system() != "Darwin":
        raise SystemExit("build_macos_dmg.py 只能在 macOS 上运行")
    app = DIST_DIR / "VideoCaptioner.app"
    if not app.exists():
        raise SystemExit(f"未找到 {app}，请先运行 build_desktop.py")
    version = _version()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_DIR / f"VideoCaptioner-{version}-{_platform_tag()}.dmg"
    out.unlink(missing_ok=True)

    # ad-hoc 签名：尽力而为，失败不阻断打包（CI 真机的 .app 应当成功）。
    res = _run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=False)
    if res.returncode != 0:
        print("⚠ ad-hoc codesign 失败（不阻断打包）；首次打开可能被判「已损坏」，需手动清 quarantine")

    # 暂存目录放 .app + 指向 /Applications 的软链，hdiutil 打成拖拽安装的 dmg。
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "dmg"
        stage.mkdir()
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        _run([
            "hdiutil", "create",
            "-volname", "VideoCaptioner",
            "-srcfolder", str(stage),
            "-fs", "HFS+",
            "-format", "UDZO",
            "-ov",
            str(out),
        ])
    print(f"Created {out.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    build_dmg()
