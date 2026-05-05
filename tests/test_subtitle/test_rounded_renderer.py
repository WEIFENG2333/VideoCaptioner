"""Tests for rounded subtitle video rendering."""

import subprocess
from pathlib import Path

from PIL import Image

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.subtitle import rounded_renderer


class FixedTemporaryDirectory:
    """TemporaryDirectory replacement that leaves files available for assertions."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.mkdir(parents=True, exist_ok=True)
        return str(self.path)

    def __exit__(self, exc_type, exc, tb):
        return False


def make_asr_data(count: int) -> ASRData:
    segments = [
        ASRDataSeg(
            text=f"source {index}",
            translated_text=f"target {index}",
            start_time=index * 1000,
            end_time=index * 1000 + 500,
        )
        for index in range(count)
    ]
    return ASRData(segments)


def stub_subtitle_image(*args, **kwargs):
    return Image.new("RGBA", (8, 8), (0, 0, 0, 0))


def test_rounded_video_intermediate_batches_use_bounded_encoding(
    monkeypatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rounded_renderer, "_get_video_info", lambda path: (320, 180, 3.0))
    monkeypatch.setattr(rounded_renderer, "render_subtitle_image", stub_subtitle_image)
    monkeypatch.setattr(
        rounded_renderer.tempfile,
        "TemporaryDirectory",
        lambda *args, **kwargs: FixedTemporaryDirectory(tmp_path / "rounded-temp"),
    )
    monkeypatch.setattr(rounded_renderer.subprocess, "run", fake_run)

    output_path = tmp_path / "output.mp4"
    rounded_renderer.render_rounded_video(
        video_path=str(tmp_path / "input.mp4"),
        asr_data=make_asr_data(51),
        output_path=str(output_path),
        layout=SubtitleLayoutEnum.ONLY_TRANSLATE,
        crf=28,
        preset="medium",
    )

    assert len(commands) == 2
    first_cmd = commands[0]
    assert first_cmd[first_cmd.index("-crf") + 1] == "18"
    assert first_cmd[first_cmd.index("-preset") + 1] == "ultrafast"
    assert "-hide_banner" in first_cmd
    assert first_cmd[first_cmd.index("-loglevel") + 1] == "error"

    final_cmd = commands[-1]
    assert final_cmd[final_cmd.index("-crf") + 1] == "28"
    assert final_cmd[final_cmd.index("-preset") + 1] == "medium"


def test_rounded_video_cleans_processed_temp_files(monkeypatch, tmp_path: Path) -> None:
    temp_path = tmp_path / "rounded-temp"

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rounded_renderer, "_get_video_info", lambda path: (320, 180, 3.0))
    monkeypatch.setattr(rounded_renderer, "render_subtitle_image", stub_subtitle_image)
    monkeypatch.setattr(
        rounded_renderer.tempfile,
        "TemporaryDirectory",
        lambda *args, **kwargs: FixedTemporaryDirectory(temp_path),
    )
    monkeypatch.setattr(rounded_renderer.subprocess, "run", fake_run)

    output_path = tmp_path / "output.mp4"
    rounded_renderer.render_rounded_video(
        video_path=str(tmp_path / "input.mp4"),
        asr_data=make_asr_data(101),
        output_path=str(output_path),
        layout=SubtitleLayoutEnum.ONLY_TRANSLATE,
        crf=28,
        preset="medium",
    )

    assert output_path.exists()
    assert not list(temp_path.glob("batch_*.mp4"))
    assert not list(temp_path.glob("subtitle_*.png"))
