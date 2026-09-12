"""Dubbing provider/model/voice presets."""

from dataclasses import dataclass

SILICONFLOW_COSYVOICE2_MODEL = "FunAudioLLM/CosyVoice2-0.5B"

SILICONFLOW_VOICE_ALIASES = {
    "anna": f"{SILICONFLOW_COSYVOICE2_MODEL}:anna",
    "alex": f"{SILICONFLOW_COSYVOICE2_MODEL}:alex",
    "bella": f"{SILICONFLOW_COSYVOICE2_MODEL}:bella",
    "benjamin": f"{SILICONFLOW_COSYVOICE2_MODEL}:benjamin",
    "charles": f"{SILICONFLOW_COSYVOICE2_MODEL}:charles",
    "claire": f"{SILICONFLOW_COSYVOICE2_MODEL}:claire",
    "david": f"{SILICONFLOW_COSYVOICE2_MODEL}:david",
    "diana": f"{SILICONFLOW_COSYVOICE2_MODEL}:diana",
}

GEMINI_VOICES = {
    "Achernar",
    "Achird",
    "Algenib",
    "Algieba",
    "Alnilam",
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

EDGE_VOICE_ALIASES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
    "yunjian": "zh-CN-YunjianNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "yunxia": "zh-CN-YunxiaNeural",
    "yunyang": "zh-CN-YunyangNeural",
    "hiugaai": "zh-HK-HiuGaaiNeural",
    "hiumaan": "zh-HK-HiuMaanNeural",
    "wanlung": "zh-HK-WanLungNeural",
    "hsiaochen": "zh-TW-HsiaoChenNeural",
    "hsiaoyu": "zh-TW-HsiaoYuNeural",
    "yunjhe": "zh-TW-YunJheNeural",
    "ava": "en-US-AvaNeural",
    "andrew": "en-US-AndrewNeural",
    "emma": "en-US-EmmaNeural",
    "brian": "en-US-BrianNeural",
    "jenny": "en-US-JennyNeural",
    "guy": "en-US-GuyNeural",
    "aria": "en-US-AriaNeural",
    "libby": "en-GB-LibbyNeural",
    "ryan": "en-GB-RyanNeural",
    "sonia": "en-GB-SoniaNeural",
    "thomas": "en-GB-ThomasNeural",
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
    "edge-cn-female": DubbingPreset(
        name="edge-cn-female",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["xiaoxiao"],
    ),
    "edge-cn-male": DubbingPreset(
        name="edge-cn-male",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["yunxi"],
    ),
    "edge-en-female": DubbingPreset(
        name="edge-en-female",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["jenny"],
    ),
    "edge-en-male": DubbingPreset(
        name="edge-en-male",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["guy"],
    ),
}

for _preset_name, _alias, _prompt in [
    ("siliconflow-cn-bella", "bella", "请用热情、清晰、适合视频配音的中文语气朗读。"),
    ("siliconflow-cn-charles", "charles", "请用磁性、清晰、适合视频配音的中文语气朗读。"),
    ("siliconflow-cn-claire", "claire", "请用温柔、清晰、适合视频配音的中文语气朗读。"),
    ("siliconflow-cn-david", "david", "请用欢快、清晰、适合视频配音的中文语气朗读。"),
    ("siliconflow-cn-diana", "diana", "请用欢快、清晰、适合视频配音的中文语气朗读。"),
]:
    PRESETS[_preset_name] = DubbingPreset(
        name=_preset_name,
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES[_alias],
        style_prompt=_prompt,
    )

for _preset_name, _alias, _prompt in [
    ("edge-cn-xiaoyi", "xiaoyi", ""),
    ("edge-cn-yunjian", "yunjian", ""),
    ("edge-cn-yunyang", "yunyang", ""),
    ("edge-cn-yunxia", "yunxia", ""),
    ("edge-hk-hiugaai", "hiugaai", ""),
    ("edge-hk-hiumaan", "hiumaan", ""),
    ("edge-hk-wanlung", "wanlung", ""),
    ("edge-tw-hsiaochen", "hsiaochen", ""),
    ("edge-tw-hsiaoyu", "hsiaoyu", ""),
    ("edge-tw-yunjhe", "yunjhe", ""),
    ("edge-en-ava", "ava", ""),
    ("edge-en-andrew", "andrew", ""),
    ("edge-en-emma", "emma", ""),
    ("edge-en-brian", "brian", ""),
    ("edge-en-aria", "aria", ""),
    ("edge-en-libby", "libby", ""),
    ("edge-en-ryan", "ryan", ""),
    ("edge-en-sonia", "sonia", ""),
    ("edge-en-thomas", "thomas", ""),
]:
    PRESETS[_preset_name] = DubbingPreset(
        name=_preset_name,
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES[_alias],
        style_prompt=_prompt,
    )

for _voice, _style in [
    ("Zephyr", "bright"),
    ("Puck", "upbeat"),
    ("Charon", "informative"),
    ("Kore", "firm"),
    ("Fenrir", "excitable"),
    ("Leda", "youthful"),
    ("Orus", "firm"),
    ("Aoede", "breezy"),
    ("Callirrhoe", "easy-going"),
    ("Autonoe", "bright"),
    ("Enceladus", "breathy"),
    ("Iapetus", "clear"),
    ("Umbriel", "easy-going"),
    ("Algieba", "smooth"),
    ("Despina", "smooth"),
    ("Erinome", "clear"),
    ("Algenib", "gravelly"),
    ("Rasalgethi", "informative"),
    ("Laomedeia", "upbeat"),
    ("Achernar", "soft"),
    ("Alnilam", "firm"),
    ("Schedar", "even"),
    ("Gacrux", "mature"),
    ("Pulcherrima", "forward"),
    ("Achird", "friendly"),
    ("Zubenelgenubi", "casual"),
    ("Vindemiatrix", "gentle"),
    ("Sadachbia", "lively"),
    ("Sadaltager", "knowledgeable"),
    ("Sulafat", "warm"),
]:
    _preset_name = f"gemini-{_voice.lower()}"
    PRESETS.setdefault(
        _preset_name,
        DubbingPreset(
            name=_preset_name,
            provider="gemini",
            api_base="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-3.1-flash-tts-preview",
            voice=_voice,
            style_prompt=f"Read in a {_style}, natural voice for a video dubbing track.",
        ),
    )


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
    if provider == "edge":
        lowered = voice.lower()
        if lowered in EDGE_VOICE_ALIASES:
            return EDGE_VOICE_ALIASES[lowered]
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
    if provider == "edge":
        normalized = normalize_dubbing_voice(provider, "", voice)
        if normalized in EDGE_VOICE_ALIASES.values():
            return None
        if not normalized.endswith("Neural") or normalized.count("-") < 2:
            aliases = ", ".join(sorted(EDGE_VOICE_ALIASES))
            return f"Edge TTS voice must be a short alias ({aliases}) or a full voice ID like zh-CN-XiaoxiaoNeural"
    return None
