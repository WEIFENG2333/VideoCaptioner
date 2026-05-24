"""Optional text shortening for time-constrained dubbing."""

import json
from typing import Iterable

from openai import OpenAI

from videocaptioner.core.utils.text_utils import is_mainly_cjk

from .models import DubbingConfig, DubbingSegment


def should_rewrite(segment: DubbingSegment, threshold: float) -> bool:
    """Estimate whether text is likely too long for its target duration."""
    duration_s = max(segment.target_duration_ms / 1000, 0.1)
    text = segment.text.strip()
    if is_mainly_cjk(text):
        required = len(text) / duration_s
        comfortable = 5.5
    else:
        required = max(1, len(text.split())) / duration_s
        comfortable = 2.7
    return required > comfortable * threshold


def rewrite_segments_if_needed(segments: Iterable[DubbingSegment], config: DubbingConfig) -> None:
    """Shorten long subtitle lines with an OpenAI-compatible LLM."""
    if not config.rewrite_too_long:
        return
    if not (config.llm_api_key and config.llm_api_base and config.llm_model):
        raise ValueError("Duration rewrite requires llm.api_key, llm.api_base, and llm.model")

    targets = [seg for seg in segments if should_rewrite(seg, config.rewrite_threshold)]
    if not targets:
        return

    client = OpenAI(api_key=config.llm_api_key, base_url=config.llm_api_base)
    payload = [
        {
            "index": seg.index,
            "duration_seconds": round(seg.target_duration_ms / 1000, 2),
            "speaker": seg.speaker,
            "text": seg.text,
        }
        for seg in targets
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You shorten subtitle dubbing lines while preserving meaning, language, "
                "speaker intent, names, numbers, and key facts. Return only JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Rewrite only lines that are too long for the duration. Keep one output "
                "per input index. Make each line natural to speak and shorter. JSON format: "
                '{"items":[{"index":1,"text":"..."}]}\n\n'
                f"{json.dumps({'items': payload}, ensure_ascii=False)}"
            ),
        },
    ]
    response = client.chat.completions.create(
        model=config.llm_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    result = json.loads(content)
    rewritten = {
        int(item["index"]): str(item["text"]).strip()
        for item in result.get("items", [])
        if isinstance(item, dict) and item.get("text")
    }
    for seg in targets:
        new_text = rewritten.get(seg.index)
        if new_text:
            seg.rewritten_text = new_text
