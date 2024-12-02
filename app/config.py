import os
import logging
from pathlib import Path

VERSION = "v1.1.1"
YEAR = 2024
APP_NAME = "VideoCaptioner"
AUTHOR = "Weifeng"

HELP_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
GITHUB_REPO_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
RELEASE_URL = "https://github.com/WEIFENG2333/VideoCaptioner/releases/latest"
FEEDBACK_URL = "https://github.com/WEIFENG2333/VideoCaptioner/issues"

# 路径
ROOT_PATH = Path(__file__).parent

RESOURCE_PATH = ROOT_PATH.parent / "resource"
APPDATA_PATH = ROOT_PATH.parent / "AppData"
WORK_PATH = ROOT_PATH.parent / "work-dir"


BIN_PATH = RESOURCE_PATH / "bin"
ASSETS_PATH = RESOURCE_PATH / "assets"
SUBTITLE_STYLE_PATH = RESOURCE_PATH / "subtitle_style"

CACHE_PATH = APPDATA_PATH / "cache"
LOG_PATH = APPDATA_PATH / "logs"
SETTINGS_PATH = APPDATA_PATH / "settings.json"
MODEL_PATH = APPDATA_PATH / "models"

FASER_WHISPER_PATH = BIN_PATH / "Faster-Whisper-XXL"

# 日志配置
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 环境变量添加 bin 路径
os.environ["PATH"] = os.environ["PATH"] + os.pathsep + str(BIN_PATH)
if FASER_WHISPER_PATH.exists():
    os.environ["PATH"] = os.environ["PATH"] + os.pathsep + str(FASER_WHISPER_PATH)

# 创建路径
for p in [CACHE_PATH, LOG_PATH, WORK_PATH, MODEL_PATH]:
    p.mkdir(parents=True, exist_ok=True)
