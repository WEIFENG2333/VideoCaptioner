"""
VideoCaptioner 路径与配置模块

支持三种运行模式:
  1. PyInstaller 打包模式 (sys.frozen=True)
  2. 源码开发模式 (项目根目录存在 resource/)
  3. pip 安装模式 (通过 platformdirs 定位数据目录)

目录职责划分:
  程序目录 (_EXE_DIR / _PROJECT_ROOT):
    - resource/bin/     → ffmpeg, 7z, Faster-Whisper 等二进制工具
    - work-dir/         → 默认视频处理工作目录

  只读资源 (RESOURCE_PATH, 打包时来自 _MEIPASS):
    - assets/           → logo、背景图、QSS 样式
    - fonts/            → 内置字体
    - translations/     → 国际化 .qm 文件

  用户数据 (APPDATA_PATH, 系统标准目录, 升级不受影响):
    - settings.json     → 用户设置 + API Key
    - logs/             → 应用日志
    - cache/            → LLM/ASR/翻译缓存
    - models/           → ASR 模型 (默认位置, 可在设置中自定义)
    - resource/subtitle_style/ → 用户自定义字幕样式
"""

import logging
import os
import sys
from pathlib import Path

# ── 版本号 ──────────────────────────────────────────────────────────────────
try:
    from videocaptioner._version import __version__ as _raw_version
    # Strip dev suffix (e.g. "1.5.0.dev103+g38544177c" → "1.5.0")
    VERSION = _raw_version.split(".dev")[0]
except Exception:
    VERSION = "0.0.0-dev"

YEAR = 2026
APP_NAME = "VideoCaptioner"
AUTHOR = "Weifeng"

HELP_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
GITHUB_REPO_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
RELEASE_URL = "https://github.com/WEIFENG2333/VideoCaptioner/releases/latest"
FEEDBACK_URL = "https://github.com/WEIFENG2333/VideoCaptioner/issues"

# ── 基础路径检测 ────────────────────────────────────────────────────────────
_PACKAGE_DIR = Path(__file__).parent        # videocaptioner/
_PROJECT_ROOT = _PACKAGE_DIR.parent         # 项目根目录

if getattr(sys, "frozen", False):
    # ── PyInstaller 打包模式 ──
    _MEIPASS = Path(sys._MEIPASS)           # type: ignore[attr-defined]
    _EXE_DIR = Path(sys.executable).parent

    # 程序目录: 二进制工具 + 默认工作目录
    ROOT_PATH = _EXE_DIR
    WORK_PATH = _EXE_DIR / "work-dir"
    BIN_PATH = _EXE_DIR / "resource" / "bin"

    # 只读资源: 打包在 _MEIPASS 里
    RESOURCE_PATH = _MEIPASS / "resource"

    # 用户数据: 系统标准目录 (升级程序不影响)
    from platformdirs import user_data_path
    APPDATA_PATH = user_data_path(APP_NAME)

elif (_PROJECT_ROOT / "resource").is_dir():
    # ── 源码开发模式 ──
    ROOT_PATH = _PROJECT_ROOT
    WORK_PATH = ROOT_PATH / "work-dir"
    BIN_PATH = ROOT_PATH / "resource" / "bin"
    RESOURCE_PATH = ROOT_PATH / "resource"
    APPDATA_PATH = ROOT_PATH / "AppData"

else:
    # ── pip 安装模式 ──
    from platformdirs import user_data_path
    ROOT_PATH = user_data_path(APP_NAME)
    WORK_PATH = Path.home() / "VideoCaptioner"
    BIN_PATH = ROOT_PATH / "resource" / "bin"
    RESOURCE_PATH = ROOT_PATH / "resource"
    APPDATA_PATH = ROOT_PATH

# ── 只读资源路径 ────────────────────────────────────────────────────────────
ASSETS_PATH = RESOURCE_PATH / "assets"
FONTS_PATH = RESOURCE_PATH / "fonts"
TRANSLATIONS_PATH = RESOURCE_PATH / "translations"

# pip 安装时的字体回退: 包内 resources/fonts/
_BUNDLED_FONTS = _PACKAGE_DIR / "resources" / "fonts"
if not FONTS_PATH.exists() and _BUNDLED_FONTS.exists():
    FONTS_PATH = _BUNDLED_FONTS

# ── 用户数据路径 ────────────────────────────────────────────────────────────
SETTINGS_PATH = APPDATA_PATH / "settings.json"
LOG_PATH = APPDATA_PATH / "logs"
LLM_LOG_FILE = LOG_PATH / "llm_requests.jsonl"
CACHE_PATH = APPDATA_PATH / "cache"
MODEL_PATH = APPDATA_PATH / "models"

# 字幕样式: 开发模式直接用 resource/ 下的，其他模式放在用户数据目录
if (_PROJECT_ROOT / "resource").is_dir() and not getattr(sys, "frozen", False):
    SUBTITLE_STYLE_PATH = _PROJECT_ROOT / "resource" / "subtitle_style"
else:
    SUBTITLE_STYLE_PATH = APPDATA_PATH / "resource" / "subtitle_style"

# ── 二进制工具路径 ──────────────────────────────────────────────────────────
FASTER_WHISPER_PATH = BIN_PATH / "Faster-Whisper-XXL"

# ── 日志配置 ────────────────────────────────────────────────────────────────
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ── 环境变量: 将 bin 加入 PATH ─────────────────────────────────────────────
if BIN_PATH.exists():
    os.environ["PATH"] = str(FASTER_WHISPER_PATH) + os.pathsep + os.environ["PATH"]
    os.environ["PATH"] = str(BIN_PATH) + os.pathsep + os.environ["PATH"]

if (BIN_PATH / "vlc").exists():
    os.environ["PYTHON_VLC_MODULE_PATH"] = str(BIN_PATH / "vlc")

# ── 创建必要目录 ────────────────────────────────────────────────────────────
for _p in [APPDATA_PATH, CACHE_PATH, LOG_PATH, WORK_PATH, MODEL_PATH]:
    _p.mkdir(parents=True, exist_ok=True)

# ── PyInstaller 首次运行: 复制可写预设资源 ──────────────────────────────────
if getattr(sys, "frozen", False):
    import shutil

    _bundled_styles = Path(sys._MEIPASS) / "resource" / "subtitle_style"  # type: ignore[attr-defined]
    if _bundled_styles.exists() and not SUBTITLE_STYLE_PATH.exists():
        shutil.copytree(_bundled_styles, SUBTITLE_STYLE_PATH)
