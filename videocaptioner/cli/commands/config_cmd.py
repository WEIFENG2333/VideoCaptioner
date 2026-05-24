"""config command — view, edit, and manage configuration."""

import os
import subprocess
import sys
from argparse import Namespace
from copy import deepcopy

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.config import (
    CONFIG_FILE,
    DEFAULTS,
    _set_nested,
    _write_toml,
    ensure_config_dir,
    format_config,
    get,
    load_config_file,
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
        return _init(args)
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


def _init(args: Namespace) -> int:
    """Create an onboarding config file."""
    config_data = _build_onboarding_config(args)
    template = _render_onboarding_template(config_data)
    if getattr(args, "print_template", False):
        print(template)
        return EXIT.SUCCESS
    if getattr(args, "non_interactive", False):
        return _write_onboarding_config(template, force=getattr(args, "force", False))
    return _interactive_init(args, config_data)


def _interactive_init(args: Namespace, config_data: dict) -> int:
    """Interactive configuration setup."""
    ensure_config_dir()

    if CONFIG_FILE.exists() and not getattr(args, "force", False):
        output.warn(f"Config file already exists: {CONFIG_FILE}")
        output.hint("Use 'videocaptioner config init --force' to overwrite it.")
        output.hint("Use 'videocaptioner config edit' to modify the existing file.")
        return EXIT.USAGE_ERROR

    def _prompt(msg: str, default: str = "") -> str:
        try:
            raw = input(msg).strip()
            return raw or default
        except (EOFError, KeyboardInterrupt):
            print()
            output.hint("Non-interactive mode detected. Use 'videocaptioner config init --non-interactive'.")
            raise

    print("VideoCaptioner Onboarding")
    print("=" * 40)
    print()
    print("Press Enter to keep the shown default. API keys can be skipped and added later.")
    print()

    try:
        _set_nested(config_data, "transcribe.asr", _prompt("ASR engine [bijian]: ", "bijian"))
        _set_nested(config_data, "subtitle.optimize", _yes_no("Enable AI subtitle polish? It fixes obvious ASR errors and punctuation. [Y/n]: ", True))
        _set_nested(config_data, "subtitle.split", _yes_no("Enable subtitle re-segmentation? [Y/n]: ", True))
        translator = _prompt("Translator [bing] (bing/google/llm): ", "bing")
        _set_nested(config_data, "translate.service", translator)
        print()
        print("LLM config is used for AI subtitle polish, LLM translation, and --adapt-length.")
        _set_nested(config_data, "llm.api_key", _prompt("LLM API key [skip]: "))
        _set_nested(config_data, "llm.api_base", _prompt(f"LLM API base [{DEFAULTS['llm']['api_base']}]: ", DEFAULTS["llm"]["api_base"]))
        _set_nested(config_data, "llm.model", _prompt(f"LLM model [{DEFAULTS['llm']['model']}]: ", DEFAULTS["llm"]["model"]))
        print()
        print("Dubbing config is used by 'dub' and 'process --dub-only'.")
        _set_nested(config_data, "dubbing.preset", _prompt("Dubbing preset [siliconflow-cn-female]: ", "siliconflow-cn-female"))
        _set_nested(config_data, "dubbing.api_key", _prompt("TTS API key [skip]: "))
        _set_nested(config_data, "dubbing.voice", _prompt("Default voice [anna]: ", "anna"))
        _set_nested(config_data, "dubbing.timing", _prompt("Timing [balanced] (balanced/strict/natural/none): ", "balanced"))
        _set_nested(config_data, "dubbing.audio_mode", _prompt("Audio mode [replace] (replace/mix/duck): ", "replace"))
    except (EOFError, KeyboardInterrupt):
        return EXIT.USAGE_ERROR

    template = _render_onboarding_template(config_data)
    return _write_onboarding_config(template, force=True)


def _yes_no(prompt: str, default: bool) -> bool:
    raw = input(prompt).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "true", "1"}


