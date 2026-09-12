from __future__ import annotations

import shutil
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from videocaptioner.config import ASSETS_PATH
from videocaptioner.core.realtime.backends.base import SAMPLE_RATE
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.realtime.events import TranscriptSegment
from videocaptioner.core.realtime.factory import build_backend
from videocaptioner.core.utils.video_utils import video2audio

TEST_AUDIO_PATH = ASSETS_PATH / "en.mp3"

_CHUNK_MS = 100  # 每次喂 100ms PCM
_PACE_S = 0.08  # 略快于实时：给 fun-asr 实时 WS 留节奏，又不至于太久
_GRACE_S = 12.0  # 喂完后等待后端冲刷出末句文本的上限


@dataclass(frozen=True)
class LiveCaptionCheckResult:
    """实时字幕检查结果：成功时 detail 是识别出的文本，失败时是错误信息。"""

    success: bool
    detail: str


def check_live_caption(
    config: LiveCaptionConfig, audio_path: str | Path | None = None
) -> LiveCaptionCheckResult:
    """用短音频真实转录一次，验证当前实时字幕引擎可用。"""
    path = Path(audio_path) if audio_path else TEST_AUDIO_PATH
    if not path.exists():
        return LiveCaptionCheckResult(False, f"测试音频不存在: {path}")
    work_dir = Path(tempfile.mkdtemp(prefix="videocaptioner-live-check-"))
    try:
        # 实时后端只吃 16k/mono/s16le PCM：先抽成标准 WAV 再喂。
        wav_path = work_dir / "check.wav"
        if not video2audio(str(path), output=str(wav_path)):
            return LiveCaptionCheckResult(False, "ffmpeg 提取测试音频失败")
        with wave.open(str(wav_path), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
        if not pcm:
            return LiveCaptionCheckResult(False, "测试音频解码为空")
        return _run_backend(config, pcm)
    except Exception as exc:  # noqa: BLE001 —— 各后端抛错类型不一，统一收敛为结果
        return LiveCaptionCheckResult(False, str(exc) or type(exc).__name__)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _run_backend(config: LiveCaptionConfig, pcm: bytes) -> LiveCaptionCheckResult:
    latest = ""
    errors: list[str] = []

    def on_segment(seg: TranscriptSegment) -> None:
        nonlocal latest
        if seg.text and seg.text.strip():
            latest = seg.text.strip()

    backend = build_backend(
        config,
        on_segment=on_segment,
        on_state=lambda *_: None,
        on_error=errors.append,
    )
    backend.start()
    try:
        step = SAMPLE_RATE * _CHUNK_MS // 1000 * 2  # 每块字节数（s16le）
        for off in range(0, len(pcm), step):
            backend.feed(pcm[off : off + step])
            time.sleep(_PACE_S)
        # 喂完后等后端吐字：已有文本就再给 1s 补全末句即收尾，全程无字才等满 _GRACE_S
        deadline = time.monotonic() + _GRACE_S
        while not errors and time.monotonic() < deadline:
            if latest:
                time.sleep(1.0)
                break
            time.sleep(0.1)
    finally:
        backend.stop()  # voxgate: 关 stdin(EOF) 让其冲刷末段并退出；此后 latest 才最终落定
    if latest:
        return LiveCaptionCheckResult(True, latest)
    if errors:
        return LiveCaptionCheckResult(False, errors[-1])
    return LiveCaptionCheckResult(False, "转录请求成功但结果为空")
