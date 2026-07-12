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
# 公益大模型经 curl_cffi（浏览器 TLS 指纹过 Cloudflare）：wheel 内带原生 libcurl-impersonate
# 与 CA 证书数据，需显式收集，否则打包后 import 就崩。
hiddenimports += ["curl_cffi"]
hiddenimports += collect_submodules("curl_cffi")

datas += _safe(collect_data_files, "rapidocr")
datas += collect_data_files("curl_cffi")
native_binaries = _safe(collect_dynamic_libs, "onnxruntime")
native_binaries += collect_dynamic_libs("curl_cffi")

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
    # Widgets 应用不含 QML/Quick 场景
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets",
    "PyQt5.QtWebSockets",
    # pywin32 的 MFC/GUI 组件（win32ui/Pythonwin），应用不引用
    "win32ui",
    "win32uiole",
    "pythonwin",
]

# 按文件名剔除 hook 仍会收进来的大块二进制：
# - Qt5Qml/Qt5Quick 系与 d3dcompiler（ANGLE 编译器）：Widgets 应用用不到；
# - opengl32sw（软件渲染 OpenGL 回退）：本应用无 OpenGL 视图，raster 渲染即可；
# - opencv_videoio_ffmpeg（cv2 视频读写插件，惰性加载）：OCR 只用图像 API；
# - 顶层重复的 OpenBLAS：numpy 实际从 numpy.libs 目录加载自己的那份。
_DROP_BINARY_PATTERNS = (
    "qt5qml",
    "qt5quick",
    "qt5websockets",
    "d3dcompiler",
    "opengl32sw",
    "opencv_videoio_ffmpeg",
    "mfc140u",
)


def _keep_binary(entry):
    dest, _source, _kind = entry
    name = Path(dest).name.lower()
    if any(pattern in name for pattern in _DROP_BINARY_PATTERNS):
        return False
    # OpenBLAS 只保留 numpy.libs 里的那份
    if name.startswith("libscipy_openblas") and "numpy.libs" not in dest.replace("\\", "/"):
        return False
    return True

a = Analysis(
    [str(ROOT / "videocaptioner" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=native_binaries,
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

a.binaries = [entry for entry in a.binaries if _keep_binary(entry)]

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
