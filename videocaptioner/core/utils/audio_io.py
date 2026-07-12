"""音频解码入口：ffmpeg 解码为内存 wav，喂给 pydub。

pydub 的 AudioSegment.from_file 对非 wav 输入依赖 ffprobe 探测源编码；
统一先用 ffmpeg 解码成 wav 再走 pydub 的原生 wav 路径（与 pydub 内部
的管道方案一致），整个应用与桌面包只需携带 ffmpeg 一个二进制。
"""

import io
import os
import subprocess
from typing import Union

from pydub import AudioSegment

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def load_audio(source: Union[str, bytes]) -> AudioSegment:
    """解码任意 ffmpeg 支持的音频为 AudioSegment。

    source 为文件路径或音频字节流；解码失败抛 RuntimeError。
    """
    cmd = ["ffmpeg", "-v", "error"]
    if isinstance(source, bytes):
        cmd += ["-i", "pipe:0"]
        stdin = source
    else:
        cmd += ["-i", str(source)]
        stdin = None
    cmd += ["-vn", "-f", "wav", "pipe:1"]

    result = subprocess.run(cmd, input=stdin, capture_output=True, creationflags=_NO_WINDOW)
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RuntimeError(f"ffmpeg audio decode failed: {detail}")
    return AudioSegment.from_wav(io.BytesIO(result.stdout))
