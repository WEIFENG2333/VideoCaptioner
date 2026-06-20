"""实时字幕的运行配置（纯数据，无 Qt）。

UI / CLI 各自的设置归一成 :class:`LiveCaptionConfig` 交给 session；core 层只认这个
dataclass，不反向依赖上层配置框架。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from videocaptioner.core.translate.types import TargetLanguage, TranslatorType


class LiveCaptionSource(Enum):
    """音频来源类型。"""

    MICROPHONE = "microphone"  # 麦克风
    SYSTEM = "system"  # 系统声音 / 回环（看片场景）；依赖回环输入设备


@dataclass(frozen=True)
class LiveCaptionConfig:
    """一次实时字幕会话的完整配置。"""

    # --- 后端 ---
    backend: str = "voxgate"  # "voxgate" | "fun-asr" | "qwen-asr"
    # voxgate 子进程：可执行文件路径（空则自动发现 resource/bin → PATH）
    voxgate_binary: str = ""
    # 云后端（fun-asr 等）：API Key + 模型 + 识别语言提示（voxgate 也用 source_language 作 -l）
    api_key: str = ""
    asr_model: str = ""
    source_language: str = "zh"

    # --- 音频 ---
    source: LiveCaptionSource = LiveCaptionSource.MICROPHONE
    device_index: Optional[int] = None  # None = 系统默认输入设备
    # macOS 原生系统声音捕获（ScreenCaptureKit，免装 BlackHole）。为真时忽略 device_index，
    # 改用 macsysaudio 子进程采本机播放声。仅 macOS 13+，需「屏幕录制」权限。
    system_audio_native: bool = False

    # --- 翻译 ---
    translate_enabled: bool = True
    translator_type: TranslatorType = TranslatorType.BING
    target_language: TargetLanguage = TargetLanguage.SIMPLIFIED_CHINESE
    # LLM 翻译（translator_type=OPENAI）专用：当前 LLM provider 的 key/base/model。
    # LLMTranslator 经环境变量取 key/base，故工厂建它前会把这里的值写进环境变量。
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_api_base: str = ""
