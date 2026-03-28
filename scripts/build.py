#!/usr/bin/env python3
"""
Build script for VideoCaptioner using PyInstaller.

Usage:
    python scripts/build.py          # Build for current platform
    python scripts/build.py --clean  # Clean build artifacts first

Requirements:
    pip install pyinstaller
"""

import argparse
import io
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT_DIR / "VideoCaptioner.spec"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"

# Windows binary download URLs
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
SEVENZIP_URL = "https://7-zip.org/a/7zr.exe"


def clean():
    """Remove previous build artifacts."""
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            print(f"Removing {d}")
            shutil.rmtree(d)


def _download_with_retry(url: str, max_retries: int = 3) -> bytes:
    """Download a URL with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 5
                print(f"  Attempt {attempt} failed: {e}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def download_windows_binaries():
    """Download ffmpeg and 7z binaries for Windows builds."""
    if platform.system() != "Windows":
        return

    bin_dir = ROOT_DIR / "resource" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # --- ffmpeg ---
    ffmpeg_exe = bin_dir / "ffmpeg.exe"
    if not ffmpeg_exe.exists():
        print("Downloading ffmpeg...")
        try:
            data = _download_with_retry(FFMPEG_URL)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    name = Path(member).name
                    if name in ("ffmpeg.exe", "ffprobe.exe"):
                        print(f"  Extracting {name}")
                        with zf.open(member) as src, open(bin_dir / name, "wb") as dst:
                            dst.write(src.read())
            print("  ffmpeg ready")
        except Exception as e:
            print(f"  WARNING: Failed to download ffmpeg: {e}")
    else:
        print("ffmpeg already exists, skipping download")

    # --- 7z ---
    sevenzip_exe = bin_dir / "7z.exe"
    if not sevenzip_exe.exists():
        print("Downloading 7z...")
        try:
            data = _download_with_retry(SEVENZIP_URL)
            (bin_dir / "7z.exe").write_bytes(data)
            print("  7z ready")
        except Exception as e:
            print(f"  WARNING: Failed to download 7z: {e}")
    else:
        print("7z already exists, skipping download")


def copy_writable_resources_to_dist():
    """Copy writable resource dirs to dist output (alongside the exe).

    These directories need to be writable at runtime:
    - resource/bin/: ffmpeg, 7z, Faster-Whisper downloads (Windows only)
    - resource/subtitle_style/: user-created subtitle styles (all platforms)
    """
    output_dir = DIST_DIR / "VideoCaptioner"

    # bin/ — Windows only (ffmpeg, 7z)
    if platform.system() == "Windows":
        src = ROOT_DIR / "resource" / "bin"
        dst = output_dir / "resource" / "bin"
        if src.exists():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
                    print(f"  Copied bin/{f.name} to dist")
        else:
            print("WARNING: resource/bin/ not found, skipping")

    # subtitle_style/ — all platforms (preset + user styles)
    src = ROOT_DIR / "resource" / "subtitle_style"
    dst = output_dir / "resource" / "subtitle_style"
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print("  Copied subtitle_style/ to dist")


def ensure_version_file():
    """Generate videocaptioner/_version.py if it doesn't exist.

    hatch-vcs generates this file during pip install, but it may not exist
    when building directly with PyInstaller.
    """
    version_file = ROOT_DIR / "videocaptioner" / "_version.py"
    if version_file.exists():
        print(f"Version file exists: {version_file}")
        return

    # Try to get version from git tags via hatch-vcs
    try:
        result = subprocess.run(
            [sys.executable, "-m", "hatchling", "version"],
            capture_output=True, text=True, cwd=str(ROOT_DIR),
        )
        if result.returncode == 0:
            version = result.stdout.strip()
        else:
            # Fallback: get version from git describe
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                capture_output=True, text=True, cwd=str(ROOT_DIR),
            )
            version = result.stdout.strip().lstrip("v") if result.returncode == 0 else "0.0.0"
    except Exception:
        version = "0.0.0"

    version_file.write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    print(f"Generated {version_file} with version {version}")


def build():
    """Run PyInstaller with the spec file."""
    if not SPEC_FILE.exists():
        print(f"ERROR: Spec file not found: {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]

    print(f"Building VideoCaptioner for {platform.system()} ({platform.machine()})...")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if result.returncode != 0:
        print("\nBuild FAILED!")
        sys.exit(1)

    # Copy writable resource dirs to dist output
    copy_writable_resources_to_dist()

    # Print output location
    output_dir = DIST_DIR / "VideoCaptioner"
    if platform.system() == "Darwin":
        app_bundle = DIST_DIR / "VideoCaptioner.app"
        if app_bundle.exists():
            print(f"\nmacOS app bundle: {app_bundle}")
    if output_dir.exists():
        print(f"\nBuild output: {output_dir}")

    print("\nBuild SUCCESS!")


def verify():
    """Basic verification that the build output exists and has expected files."""
    output_dir = DIST_DIR / "VideoCaptioner"
    if not output_dir.exists():
        print("ERROR: Build output directory not found")
        sys.exit(1)

    # Check executable
    if platform.system() == "Windows":
        exe = output_dir / "VideoCaptioner.exe"
    else:
        exe = output_dir / "VideoCaptioner"

    if not exe.exists():
        print(f"ERROR: Executable not found: {exe}")
        sys.exit(1)

    # PyInstaller places bundled data in _internal/ directory
    internal_dir = output_dir / "_internal"
    data_root = internal_dir if internal_dir.exists() else output_dir

    # Check resource directories are bundled
    expected_resources = [
        "resource/assets/logo.png",
        "resource/fonts/LXGWWenKai-Regular.ttf",
        "resource/subtitle_style/default.json",
        "resource/translations",
        "videocaptioner/core/prompts/split/semantic.md",
    ]

    missing = []
    for res in expected_resources:
        if not (data_root / res).exists():
            missing.append(res)

    if missing:
        print("WARNING: Missing bundled resources:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("All expected resources found in bundle.")

    # Check Windows binaries
    if platform.system() == "Windows":
        bin_dir = output_dir / "resource" / "bin"
        for name in ["ffmpeg.exe", "7z.exe"]:
            p = bin_dir / name
            if p.exists():
                print(f"  {name}: {p.stat().st_size / (1024*1024):.1f} MB")
            else:
                print(f"  WARNING: {name} not found in dist")

    print(f"\nExecutable size: {exe.stat().st_size / (1024*1024):.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Build VideoCaptioner")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing build")
    args = parser.parse_args()

    if args.verify_only:
        verify()
        return

    if args.clean:
        clean()

    # Pre-build steps
    ensure_version_file()
    download_windows_binaries()

    build()
    verify()


if __name__ == "__main__":
    main()
