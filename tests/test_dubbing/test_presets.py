import pytest

from videocaptioner.core.dubbing.presets import (
    available_dubbing_presets,
    get_dubbing_preset,
    normalize_dubbing_voice,
    validate_dubbing_voice,
)


def test_available_presets_include_main_providers():
    presets = available_dubbing_presets()

    assert "siliconflow-cn-female" in presets
    assert "gemini-en-friendly" in presets


def test_get_dubbing_preset():
    preset = get_dubbing_preset("siliconflow-cn-female")

    assert preset.provider == "siliconflow"
    assert preset.model == "FunAudioLLM/CosyVoice2-0.5B"
    assert preset.voice.endswith(":anna")


def test_get_dubbing_preset_unknown():
    with pytest.raises(ValueError, match="Unknown dubbing preset"):
        get_dubbing_preset("missing")


def test_normalize_siliconflow_short_voice_alias():
    voice = normalize_dubbing_voice("siliconflow", "FunAudioLLM/CosyVoice2-0.5B", "anna")

    assert voice == "FunAudioLLM/CosyVoice2-0.5B:anna"


def test_validate_gemini_unknown_voice():
    error = validate_dubbing_voice("gemini", "not-a-voice")

    assert error is not None
    assert "Unknown Gemini voice" in error
