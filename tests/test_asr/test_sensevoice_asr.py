import builtins
from pathlib import Path

import pytest

from videocaptioner.core.asr.sensevoice import SenseVoiceASR
from videocaptioner.core.asr.transcribe import _create_asr_instance
from videocaptioner.core.entities import TranscribeConfig, TranscribeModelEnum


class FakeSenseVoiceModel:
    def __init__(self, result):
        self.result = result
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            progress_callback(1, 2)
            progress_callback(2, 2)
        return self.result


@pytest.fixture(autouse=True)
def clear_model_cache():
    SenseVoiceASR._model_cache.clear()
    yield
    SenseVoiceASR._model_cache.clear()


def test_preserves_native_word_timestamps(test_audio_path_zh, monkeypatch):
    model = FakeSenseVoiceModel(
        [
            {
                "text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>今天天气？",
                "words": ["今", "天", "天", "气", "？"],
                "timestamp": [[100, 180], [200, 280], [500, 580], [600, 680], [700, 760]],
            }
        ]
    )
    monkeypatch.setattr(SenseVoiceASR, "_get_model", lambda self: model)
    callbacks = []

    result = SenseVoiceASR(
        str(test_audio_path_zh),
        model="iic/SenseVoiceSmall",
        device="cpu",
        language="zh",
        need_word_time_stamp=True,
    ).run(lambda progress, message: callbacks.append((progress, message)))

    assert [(seg.text, seg.start_time, seg.end_time) for seg in result] == [
        ("今", 100, 180),
        ("天", 200, 280),
        ("天", 500, 580),
        ("气", 600, 680),
        ("？", 700, 760),
    ]
    assert model.generate_kwargs["language"] == "zh"
    assert model.generate_kwargs["output_timestamp"] is True
    assert model.generate_kwargs["merge_vad"] is True
    assert callbacks[-1][0] == 100


def test_groups_words_into_readable_sentence_segments(test_audio_path_en, monkeypatch):
    model = FakeSenseVoiceModel(
        [
            {
                "text": "<|en|><|NEUTRAL|><|Speech|><|withitn|>What's new? Fine.",
                "words": ["What", "'", "s", "new", "?", "Fine", "."],
                "timestamp": [
                    [100, 180],
                    [180, 220],
                    [220, 260],
                    [300, 420],
                    [420, 480],
                    [1800, 2000],
                    [2000, 2060],
                ],
            }
        ]
    )
    monkeypatch.setattr(SenseVoiceASR, "_get_model", lambda self: model)

    result = SenseVoiceASR(
        str(test_audio_path_en),
        model="iic/SenseVoiceSmall",
        device="cpu",
        language="auto",
    ).run()

    assert [(seg.text, seg.start_time, seg.end_time) for seg in result] == [
        ("What's new?", 100, 480),
        ("Fine.", 1800, 2060),
    ]


def test_falls_back_to_clean_text_and_timestamp_bounds(test_audio_path_zh, monkeypatch):
    model = FakeSenseVoiceModel(
        [
            {
                "text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好。",
                "timestamp": [[250, 310], [500, 720], [720, 800]],
            }
        ]
    )
    monkeypatch.setattr(SenseVoiceASR, "_get_model", lambda self: model)

    result = SenseVoiceASR(str(test_audio_path_zh), device="cpu").run()

    assert len(result) == 1
    assert result.segments[0].text == "你好。"
    assert result.segments[0].start_time == 250
    assert result.segments[0].end_time == 800


def test_encoded_audio_bytes_are_converted_to_wav(test_audio_path_zh, monkeypatch):
    class InspectingModel(FakeSenseVoiceModel):
        def generate(self, **kwargs):
            input_path = Path(kwargs["input"])
            assert input_path.suffix == ".wav"
            assert input_path.exists()
            assert input_path.read_bytes().startswith(b"RIFF")
            return super().generate(**kwargs)

    model = InspectingModel(
        [
            {
                "text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好。",
                "words": ["你", "好", "。"],
                "timestamp": [[100, 200], [250, 350], [350, 400]],
            }
        ]
    )
    monkeypatch.setattr(SenseVoiceASR, "_get_model", lambda self: model)

    result = SenseVoiceASR(test_audio_path_zh.read_bytes(), device="cpu").run()

    assert result.segments[0].text == "你好。"


def test_missing_optional_dependency_has_install_hint(test_audio_path_zh, monkeypatch):
    asr = SenseVoiceASR(str(test_audio_path_zh), device="cpu")
    real_import = builtins.__import__

    def import_without_funasr(name, *args, **kwargs):
        if name == "funasr":
            raise ModuleNotFoundError("No module named 'funasr'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_funasr)

    with pytest.raises(RuntimeError, match=r"videocaptioner\[sensevoice\]"):
        asr._create_model("cpu")


def test_transcribe_factory_builds_single_worker_sensevoice(test_audio_path_zh):
    config = TranscribeConfig(
        transcribe_model=TranscribeModelEnum.SENSEVOICE,
        transcribe_language="yue",
        need_word_time_stamp=True,
        sensevoice_model="iic/SenseVoiceSmall",
        sensevoice_device="cpu",
    )

    chunked = _create_asr_instance(str(test_audio_path_zh), config)

    assert chunked.asr_class is SenseVoiceASR
    assert chunked.chunk_concurrency == 1
    assert chunked.asr_kwargs == {
        "use_cache": True,
        "need_word_time_stamp": True,
        "language": "yue",
        "model": "iic/SenseVoiceSmall",
        "device": "cpu",
    }
