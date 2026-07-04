#!/usr/bin/env python3
"""Run real packaged-app smoke tests against a desktop bundle."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 cp1252，打印中文标签（如依赖校验的中文名）会 UnicodeEncodeError 崩掉
# 冒烟测试 → 拦住产物上传。强制 UTF-8 输出，跨平台一致。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def _run(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    print("+ " + " ".join(str(part) for part in cmd))
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True, text=True)


def _find_executable(bundle: Path) -> Path:
    if bundle.is_file():
        return bundle
    candidates = []
    if platform.system() == "Windows":
        candidates.append(bundle / "VideoCaptioner.exe")
    else:
        candidates.append(bundle / "VideoCaptioner")
        candidates.append(bundle / "VideoCaptioner.app" / "Contents" / "MacOS" / "VideoCaptioner")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"VideoCaptioner executable not found under {bundle}")


def _find_bundled_tool(bundle: Path, name: str) -> Path:
    exe_name = f"{name}.exe" if platform.system() == "Windows" else name
    candidates = [
        bundle / "_internal" / "resource" / "bin" / exe_name,
        bundle / "resource" / "bin" / exe_name,
        bundle / "VideoCaptioner.app" / "Contents" / "Frameworks" / "resource" / "bin" / exe_name,
        bundle / "VideoCaptioner.app" / "Contents" / "Resources" / "resource" / "bin" / exe_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    system_tool = shutil.which(name)
    if system_tool:
        return Path(system_tool)
    raise FileNotFoundError(f"{name} not found in bundle or PATH")


def _write_sample_srt(path: Path) -> None:
    path.write_text(
        "1\n"
        "00:00:00,100 --> 00:00:01,400\n"
        "Hello from VideoCaptioner.\n\n"
        "2\n"
        "00:00:01,500 --> 00:00:02,600\n"
        "这是一条真实合成测试字幕。\n",
        encoding="utf-8",
    )


def _write_smoke_config(path: Path) -> None:
    path.write_text(
        "[transcribe]\n"
        'asr = "bijian"\n\n'
        "[dubbing]\n"
        'provider = "edge"\n'
        'preset = "edge-cn-female"\n'
        'voice = "zh-CN-XiaoxiaoNeural"\n',
        encoding="utf-8",
    )


def _create_sample_video(ffmpeg: Path, output: Path) -> None:
    _run([
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=44100",
        "-t",
        "3",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        "-y",
        str(output),
    ])


def _duration(ffprobe: Path, media: Path) -> float:
    result = subprocess.run([
        str(ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media),
    ], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _check_bundled_payload(bundle: Path) -> None:
    """新功能的原生依赖必须真打进包；缺了让 smoke 失败，堵住『OCR/实时字幕没进包也 CI 绿』。

    voxgate 不在此列（按设计运行时下载）。仅对 onedir 目录校验（传单可执行文件时跳过）。
    """
    if bundle.is_file():
        return
    required = {
        "onnxruntime 原生库（硬字幕 OCR）": ["libonnxruntime*", "onnxruntime_pybind11_state*", "onnxruntime*.dll"],
        "rapidocr 模型（硬字幕 OCR）": ["*PP-OCR*.onnx", "*ppocr*.onnx"],
        "PortAudio（实时字幕采集）": ["libportaudio*", "portaudio*.dll"],
    }
    for label, globs in required.items():
        if not any(any(bundle.rglob(g)) for g in globs):
            raise RuntimeError(f"打包缺少新功能依赖：{label}（未在包内找到 {globs}）")
        print(f"Bundled payload OK: {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="Path to dist/VideoCaptioner or an executable")
    args = parser.parse_args()

    bundle = Path(args.bundle).resolve()
    exe = _find_executable(bundle)
    _check_bundled_payload(bundle)
    ffmpeg = _find_bundled_tool(bundle, "ffmpeg")
    ffprobe = _find_bundled_tool(bundle, "ffprobe")

    with tempfile.TemporaryDirectory(prefix="videocaptioner-smoke-") as tmp:
        tmp_path = Path(tmp)
        env = os.environ.copy()
        env["PATH"] = str(ffmpeg.parent) + os.pathsep + os.defpath
        env["VIDEOCAPTIONER_CONFIG_FILE"] = str(tmp_path / "config.toml")
        env["VIDEOCAPTIONER_LLM_API_KEY"] = ""
        env["VIDEOCAPTIONER_TTS_API_KEY"] = ""
        _write_smoke_config(Path(env["VIDEOCAPTIONER_CONFIG_FILE"]))

        video = tmp_path / "sample.mp4"
        subtitle = tmp_path / "sample.srt"
        soft_out = tmp_path / "sample-soft.mp4"
        hard_out = tmp_path / "sample-hard.mp4"
        _write_sample_srt(subtitle)
        _create_sample_video(ffmpeg, video)

        _run([str(exe), "--version"], env=env)
        _run([str(exe), "style"], env=env)
        _run([str(exe), "doctor", "--json"], env=env)
        _run([
            str(exe),
            "synthesize",
            str(video),
            "-s",
            str(subtitle),
            "--subtitle-mode",
            "soft",
            "-o",
            str(soft_out),
            "-q",
        ], env=env)
        _run([
            str(exe),
            "synthesize",
            str(video),
            "-s",
            str(subtitle),
            "--subtitle-mode",
            "hard",
            "--quality",
            "low",
            "-o",
            str(hard_out),
            "-q",
        ], env=env)

        for output in [soft_out, hard_out]:
            if not output.exists() or output.stat().st_size <= 0:
                raise RuntimeError(f"Expected output was not created: {output}")
            seconds = _duration(ffprobe, output)
            if seconds < 2.5:
                raise RuntimeError(f"Output duration is unexpectedly short: {output} ({seconds:.2f}s)")
            print(f"Verified {output.name}: {output.stat().st_size} bytes, {seconds:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
