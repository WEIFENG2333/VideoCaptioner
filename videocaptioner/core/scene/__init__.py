"""可选的视觉场景理解模块（TwelveLabs Pegasus）。

Optional visual scene-context provider. Uses TwelveLabs Pegasus to describe
what is happening on screen, so the LLM optimizer/translator can correct ASR
errors and segment subtitles with the actual visual context in hand
(e.g. disambiguate homophones, proper nouns, and on-screen text).

This feature is fully opt-in and non-breaking: if no TwelveLabs API key is
configured, nothing here runs and subtitle processing behaves exactly as
before.
"""

from videocaptioner.core.scene.pegasus import (
    SceneContextError,
    SceneContextProvider,
    get_scene_context,
)

__all__ = [
    "SceneContextError",
    "SceneContextProvider",
    "get_scene_context",
]
