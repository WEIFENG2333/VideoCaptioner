import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from platformdirs import user_data_path

try:
    # 取干净的发布号（"2.0.0.post1.dev0+g123" → "2.0.0"）。
    # 版本唯一来源是 git tag（hatch-vcs 生成 _version.py），升版本打 tag 即可。
    import re as _re

    from videocaptioner._version import __version__ as _raw_version

    _match = _re.match(r"\d+\.\d+\.\d+", _raw_version)
    VERSION = _match.group(0) if _match else _raw_version
except Exception:
    VERSION = "0.0.0-dev"
YEAR = 2026
APP_NAME = "VideoCaptioner"
AUTHOR = "Weifeng"

HELP_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
GITHUB_REPO_URL = "https://github.com/WEIFENG2333/VideoCaptioner"
RELEASE_URL = "https://github.com/WEIFENG2333/VideoCaptioner/releases/latest"
# 官方模型中转站（OpenAI 兼容网关）：注册 / 充值 / 创建 Key 的入口
OFFICIAL_API_SITE_URL = "https://api.videocaptioner.cn/"
FEEDBACK_URL = "https://github.com/WEIFENG2333/VideoCaptioner/issues"
# 更新检查后端：客户端启动调它，一次拿 block / update / announcement（飞书多维表格驱动）。
# 二进制仍在 GitHub Release，响应给直链；core/update 下载时自动加 ghproxy 镜像兜底 + 校验 sha256。
UPDATE_CHECK_URL = "https://backend.videocaptioner.cn/api/update/check"
# 用户反馈后端：客户端 multipart 提交到这里，后端写入飞书多维表格。端点写死，不走环境变量/配置。
FEEDBACK_API_URL = "https://vc-feedback-backend.weifeng.workers.dev/api/feedback"

# Detect where read-only bundled/source resources live.
_PACKAGE_DIR = Path(__file__).parent
_PROJECT_ROOT = _PACKAGE_DIR.parent
_IS_FROZEN = getattr(sys, "frozen", False)
_PACKAGE_RESOURCE_PATH = _PACKAGE_DIR / "resources"
_SOURCE_RESOURCE_PATH = _PROJECT_ROOT / "resource"

if _IS_FROZEN:
    ROOT_PATH = Path(sys.executable).resolve().parent
    RESOURCE_PATH = Path(getattr(sys, "_MEIPASS")) / "resource"
elif _SOURCE_RESOURCE_PATH.is_dir():
    ROOT_PATH = _PROJECT_ROOT
    RESOURCE_PATH = _SOURCE_RESOURCE_PATH
else:
    # Installed via pip — package resources are copied into videocaptioner/resources.
    ROOT_PATH = user_data_path(APP_NAME)
    RESOURCE_PATH = _PACKAGE_RESOURCE_PATH if _PACKAGE_RESOURCE_PATH.exists() else ROOT_PATH / "resource"

APPDATA_PATH = user_data_path(APP_NAME)
WORK_PATH = Path.home() / APP_NAME

ASSETS_PATH = RESOURCE_PATH / "assets"
# UI 翻译目录（key-based gettext）：{lang}/LC_MESSAGES/videocaptioner.mo。
I18N_PATH = RESOURCE_PATH / "i18n"
BUILTIN_SUBTITLE_STYLE_PATH = RESOURCE_PATH / "subtitle_styles"

# Writable user data. Keep generated/downloaded files out of source trees,
# frozen bundles, and package directories so dev, pip, and desktop builds share
# the same runtime layout.
BIN_PATH = APPDATA_PATH / "bin"
USER_SUBTITLE_STYLE_PATH = APPDATA_PATH / "subtitle_styles"
SUBTITLE_STYLE_PATH = USER_SUBTITLE_STYLE_PATH
FONTS_PATH = RESOURCE_PATH / "fonts"

BUNDLED_BIN_PATH = RESOURCE_PATH / "bin"


def find_binary(name: str, configured: str = "") -> Optional[str]:
    """发现一个随包/可下载的二进制：配置路径 → 自带 bin → 用户 bin → PATH，找不到返回 None。

    ``name`` 不带扩展名（如 ``"ffmpeg"`` / ``"voxgate"``）；Windows 自动补 ``.exe``（已带则不重复
    补）。``configured`` 是设置里用户手动指定的绝对路径（可空，优先级最高）。voxgate / macsysaudio /
    ffmpeg 等都走这里，别再各自重写一份发现逻辑。
    """
    exe = name
    if os.name == "nt" and not name.lower().endswith(".exe"):
        exe = f"{name}.exe"
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(BUNDLED_BIN_PATH / exe)
    candidates.append(BIN_PATH / exe)
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return shutil.which(exe)

LOG_PATH = APPDATA_PATH / "logs"
LLM_LOG_FILE = LOG_PATH / "llm_requests.jsonl"
CACHE_PATH = APPDATA_PATH / "cache"
MODEL_PATH = APPDATA_PATH / "models"

FASTER_WHISPER_PATH = BIN_PATH / "Faster-Whisper-XXL"

# Logging
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Create data directories
for p in [APPDATA_PATH, CACHE_PATH, LOG_PATH, WORK_PATH, MODEL_PATH, BIN_PATH, USER_SUBTITLE_STYLE_PATH]:
    p.mkdir(parents=True, exist_ok=True)

# Add bin paths to PATH. User-downloaded binaries take precedence over bundled
# tools, while packaged ffmpeg still works out of the box.
for _path in [FASTER_WHISPER_PATH, BIN_PATH, BUNDLED_BIN_PATH]:
    if _path.exists():
        os.environ["PATH"] = str(_path) + os.pathsep + os.environ["PATH"]
