"""Dubbing provider/model/voice presets."""

from dataclasses import dataclass

SILICONFLOW_COSYVOICE2_MODEL = "FunAudioLLM/CosyVoice2-0.5B"

SILICONFLOW_VOICE_ALIASES = {
    "anna": f"{SILICONFLOW_COSYVOICE2_MODEL}:anna",
    "alex": f"{SILICONFLOW_COSYVOICE2_MODEL}:alex",
    "benjamin": f"{SILICONFLOW_COSYVOICE2_MODEL}:benjamin",
}

GEMINI_VOICES = {
    "Achird",
    "Aoede",
    "Autonoe",
    "Callirrhoe",
    "Charon",
    "Despina",
    "Enceladus",
    "Erinome",
    "Fenrir",
    "Gacrux",
    "Iapetus",
    "Kore",
    "Laomedeia",
    "Leda",
    "Orus",
    "Puck",
    "Pulcherrima",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Sulafat",
    "Umbriel",
    "Vindemiatrix",
    "Zephyr",
    "Zubenelgenubi",
}


@dataclass(frozen=True)
class DubbingPreset:
    name: str
    provider: str
    api_base: str
    model: str
    voice: str
    style_prompt: str = ""


PRESETS: dict[str, DubbingPreset] = {
    "siliconflow-cn-female": DubbingPreset(
        name="siliconflow-cn-female",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["anna"],
        style_prompt="请用自然、清晰、适合视频配音的中文语气朗读。",
    ),
    "siliconflow-cn-male": DubbingPreset(
        name="siliconflow-cn-male",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["alex"],
        style_prompt="请用自然、清晰、适合视频配音的中文语气朗读。",
    ),
    "siliconflow-cn-deep-male": DubbingPreset(
        name="siliconflow-cn-deep-male",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["benjamin"],
        style_prompt="请用沉稳、清晰、适合视频配音的中文语气朗读。",
    ),
    "gemini-en-neutral": DubbingPreset(
        name="gemini-en-neutral",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        style_prompt="Read naturally and clearly for a video dubbing track.",
    ),
    "gemini-en-friendly": DubbingPreset(
        name="gemini-en-friendly",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Achird",
        style_prompt="Read in a friendly, natural, conversational voice for a video dubbing track.",
    ),
    "gemini-en-upbeat": DubbingPreset(
        name="gemini-en-upbeat",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Puck",
        style_prompt="Read in an upbeat, clear, energetic voice for a video dubbing track.",
    ),
}


def get_dubbing_preset(name: str) -> DubbingPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown dubbing preset: {name}. Available presets: {available}") from exc


def available_dubbing_presets() -> list[str]:
    return sorted(PRESETS)


def normalize_dubbing_voice(provider: str, model: str, voice: str) -> str:
    """Convert user-facing voice names to provider-native voice IDs."""
    if not voice:
        return voice
    if provider == "siliconflow":
        lowered = voice.lower()
        if lowered in SILICONFLOW_VOICE_ALIASES:
            return SILICONFLOW_VOICE_ALIASES[lowered]
        if ":" not in voice and "/" not in voice:
            return f"{model}:{voice}"
        return voice
    if provider == "gemini":
        for known in GEMINI_VOICES:
            if voice.lower() == known.lower():
                return known
        return voice
    return voice


def validate_dubbing_voice(provider: str, voice: str) -> str | None:
    """Return an error message when a voice does not match provider constraints."""
    if not voice:
        return None
    if provider == "gemini" and voice not in GEMINI_VOICES:
        available = ", ".join(sorted(GEMINI_VOICES))
        return f"Unknown Gemini voice: {voice}. Available voices: {available}"
    if provider == "siliconflow" and ":" not in voice:
        return "SiliconFlow voice must be a built-in alias or a provider voice ID like model:voice"
    return None
