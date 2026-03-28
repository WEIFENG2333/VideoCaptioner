# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for VideoCaptioner.

Usage:
    pyinstaller VideoCaptioner.spec
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

# ── Data files to bundle ───────────────────────────────────────────────
# Format: (source, dest_in_bundle)
datas = [
    # Resource directories
    (str(ROOT / "resource" / "assets"), "resource/assets"),
    (str(ROOT / "resource" / "fonts"), "resource/fonts"),
    (str(ROOT / "resource" / "subtitle_style"), "resource/subtitle_style"),
    (str(ROOT / "resource" / "translations"), "resource/translations"),
    # Prompt template .md files
    (str(ROOT / "videocaptioner" / "core" / "prompts"), "videocaptioner/core/prompts"),
]

# ── Hidden imports ─────────────────────────────────────────────────────
# Modules that PyInstaller can't auto-detect
hiddenimports = [
    # Qt plugins & bindings
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSvg",
    "PyQt5.sip",
    # qfluentwidgets
    "qfluentwidgets",
    "qfluentwidgets._rc",
    "qfluentwidgets._rc.resource",
    "qfluentwidgets.common",
    "qfluentwidgets.components",
    "qfluentwidgets.multimedia",
    "qfluentwidgets.window",
    # Core dependencies
    "openai",
    "requests",
    "diskcache",
    "yt_dlp",
    "modelscope",
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
    # stdlib modules sometimes missed
    "json",
    "logging",
    "traceback",
    "string",
    "functools",
    "pathlib",
    "typing",
]

# ── Excluded modules (reduce bundle size) ──────────────────────────────
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
    [str(ROOT / "videocaptioner" / "ui" / "main.py")],
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
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resource" / "assets" / "logo.png"),
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

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VideoCaptioner.app",
        icon=str(ROOT / "resource" / "assets" / "logo.png"),
        bundle_identifier="com.weifeng.videocaptioner",
        info_plist={
            "CFBundleName": "VideoCaptioner",
            "CFBundleDisplayName": "VideoCaptioner",
            "CFBundleVersion": "1.5.0",
            "CFBundleShortVersionString": "1.5.0",
            "NSHighResolutionCapable": True,
        },
    )
