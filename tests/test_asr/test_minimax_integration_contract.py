"""MiniMax provider wiring tests."""

from videocaptioner.core.entities import (
    TranscribeConfig,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    get_asr_language_capability,
)


def test_minimax_enum_and_factory_policy(tmp_path):
    from videocaptioner.core.asr.minimax_api import MiniMaxASR
    from videocaptioner.core.asr.transcribe import _create_asr_instance

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"ID3-test")
    config = TranscribeConfig(
        transcribe_model=TranscribeModelEnum.MINIMAX_API,
        minimax_api_key="[REDACTED_SECRET]",
        minimax_api_base="https://api.minimaxi.com/v1",
        minimax_api_model="asr-1.0",
        transcribe_language="zh",
    )

    chunked = _create_asr_instance(str(audio_path), config)

    assert chunked.asr_class is MiniMaxASR
    assert chunked.chunk_concurrency == 1
    assert chunked.chunk_length_ms <= 480 * 1000
    assert chunked.asr_kwargs["model"] == "asr-1.0"
    assert chunked.asr_kwargs["language"] == "zh"


def test_minimax_config_is_masked_in_print_config():
    config = TranscribeConfig(
        transcribe_model=TranscribeModelEnum.MINIMAX_API,
        minimax_api_key="[REDACTED_SECRET]",
        minimax_api_base="https://api.minimaxi.com/v1",
        minimax_api_model="asr-1.0",
    )

    rendered = config.print_config()
    assert "MiniMax" in rendered
    assert "[REDACTED_SECRET]" not in rendered
    assert "asr-1.0" in rendered


def test_minimax_gui_language_capability_matches_provider_contract():
    capability = get_asr_language_capability(TranscribeModelEnum.MINIMAX_API)

    assert capability.supports_auto is True
    assert TranscribeLanguageEnum.YUE in capability.supported_languages
    assert TranscribeLanguageEnum.FILIPINO in capability.supported_languages
    assert TranscribeLanguageEnum.UKRAINIAN in capability.supported_languages
    assert TranscribeLanguageEnum.HINDI not in capability.supported_languages
