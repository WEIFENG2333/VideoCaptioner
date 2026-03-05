from pathlib import Path

from app.core.asr.chunked_asr import ChunkedASR
from app.core.asr.qwen_asr import QwenASR
from app.core.asr.transcribe import _create_asr_instance
from app.core.entities import TranscribeConfig, TranscribeModelEnum


def test_qwen_asr_make_segments_word_level():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=True,
    )

    resp = {
        "text": "你好世界",
        "time_stamps": [
            {"text": "你好", "start": 0.0, "end": 0.4},
            {"text": "世界", "start": 0.4, "end": 0.9},
        ],
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 2
    assert segments[0].text == "你好"
    assert segments[0].start_time == 0
    assert segments[0].end_time == 400


def test_qwen_asr_make_segments_sentence_level_fallback():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=False,
    )

    resp = {
        "text": "这是一段句子级转录。",
        "time_stamps": [{"start": 0.0, "end": 1.5}],
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 1
    assert segments[0].text == "这是一段句子级转录。"
    assert segments[0].start_time == 0
    assert segments[0].end_time == 1500


def test_qwen_asr_make_segments_vllm_verbose_json_word_level():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        backend="vllm",
        need_word_time_stamp=True,
    )

    resp = {
        "text": "hello world",
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ],
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 2
    assert segments[1].text == "world"
    assert segments[1].start_time == 500
    assert segments[1].end_time == 1000


def test_qwen_asr_normalize_result_legacy_start_end_fields():
    class LegacyTimestamp:
        def __init__(self, text: str, start: float, end: float):
            self.text = text
            self.start = start
            self.end = end

    class LegacyResult:
        def __init__(self):
            self.time_stamps = [
                LegacyTimestamp("今日", 0.0, 0.5),
                LegacyTimestamp("のストーリー", 0.5, 1.2),
            ]

    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=True,
    )

    normalized = asr._normalize_result(LegacyResult())
    segments = asr._make_segments(normalized)

    assert len(segments) == 2
    assert segments[0].start_time == 0
    assert segments[0].end_time == 500
    assert segments[1].start_time == 500
    assert segments[1].end_time == 1200


def test_qwen_asr_make_segments_all_zero_timestamps_triggers_synthetic_timeline():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=True,
    )

    resp = {
        "words": [
            {"word": "a", "start": 0.0, "end": 0.0},
            {"word": "b", "start": 0.0, "end": 0.0},
        ]
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 2
    assert segments[0].start_time == 0
    assert segments[0].end_time > 0
    assert segments[1].start_time >= segments[0].end_time


def test_qwen_asr_make_segments_non_monotonic_but_non_zero_keeps_original_timestamps():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=True,
    )

    resp = {
        "words": [
            {"word": "a", "start": 0.0, "end": 0.2},
            {"word": "b", "start": 0.15, "end": 0.4},
        ]
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 2
    assert segments[0].start_time == 0
    assert segments[0].end_time == 200
    assert segments[1].start_time == 150
    assert segments[1].end_time == 400


def test_qwen_asr_make_segments_partial_zero_timestamps_are_repaired():
    asr = QwenASR(
        audio_input=b"dummy-audio-bytes",
        model_name="Qwen/Qwen3-ASR-0.6B",
        need_word_time_stamp=True,
    )

    resp = {
        "words": [
            {"word": "今", "start": 0.0, "end": 0.0},
            {"word": "日", "start": 0.0, "end": 0.0},
            {"word": "は", "start": 8.0, "end": 8.5},
            {"word": "晴", "start": 9.0, "end": 9.5},
        ]
    }
    segments = asr._make_segments(resp)

    assert len(segments) == 4
    assert segments[0].end_time > 0
    assert segments[1].end_time > segments[1].start_time
    assert segments[2].start_time == 8000
    assert segments[2].end_time == 8500
    assert segments[3].start_time == 9000
    assert segments[3].end_time == 9500


def test_create_asr_instance_qwen_model():
    audio_path = Path(__file__).resolve().parent.parent / "fixtures" / "audio" / "en.mp3"
    assert audio_path.exists()

    config = TranscribeConfig(
        transcribe_model=TranscribeModelEnum.QWEN_ASR,
        transcribe_language="zh",
        need_word_time_stamp=True,
        qwen_asr_model="Qwen/Qwen3-ASR-0.6B",
        qwen_asr_aligner_model="Qwen/Qwen3-ForcedAligner-0.6B",
        qwen_asr_backend="transformers",
        qwen_asr_max_new_tokens=1024,
    )

    asr = _create_asr_instance(str(audio_path), config)

    assert isinstance(asr, ChunkedASR)
    assert asr.asr_class is QwenASR
    assert asr.asr_kwargs["model_name"] == "Qwen/Qwen3-ASR-0.6B"
    assert asr.asr_kwargs["need_word_time_stamp"] is True
