import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from videocaptioner.core.dubbing import DubbingResult
from videocaptioner.core.dubbing.models import DubbingConfig
from videocaptioner.core.entities import DubbingTask, DubbingUIConfig
from videocaptioner.ui.thread.dubbing_thread import DubbingThread

from .conftest import run_thread_with_timeout


class FakeDubbingPipeline:
    def __init__(self, config: DubbingConfig):
        self.config = config

    def run(
        self,
        subtitle_path,
        output_audio_path,
        *,
        video_path=None,
        output_video_path=None,
        text_track="auto",
        work_dir=None,
        callback=None,
    ):
        if callback:
            callback(50, "fake dubbing")
        audio = Path(output_audio_path)
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"fake-audio")
        video = Path(output_video_path) if output_video_path else None
        if video:
            video.write_bytes(b"fake-video")
        return DubbingResult(
            audio_path=audio,
            video_path=video,
            segments=[],
            duration_ms=1000,
            warnings=[],
        )


def test_dubbing_thread_finishes_with_mock_pipeline(tmp_path, monkeypatch, qapp):
    subtitle = tmp_path / "input.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    output_audio = tmp_path / "dub.wav"
    output_video = tmp_path / "dub.mp4"

    monkeypatch.setattr(
        "videocaptioner.ui.thread.dubbing_thread.DubbingPipeline",
        FakeDubbingPipeline,
    )

    task = DubbingTask(
        subtitle_path=str(subtitle),
        output_audio_path=str(output_audio),
        output_video_path=str(output_video),
        task_dir=str(tmp_path / "tasks" / "demo"),
        dubbing_config=DubbingUIConfig(enabled=True),
    )
    thread = DubbingThread(task)
    result = run_thread_with_timeout(thread, timeout_ms=5000)

    assert result["error"] is None
    assert result["finished"]
    assert output_audio.exists()
    assert output_video.exists()
