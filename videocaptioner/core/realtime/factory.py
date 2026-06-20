"""把 :class:`LiveCaptionConfig` 装配成具体后端 / 翻译函数。

新增后端在 :func:`build_backend` 加分支；翻译服务复用 ``TranslatorFactory``。
core 层不反向依赖 UI。
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.realtime.backends.base import (
    LiveCaptionError,
    LiveTranscriber,
    OnError,
    OnSegment,
    OnState,
)
from videocaptioner.core.realtime.backends.voxgate import VoxgateBackend, find_voxgate_binary
from videocaptioner.core.realtime.caption import TranslateFn
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.types import TranslatorType
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_factory")


def _target_lang_code(target) -> str:
    """把目标语言枚举归到 zh/en/ja 大类码（用于判断「目标==所说语言」）。
    按枚举成员名归类、不随显示文案变；其它语言返回 ""（照常翻译）。"""
    name = (getattr(target, "name", "") or "").upper()
    if "CHINESE" in name or name == "CANTONESE":
        return "zh"
    if name.startswith("ENGLISH"):
        return "en"
    if name == "JAPANESE":
        return "ja"
    return ""


class _LazyTranslator:
    """首次调用时再构造底层翻译器（构造会联网），失败后静默禁用。"""

    def __init__(self, cfg: LiveCaptionConfig) -> None:
        self._cfg = cfg
        self._tr = None
        self._lock = threading.Lock()
        self._failed = False

    def translate(self, text: str) -> str:
        if self._failed or not text.strip() or self._looks_same_language(text):
            return ""
        with self._lock:
            if self._tr is None:
                try:
                    # LLM 翻译器（OPENAI）从 OPENAI_API_KEY/BASE_URL 环境变量取凭据，
                    # 故建器前先把所选 provider 的 key/base 写入环境变量。
                    if self._cfg.translator_type == TranslatorType.OPENAI:
                        if self._cfg.llm_api_key and self._cfg.llm_api_base:
                            os.environ["OPENAI_API_KEY"] = self._cfg.llm_api_key
                            os.environ["OPENAI_BASE_URL"] = self._cfg.llm_api_base
                        else:
                            logger.warning("实时字幕 LLM 翻译未配置 Key/Base，已禁用译文。")
                            self._failed = True
                            return ""
                    self._tr = TranslatorFactory.create_translator(
                        translator_type=self._cfg.translator_type,
                        thread_num=1,
                        batch_num=1,
                        target_language=self._cfg.target_language,
                        model=self._cfg.llm_model,
                        # 实时翻译关思考求低延迟（仅 LLM 翻译生效；不支持的端点由 call_llm 去掉）。
                        disable_thinking=True,
                    )
                except Exception as exc:
                    logger.warning("实时翻译器初始化失败，已禁用译文：%s", exc)
                    self._failed = True
                    return ""
        try:
            data = [SubtitleProcessData(index=0, original_text=text)]
            self._tr._translate_chunk(data)
            out = data[0].translated_text or ""
        except Exception as exc:
            logger.debug("实时翻译失败（已忽略）：%s", exc)
            return ""
        # 译文≈原文（目标==所说语言）→ 返回空、源文单显。否则同语言时译文滞后于生长中的原文，
        # has_tgt 在相等/不等间反复切，导致译文行闪烁后消失。
        if out.strip() == text.strip():
            return ""
        return out

    def _looks_same_language(self, text: str) -> bool:
        """按文本实际字符构成判断主语言是否 == 目标语言，不依赖用户配置的识别语言
        （可能设错或被多语模型识别成别的语言）。只分 zh / en / ja 三大类。"""
        tgt = _target_lang_code(self._cfg.target_language)
        if not tgt:
            return False
        if any("぀" <= c <= "ヿ" for c in text):  # 含假名 → 日文
            return tgt == "ja"
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        latin = sum(1 for c in text if c.isascii() and c.isalpha())
        if cjk + latin == 0:
            return False
        return tgt == ("zh" if cjk >= latin else "en")

    def close(self) -> None:
        if self._tr is not None:
            try:
                self._tr.stop()
            except Exception:
                pass


def build_translate_fn(cfg: LiveCaptionConfig) -> Optional[TranslateFn]:
    """翻译关闭时返回 None；否则返回 ``translate(text) -> str``。"""
    if not cfg.translate_enabled:
        return None
    return _LazyTranslator(cfg).translate


def build_backend(
    cfg: LiveCaptionConfig,
    on_segment: OnSegment,
    on_state: OnState,
    on_error: OnError,
) -> LiveTranscriber:
    if cfg.backend == "voxgate":
        binary = find_voxgate_binary(cfg.voxgate_binary)
        if not binary:
            raise LiveCaptionError(
                "未找到 voxgate 可执行文件。请在设置中指定其路径，或把二进制放入应用 bin 目录。"
            )
        return VoxgateBackend(
            binary=binary,
            # -l 仅是语言提示、不限制实际识别（豆包多语）；auto 退化为 zh 提示。
            language=("zh" if cfg.source_language == "auto" else cfg.source_language),
            on_segment=on_segment,
            on_state=on_state,
            on_error=on_error,
        )
    if cfg.backend == "fun-asr":
        from videocaptioner.core.realtime.backends.fun_asr import FunAsrBackend

        return FunAsrBackend(
            api_key=cfg.api_key,
            model=cfg.asr_model,
            language=cfg.source_language,
            on_segment=on_segment,
            on_state=on_state,
            on_error=on_error,
        )
    if cfg.backend == "qwen-asr":
        from videocaptioner.core.realtime.backends.qwen_asr import QwenAsrBackend

        # Qwen-ASR 实时只有一个模型（qwen3-asr-flash-realtime），用后端默认即可，无需配置项。
        # source_language="auto" 时后端省略 language → 服务端在 27 种语言里自动检测。
        return QwenAsrBackend(
            api_key=cfg.api_key,
            language=cfg.source_language,
            on_segment=on_segment,
            on_state=on_state,
            on_error=on_error,
        )
    raise LiveCaptionError(f"未知的实时转录后端：{cfg.backend}")
