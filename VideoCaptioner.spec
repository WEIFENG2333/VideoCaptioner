# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the VideoCaptioner desktop bundle."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None


def _safe(fn, name):
    """collect_* 对未安装的包会抛错；可选依赖（ocr extra）缺失时返回空，base 包仍可打。"""
    try:
        return fn(name)
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] skip {fn.__name__}({name!r}): {exc}")
        return []

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
# yt-dlp 的 ~900 个 extractor 子模块动态加载，必须显式收集，否则包内下载报 extractor 缺失。
hiddenimports += collect_submodules("yt_dlp")
# 实时字幕：sounddevice 经 cffi dlopen PortAudio；websocket-client 提供顶层 websocket 包。
hiddenimports += ["sounddevice", "_sounddevice_data", "cffi", "_cffi_backend", "websocket", "numpy"]
# 硬字幕 OCR（可选 ocr extra）：rapidocr 自带 PP-OCR 模型 + yaml 配置（Path(__file__) 读取，需打进包，离线可用）；
# onnxruntime 的原生库（libonnxruntime.*.dylib / onnxruntime_pybind11_state.so）。ocr 未装时这些为空、不影响 base 包。
hiddenimports += ["onnxruntime", "rapidocr", "rapidfuzz"]
hiddenimports += _safe(collect_submodules, "rapidocr")

datas += _safe(collect_data_files, "rapidocr")
ocr_binaries = _safe(collect_dynamic_libs, "onnxruntime")

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
    binaries=ocr_binaries,
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
