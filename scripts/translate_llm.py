#!/usr/bin/env python3
"""
Translate .ts files using OpenAI Structured Outputs

Ensures 1:1 mapping between source and translation with zero data loss.
Target language is automatically detected from filename.

Usage:
    python scripts/translate_llm.py <file>

Examples:
    python scripts/translate_llm.py resource/translations/VideoCaptioner_en_US.ts
    python scripts/translate_llm.py resource/translations/VideoCaptioner_zh_HK.ts
    python scripts/translate_llm.py resource/translations/VideoCaptioner_ja_JP.ts
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from openai import OpenAI
from pydantic import BaseModel

# ============================================================================
# Configuration
# ============================================================================

BATCH_SIZE = 10
MODEL = "gpt-5"
TEMPERATURE = 1

# Technical terms that should not be translated
PRESERVE_TERMS = [
    "ASR",
    "LLM",
    "TTS",
    "FFmpeg",
    "Whisper",
    "FasterWhisper",
    "WhisperCpp",
    "OpenAI",
    "GPU",
    "CPU",
    "CUDA",
    "VAD",
    "Silero",
    "Pyannote",
    "WebRTC",
    "Auditok",
]

# Language mapping from locale code to target language
LANGUAGE_MAP = {
    "en_US": "English",
    "zh_HK": "Traditional Chinese (Hong Kong)",
    "zh_TW": "Traditional Chinese (Taiwan)",
    "ja_JP": "Japanese",
    "ko_KR": "Korean",
    "fr_FR": "French",
    "de_DE": "German",
    "es_ES": "Spanish",
    "it_IT": "Italian",
    "pt_BR": "Portuguese (Brazil)",
    "ru_RU": "Russian",
    "ar_SA": "Arabic",
    "th_TH": "Thai",
    "vi_VN": "Vietnamese",
}

# ============================================================================
# Structured Output Models
# ============================================================================


class Translation(BaseModel):
    """Single translation with index for guaranteed ordering"""

    index: int
    source: str
    translation: str


class TranslationBatch(BaseModel):
    """Batch of translations with strict schema"""

    translations: List[Translation]


# ============================================================================
# OpenAI Client
# ============================================================================

# Use direct OpenAI API (bypass any custom base_url in environment)

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = OpenAI(
    api_key=api_key, base_url="https://api.openai.com/v1"  # Force direct OpenAI API
)


# ============================================================================
# Core Functions
# ============================================================================


def detect_target_language(filename: str) -> str:
    """Detect target language from filename"""
    # Extract locale code (e.g., "en_US" from "VideoCaptioner_en_US.ts")
    match = re.search(r"_([a-z]{2}_[A-Z]{2})\.ts$", filename)

    if not match:
        raise ValueError(
            f"Cannot detect language from filename: {filename}\n"
            f"Expected format: VideoCaptioner_<locale>.ts (e.g., VideoCaptioner_en_US.ts)"
        )

    locale = match.group(1)

    if locale not in LANGUAGE_MAP:
        raise ValueError(
            f"Unsupported locale: {locale}\n"
            f"Supported: {', '.join(LANGUAGE_MAP.keys())}"
        )

    return LANGUAGE_MAP[locale]


def translate_batch(
    texts: List[str], target_lang: str, start_index: int
) -> List[Translation]:
    """
    Translate a batch of texts using structured outputs.

    Returns translations with guaranteed index matching.
    """

    # Build numbered input
    items = [{"index": start_index + i, "text": text} for i, text in enumerate(texts)]

    # Construct clear, professional prompt
    prompt = f"""You are a professional UI translator. Translate these texts to {target_lang}.

**CRITICAL REQUIREMENTS:**
1. Maintain exact 1:1 mapping - every input MUST have corresponding output
2. Keep translations concise and natural for UI context
3. Use standard UI terminology (e.g., "Settings", "Cancel", "OK")
4. NEVER translate technical terms: {', '.join(PRESERVE_TERMS)}
5. Preserve formatting markers like {{variable}}, %s, \\n
6. Match the tone: formal for settings, friendly for messages

