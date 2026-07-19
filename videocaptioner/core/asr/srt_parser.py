"""SRT parsing and file-level parallel-track detection.

SRT has no standard field that says whether two text lines are visual wrapping
or source/translation tracks.  Classification therefore belongs at file level:
consistent two-line structure plus cross-script, cross-language, duplicate, or
same-language revision evidence indicates parallel tracks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from langdetect import LangDetectException, detect

_TIME_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})\s-->\s"
    r"(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})"
)
_SAMPLE_LIMIT = 50
_TWO_LINE_COVERAGE = 0.70
_PARALLEL_EVIDENCE = 0.70
_REVISION_SIMILARITY = 0.55


@dataclass(frozen=True)
class ParsedSrtCue:
    start_time: int
    end_time: int
    text_lines: tuple[str, ...]


def _milliseconds(parts: tuple[str, ...]) -> int:
    hours, minutes, seconds, millis = map(int, parts)
    return hours * 3_600_000 + minutes * 60_000 + seconds * 1000 + millis


def parse_srt_cues(content: str) -> list[ParsedSrtCue]:
    cues: list[ParsedSrtCue] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        # Keep compatibility with SRT position metadata appended after the
        # timestamp (``X1:… X2:…``), which some authoring tools emit.
        match = _TIME_PATTERN.match(lines[1].strip())
        if match is None:
            continue
        groups = match.groups()
        cues.append(
            ParsedSrtCue(
                _milliseconds(groups[:4]),
                _milliseconds(groups[4:]),
                tuple(lines[2:]),
            )
        )
    return cues


def _normalized(text: str) -> str:
    return "".join(ch.casefold() for ch in text if ch.isalnum())


def _script_class(text: str) -> str:
    scripts = {
        "cjk": r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]",
        "latin": r"[A-Za-z\u00c0-\u024f]",
        "cyrillic": r"[\u0400-\u04ff]",
        "arabic": r"[\u0600-\u06ff]",
        "hebrew": r"[\u0590-\u05ff]",
        "thai": r"[\u0e00-\u0e7f]",
    }
    found = [name for name, pattern in scripts.items() if re.search(pattern, text)]
    return found[0] if len(found) == 1 else "mixed" if found else "other"


def _parallel_pair_evidence(top: str, bottom: str) -> bool:
    a, b = _normalized(top), _normalized(bottom)
    if not a or not b:
        return False
    top_script, bottom_script = _script_class(top), _script_class(bottom)
    if top_script != bottom_script and "other" not in {top_script, bottom_script}:
        return True
    # Same-language translated/revised tracks are commonly identical or close
    # paraphrases; ordinary visual wrapping normally continues the sentence.
    if SequenceMatcher(None, a, b).ratio() >= _REVISION_SIMILARITY:
        return True
    try:
        return detect(top) != detect(bottom)
    except LangDetectException:
        return False


def has_parallel_text_tracks(cues: list[ParsedSrtCue]) -> bool:
    """Return whether line 1/2 consistently represent parallel text tracks."""
    if not cues:
        return False
    two_line = [cue for cue in cues if len(cue.text_lines) == 2]
    if len(two_line) / len(cues) < _TWO_LINE_COVERAGE:
        return False
    sample = two_line[:_SAMPLE_LIMIT]
    evidence = sum(
        _parallel_pair_evidence(cue.text_lines[0], cue.text_lines[1]) for cue in sample
    )
    return evidence / len(sample) >= _PARALLEL_EVIDENCE


def split_srt_tracks(content: str) -> list[tuple[int, int, str, str]]:
    """Parse SRT into ``(start, end, source, translation)`` records."""
    cues = parse_srt_cues(content)
    parallel = has_parallel_text_tracks(cues)
    records = []
    for cue in cues:
        if parallel and len(cue.text_lines) == 2:
            source, translation = cue.text_lines
        else:
            source, translation = "\n".join(cue.text_lines), ""
        records.append((cue.start_time, cue.end_time, source, translation))
    return records