def _build_onboarding_config(args: Namespace) -> dict:
    config_data = deepcopy(DEFAULTS)
    profile = getattr(args, "profile", "basic")
    _set_nested(config_data, "translate.service", "bing")
    _set_nested(config_data, "dubbing.preset", "siliconflow-cn-female" if profile == "dubbing" else "")
    _set_nested(config_data, "dubbing.voice", "anna")
    _set_nested(config_data, "dubbing.timing", "balanced")
    _set_nested(config_data, "dubbing.audio_mode", "replace")

    mappings = {
        "llm_api_key": "llm.api_key",
        "llm_api_base": "llm.api_base",
        "llm_model": "llm.model",
        "asr": "transcribe.asr",
        "translator": "translate.service",
        "tts_api_key": "dubbing.api_key",
        "dub_preset": "dubbing.preset",
        "voice": "dubbing.voice",
        "timing": "dubbing.timing",
        "audio_mode": "dubbing.audio_mode",
    }
    for attr, key in mappings.items():
        value = getattr(args, attr, None)
        if value is not None:
            _set_nested(config_data, key, value)
    if getattr(args, "no_optimize", False):
        _set_nested(config_data, "subtitle.optimize", False)
    if getattr(args, "no_split", False):
        _set_nested(config_data, "subtitle.split", False)
    return config_data


def _render_onboarding_template(config_data: dict) -> str:
    """Human-readable, commented TOML template."""
    from io import StringIO

    template_data = _user_facing_config(config_data)
    f = StringIO()
    f.write("# VideoCaptioner configuration\n")
    f.write("# Priority: CLI flags > environment variables > this file > built-in defaults.\n")
    f.write("# Keep API keys private. This file is written with 0600 permissions on Unix.\n\n")
    f.write("# [llm] is used for AI subtitle polish, LLM translation, reflective translation, and dubbing length adaptation.\n")
    f.write("# [whisper_api] is only needed when transcribe.asr = \"whisper-api\".\n")
    f.write("# [transcribe] controls speech-to-text. bijian/jianying need no key; whisper-cpp needs a local binary/model.\n")
    f.write("# [subtitle] split and AI polish use LLM; [translate] can use bing/google/llm.\n")
    f.write("# [synthesize] controls subtitle embedding/burning.\n")
    f.write("# [dubbing] preset selects provider/model/voice defaults; timing controls speech fitting; audio_mode controls original audio.\n\n")
    _write_toml(f, template_data)
    f.write("\n# Optional multi-speaker example:\n")
    f.write("# [dubbing.speakers.Alice]\n# voice = \"anna\"\n# [dubbing.speakers.Bob]\n# voice = \"benjamin\"\n# clone_audio = \"bob-reference.wav\"\n# clone_text = \"Exact words spoken in the reference audio.\"\n\n")
    return f.getvalue()


def _user_facing_config(config_data: dict) -> dict:
    """Keep onboarding config focused on settings users actually choose."""
    return {
        "llm": {
            "api_key": config_data["llm"]["api_key"],
            "api_base": config_data["llm"]["api_base"],
            "model": config_data["llm"]["model"],
        },
        "whisper_api": {
            "api_key": config_data["whisper_api"]["api_key"],
            "api_base": config_data["whisper_api"]["api_base"],
            "model": config_data["whisper_api"]["model"],
        },
        "transcribe": {
            "asr": config_data["transcribe"]["asr"],
        },
        "subtitle": {
            "optimize": config_data["subtitle"]["optimize"],
            "split": config_data["subtitle"]["split"],
            "thread_num": config_data["subtitle"]["thread_num"],
            "batch_size": config_data["subtitle"]["batch_size"],
        },
        "translate": {
            "service": config_data["translate"]["service"],
            "reflect": config_data["translate"]["reflect"],
        },
        "synthesize": {
            "subtitle_mode": config_data["synthesize"]["subtitle_mode"],
            "quality": config_data["synthesize"]["quality"],
            "layout": config_data["synthesize"]["layout"],
            "style": config_data["synthesize"]["style"],
        },
        "dubbing": {
            "preset": config_data["dubbing"]["preset"],
            "api_key": config_data["dubbing"]["api_key"],
            "voice": config_data["dubbing"]["voice"],
            "tts_workers": config_data["dubbing"]["tts_workers"],
            "timing": config_data["dubbing"]["timing"],
            "audio_mode": config_data["dubbing"]["audio_mode"],
            "rewrite_too_long": config_data["dubbing"]["rewrite_too_long"],
        },
        "output": config_data["output"],
    }


def _write_onboarding_config(template: str, *, force: bool) -> int:
    ensure_config_dir()
    if CONFIG_FILE.exists() and not force:
        output.warn(f"Config file already exists: {CONFIG_FILE}")
        output.hint("Use --force to overwrite, or 'videocaptioner config edit' to modify it.")
        return EXIT.USAGE_ERROR
    CONFIG_FILE.write_text(template, encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    # Validate parseability before reporting success.
    load_config_file(CONFIG_FILE)
    output.success(f"Configuration saved to {CONFIG_FILE}")
    output.hint("Run 'videocaptioner doctor' to check dependencies and missing keys.")
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
