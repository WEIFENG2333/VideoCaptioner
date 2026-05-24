from pathlib import Path

from pydub import AudioSegment

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.speech import SynthesisResult


class FakeSynthesizer:
    calls = []

    def synthesize(self, request):
        self.calls.append(request.text)
        audio = AudioSegment.silent(duration=350, frame_rate=24000)
        Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
        audio.export(request.output_path, format="wav")
        return SynthesisResult(
            output_path=request.output_path,
            voice=request.voice or "fake",
            format="wav",
            provider_metadata={},
        )


def test_dubbing_pipeline_creates_timeline_audio(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n[Alice] Hello\n\n"
        "2\n00:00:01,200 --> 00:00:02,000\nBob: Hi\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )

    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
    )
    result = DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert output.exists()
    assert result.duration_ms == 2000
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "Alice"
    assert result.segments[1].speaker == "Bob"
    assert output.with_suffix(".dubbing.json").exists()


def test_dubbing_pipeline_uses_configured_workers(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nTwo\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nThree\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"
    seen_workers = []

    class CapturingExecutor:
        def __init__(self, max_workers):
            seen_workers.append(max_workers)
            from concurrent.futures import ThreadPoolExecutor

            self._executor = ThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self):
            return self._executor.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._executor.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.ThreadPoolExecutor", CapturingExecutor)

    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        tts_workers=2,
    )
    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert seen_workers == [2]
