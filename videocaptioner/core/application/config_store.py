"""Shared TOML configuration store used by CLI and desktop UI."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

from videocaptioner.config import APPDATA_PATH

_DEFAULT_CONFIG_FILE = APPDATA_PATH / "config.toml"
CONFIG_FILE = Path(os.environ.get("VIDEOCAPTIONER_CONFIG_FILE", str(_DEFAULT_CONFIG_FILE)))
CONFIG_DIR = CONFIG_FILE.parent

ENV_MAP: Dict[str, str] = {
    "OPENAI_API_KEY": "llm.providers.openai.api_key",
    "OPENAI_BASE_URL": "llm.providers.openai.api_base",
    "OPENAI_MODEL": "llm.providers.openai.model",
    "VIDEOCAPTIONER_LLM_SERVICE": "llm.service",
    "VIDEOCAPTIONER_LLM_API_KEY": "llm.api_key",
    "VIDEOCAPTIONER_LLM_API_BASE": "llm.api_base",
    "VIDEOCAPTIONER_LLM_MODEL": "llm.model",
    "VIDEOCAPTIONER_WHISPER_API_KEY": "whisper_api.api_key",
    "VIDEOCAPTIONER_WHISPER_API_BASE": "whisper_api.api_base",
    "DASHSCOPE_API_KEY": "fun_asr.api_key",
    "BAILIAN_ASR_API_KEY": "fun_asr.api_key",
    "VIDEOCAPTIONER_FUN_ASR_API_KEY": "fun_asr.api_key",
    "VIDEOCAPTIONER_FUN_ASR_API_BASE": "fun_asr.api_base",
    "VIDEOCAPTIONER_FUN_ASR_MODEL": "fun_asr.model",
    "VIDEOCAPTIONER_DEEPLX_ENDPOINT": "translate.deeplx_endpoint",
    "VIDEOCAPTIONER_TARGET_LANG": "translate.target_language",
    "VIDEOCAPTIONER_DUBBING_PROVIDER": "dubbing.provider",
    "VIDEOCAPTIONER_DUB_PRESET": "dubbing.preset",
    "VIDEOCAPTIONER_TTS_API_KEY": "dubbing.api_key",
    "VIDEOCAPTIONER_TTS_API_BASE": "dubbing.api_base",
    "VIDEOCAPTIONER_TTS_MODEL": "dubbing.model",
    "VIDEOCAPTIONER_TTS_VOICE": "dubbing.voice",
    "VIDEOCAPTIONER_TTS_STYLE_PROMPT": "dubbing.style_prompt",
    "VIDEOCAPTIONER_TTS_WORKERS": "dubbing.tts_workers",
    "VIDEOCAPTIONER_TTS_USE_CACHE": "dubbing.use_cache",
    "VIDEOCAPTIONER_TTS_FIT_MODE": "dubbing.fit_mode",
    "VIDEOCAPTIONER_DUB_TIMING": "dubbing.timing",
    "VIDEOCAPTIONER_DUB_AUDIO_MODE": "dubbing.audio_mode",
    "VIDEOCAPTIONER_TTS_MAX_SPEED": "dubbing.max_speed",
    "VIDEOCAPTIONER_TTS_REWRITE_TOO_LONG": "dubbing.rewrite_too_long",
    "VIDEOCAPTIONER_TTS_MIX_ORIGINAL_AUDIO": "dubbing.mix_original_audio",
}

DEFAULTS: Dict[str, Any] = {
    "app": {
        "work_dir": "",
        "cache_enabled": True,
        # 流水线成功后保留任务目录（中间产物）；默认跑完即清。
        "keep_intermediates": False,
    },
    "ui": {
        "theme_mode": "Dark",
        "theme_color": "#ff00e889",
        "dpi_scale": "Auto",
        "language": "Auto",
        "mica_enabled": False,
        "check_update_at_startup": True,
        "subtitle_preview_image": "",
        # 字幕样式预览的自定义示例文字（原文/译文）与调色板最近用色：UI 持久化偏好，
        # 必须进 DEFAULTS + 绑定，否则 cfg.set(save=True) 是空操作、重启即丢。
        "subtitle_preview_source": (
            "Mathematics is the language in which the laws of the universe are written."
        ),
        "subtitle_preview_target": "数学，是书写宇宙规律的语言。",
        "recent_colors": [],
        # 工作台右栏折叠态 + 批量页模式/并发：UI 持久化键，过去漏在 DEFAULTS 外，
        # 导致 `config set` 因 parse_value 查不到键而按字符串存（bool 反向、范围抛错）。
        "transcribe_panel_collapsed": False,
        "subtitle_panel_collapsed": False,
        "synthesis_panel_collapsed": False,
        "batch_mode": "full",
        "batch_concurrency": 1,
    },
    "feedback": {
        # 匿名设备 ID：首次提交反馈时生成并持久化，供后端去重/跟进，非个人信息。
        "client_id": "",
    },
    "llm": {
        "service": "openai",
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "providers": {
            "openai": {
                "api_key": "",
                "api_base": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "model_options": [],
            },
            "silicon_cloud": {
                "api_key": "",
                "api_base": "https://api.siliconflow.cn/v1",
                "model": "gpt-4o-mini",
                "model_options": [],
            },
            "deepseek": {
                "api_key": "",
                "api_base": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "model_options": [],
            },
            "ollama": {
                "api_key": "ollama",
                "api_base": "http://localhost:11434/v1",
                "model": "llama2",
                "model_options": [],
            },
            "lm_studio": {
                "api_key": "lmstudio",
                "api_base": "http://localhost:1234/v1",
                "model": "qwen2.5:7b",
                "model_options": [],
            },
            "gemini": {
                "api_key": "",
                "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "model": "gemini-pro",
                "model_options": [],
            },
            "chatglm": {
                "api_key": "",
                "api_base": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4",
                "model_options": [],
            },
        },
    },
    "whisper_api": {
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "whisper-1",
        "prompt": "",
    },
    "fun_asr": {
        "api_key": "",
        "api_base": "https://dashscope.aliyuncs.com",
        "model": "fun-asr",
    },
    "transcribe": {
        "asr": "bijian",
        "language": "auto",
        "output_format": "srt",
        "word_timestamp": False,
        "faster_whisper": {
            "program": "faster-whisper-xxl.exe",
            "model": "tiny",
            "model_dir": "",
            "device": "auto",
            "vad_filter": True,
            "vad_method": "silero_v4",
            "vad_threshold": 0.4,
            "voice_extraction": False,
            "one_word": True,
            "prompt": "",
        },
        "whisper_cpp": {
            "model": "tiny",
        },
    },
    "subtitle": {
        "optimize": False,
        "translate": False,
        "split": False,
        "max_word_count_cjk": 28,
        "max_word_count_english": 20,
        "thread_num": 10,
        "batch_size": 10,
        "custom_prompt": "",
    },
    "translate": {
        "service": "bing",
        "target_language": "zh-Hans",
        "reflect": False,
        "deeplx_endpoint": "",
    },
    "synthesize": {
        "need_video": True,
        # subtitle_mode 与 soft_subtitle 必须同义：硬字幕。过去 subtitle_mode="soft"
        # 而 soft_subtitle=False，导致 CLI(读 subtitle_mode) 默认软、GUI(读 soft_subtitle)
        # 默认硬，同一份全新配置出厂行为相反。
        "subtitle_mode": "hard",
        "quality": "medium",
        "layout": "target-above",
        "render_mode": "rounded",
        "style": "rounded/default",
        "soft_subtitle": False,
    },
    "dubbing": {
        "enabled": False,
        "provider": "edge",
        "preset": "edge-cn-female",
        "api_key": "",
        "api_base": "",
        "model": "edge-tts",
        "voice": "zh-CN-XiaoxiaoNeural",
        "text_track": "auto",
        "clone_audio": "",
        "clone_text": "",
        "response_format": "mp3",
        "sample_rate": 32000,
        "speed": 1.0,
        "gain": 0,
        "tts_workers": 5,
        "use_cache": True,
        "style_prompt": "",
        "timing": "balanced",
        "audio_mode": "replace",
        "fit_mode": "tempo",
        "max_speed": 2.0,
        "target_padding_ms": 80,
        "rewrite_too_long": False,
        "rewrite_threshold": 1.15,
        "mix_original_audio": False,
        "original_audio_volume": 0.25,
        "dubbed_audio_volume": 1.0,
    },
    "live_caption": {
        "backend": "voxgate",
        "fun_asr_model": "fun-asr-mtl-realtime",
        "source_language": "auto",
        "voxgate_binary": "",
        "show_overlay": True,
        "source": "microphone",
        "device_index": -1,
        "translate_enabled": True,
        "translator_service": "bing",
        "target_language": "简体中文",
        "display_mode": "bilingual",
        "bg_style": "translucent",
        "font_scale": 60,
        "auto_fade": True,
    },
    "output": {
        "format": "srt",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def set_nested(data: dict, dotted_key: str, value: Any) -> None:
    keys = dotted_key.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def get_nested(data: dict, dotted_key: str, default: Any = None) -> Any:
    keys = dotted_key.split(".")
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, default)  # type: ignore[assignment]
        if data is default:
            return default
    return data


def load_config_file(path: Optional[Path] = None) -> dict:
    path = path or CONFIG_FILE
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        print(f"! Warning: Failed to parse config file {path}: {exc}", file=sys.stderr)
        print("  Run 'videocaptioner config init' to recreate it.", file=sys.stderr)
        return {}


def load_env_overrides() -> dict:
    overrides: Dict[str, Any] = {}
    for env_var, dotted_key in ENV_MAP.items():
        value = os.environ.get(env_var)
        if value is None:
            continue
        if is_secret_key(dotted_key):
            value = value.strip()
        try:
            parsed_value = parse_value(value, dotted_key)
        except ValueError as exc:
            print(f"! Warning: Invalid environment value {env_var}: {exc}", file=sys.stderr)
            continue
        set_nested(overrides, dotted_key, parsed_value)
    return overrides


def build_config(
    cli_overrides: Optional[dict] = None,
    config_path: Optional[Path] = None,
) -> dict:
    config = deepcopy(DEFAULTS)
    config = deep_merge(config, load_config_file(config_path))
    config = deep_merge(config, load_env_overrides())
    if cli_overrides:
        config = deep_merge(config, cli_overrides)
    normalize_active_aliases(config)
    return config


def get(config: dict, key: str, default: Any = None) -> Any:
    return get_nested(config, key, default)


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def parse_value(raw: str, key: str) -> Any:
    default_val = get_nested(DEFAULTS, key)
    if isinstance(default_val, bool):
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Expected boolean for '{key}', got '{raw}' (use true/false)")
    if isinstance(default_val, int):
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Expected integer for '{key}', got '{raw}'") from exc
    if isinstance(default_val, float):
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"Expected number for '{key}', got '{raw}'") from exc
    if isinstance(default_val, list):
        raw = raw.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = tomllib.loads(f"value = {raw}")["value"]
            except Exception as exc:
                raise ValueError(f"Expected TOML array for '{key}', got '{raw}'") from exc
            if not isinstance(parsed, list):
                raise ValueError(f"Expected TOML array for '{key}', got '{raw}'")
            return parsed
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def save_config_value(key: str, value: str, config_path: Optional[Path] = None) -> None:
    path = config_path or CONFIG_FILE
    ensure_config_dir()
    existing = load_config_file(path)
    if is_secret_key(key):
        value = value.strip()
    set_nested(existing, key, parse_value(value, key))
    sync_aliases_for_saved_key(existing, key)
    write_config_file(existing, path)


def save_many(values: dict[str, Any], config_path: Optional[Path] = None) -> None:
    path = config_path or CONFIG_FILE
    ensure_config_dir()
    existing = load_config_file(path)
    for key, value in values.items():
        if is_secret_key(key) and isinstance(value, str):
            value = value.strip()
        set_nested(existing, key, value)
    normalize_active_aliases(existing)
    write_config_file(existing, path)


def normalize_active_aliases(config: dict) -> None:
    """Keep generic LLM fields aligned with the selected provider.

    Provider sections are the canonical storage for per-provider credentials.
    The generic `llm.api_key/api_base/model` fields remain as a runtime alias
    for the currently selected provider because older execution paths and CLI
    flags still use those keys.
    """
    service = str(get_nested(config, "llm.service", "openai") or "openai")
    providers = get_nested(config, "llm.providers", {})
    if not isinstance(providers, dict):
        providers = {}
        set_nested(config, "llm.providers", providers)

    provider = providers.setdefault(service, {})
    if not isinstance(provider, dict):
        provider = {}
        providers[service] = provider

    for field in ("api_key", "api_base", "model"):
        provider_value = provider.get(field)
        generic_value = get_nested(config, f"llm.{field}", "")
        generic_default = DEFAULTS["llm"].get(field)
        provider_default = DEFAULTS["llm"].get("providers", {}).get(service, {}).get(field)
        generic_is_explicit = generic_value not in (None, "") and generic_value != generic_default
        provider_is_explicit = (
            provider_value not in (None, "") and provider_value != provider_default
        )

        if provider_is_explicit:
            set_nested(config, f"llm.{field}", provider_value)
        elif generic_is_explicit:
            provider[field] = generic_value
        elif provider_value not in (None, ""):
            set_nested(config, f"llm.{field}", provider_value)
        elif generic_value not in (None, ""):
            provider[field] = generic_value


def sync_aliases_for_saved_key(config: dict, changed_key: str) -> None:
    """Synchronize LLM aliases after a single `config set` operation."""
    merged = deepcopy(DEFAULTS)
    merged = deep_merge(merged, config)
    active_provider = str(get_nested(merged, "llm.service", "openai") or "openai")

    parts = changed_key.split(".")
    if changed_key == "llm.service":
        normalize_active_aliases(merged)
        for field in ("api_key", "api_base", "model"):
            value = get_nested(merged, f"llm.{field}", "")
            set_nested(config, f"llm.{field}", value)
        return

    if len(parts) == 4 and parts[:2] == ["llm", "providers"]:
        provider, field = parts[2], parts[3]
        if provider == active_provider and field in {"api_key", "api_base", "model"}:
            set_nested(config, f"llm.{field}", get_nested(config, changed_key, ""))
        return

    if len(parts) == 2 and parts[0] == "llm" and parts[1] in {"api_key", "api_base", "model"}:
        set_nested(config, f"llm.providers.{active_provider}.{parts[1]}", get_nested(config, changed_key, ""))


def write_config_file(data: dict, path: Optional[Path] = None) -> None:
    path = path or CONFIG_FILE
    ensure_config_dir()
    with open(path, "w", encoding="utf-8") as f:
        write_toml(f, data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_toml(f, data: dict, parent_key: str = "") -> None:
    for key, value in data.items():
        if not isinstance(value, dict):
            f.write(f"{key} = {toml_value(value)}\n")
    for key, value in data.items():
        if isinstance(value, dict):
            full_key = f"{parent_key}.{key}" if parent_key else key
            f.write(f"\n[{full_key}]\n")
            write_toml(f, value, full_key)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return f'"{value!s}"'


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def format_config(config: dict, indent: int = 0) -> str:
    lines = []
    prefix = "  " * indent
    for key, value in config.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(format_config(value, indent + 1))
        elif isinstance(value, str) and ("key" in key or "token" in key) and value:
            masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
            lines.append(f"{prefix}{key} = {masked}")
        else:
            lines.append(f"{prefix}{key} = {value}")
    return "\n".join(lines)


def is_secret_key(key: str) -> bool:
    leaf = key.rsplit(".", 1)[-1].lower()
    return "key" in leaf or leaf.endswith("token") or leaf.endswith("secret")
