"""统一的媒体信息探测：解析 ``ffmpeg -i`` 的 stderr 元数据，不依赖 ffprobe。

ffmpeg 对只有 ``-i`` 的调用固定以非 0 退出，并把媒体元数据打印到 stderr；
这里只做文本解析，因此桌面包只需携带 ffmpeg 一个二进制。
全项目的「这个文件是什么媒体」问题统一经由 :func:`probe_media` 回答。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("media_info")

_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+\.?\d*)")
_BITRATE_RE = re.compile(r"bitrate: (\d+) kb/s")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
# 裸流/VFR 容器可能只报 tbr 不报 fps；tbn 是时基（常为 90k/16k）不能当帧率
_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr")
_AUDIO_RE = re.compile(
    r"Stream #\d+:(\d+)(?:\[0x[0-9a-fA-F]+\])?(?:\(([a-z]{3})\))?.*?: Audio: (\w+)"
)
_HZ_RE = re.compile(r"(\d+) Hz")


@dataclass(frozen=True)
class AudioStream:
    """媒体中的一条音频流（多音轨选择用）。"""

    index: int
    codec: str
    language: str = ""


@dataclass(frozen=True)
class MediaInfo:
    """一次 :func:`probe_media` 的结果。纯音频文件的视频字段为 0/空。"""

    duration_seconds: float = 0.0
    bitrate_kbps: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_streams: tuple[AudioStream, ...] = ()
    audio_codec: str = ""
    audio_sampling_rate: int = 0

    @property
    def has_video(self) -> bool:
        return bool(self.video_codec)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_streams)

    @property
    def resolution(self) -> tuple[int, int]:
        return self.width, self.height


def probe_media(file_path: str) -> MediaInfo | None:
    """探测媒体文件信息；不是有效媒体（无任何音视频流）或探测失败时返回 None。

    调用方无法从 None 区分「ffmpeg 不可用」与「文件无效」；需要区分时
    自行先 ``shutil.which("ffmpeg")``（如 UI 报错文案），原因也会写日志。
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATIONFLAGS,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # OSError 覆盖 FileNotFoundError/PermissionError（如杀软锁二进制）——探测失败按无处理
        logger.error("媒体探测失败（ffmpeg 不可用或超时）: %s", exc)
        return None
    info = _parse_ffmpeg_output(result.stderr or "")
    if info.has_video or info.has_audio:
        return info
    logger.warning("文件没有任何音视频流: %s", file_path)
    return None


def _parse_ffmpeg_output(text: str) -> MediaInfo:
    """逐行解析 ffmpeg -i 的 stderr（行级解析，避免跨行正则误匹配）。"""
    duration = 0.0
    bitrate = 0
    width = height = 0
    fps = 0.0
    video_codec = ""
    audio_codec = ""
    audio_hz = 0
    audio_streams: list[AudioStream] = []

    for line in text.splitlines():
        if not video_codec and (m := _VIDEO_RE.search(line)):
            # 音频文件的内嵌封面也是一条 Video 流（mjpeg/png, attached pic），不算视频
            if "attached pic" in line:
                continue
            video_codec = m.group(1)
            width, height = int(m.group(2)), int(m.group(3))
            if fm := _FPS_RE.search(line) or _TBR_RE.search(line):
                fps = float(fm.group(1))
        elif m := _AUDIO_RE.search(line):
            audio_streams.append(
                AudioStream(index=int(m.group(1)), codec=m.group(3), language=m.group(2) or "")
            )
            if not audio_codec:
                audio_codec = m.group(3)
                if hz := _HZ_RE.search(line):
                    audio_hz = int(hz.group(1))
        elif m := _DURATION_RE.search(line):
            h, mi, s = m.groups()
            duration = int(h) * 3600 + int(mi) * 60 + float(s)
            if bm := _BITRATE_RE.search(line):
                bitrate = int(bm.group(1))

    return MediaInfo(
        duration_seconds=duration,
        bitrate_kbps=bitrate,
        width=width,
        height=height,
        fps=fps,
        video_codec=video_codec,
        audio_streams=tuple(audio_streams),
        audio_codec=audio_codec,
        audio_sampling_rate=audio_hz,
    )


def extract_thumbnail(video_path: str, thumbnail_path: str, seek_seconds: float) -> bool:
    """在 ``seek_seconds`` 处抽一帧存为缩略图；成功返回 True。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(thumbnail_path)), exist_ok=True)
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(max(0.0, seek_seconds)),
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                thumbnail_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATIONFLAGS,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("缩略图提取失败: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning("缩略图提取失败: %s", (result.stderr or "").strip()[-200:])
        return False
    return os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0
