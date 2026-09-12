"""Translation-service connectivity check contracts (no live network)."""

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.entities import SubtitleConfig, TranslatorServiceEnum
from videocaptioner.core.translate.check import check_translation
from videocaptioner.core.translate.types import TargetLanguage, TranslatorType


class _FakeTranslator:
    def __init__(self, translated_text="测试译文", last_error=""):
        self.translated_text = translated_text
        self.last_error = last_error
        self.sources = []
        self.stopped = False

    def translate_subtitle(self, data: ASRData) -> ASRData:
        self.sources.append(data.segments[0].text)
        data.segments[0].translated_text = self.translated_text
        return data

    def stop(self):
        self.stopped = True


def _config(service, **kwargs):
    return SubtitleConfig(
        translator_service=service,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        **kwargs,
    )


def test_check_runs_real_factory_path_and_stops_translator(monkeypatch):
    fake = _FakeTranslator()
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(
        "videocaptioner.core.translate.check.TranslatorFactory.create_translator", create
    )
    result = check_translation(_config(TranslatorServiceEnum.BING))

    assert result.success and result.translated_text == "测试译文"
    assert captured["translator_type"] == TranslatorType.BING
    assert captured["thread_num"] == captured["batch_num"] == 1
    assert fake.sources and "translation service test" in fake.sources[0]
    assert fake.stopped


def test_check_rejects_missing_deeplx_endpoint(monkeypatch):
    monkeypatch.delenv("DEEPLX_ENDPOINT", raising=False)
    result = check_translation(_config(TranslatorServiceEnum.DEEPLX, deeplx_endpoint="  "))
    assert not result.success
    assert "DeepLX" in result.detail


def test_check_rejects_incomplete_llm_config():
    result = check_translation(
        _config(
            TranslatorServiceEnum.OPENAI,
            base_url="https://example.com/v1",
            api_key="",
            llm_model="model",
        )
    )
    assert not result.success
    assert "LLM" in result.detail


def test_check_treats_empty_translation_as_failure(monkeypatch):
    fake = _FakeTranslator("", "HTTP 429 Too Many Requests")
    monkeypatch.setattr(
        "videocaptioner.core.translate.check.TranslatorFactory.create_translator",
        lambda **_kwargs: fake,
    )
    result = check_translation(_config(TranslatorServiceEnum.GOOGLE))
    assert not result.success
    assert result.detail == "HTTP 429 Too Many Requests"
    assert fake.stopped
