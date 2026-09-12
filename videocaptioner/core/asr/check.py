"""转录服务连通性检查：所有提供商统一入口。

用内置短音频跑一次真实转录（B 接口 / J 接口 / Whisper API / 百炼
Fun-ASR / whisper-cpp / faster-whisper 全部走生产路径），设置页的
「测试转录」按钮与 ``videocaptioner doctor --check-api`` 共用。

强制 use_cache=False：缓存命中会让坏掉的 Key/服务误报成功。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from videocaptioner.config import ASSETS_PATH
from videocaptioner.core.asr.transcribe import transcribe
from videocaptioner.core.entities import SubtitleLayoutEnum, TranscribeConfig
from videocaptioner.core.utils.video_utils import video2audio

TEST_AUDIO_PATH = ASSETS_PATH / "en.mp3"


@dataclass(frozen=True)
class TranscribeCheckResult:
    """转录检查结果：成功时 detail 是识别出的文本，失败时是错误信息。"""

    success: bool
    detail: str


def check_transcribe(
    config: TranscribeConfig, audio_path: str | Path | None = None
) -> TranscribeCheckResult:
    """用短音频真实转录一次，验证当前转录服务可用。"""
    path = Path(audio_path) if audio_path else TEST_AUDIO_PATH
    if not path.exists():
        return TranscribeCheckResult(False, f"测试音频不存在: {path}")
    work_dir = Path(tempfile.mkdtemp(prefix="videocaptioner-asr-check-"))
    try:
        # 与生产链路一致：先抽 16kHz 单声道 WAV 再转录（本地引擎只收 WAV）
        wav_path = work_dir / "check.wav"
        if not video2audio(str(path), output=str(wav_path)):
            return TranscribeCheckResult(False, "ffmpeg 提取测试音频失败")
        asr_data = transcribe(str(wav_path), config, use_cache=False)
    except Exception as exc:  # noqa: BLE001 —— 各提供商抛错类型不一，统一收敛为结果
        return TranscribeCheckResult(False, str(exc) or type(exc).__name__)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    text = " ".join(
        asr_data.to_txt(layout=SubtitleLayoutEnum.ONLY_ORIGINAL).split()
    ).strip()
    if not text:
        return TranscribeCheckResult(False, "转录请求成功但结果为空")
    return TranscribeCheckResult(True, text)
