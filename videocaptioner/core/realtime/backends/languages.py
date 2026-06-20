from __future__ import annotations

AUTO = "auto"

# Fun-ASR 两个实时模型各自的支持集（不含 auto）；后端 _language_hints 按模型取用。
FUN_ASR_MTL_LANGS: tuple[str, ...] = ("zh", "yue", "en", "ja", "th", "vi", "id")
FUN_ASR_REALTIME_LANGS: tuple[str, ...] = ("zh", "en", "ja")

# 每个 provider 的识别语言下拉集（含 auto，且 auto 在首位）。
VOXGATE_LANGS: tuple[str, ...] = (AUTO, "zh", "en")
FUN_ASR_LANGS: tuple[str, ...] = (AUTO, *FUN_ASR_MTL_LANGS)
QWEN_ASR_LANGS: tuple[str, ...] = (
    AUTO,
    "zh", "yue", "en", "es", "ja", "ko", "fr", "de", "pt", "ru",
    "it", "ar", "hi", "id", "th", "vi", "tr", "uk", "ms", "fil",
    "pl", "cs", "sv", "da", "no", "fi", "is",
)

PROVIDER_SOURCE_LANGS: dict[str, tuple[str, ...]] = {
    "voxgate": VOXGATE_LANGS,
    "fun-asr": FUN_ASR_LANGS,
    "qwen-asr": QWEN_ASR_LANGS,
}


def source_lang_codes(provider: str) -> tuple[str, ...]:
    """该 provider 支持的识别语言 code（含 auto）；未知 provider 退回 voxgate 的中英集。"""
    return PROVIDER_SOURCE_LANGS.get(provider, VOXGATE_LANGS)


def all_source_lang_codes() -> list[str]:
    """所有 provider 支持语言的并集（保序去重）。校验器用：任一 provider 的选择都能持久化。"""
    seen: dict[str, None] = {}
    for codes in PROVIDER_SOURCE_LANGS.values():
        for code in codes:
            seen.setdefault(code, None)
    return list(seen)
