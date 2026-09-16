"""CLI surface tests for MiniMax ASR."""

from videocaptioner.cli.commands.doctor import _check_transcribe
from videocaptioner.cli.config import DEFAULTS, ENV_MAP
from videocaptioner.cli.main import build_parser


def test_transcribe_parser_accepts_minimax_options():
    args = build_parser().parse_args(
        [
            "transcribe",
            "sample.wav",
            "--asr",
            "minimax",
            "--minimax-api-key",
            "[REDACTED_SECRET]",
            "--minimax-api-base",
            "https://api.minimaxi.com/v1",
            "--minimax-model",
            "asr-1.0",
        ]
    )

    assert args.asr == "minimax"
    assert args.minimax_api_key == "[REDACTED_SECRET]"
    assert args.minimax_api_base == "https://api.minimaxi.com/v1"
    assert args.minimax_model == "asr-1.0"


def test_process_parser_accepts_minimax():
    args = build_parser().parse_args(["process", "sample.mp4", "--asr", "minimax"])
    assert args.asr == "minimax"


def test_minimax_defaults_and_environment_mapping_exist():
    assert DEFAULTS["minimax_api"] == {
        "api_key": "",
        "api_base": "https://api.minimaxi.com/v1",
        "model": "asr-1.0",
    }
    assert ENV_MAP["VIDEOCAPTIONER_MINIMAX_API_KEY"] == "minimax_api.api_key"
    assert ENV_MAP["VIDEOCAPTIONER_MINIMAX_API_BASE"] == "minimax_api.api_base"
    assert ENV_MAP["VIDEOCAPTIONER_MINIMAX_MODEL"] == "minimax_api.model"


def test_doctor_reports_missing_minimax_key():
    config = {
        "transcribe": {"asr": "minimax"},
        "minimax_api": {"api_key": ""},
    }
    checks = _check_transcribe(config)
    assert any(c.name == "minimax_api.api_key" and c.status == "error" for c in checks)


def test_doctor_accepts_configured_minimax_key():
    config = {
        "transcribe": {"asr": "minimax"},
        "minimax_api": {"api_key": "configured"},
    }
    checks = _check_transcribe(config)
    assert not any(c.name == "minimax_api.api_key" and c.status == "error" for c in checks)