**Input texts (index: text):**
{chr(10).join([f"{item['index']}: {item['text']}" for item in items])}

**Your task:**
Return EXACTLY {len(texts)} translations with matching indices."""

    # Call OpenAI with structured output
    completion = client.beta.chat.completions.parse(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": f"You are an expert UI translator specializing in {target_lang}. "
                "You always return complete, accurate translations.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format=TranslationBatch,
        temperature=TEMPERATURE,
    )

    result = completion.choices[0].message.parsed

    # Validate we got all translations
    if len(result.translations) != len(texts):
        raise ValueError(
            f"Translation mismatch: expected {len(texts)}, got {len(result.translations)}"
        )

    return sorted(result.translations, key=lambda x: x.index)


def translate_file(ts_file: Path, target_lang: str) -> None:
    """Translate a .ts file with progress tracking"""

    # Parse XML
    tree = ET.parse(ts_file)
    root = tree.getroot()

    # Collect untranslated entries
    entries = []
    for message in root.findall(".//message"):
        source = message.find("source")
        translation = message.find("translation")

        if source is not None and translation is not None:
            text = source.text or ""
            if not translation.text or translation.get("type") == "unfinished":
                entries.append((text, translation))

    if not entries:
        print("✨ All translations already complete!")
        return

    total = len(entries)
    print(f"📊 Found {total} texts to translate")
    print(f"🎯 Target language: {target_lang}")
    print(f"🔧 Using model: {MODEL}")
    print("─" * 60)

    # Process in batches
    success_count = 0

    for i in range(0, total, BATCH_SIZE):
        batch_texts = [entry[0] for entry in entries[i : i + BATCH_SIZE]]
        batch_elements = [entry[1] for entry in entries[i : i + BATCH_SIZE]]

        batch_num = i // BATCH_SIZE + 1
        total_batches = (total - 1) // BATCH_SIZE + 1

        print(
            f"🔄 Batch {batch_num}/{total_batches} ({len(batch_texts)} texts)...",
            end=" ",
            flush=True,
        )

        try:
            # Get structured translations
            translations = translate_batch(batch_texts, target_lang, i)

            # Verify and apply translations
            for j, trans in enumerate(translations):
                # Double-check index matches
                expected_index = i + j
                if trans.index != expected_index:
                    raise ValueError(f"Index mismatch at position {j}")

                # Apply translation
                elem = batch_elements[j]
                elem.text = trans.translation

                # Remove 'unfinished' attribute
                if "type" in elem.attrib:
                    del elem.attrib["type"]

            success_count += len(translations)
            print(f"✅ {len(translations)}")

        except Exception as e:
            print(f"❌ {type(e).__name__}: {str(e)[:50]}")
            continue

    # Save with pretty formatting
    print("\n💾 Saving translations...")
    tree.write(ts_file, encoding="utf-8", xml_declaration=True)

    # Summary
    print("─" * 60)
    print(f"✨ Complete! {success_count}/{total} translations applied")
    print(f"📁 File: {ts_file}")
    print("\n💡 Next steps:")
    print(f"   1. Review: linguist {ts_file}")
    print(f"   2. Compile: ./scripts/trans-compile.sh")
    print(f"   3. Test: Switch to {target_lang} in app\n")


# ============================================================================
# CLI Entry Point
# ============================================================================


def main():
    # Validate arguments
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ts_file = Path(sys.argv[1])

    # Validate file exists
    if not ts_file.exists():
        print(f"❌ File not found: {ts_file}")
        sys.exit(1)

    # Auto-detect target language
    try:
        target_lang = detect_target_language(ts_file.name)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Banner
    print("\n" + "=" * 60)
    print("🌐 OpenAI Structured Translation")
    print("=" * 60)
    print(f"📄 File: {ts_file.name}")
    print(f"🎯 Target: {target_lang} (auto-detected)")
    print("=" * 60 + "\n")

    # Execute translation
    try:
        translate_file(ts_file, target_lang)
    except KeyboardInterrupt:
        print("\n\n⚠️  Translation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
