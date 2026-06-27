"""TwelveLabs Pegasus scene-context provider tests.

The unit tests run with no network and no API key. The integration test
requires:
    TWELVELABS_API_KEY: a TwelveLabs API key (free tier at https://twelvelabs.io)
and is skipped otherwise.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from videocaptioner.core.scene import (
    SceneContextError,
    SceneContextProvider,
    get_scene_context,
)


class TestSceneContextProviderUnit:
    """No-network unit tests for the provider's guards and fallbacks."""

    def test_not_available_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TWELVELABS_API_KEY", raising=False)
        provider = SceneContextProvider(api_key="")
        assert provider.is_available is False

    def test_available_with_key(self) -> None:
        assert SceneContextProvider(api_key="dummy").is_available is True

    def test_max_tokens_floor(self) -> None:
        # Pegasus requires max_tokens >= 512; smaller values are clamped up.
        assert SceneContextProvider(api_key="k", max_tokens=10).max_tokens == 512

    def test_get_scene_context_returns_none_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TWELVELABS_API_KEY", raising=False)
        # No key -> best-effort wrapper returns None, no network call.
        assert get_scene_context("https://example.com/v.mp4", api_key="") is None

    def test_get_scene_context_swallows_missing_file(self) -> None:
        # A local file that does not exist must not crash the pipeline.
        assert get_scene_context("/no/such/video.mp4", api_key="dummy-key") is None

    def test_missing_file_raises_on_provider(self) -> None:
        provider = SceneContextProvider(api_key="dummy-key")
        with pytest.raises(SceneContextError):
            provider.describe_video("/no/such/video.mp4")


@pytest.mark.integration
class TestSceneContextProviderLive:
    """Live test against the TwelveLabs API (Pegasus 1.5).

    Generates a short, valid local clip with ffmpeg and exercises the full
    upload-as-asset + analyze path. Pegasus requires a window >= 4s and a
    resolution >= 360x360.
    """

    def test_describe_local_video(
        self, check_env_vars: Callable, tmp_path: Path
    ) -> None:
        check_env_vars("TWELVELABS_API_KEY")
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not available to generate a test clip")

        clip = tmp_path / "scene_probe.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "testsrc=size=640x360:rate=30:duration=6",
                "-vf", "drawtext=text='VideoCaptioner Scene Test':"
                       "fontcolor=white:fontsize=26:x=30:y=160",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(clip),
            ],
            check=True,
            capture_output=True,
        )

        provider = SceneContextProvider(api_key=os.environ["TWELVELABS_API_KEY"])
        text = provider.describe_video(str(clip))

        print("\n" + "=" * 60)
        print("Pegasus scene context:")
        print(text)
        print("=" * 60)

        assert isinstance(text, str)
        assert text.strip(), "Pegasus returned an empty description"
