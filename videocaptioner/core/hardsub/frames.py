"""基于项目自带 ffmpeg 的抽帧（无 PyQt/OpenCV）：rawvideo 管道直出 numpy，多平台一致。

- ``grab_frame`` 单帧 / ``sample_frames`` 均匀 N 帧（区域检测）/ ``iter_roi_rgb`` 按间隔流式裁 ROI（提取）。
- 所有解码带 ``-noautorotate``：probe 读编码宽高，自动转向会让竖屏视频宽高互换、reshape 错切（静默损坏）。
"""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator, Optional

import numpy as np

from videocaptioner import config as app_config
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.media_info import probe_media

logger = setup_logger("hardsub_frames")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def ffmpeg_executable() -> str:
    """解析 ffmpeg 可执行路径（自带 bin → 用户 bin → PATH）；找不到回退裸名让系统再碰运气。"""
    return app_config.find_binary("ffmpeg") or "ffmpeg"


def probe_dimensions(video_path: str) -> Optional[tuple[int, int, float, float]]:
    """返回 (width, height, fps, duration_seconds)；失败返回 None。"""
    info = probe_media(video_path)
    if info is None or info.width <= 0 or info.height <= 0:
        return None
    fps = info.fps if info.fps > 0 else 25.0
    return info.width, info.height, fps, info.duration_seconds


def _read_exact(stream, size: int) -> Optional[bytes]:
    """从管道精确读满 size 字节（管道会分片返回，必须循环读满才算一帧）。"""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def grab_frame(video_path: str, t_sec: float, max_width: int = 0) -> Optional[np.ndarray]:
    """取 ``t_sec`` 处单帧为 RGB ndarray (H,W,3)。max_width>0 时等比缩到该宽度。

    ``-ss`` 放 ``-i`` 前 = 快速关键帧 seek，对框选预览足够（不需要精确到帧）。
    """
    dims = probe_dimensions(video_path)
    if dims is None:
        return None
    width, height, _, _ = dims
    vf = []
    if max_width and width > max_width:
        new_w = max_width
        new_h = int(round(height * max_width / width))
        new_h -= new_h % 2
        vf.append(f"scale={new_w}:{new_h}")
        out_w, out_h = new_w, new_h
    else:
        out_w, out_h = width, height
    cmd = [
        ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-noautorotate",
        "-ss", f"{max(0.0, t_sec):.3f}", "-i", video_path, "-frames:v", "1",
    ]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        out = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        logger.warning("抽帧失败 t=%.2f: %s", t_sec, exc)
        return None
    expected = out_w * out_h * 3
    if len(out) < expected:
        return None
    return np.frombuffer(out[:expected], np.uint8).reshape(out_h, out_w, 3)


def _grab_scaled(video_path: str, t_sec: float, out_w: int, out_h: int) -> Optional[np.ndarray]:
    """``-ss`` 快速 seek 抽 t 处单帧、缩到 out_w×out_h 的 RGB（区域采样用，定位到最近关键帧即可）。"""
    cmd = [
        ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-noautorotate",
        "-ss", f"{max(0.0, t_sec):.3f}", "-i", video_path, "-frames:v", "1",
        "-vf", f"scale={out_w}:{out_h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    try:
        out = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    expected = out_w * out_h * 3
    if len(out) < expected:
        return None
    return np.frombuffer(out[:expected], np.uint8).reshape(out_h, out_w, 3)


def sample_frames(
    video_path: str, count: int, max_width: int = 960
) -> list[tuple[float, np.ndarray]]:
    """均匀抽 ``count`` 帧（缩到 max_width 宽）为 RGB，给字幕区域自动检测。返回 [(时间秒, frame)]。

    用 ``count`` 个 ``-ss`` 快速 seek 并行抽帧，而非 ``fps`` 滤镜（后者全解码整段、长视频极慢）。
    """
    dims = probe_dimensions(video_path)
    if dims is None or count <= 0:
        return []
    width, height, _, duration = dims
    out_w = min(width, max_width)
    out_h = int(round(height * out_w / width))
    out_h -= out_h % 2
    if duration <= 0:
        single = _grab_scaled(video_path, 0.0, out_w, out_h)
        return [(0.0, single)] if single is not None else []

    interval = duration / count
    # 偏移半个间隔取每段中点，避开纯片头/片尾黑场
    timestamps = [min(duration, (k + 0.5) * interval) for k in range(count)]
    workers = min(8, max(2, (os.cpu_count() or 4)))
    frames: list[tuple[float, Optional[np.ndarray]]] = [(t, None) for t in timestamps]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_grab_scaled, video_path, t, out_w, out_h): i
            for i, t in enumerate(timestamps)
        }
        for fut in futures:
            i = futures[fut]
            try:
                frames[i] = (timestamps[i], fut.result())
            except Exception:  # noqa: BLE001
                pass
    return [(t, f) for t, f in frames if f is not None]


def iter_roi_rgb(
    video_path: str, roi: tuple[int, int, int, int], interval: float
) -> Iterator[tuple[float, np.ndarray]]:
    """按 ``interval`` 秒抽样，yield (时间秒, 裁过 ROI 的 RGB 帧 (h,w,3))。

    抽全帧后 numpy 裁 ROI（ffmpeg crop 滤镜会让文字错位/重影）；按帧号选帧（fps 滤镜会漂移到错误源帧）；
    用 RGB（gray 的亮度加权丢白边字对比度）。
    """
    dims = probe_dimensions(video_path)
    if dims is None:
        return
    src_w, src_h, fps, _ = dims
    x, y, w, h = roi
    if w <= 0 or h <= 0 or interval <= 0 or fps <= 0:
        return
    step = max(1, round(fps * interval))  # 每隔 step 个源帧取一帧
    out_interval = step / fps              # 实际采样间隔（≈ 请求的 interval）
    vf = f"select=not(mod(n\\,{step}))"
    cmd = [
        ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-noautorotate",
        "-i", video_path, "-vf", vf, "-vsync", "0",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    frame_bytes = src_w * src_h * 3
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=frame_bytes, creationflags=_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ROI 抽帧启动失败: %s", exc)
        return
    assert proc.stdout is not None
    k = 0
    try:
        while True:
            raw = _read_exact(proc.stdout, frame_bytes)
            if raw is None:
                break
            full = np.frombuffer(raw, np.uint8).reshape(src_h, src_w, 3)
            yield k * out_interval, full[y : y + h, x : x + w]
            k += 1
    finally:
        try:
            proc.stdout.close()
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
