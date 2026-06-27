"""TwelveLabs Pegasus 视觉场景上下文提供器。

Generates a short natural-language description of a video's visual scenes
using TwelveLabs Pegasus, to be fed as reference context into the LLM
subtitle optimizer/translator. This helps the model:

- disambiguate ASR homophones using the on-screen setting,
- preserve proper nouns / on-screen text it would otherwise mangle,
- segment subtitles along visual scene boundaries.

The TwelveLabs SDK (``twelvelabs``) is imported lazily, so this is a pure
optional dependency — the rest of VideoCaptioner never imports it unless the
user explicitly enables scene context.

Get a free API key at https://twelvelabs.io (there is a generous free tier).
"""

import os
from pathlib import Path
from typing import Optional

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("scene_context")

# Pegasus 1.5 input constraints (verified against the v1.3 API):
#   - direct local-file asset upload is capped at 200 MB; public URLs up to 4 GB,
#   - the analyzed window must be >= 4s and the resolution >= 360x360,
#   - max_tokens must be >= 512 for this model.
MAX_LOCAL_UPLOAD_BYTES = 200 * 1024 * 1024
DEFAULT_MODEL = "pegasus1.5"
DEFAULT_MAX_TOKENS = 1024

DEFAULT_PROMPT = (
    "You are helping correct and segment the subtitles of this video. "
    "In 3-5 sentences, describe the visual scene: the setting, the people or "
    "subjects on screen, any visible on-screen text, brand names, product "
    "names, or domain-specific terminology. Be concise and factual. This "
    "description will be used as reference context to fix speech-recognition "
    "errors, so prioritise proper nouns and terms that are easy to "
    "mis-transcribe."
)


class SceneContextError(RuntimeError):
    """Raised when scene-context generation fails in a way the caller should know about."""


class SceneContextProvider:
    """Generate visual scene context for a video using TwelveLabs Pegasus.

    Args:
        api_key: TwelveLabs API key. Falls back to the ``TWELVELABS_API_KEY``
            environment variable when not provided.
        model: Pegasus model name (default ``pegasus1.5``).
        prompt: Analysis prompt. Defaults to a subtitle-correction-oriented prompt.
        max_tokens: Maximum tokens for the generated description (>= 512).
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        prompt: str = DEFAULT_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.api_key = api_key or os.environ.get("TWELVELABS_API_KEY", "")
        self.model = model or DEFAULT_MODEL
        self.prompt = prompt or DEFAULT_PROMPT
        # Pegasus requires max_tokens >= 512.
        self.max_tokens = max(int(max_tokens), 512)

    @property
    def is_available(self) -> bool:
        """True if an API key is configured (does not validate it)."""
        return bool(self.api_key)

    def _client(self):
        """Create a TwelveLabs client, importing the SDK lazily."""
        try:
            from twelvelabs import TwelveLabs
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise SceneContextError(
                "The 'twelvelabs' package is required for scene context. "
                "Install it with: pip install 'videocaptioner[scene]' "
                "(or pip install twelvelabs)."
            ) from exc
        if not self.api_key:
            raise SceneContextError(
                "No TwelveLabs API key configured. Set scene.api_key or the "
                "TWELVELABS_API_KEY environment variable. Get a free key at "
                "https://twelvelabs.io"
            )
        return TwelveLabs(api_key=self.api_key)

    def describe_video(self, video: str) -> str:
        """Return a natural-language description of the video's visual scenes.

        Args:
            video: A public http(s) URL to the video, or a local file path.
                Local files are uploaded as a TwelveLabs asset (<= 200 MB);
                use a public URL for larger files (up to 4 GB).

        Returns:
            The Pegasus-generated scene description (may be empty if the model
            returns nothing).

        Raises:
            SceneContextError: on missing SDK/key or upload/analysis failure.
        """
        client = self._client()
        video_context = self._build_video_context(client, video)

        logger.info("Generating visual scene context with TwelveLabs %s...", self.model)
        try:
            response = client.analyze(
                model_name=self.model,
                video=video_context,
                prompt=self.prompt,
                max_tokens=self.max_tokens,
                temperature=0.2,
            )
        except Exception as exc:
            raise SceneContextError(f"Pegasus analysis failed: {exc}") from exc

        text = (getattr(response, "data", None) or "").strip()
        logger.debug("Scene context (%d chars): %s", len(text), text[:200])
        return text

    def _build_video_context(self, client, video: str):
        """Build a VideoContext from a URL or a local file path."""
        from twelvelabs.types import VideoContext_AssetId, VideoContext_Url

        if _looks_like_url(video):
            return VideoContext_Url(url=video)

        path = Path(video)
        if not path.exists():
            raise SceneContextError(f"Video file not found: {video}")

        size = path.stat().st_size
        if size > MAX_LOCAL_UPLOAD_BYTES:
            raise SceneContextError(
                f"Video file is {size / 1024 / 1024:.0f} MB, which exceeds the "
                f"{MAX_LOCAL_UPLOAD_BYTES // 1024 // 1024} MB local-upload limit. "
                "Host it at a public URL (up to 4 GB) and pass the URL instead."
            )

        logger.info("Uploading %s as a TwelveLabs asset...", path.name)
        try:
            with open(path, "rb") as fh:
                asset = client.assets.create(method="direct", file=fh)
        except Exception as exc:
            raise SceneContextError(f"Asset upload failed: {exc}") from exc

        asset_id = getattr(asset, "id", None)
        if not asset_id:
            raise SceneContextError("Asset upload returned no asset id.")
        return VideoContext_AssetId(asset_id=asset_id)


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def get_scene_context(
    video: str,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    prompt: str = DEFAULT_PROMPT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Optional[str]:
    """Convenience wrapper that never raises; returns ``None`` on any failure.

    Intended for the subtitle pipeline, where scene context is a best-effort
    enhancement: if it fails (no key, bad video, network error) we simply
    proceed without it rather than aborting the whole job.
    """
    try:
        provider = SceneContextProvider(
            api_key=api_key, model=model, prompt=prompt, max_tokens=max_tokens
        )
        if not provider.is_available:
            return None
        text = provider.describe_video(video)
        return text or None
    except SceneContextError as exc:
        logger.warning("Scene context unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - best-effort, must never break the pipeline
        logger.warning("Unexpected error generating scene context: %s", exc)
        return None
