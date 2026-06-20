"""模型与文件下载基建（纯 Python，无 PyQt 依赖）。

- downloader: 通用单文件下载（镜像兜底 / 断点续传 / 进度回调 / SHA1 校验）
- models: 本地 ASR 模型清单（whisper-cpp / faster-whisper）与安装管理
- net: 在线视频下载的网络环境（代理 / cookies / B 站风控 / 错误翻译）
- source_check: 下载源连通性检查（YouTube / 哔哩哔哩 真实解析）
"""

from videocaptioner.core.download.dependencies import (
    DEPENDENCIES,
    DependencyAsset,
    DependencySpec,
    DependencyUnsupported,
    asset_for,
    current_platform,
    dependency_for,
    install_dependency,
    installed_path,
    is_installed,
    iter_dependencies,
)
from videocaptioner.core.download.downloader import (
    DownloadCancelled,
    DownloadError,
    DownloadProgress,
    download_file,
)
from videocaptioner.core.download.models import (
    FASTER_WHISPER_MODELS,
    WHISPER_CPP_MODELS,
    ModelFile,
    ModelSpec,
    download_model,
    find_model,
    has_partial_download,
    iter_models,
    model_install_state,
    remove_model,
)
from videocaptioner.core.download.net import (
    cookies_file,
    fetch_bilibili_buvid,
    friendly_download_error,
    inject_bilibili_buvid,
    is_bilibili_url,
    system_proxy,
)
from videocaptioner.core.download.programs import (
    ProgramInstallPlan,
    ProgramStatus,
    ProgramVariant,
    detect_program,
    program_install_plan,
    program_variants,
)
from videocaptioner.core.download.source_check import (
    DOWNLOAD_SOURCES,
    DownloadSource,
    SourceCheckResult,
    check_download_source,
    check_download_sources,
)

__all__ = [
    "DOWNLOAD_SOURCES",
    "DownloadCancelled",
    "DownloadError",
    "DownloadProgress",
    "DownloadSource",
    "SourceCheckResult",
    "check_download_source",
    "check_download_sources",
    "cookies_file",
    "download_file",
    "fetch_bilibili_buvid",
    "friendly_download_error",
    "inject_bilibili_buvid",
    "is_bilibili_url",
    "system_proxy",
    "ModelFile",
    "ModelSpec",
    "WHISPER_CPP_MODELS",
    "FASTER_WHISPER_MODELS",
    "find_model",
    "iter_models",
    "model_install_state",
    "has_partial_download",
    "remove_model",
    "download_model",
    "ProgramStatus",
    "ProgramInstallPlan",
    "ProgramVariant",
    "detect_program",
    "program_install_plan",
    "program_variants",
    "DEPENDENCIES",
    "DependencyAsset",
    "DependencySpec",
    "DependencyUnsupported",
    "asset_for",
    "current_platform",
    "dependency_for",
    "install_dependency",
    "installed_path",
    "is_installed",
    "iter_dependencies",
]
