"""实时语音转录 / 翻译（实时字幕）核心层。

后端无关：每个 ASR 后端把自家 wire 协议翻成统一的实时转录事件
（:class:`TranscriptSegment`，自带稳定 per-sentence ``seg_id``），再由
:class:`CaptionAssembler` 按 ``seg_id`` upsert + 双色 + 翻译装配成可直接上屏的
:class:`CaptionEntry`（**分句是后端的职责**）。新增后端只需实现 :class:`LiveTranscriber`。
"""

from videocaptioner.core.realtime.backends.base import (
    LiveCaptionError,
    LiveTranscriber,
    TranscriberState,
)
from videocaptioner.core.realtime.caption import CaptionAssembler
from videocaptioner.core.realtime.config import LiveCaptionConfig, LiveCaptionSource
from videocaptioner.core.realtime.events import CaptionEntry, TranscriptSegment

__all__ = [
    "CaptionAssembler",
    "CaptionEntry",
    "LiveCaptionConfig",
    "LiveCaptionError",
    "LiveCaptionSource",
    "LiveTranscriber",
    "TranscriberState",
    "TranscriptSegment",
]
