import importlib.util

from videocaptioner.core.entities import TranscribeModelEnum
from videocaptioner.core.utils import platform_utils


def test_sensevoice_is_hidden_when_runtime_is_incomplete(monkeypatch):
    monkeypatch.setattr(platform_utils, "is_macos", lambda: False)
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: object() if name in {"funasr", "torch"} else None,
    )

    assert TranscribeModelEnum.SENSEVOICE not in platform_utils.get_available_transcribe_models()
    assert platform_utils.is_model_available(TranscribeModelEnum.SENSEVOICE) is False


def test_sensevoice_is_available_when_runtime_is_complete(monkeypatch):
    monkeypatch.setattr(platform_utils, "is_macos", lambda: False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    assert TranscribeModelEnum.SENSEVOICE in platform_utils.get_available_transcribe_models()
    assert platform_utils.is_model_available(TranscribeModelEnum.SENSEVOICE) is True
