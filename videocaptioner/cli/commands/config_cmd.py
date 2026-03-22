"""config command — view, edit, and manage configuration."""

import os
import subprocess
import sys
from argparse import Namespace

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import (
    CONFIG_FILE,
    DEFAULTS,
    ensure_config_dir,
    format_config,
    get,
    save_config_value,
)


def run(args: Namespace, config: dict) -> int:
    action = getattr(args, "config_action", None)

    if action == "show":
        return _show(config)
    elif action == "path":
        return _path()
    elif action == "set":
        return _set(args.key, args.value)
    elif action == "get":
        return _get(args.key, config)
    elif action == "init":
        return _init()
    elif action == "edit":
        return _edit()
    else:
        print("Usage: videocaptioner config <show|set|get|path|init|edit>")
        return EXIT.USAGE_ERROR


def _show(config: dict) -> int:
    print(format_config(config))
    return EXIT.SUCCESS


def _path() -> int:
    print(CONFIG_FILE)
    exists = CONFIG_FILE.exists()
    if not exists:
        output.hint("File does not exist yet. Run 'videocaptioner config init' to create it.")
    return EXIT.SUCCESS


def _set(key: str, value: str) -> int:
    # Validate key exists and is a leaf value (not a section)
    default_val = get(DEFAULTS, key)
    if default_val is None:
        output.error(f"Unknown config key: {key}")
        output.hint("Run 'videocaptioner config show' to see available keys.")
        return EXIT.GENERAL_ERROR
    if isinstance(default_val, dict):
        output.error(f"'{key}' is a config section, not a single value. Use a full key like '{key}.<subkey>'")
        return EXIT.GENERAL_ERROR
    try:
        save_config_value(key, value)
    except ValueError as e:
        output.error(str(e))
        return EXIT.GENERAL_ERROR
    # Mask sensitive values in success message
    display = f"{value[:4]}...{value[-4:]}" if ("key" in key) and len(value) > 8 else value
    output.success(f"{key} = {display}")
    return EXIT.SUCCESS


def _get(key: str, config: dict) -> int:
    value = get(config, key)
    if value is None:
        output.error(f"Key not found: {key}")
        output.hint("Run 'videocaptioner config show' to see available keys.")
        return EXIT.GENERAL_ERROR
    if isinstance(value, dict):
        print(format_config(value))
    elif isinstance(value, str) and ("key" in key or "token" in key) and value:
        masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
        print(masked)
    else:
        print(value)
    return EXIT.SUCCESS


def _init() -> int:
    """Interactive configuration setup."""
    ensure_config_dir()

    def _prompt(msg: str) -> str:
        try:
            return input(msg).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            output.hint("Non-interactive mode. Use 'videocaptioner config set <key> <value>' instead.")
            return ""

    print("VideoCaptioner Configuration Setup")
    print("=" * 40)
    print()

    print("LLM Configuration (required for subtitle optimization and LLM translation)")
    api_key = _prompt("  LLM API Key [skip]: ")
    if api_key:
        save_config_value("llm.api_key", api_key)

    api_base = _prompt(f"  LLM API Base URL [{DEFAULTS['llm']['api_base']}]: ")
    if api_base:
        save_config_value("llm.api_base", api_base)

    model = _prompt(f"  LLM Model [{DEFAULTS['llm']['model']}]: ")
    if model:
        save_config_value("llm.model", model)

    print()
    print("Whisper API Configuration (only needed for --asr whisper-api)")
    whisper_key = _prompt("  Whisper API Key [skip]: ")
    if whisper_key:
        save_config_value("whisper_api.api_key", whisper_key)

    print()
    output.success(f"Configuration saved to {CONFIG_FILE}")
    return EXIT.SUCCESS


def _edit() -> int:
    """Open config file in $EDITOR."""
    if not CONFIG_FILE.exists():
        ensure_config_dir()
        # Create with defaults
        from videocaptioner.cli.config import _write_toml
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            _write_toml(f, DEFAULTS)
        output.info(f"Created default config at {CONFIG_FILE}")

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
    if not editor:
        if sys.platform == "darwin":
            editor = "open"
        elif sys.platform == "win32":
            editor = "notepad"
        else:
            editor = "vi"

    subprocess.run([editor, str(CONFIG_FILE)])
    return EXIT.SUCCESS
