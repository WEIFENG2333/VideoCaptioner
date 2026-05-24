"""Parse subtitle files into dubbing segments."""

import json
import re
from pathlib import Path
from typing import Any

from videocaptioner.core.asr.asr_data import ASRData

from .models import DubbingSegment

_BRACKET_SPEAKER_RE = re.compile(r"^\s*[\[\(【](?P<speaker>[^\]\)】]{1,40})[\]\)】]\s*(?P<text>.+)$", re.S)
_COLON_SPEAKER_RE = re.compile(r"^\s*(?P<speaker>[\w\u4e00-\u9fff ._-]{1,40})\s*[:：]\s*(?P<text>.+)$", re.S)


def load_dubbing_segments(path: str, *, text_track: str = "auto") -> list[DubbingSegment]:
    """Load SRT/ASS/VTT/JSON subtitles and extract optional speaker labels.

    Speaker label formats for plain subtitle files:

    - ``[Alice] Hello``
    - ``Alice: Hello``
    - ``【小明】你好``

    JSON input may be either an array or a dict keyed by subtitle number. Fields:
    ``start_time``/``end_time`` in milliseconds, ``text`` or
    ``original_subtitle``, and optional ``speaker``.
    """
    subtitle_path = Path(path)
    if subtitle_path.suffix.lower() == ".json":
        return _from_json(json.loads(subtitle_path.read_text(encoding="utf-8")), text_track)

    asr_data = ASRData.from_subtitle_file(path)
    segments: list[DubbingSegment] = []
    for index, seg in enumerate(asr_data.segments, 1):
        raw_text = _select_text(seg.text, seg.translated_text, text_track)
        speaker, text = split_speaker(raw_text)
        if text.strip():
            segments.append(
                DubbingSegment(
                    index=index,
                    start_ms=seg.start_time,
                    end_ms=seg.end_time,
                    speaker=speaker,
                    text=text.strip(),
                )
            )
    return segments


def split_speaker(text: str) -> tuple[str, str]:
    """Extract speaker name from a subtitle line."""
    cleaned = text.strip()
    for pattern in (_BRACKET_SPEAKER_RE, _COLON_SPEAKER_RE):
        match = pattern.match(cleaned)
        if match:
            speaker = match.group("speaker").strip()
            content = match.group("text").strip()
            if speaker and content:
                return speaker, content
    return "default", cleaned


def _select_text(original: str, translated: str, text_track: str) -> str:
    if text_track in {"source", "original", "first"}:
        return original
    if text_track in {"target", "translated", "second"}:
        return translated or original
    return translated or original


def _from_json(data: Any, text_track: str) -> list[DubbingSegment]:
    if isinstance(data, dict):
        items = [data[k] for k in sorted(data.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("Dubbing JSON must be an object or array")

    segments: list[DubbingSegment] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        original = str(item.get("text") or item.get("original_subtitle") or "")
        translated = str(item.get("translated_text") or item.get("translated_subtitle") or "")
        raw_text = _select_text(original, translated, text_track)
        speaker = str(item.get("speaker") or "").strip()
        if speaker:
            text = raw_text.strip()
        else:
            speaker, text = split_speaker(raw_text)
        if not text:
            continue
        segments.append(
            DubbingSegment(
                index=int(item.get("index") or index),
                start_ms=int(item["start_time"]),
                end_ms=int(item["end_time"]),
                speaker=speaker or "default",
                text=text,
            )
        )
    return segments
