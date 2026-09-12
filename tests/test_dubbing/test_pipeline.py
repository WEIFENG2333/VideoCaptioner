from pathlib import Path

import pytest
from pydub import AudioSegment

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.speech import SynthesisResult


@pytest.fixture(autouse=True)
def isolated_tts_cache(tmp_path, monkeypatch):
    """TTS 分段缓存是全局内容寻址目录，测试必须隔离到 tmp。"""
    cache_dir = tmp_path / "tts-cache"
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.TTS_SEGMENT_CACHE_DIR", cache_dir
    )
    return cache_dir


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
    # 报告进工作目录（随任务目录生灭），不再散落在音频旁
    assert result.report_path == tmp_path / "parts" / "report.json"
    assert result.report_path.exists()
    assert not output.with_suffix(".dubbing.json").exists()


def test_segment_cache_reused_across_runs(tmp_path, monkeypatch, isolated_tts_cache):
    """同文本同配置重跑命中全局缓存，不再调 TTS。"""
    srt = tmp_path / "input.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    config = DubbingConfig(
        provider="gemini", api_key="t", base_url="", model="m", voice="Kore"
    )

    FakeSynthesizer.calls = []
    DubbingPipeline(config).run(str(srt), str(tmp_path / "a.wav"), work_dir=str(tmp_path / "w1"))
    first_calls = len(FakeSynthesizer.calls)
    DubbingPipeline(config).run(str(srt), str(tmp_path / "b.wav"), work_dir=str(tmp_path / "w2"))

    assert first_calls == 1
    assert len(FakeSynthesizer.calls) == 1  # 第二次全部命中缓存
    assert any(isolated_tts_cache.iterdir())


def test_stretch_to_fit_slows_short_speech_by_default(tmp_path, monkeypatch, isolated_tts_cache):
    """默认把短于槽位的配音放慢拉伸到原时长；关闭后保持原速不调速。"""
    srt = tmp_path / "input.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    factors: list[float] = []

    def fake_change_tempo(src, out, factor):
        factors.append(factor)
        AudioSegment.silent(duration=max(1, int(350 / factor)), frame_rate=24000).export(
            out, format="wav"
        )

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.change_tempo", fake_change_tempo
    )
    base = dict(provider="gemini", api_key="t", base_url="", model="m", voice="Kore")

    # 默认 stretch_to_fit=True：350ms 配音 < ~920ms 槽位 → 放慢（factor<1）拉伸
    DubbingPipeline(DubbingConfig(**base)).run(
        str(srt), str(tmp_path / "a.wav"), work_dir=str(tmp_path / "w1")
    )
    assert factors, "短配音未被拉伸"
    assert all(f < 1.0 for f in factors), factors

    # 关闭后短配音保持原速，不调用 change_tempo
    factors.clear()
    DubbingPipeline(DubbingConfig(**base, stretch_to_fit=False)).run(
        str(srt), str(tmp_path / "b.wav"), work_dir=str(tmp_path / "w2")
    )
    assert not factors, f"关闭拉伸后不应调速: {factors}"


def test_segment_cache_key_includes_synthesis_config(tmp_path, monkeypatch):
    """音色/速度等配置变化必须使缓存失效（曾因漏 speed/gain 复用旧音频）。"""
    srt = tmp_path / "input.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    base = dict(provider="gemini", api_key="t", base_url="", model="m", voice="Kore")

    FakeSynthesizer.calls = []
    DubbingPipeline(DubbingConfig(**base)).run(
        str(srt), str(tmp_path / "a.wav"), work_dir=str(tmp_path / "w1")
    )
    DubbingPipeline(DubbingConfig(**base, speed=1.5)).run(
        str(srt), str(tmp_path / "b.wav"), work_dir=str(tmp_path / "w2")
    )

    assert len(FakeSynthesizer.calls) == 2  # speed 变了 → 重新合成


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


def test_dubbing_pipeline_edge_forces_fixed_workers(tmp_path, monkeypatch):
    """Edge 免费，并发由程序内部固定为 5，忽略 config.tts_workers。"""
    lines = "".join(
        f"{i}\n00:00:0{i-1},000 --> 00:00:0{i},000\nLine {i}\n\n" for i in range(1, 8)
    )
    srt = tmp_path / "input.srt"
    srt.write_text(lines, encoding="utf-8")
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
        provider="edge",
        api_key="",
        base_url="",
        model="edge-tts",
        voice="zh-CN-XiaoxiaoNeural",
        tts_workers=20,
    )
    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    # 7 段、配置 20 并发，但 Edge 固定 5 → min(5, 7) == 5
    assert seen_workers == [5]
