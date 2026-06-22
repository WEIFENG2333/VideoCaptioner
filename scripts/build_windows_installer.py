#!/usr/bin/env python3
"""用 Inno Setup 把 dist/VideoCaptioner onedir 打成 Setup.exe（仅 Windows）。

per-user 安装到 %LOCALAPPDATA%\\Programs\\VideoCaptioner：无需管理员，安装目录可写 → 应用内
自更新（core/update 的 rm+mv 换装）照常生效。带开始菜单/桌面快捷方式 + 卸载程序。便携 zip 由
build_desktop.py 单独产出，两者基于同一 onedir。CI 用 `choco install innosetup` 装编译器。
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from shutil import which

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_desktop import ARTIFACT_DIR, DIST_DIR, ROOT, _version  # noqa: E402

ISS = ROOT / "packaging" / "windows" / "VideoCaptioner.iss"


def _find_iscc() -> str:
    exe = which("ISCC") or which("iscc")
    if exe:
        return exe
    for base in (
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ):
        cand = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if cand.is_file():
            return str(cand)
    raise SystemExit("未找到 Inno Setup 编译器 ISCC.exe（CI 用 `choco install innosetup -y` 安装）")


def build_installer() -> Path:
    if platform.system() != "Windows":
        raise SystemExit("build_windows_installer.py 只能在 Windows 上运行")
    source = DIST_DIR / "VideoCaptioner"
    if not (source / "VideoCaptioner.exe").exists():
        raise SystemExit(f"未找到 {source}\\VideoCaptioner.exe，请先运行 build_desktop.py")
    version = _version()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_base = f"VideoCaptioner-{version}-windows-x64-setup"
    cmd = [
        _find_iscc(),
        f"/DAppVersion={version}",
        f"/DSourceDir={source}",
        f"/DOutputDir={ARTIFACT_DIR}",
        f"/DOutputBase={out_base}",
        str(ISS),
    ]
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)
    out = ARTIFACT_DIR / f"{out_base}.exe"
    if not out.is_file():
        raise SystemExit(f"ISCC 未产出 {out}")
    print(f"Created {out}")
    return out


if __name__ == "__main__":
    build_installer()
