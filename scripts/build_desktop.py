#!/usr/bin/env python3
"""Build a desktop bundle for the current platform with PyInstaller."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "VideoCaptioner.spec"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
ARTIFACT_DIR = ROOT / "artifacts"
RUNTIME_DIR = BUILD_DIR / "desktop-runtime"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT), check=True, **kwargs)


def _version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("videocaptioner").lstrip("v")
    except Exception:
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "hatchling", "version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().lstrip("v")
    except Exception:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().lstrip("v")
    return "0.0.0-dev"


def ensure_version_file(version: str) -> None:
    version_file = ROOT / "videocaptioner" / "_version.py"
    if version_file.exists():
        return
    version_file.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    print(f"Generated {version_file.relative_to(ROOT)} ({version})")


def clean() -> None:
    for path in [BUILD_DIR, DIST_DIR, ARTIFACT_DIR]:
        if path.exists():
            print(f"Removing {path.relative_to(ROOT)}")
            shutil.rmtree(path)


def prepare_ffmpeg() -> None:
    """Download the current platform's static ffmpeg/ffprobe into runtime resources."""
    try:
        from static_ffmpeg.run import (
            get_or_fetch_platform_executables_else_raise,
            get_platform_key,
        )
    except ImportError as exc:
        raise RuntimeError(
            "static-ffmpeg is required for desktop builds. "
            "Run with: uv run --with pyinstaller --with static-ffmpeg python scripts/build_desktop.py"
        ) from exc

    runtime_bin = RUNTIME_DIR / "resource" / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    cache_dir = BUILD_DIR / "static-ffmpeg" / get_platform_key()
    ffmpeg, ffprobe = get_or_fetch_platform_executables_else_raise(download_dir=str(cache_dir))
    for src in [Path(ffmpeg), Path(ffprobe)]:
        dst = runtime_bin / src.name
        if dst.exists():
            dst.chmod(dst.stat().st_mode | stat.S_IWUSR)
        shutil.copy2(src, dst)
        if platform.system() != "Windows":
            mode = dst.stat().st_mode
            dst.chmod(mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"Bundled {dst.relative_to(ROOT)}")


def prepare_macsysaudio() -> None:
    """Build the macOS system-audio helper (ScreenCaptureKit) into runtime resources.

    macOS only, ~91KB static Swift binary — small + unchanging, so it ships INSIDE the
    bundle (no download step, no signing needed: an unsigned helper still works, the user
    just grants「屏幕录制」once and the grant persists for a never-updated app).

    Same staging pattern as ffmpeg: build → copy into RUNTIME_DIR/resource/bin with +x;
    PyInstaller's onedir COLLECT preserves the mode bit, so find_macsysaudio_binary finds
    an executable at BUNDLED_BIN_PATH (else os.access(X_OK) fails and 「系统声音」 hides).

    Best-effort: without the Swift toolchain (Xcode CLT) it warns and continues — the app
    still runs, system audio capture is just unavailable. Needs native/macsysaudio/ in the
    repo (git-tracked) for the build.sh source to exist on a fresh checkout.
    """
    if platform.system() != "Darwin":
        return
    runtime_bin = RUNTIME_DIR / "resource" / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    build_sh = ROOT / "native" / "macsysaudio" / "build.sh"
    src = ROOT / "resource" / "bin" / "macsysaudio"
    try:
        if build_sh.exists():
            _run(["bash", str(build_sh)])
    except Exception as exc:
        print(f"WARNING: macsysaudio build failed ({exc}); system audio will be unavailable")
    if not src.exists():
        print("WARNING: macsysaudio binary not found (native/macsysaudio not built); "
              "system audio capture will be unavailable in this build")
        return
    dst = runtime_bin / "macsysaudio"
    if dst.exists():
        dst.chmod(dst.stat().st_mode | stat.S_IWUSR)
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Bundled {dst.relative_to(ROOT)}")


def build_pyinstaller() -> None:
    env = os.environ.copy()
    env["VIDEOCAPTIONER_DESKTOP_RUNTIME_DIR"] = str(RUNTIME_DIR)
    _run([
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "pyinstaller"),
    ], env=env)


def _platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    if system == "darwin":
        system = "macos"
    return f"{system}-{machine}"


def _archive_dir(source: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    if platform.system() == "Darwin":
        # macOS 必须用 ditto：zipfile 会把符号链接拍平成普通文件、丢掉可执行位，解压出的
        # .app（Python/Qt framework 的 Versions/Current 软链 + 主程序 +x）将无法启动。
        # ditto 保留软链/权限/代码签名，且产物是标准 zip。客户端 _extract 对应也用 ditto。
        _run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(source), str(archive)])
    else:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for file in sorted(source.rglob("*")):
                if file.is_file():
                    zf.write(file, file.relative_to(source.parent))
    print(f"Created {archive.relative_to(ROOT)}")


def verify_bundle() -> None:
    bundle = DIST_DIR / "VideoCaptioner"
    if platform.system() == "Windows":
        exe = bundle / "VideoCaptioner.exe"
    else:
        exe = bundle / "VideoCaptioner"
    if not exe.exists():
        raise RuntimeError(f"Executable not found: {exe}")

    data_root = bundle / "_internal"
    required = [
        data_root / "resource" / "assets" / "logo.png",
        data_root / "resource" / "fonts" / "NotoSansSC-Regular.ttf",
        data_root / "resource" / "subtitle_styles" / "ass" / "default.json",
        data_root / "resource" / "bin" / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"),
        data_root / "resource" / "bin" / ("ffprobe.exe" if platform.system() == "Windows" else "ffprobe"),
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing bundled resources:\n  - " + "\n  - ".join(missing))
    if platform.system() == "Darwin":
        # 软检查（不阻断构建）：缺它只是「系统声音」不可用，不是整包坏了。
        helper = data_root / "resource" / "bin" / "macsysaudio"
        print(f"  macsysaudio (系统声音): {'present' if helper.exists() else 'MISSING — system audio disabled'}")
    print(f"Verified desktop bundle: {bundle.relative_to(ROOT)}")


def archive(version: str) -> None:
    bundle = DIST_DIR / "VideoCaptioner"
    tag = _platform_tag()
    _archive_dir(bundle, ARTIFACT_DIR / f"VideoCaptioner-{version}-{tag}.zip")
    app = DIST_DIR / "VideoCaptioner.app"
    if app.exists():
        # ad-hoc 签名后再打包：更新负载（app-zip）与 dmg 走同一签名姿态，规避 Apple Silicon
        # 「已损坏」硬拦截。无 Apple 证书，ad-hoc 不消除 Gatekeeper 首启提示（需公证）。
        if subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)]).returncode != 0:
            print("⚠ ad-hoc codesign 失败（不阻断打包）")
        _archive_dir(app, ARTIFACT_DIR / f"VideoCaptioner-{version}-{tag}-app.zip")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="Remove build/dist/artifacts first")
    parser.add_argument("--no-archive", action="store_true", help="Build and verify without creating zip archives")
    args = parser.parse_args()

    version = _version()
    if args.clean:
        clean()
    ensure_version_file(version)
    prepare_ffmpeg()
    prepare_macsysaudio()
    build_pyinstaller()
    verify_bundle()
    if not args.no_archive:
        archive(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
