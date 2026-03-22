"""CLI configuration management.

Config priority (highest to lowest):
  1. Command-line arguments
  2. Environment variables (VIDEOCAPTIONER_*)
  3. User config file (~/.config/videocaptioner/config.toml)
  4. Built-in defaults
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from platformdirs import user_config_dir

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

APP_NAME = "videocaptioner"

# Default config directory
CONFIG_DIR = Path(user_config_dir(APP_NAME))
CONFIG_FILE = CONFIG_DIR / "config.toml"

# Environment variable prefix
ENV_PREFIX = "VIDEOCAPTIONER_"

# Flat env var → nested TOML key mapping
ENV_MAP: Dict[str, str] = {
    "LLM_API_KEY": "llm.api_key",
    "LLM_API_BASE": "llm.api_base",
    "LLM_MODEL": "llm.model",
    "WHISPER_API_KEY": "whisper_api.api_key",
    "WHISPER_API_BASE": "whisper_api.api_base",
    "DEEPLX_ENDPOINT": "translate.deeplx_endpoint",
    "TARGET_LANG": "translate.target_language",
}

DEFAULTS: Dict[str, Any] = {
    "llm": {
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "whisper_api": {
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "whisper-1",
        "prompt": "",
    },
    "transcribe": {
        "asr": "faster-whisper",
        "language": "auto",
        "faster_whisper": {
            "model": "large-v3",
            "device": "auto",
            "vad_filter": True,
            "vad_method": "silero-v4-fw",
            "vad_threshold": 0.5,
            "voice_extraction": False,
            "prompt": "",
        },
        "whisper_cpp": {
            "model": "large-v2",
        },
    },
    "subtitle": {
        "optimize": True,
        "translate": False,
        "split": True,
        "max_word_count_cjk": 18,
        "max_word_count_english": 12,
        "thread_num": 4,
        "batch_size": 10,
    },
    "translate": {
        "service": "llm",
        "target_language": "zh-Hans",
        "reflect": False,
        "deeplx_endpoint": "",
    },
    "synthesize": {
        "subtitle_mode": "soft",
        "quality": "medium",
        "layout": "target-above",
        "style": "default",
    },
    "output": {
        "format": "srt",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _set_nested(d: dict, dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using dotted key notation (e.g. 'llm.api_key')."""
    keys = dotted_key.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _get_nested(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Get a value from a nested dict using dotted key notation."""
    keys = dotted_key.split(".")
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)  # type: ignore[assignment]
        if d is default:
            return default
    return d


def load_config_file(path: Optional[Path] = None) -> dict:
    """Load and parse a TOML config file. Returns empty dict if file doesn't exist."""
    path = path or CONFIG_FILE
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        import sys
        print(f"! Warning: Failed to parse config file {path}: {e}", file=sys.stderr)
        print("  Run 'videocaptioner config init' to recreate it.", file=sys.stderr)
        return {}


def load_env_overrides() -> dict:
    """Read VIDEOCAPTIONER_* environment variables and map them to config keys."""
    overrides: Dict[str, Any] = {}
    for env_suffix, dotted_key in ENV_MAP.items():
        env_var = ENV_PREFIX + env_suffix
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(overrides, dotted_key, value)
    return overrides


def build_config(
    cli_overrides: Optional[dict] = None,
    config_path: Optional[Path] = None,
) -> dict:
    """Build final config by merging all sources (priority: cli > env > file > defaults)."""
    config = DEFAULTS.copy()
    # Layer 1: config file
    file_config = load_config_file(config_path)
    config = _deep_merge(config, file_config)
    # Layer 2: environment variables
    env_config = load_env_overrides()
    config = _deep_merge(config, env_config)
    # Layer 3: CLI argument overrides
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)
    return config


def get(config: dict, key: str, default: Any = None) -> Any:
    """Convenience accessor for dotted keys."""
    return _get_nested(config, key, default)


def ensure_config_dir() -> Path:
    """Ensure the config directory exists and return its path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def _parse_value(raw: str, key: str) -> Any:
    """Parse a string value into the correct Python type based on DEFAULTS."""
    # Infer type from defaults
    default_val = _get_nested(DEFAULTS, key)
    if isinstance(default_val, bool):
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Expected boolean for '{key}', got '{raw}' (use true/false)")
    if isinstance(default_val, int):
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"Expected integer for '{key}', got '{raw}'")
    if isinstance(default_val, float):
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"Expected number for '{key}', got '{raw}'")
    return raw


def save_config_value(key: str, value: str, config_path: Optional[Path] = None) -> None:
    """Set a single value in the config file. Creates the file if it doesn't exist."""
    path = config_path or CONFIG_FILE
    ensure_config_dir()

    existing = load_config_file(path)
    _set_nested(existing, key, _parse_value(value, key))

    with open(path, "w", encoding="utf-8") as f:
        _write_toml(f, existing)
    # Restrict permissions — config may contain API keys
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_toml(f, data: dict, parent_key: str = "") -> None:
    """Write a dict as valid TOML, handling arbitrary nesting depth."""
    # Write scalar values at this level first
    for key, value in data.items():
        if not isinstance(value, dict):
            f.write(f"{key} = {_toml_value(value)}\n")

    # Write sub-tables recursively
    for key, value in data.items():
        if isinstance(value, dict):
            full_key = f"{parent_key}.{key}" if parent_key else key
            f.write(f"\n[{full_key}]\n")
            _write_toml(f, value, full_key)


def _toml_value(value: Any) -> str:
    """Convert a Python value to TOML representation."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = (value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t"))
        return f'"{escaped}"'
    return f'"{value!s}"'


def format_config(config: dict, indent: int = 0) -> str:
    """Format config dict for display."""
    lines = []
    prefix = "  " * indent
    for key, value in config.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(format_config(value, indent + 1))
        elif isinstance(value, str) and ("key" in key or "token" in key) and value:
            # Mask sensitive values
            masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
            lines.append(f"{prefix}{key} = {masked}")
        else:
            lines.append(f"{prefix}{key} = {value}")
    return "\n".join(lines)
