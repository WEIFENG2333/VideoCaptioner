# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the VideoCaptioner desktop bundle."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

ROOT = Path(SPECPATH)
RUNTIME_DIR = Path(os.environ.get("VIDEOCAPTIONER_DESKTOP_RUNTIME_DIR", ROOT / "build" / "desktop-runtime"))


def _data(src: Path, dest: str):
    return (str(src), dest)


datas = [
    _data(ROOT / "resource" / "assets", "resource/assets"),
    _data(ROOT / "resource" / "fonts", "resource/fonts"),
    _data(ROOT / "resource" / "subtitle_styles", "resource/subtitle_styles"),
    _data(ROOT / "resource" / "i18n", "resource/i18n"),
    _data(ROOT / "videocaptioner" / "core" / "prompts", "videocaptioner/core/prompts"),
]

runtime_bin = RUNTIME_DIR / "resource" / "bin"
if runtime_bin.exists():
    datas.append(_data(runtime_bin, "resource/bin"))

hiddenimports = [
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSvg",
    "PyQt5.sip",
    "openai",
    "requests",
    "edge_tts",
    "diskcache",
    "yt_dlp",
    "psutil",
    "json_repair",
    "langdetect",
    "pydub",
    "tenacity",
    "GPUtil",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "fontTools",
    "fontTools.ttLib",
]
hiddenimports += collect_submodules("qfluentwidgets")

excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "numpy.testing",
    "pytest",
    "pyright",
    "ruff",
    "test",
    "unittest",
]

a = Analysis(
    [str(ROOT / "videocaptioner" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoCaptioner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # 桌面 GUI 包：Windows 双击不弹控制台。命令行用户走 pip 安装的 CLI。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoCaptioner",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VideoCaptioner.app",
        bundle_identifier="com.weifeng.videocaptioner",
        info_plist={
            "CFBundleName": "VideoCaptioner",
            "CFBundleDisplayName": "VideoCaptioner",
            "NSHighResolutionCapable": True,
        },
    )
