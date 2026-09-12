"""采集环境诊断（绝无密钥）+ 匿名 client_id。无 PyQt。

诊断只读一个**非敏感 key 白名单**（provider/语言名称等），绝不读 `*.api_key` / `*.api_base`；
再过一道 `_is_safe` 兜底，凡像密钥/URL/token 的值一律丢弃。对齐项目「发送前剥离密钥」硬规则。
"""

from __future__ import annotations

import platform as _platform
import sys
import uuid

from videocaptioner import config
from videocaptioner.config import APPDATA_PATH
from videocaptioner.core.application import config_store
from videocaptioner.core.download.dependencies import current_platform

# 匿名设备 ID 存独立文件（不进配置文件）：一行 UUID，丢了重生成即可。
_CLIENT_ID_FILE = APPDATA_PATH / "feedback_client_id"

# 只采集这些非敏感字段（值是 provider/语言名称，不是凭据）。
_DIAG_KEYS = {
    "llm_service": "llm.service",
    "llm_model": "llm.model",
    "translate_service": "translate.service",
    "translate_target": "translate.target_language",
    "dubbing_provider": "dubbing.provider",
}

# 兜底：值里出现这些片段视为疑似敏感，丢弃不发（白名单已保证安全，这是双保险）。
_SECRET_MARKERS = ("key", "token", "secret", "sk-", "bearer", "://", "password")


def _is_safe(value: str) -> bool:
    low = value.lower()
    return not any(marker in low for marker in _SECRET_MARKERS) and len(value) <= 64


def platform_tag() -> str:
    """X-App-Platform：收敛到契约枚举 windows-x64 / macos-x64 / macos-arm64
    （current_platform() 的 dev linux-x64 / windows-arm64 不在枚举内，归入最近发行值）。"""
    os_key, arch = current_platform()
    tag = f"{os_key}-{arch}"
    if tag in ("windows-x64", "macos-x64", "macos-arm64"):
        return tag
    return "macos-x64" if os_key == "macos" else "windows-x64"


def get_or_create_client_id() -> str:
    """本机匿名设备 ID（首次生成并持久化到独立文件，不入配置文件）。"""
    try:
        cid = _CLIENT_ID_FILE.read_text(encoding="utf-8").strip()
        if cid:
            return cid
    except OSError:
        pass
    cid = str(uuid.uuid4())
    try:
        _CLIENT_ID_FILE.write_text(cid, encoding="utf-8")
    except OSError:  # 落盘失败不该挡住反馈，用临时 ID 继续
        pass
    return cid


def gather_diagnostics() -> dict:
    """组装随反馈一起发送的环境信息（默认附带，无 UI 开关）。绝不含密钥。"""
    diag: dict[str, object] = {
        "app_version": config.VERSION,
        "platform": platform_tag(),
        "os": _platform.platform(),
        "python": _platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "ffmpeg": "ok" if config.find_binary("ffmpeg") else "missing",
    }
    cfg = config_store.load_config_file()
    language = str(config_store.get_nested(cfg, "ui.language", "") or "")
    if language:
        diag["language"] = language
    for label, key in _DIAG_KEYS.items():
        value = config_store.get_nested(cfg, key, "")
        if isinstance(value, str) and value and _is_safe(value):
            diag[label] = value
    return diag
