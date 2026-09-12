"""本地音频采集（sounddevice / PortAudio）→ 16k/mono/s16le PCM。

首选 16k 单声道打开，系统按需做抗混叠重采样；设备不收单声道则回退原生声道数、回调里按声道
均值下混（非取声道 0，防非对称设备丢音）。回调只入队（满丢最新块）、不阻塞不抛异常；上层用
read() 拉取。

macOS 系统声音走 audio/system_mac.py，不经本模块。
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import List, Optional

from videocaptioner.core.realtime.backends.base import SAMPLE_RATE
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_audio")


class AudioSourceError(RuntimeError):
    """音频采集错误（无设备 / 打开失败）。"""


@dataclass(frozen=True)
class AudioDevice:
    """一个可选的输入设备。"""

    index: int
    name: str
    is_default: bool


def _sd():
    """延迟导入 sounddevice：导入即加载 PortAudio，放到真正用时再触发。"""
    try:
        import sounddevice  # noqa: PLC0415
    except Exception as exc:  # PortAudio 缺失等
        raise AudioSourceError(f"无法加载音频库 sounddevice：{exc}") from exc
    return sounddevice


def list_input_devices() -> List[AudioDevice]:
    """枚举所有可用输入设备（max_input_channels > 0）。"""
    sd = _sd()
    try:
        devices = sd.query_devices()
        default_in = sd.default.device[0]
    except Exception as exc:
        raise AudioSourceError(f"枚举音频设备失败：{exc}") from exc

    result: List[AudioDevice] = []
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        result.append(
            AudioDevice(
                index=idx,
                name=dev.get("name", f"设备 {idx}"),
                is_default=(idx == default_in),
            )
        )
    return result


class AudioCapture:
    """从一个输入设备以 16k/mono/s16le 采集，按块入队供拉取。"""

    def __init__(self, device_index: Optional[int] = None, queue_max: int = 256) -> None:
        self._device_index = device_index
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=queue_max)
        self._stream = None
        self._channels = 1  # 实际打开的声道数（>1 时回调里均值下混成 mono）
        self._dropped = 0
        self._overruns = 0

    def _device_max_channels(self, sd) -> int:  # noqa: ANN001
        """目标设备的最大输入声道数（默认设备 None 也解析到真实设备）；查不到返回 0。"""
        try:
            index = self._device_index
            if index is None:
                index = sd.default.device[0]
            info = sd.query_devices(index)
            return int(info.get("max_input_channels", 0))
        except Exception:
            return 0

    def start(self) -> None:
        sd = _sd()
        # 部分设备拒绝单声道打开：先试 1 声道，不收则回退原生声道数，多声道由回调下混成 mono。
        candidates = []
        for ch in (1, self._device_max_channels(sd), 2):
            if ch >= 1 and ch not in candidates:
                candidates.append(ch)
        last_exc: Optional[Exception] = None
        for ch in candidates:
            stream = None
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=ch,
                    dtype="int16",
                    device=self._device_index,
                    blocksize=SAMPLE_RATE // 20,  # ~50ms 一块
                    callback=self._callback,
                )
                stream.start()
            except Exception as exc:
                last_exc = exc
                if stream is not None:  # start() 失败先关掉，避免泄漏 PortAudio 流
                    try:
                        stream.close()
                    except Exception:
                        pass
                continue
            self._stream = stream
            self._channels = ch
            logger.info("音频采集已启动：设备=%s 声道=%d @16k", self._device_index, ch)
            return
        raise AudioSourceError(
            f"打开音频输入失败（无法以 16kHz 打开该设备，请在设置里换一个输入设备）：{last_exc}"
        ) from last_exc

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status and getattr(status, "input_overflow", False):
            # 输入溢出：音频在入队前已被设备/回调丢弃，计数告警
            self._overruns += 1
            if self._overruns % 20 == 1:
                logger.warning("音频采集 overflow ×%d：回调跟不上，可能丢音频", self._overruns)
        # 多声道按声道均值下混成 mono（非取声道 0，防非对称设备丢音）；int32 累加防 int16 溢出。
        mono = (indata if self._channels == 1
                else indata.astype("int32").mean(axis=1).round().astype("int16").reshape(-1, 1))
        pcm = mono.tobytes()
        if not pcm:
            return
        try:
            self._queue.put_nowait(pcm)
        except queue.Full:
            # 队列满丢「最新」块（接缝落在实时边缘、危害最小）；绝不丢最旧，否则从语音中段挖洞。
            self._dropped += 1
            if self._dropped % 20 == 1:
                logger.warning("音频队列溢出丢帧 ×%d：消费端跟不上", self._dropped)

    def read(self, timeout: float = 0.1) -> Optional[bytes]:
        """拉取一块 PCM；超时返回 None（让上层有机会检查取消）。"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.debug("关闭音频流异常", exc_info=True)
