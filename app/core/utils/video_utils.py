import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Literal, Optional

from ..utils.ass_auto_wrap import auto_wrap_ass_file
from ..utils.logger import setup_logger

logger = setup_logger("video_utils")


@contextmanager
def temporary_subtitle_file(subtitle_path: str):
    """临时字幕文件上下文管理器

    自动复制字幕文件到临时位置，使用后自动清理

    Args:
        subtitle_path: 原始字幕文件路径

    Yields:
        临时字幕文件路径
    """
    suffix = Path(subtitle_path).suffix.lower()
    temp_fd, temp_path = tempfile.mkstemp(
        suffix=suffix, prefix="VideoCaptioner_subtitle_"
    )
    os.close(temp_fd)

    try:
        # 复制字幕到临时位置
        shutil.copy2(subtitle_path, temp_path)
        yield temp_path
    finally:
        # 自动清理临时文件
        Path(temp_path).unlink(missing_ok=True)


def get_audio_stream_count(video_path: str) -> int:
    """获取视频文件的音频轨道数量

    Args:
        video_path: 视频文件路径

    Returns:
        音频轨道数量，如果检测失败返回 1（默认假设单音轨）
    """
    try:
        cmd = ["ffmpeg", "-i", video_path]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        # ffmpeg 的流信息在 stderr 中
        # 搜索 "Stream #0:X(XXX): Audio" 这样的行
        audio_count = len(re.findall(r"Stream #\d+:\d+.*?: Audio", result.stderr))
        logger.info(f"检测到 {audio_count} 个音频轨道")
        return audio_count if audio_count > 0 else 1
    except Exception as e:
        logger.warning(f"检测音频轨道数量失败: {e}，默认假设为单音轨")
        return 1


def video2audio(input_file: str, output: str = "") -> bool:
    """使用 ffmpeg 将视频转换为音频

    支持单音轨和多音轨视频，根据音轨数量自动选择合适的转换方式
    """
    # 创建output目录
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = str(output_path)

    # 检测音轨数量
    audio_count = get_audio_stream_count(input_file)

    # 根据音轨数量选择转换策略
    if audio_count > 1:
        logger.info(f"检测到 {audio_count} 个音轨，使用 amerge 滤镜混合多音轨音频")
        cmd = [
            "ffmpeg",
            "-i",
            input_file,
            "-filter_complex",
            "amerge,pan=mono|c0=FC",  # 混合所有音轨并转为单声道
            "-ar",
            "16000",
            "-y",
            output,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-i",
            input_file,
            "-vn",
            "-ac",
            "1",  # 单声道
            "-ar",
            "16000",  # 采样率16kHz
            "-y",
            output,
        ]

    logger.info(f"转换为音频执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        if result.returncode == 0 and Path(output).is_file():
            logger.info("音频转换成功")
            return True
        else:
            logger.error("音频转换失败")
            return False
    except Exception as e:
        logger.exception(f"音频转换出错: {str(e)}")
        return False


def check_cuda_available() -> bool:
    """检查CUDA是否可用"""
    logger.info("检查CUDA是否可用")
    try:
        # 首先检查ffmpeg是否支持cuda
        result = subprocess.run(
            ["ffmpeg", "-hwaccels"],
            capture_output=True,
            text=True,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        if "cuda" not in result.stdout.lower():
            logger.info("CUDA不在支持的硬件加速器列表中")
            return False

        # 进一步检查CUDA设备信息
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-init_hw_device", "cuda"],
            capture_output=True,
            text=True,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )

        # 如果stderr中包含"Cannot load cuda" 或 "Failed to load"等错误信息，说明CUDA不可用
        if any(
            error in result.stderr.lower()
            for error in ["cannot load cuda", "failed to load", "error"]
        ):
            logger.info("CUDA设备初始化失败")
            return False

        logger.info("CUDA可用")
        return True

    except Exception as e:
        logger.exception(f"检查CUDA出错: {str(e)}")
        return False


def add_subtitles(
    input_file: str,
    subtitle_file: str,
    output: str,
    quality: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = "medium",
    vcodec: str = "libx264",
    soft_subtitle: bool = False,
    progress_callback: Optional[Callable] = None,
) -> None:
    assert Path(input_file).is_file(), "输入文件不存在"
    assert Path(subtitle_file).is_file(), "字幕文件不存在"

    # 使用临时文件上下文管理器处理字幕（自动清理）
    with temporary_subtitle_file(subtitle_file) as temp_subtitle_path:
        # 如果是 ASS 字幕，进行自动换行处理
        suffix = Path(subtitle_file).suffix.lower()
        processed_subtitle = temp_subtitle_path
        if suffix == ".ass":
            processed_subtitle = auto_wrap_ass_file(temp_subtitle_path)

        # 如果是WebM格式，强制使用硬字幕
        if Path(output).suffix.lower() == ".webm":
            soft_subtitle = False
            logger.info("WebM格式视频，强制使用硬字幕")

        if soft_subtitle:
            # 添加软字幕
            cmd = [
                "ffmpeg",
                "-i",
                input_file,
                "-i",
                processed_subtitle,
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "mov_text",
                "-y",
                output,
            ]
            logger.info(f"添加软字幕执行命令: {' '.join(cmd)}")
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                ),
            )
        else:
            # 使用硬字幕
            subtitle_path_escaped = (
                Path(processed_subtitle).as_posix().replace(":", r"\:")
            )

            # 根据输出文件后缀决定vf参数
            if Path(output).suffix.lower() == ".ass":
                vf = f"ass='{subtitle_path_escaped}'"
            else:
                vf = f"subtitles='{subtitle_path_escaped}'"

            if Path(output).suffix.lower() == ".webm":
                vcodec = "libvpx-vp9"
                logger.info("WebM格式视频，使用libvpx-vp9编码器")

            # 检查CUDA是否可用
            use_cuda = check_cuda_available()
            cmd = ["ffmpeg"]
            if use_cuda:
                logger.info("使用CUDA加速")
                cmd.extend(["-hwaccel", "cuda"])
            cmd.extend(
                [
                    "-i",
                    input_file,
                    "-acodec",
                    "copy",
                    "-vcodec",
                    vcodec,
                    "-preset",
                    quality,
                    "-vf",
                    vf,
                    "-y",
                    output,
                ]
            )

            cmd_str = subprocess.list2cmdline(cmd)
            logger.info(f"添加硬字幕执行命令: {cmd_str}")

            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )

                # 实时读取输出并调用回调函数
                total_duration = None
                current_time = 0

                while True:
                    output_line = process.stderr.readline()
                    if not output_line or (process.poll() is not None):
                        break
                    if not progress_callback:
                        continue

                    if total_duration is None:
                        duration_match = re.search(
                            r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})", output_line
                        )
                        if duration_match:
                            h, m, s = map(float, duration_match.groups())
                            total_duration = h * 3600 + m * 60 + s
                            logger.info(f"视频总时长: {total_duration}秒")

                    # 解析当前处理时间
                    time_match = re.search(
                        r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", output_line
                    )
                    if time_match:
                        h, m, s = map(float, time_match.groups())
                        current_time = h * 3600 + m * 60 + s

                    # 计算进度百分比
                    if total_duration:
                        progress = (current_time / total_duration) * 100
                        progress_callback(f"{round(progress)}", "正在合成")

                if progress_callback:
                    progress_callback("100", "合成完成")

                # 检查进程的返回码
                return_code = process.wait()
                if return_code != 0:
                    error_info = process.stderr.read()
                    logger.error(f"视频合成失败: {error_info}")
                    raise Exception(f"FFmpeg 返回码: {return_code}")
                logger.info("视频合成完成")

            except Exception as e:
                logger.exception(f"FFmpeg 执行出错: {str(e)}")
                if process and process.poll() is None:
                    process.kill()
                raise


def get_video_info(file_path: str) -> Optional[Dict]:
    """获取视频信息"""
    try:
        cmd = ["ffmpeg", "-i", file_path]

        # logger.info(f"获取视频信息执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        info = result.stderr

        video_info_dict = {
            "file_name": Path(file_path).stem,
            "file_path": file_path,
            "duration_seconds": 0,
            "bitrate_kbps": 0,
            "video_codec": "",
            "width": 0,
            "height": 0,
            "fps": 0,
            "audio_codec": "",
            "audio_sampling_rate": 0,
            "thumbnail_path": "",
        }

        # 提取时长
        if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
            hours, minutes, seconds = map(float, duration_match.groups())
            video_info_dict["duration_seconds"] = hours * 3600 + minutes * 60 + seconds

        # 提取比特率
        if bitrate_match := re.search(r"bitrate: (\d+) kb/s", info):
            video_info_dict["bitrate_kbps"] = int(bitrate_match.group(1))

        # 提取视频流信息
        if video_stream_match := re.search(
            r"Stream #.*?Video: (\w+)(?:\s*\([^)]*\))?.* (\d+)x(\d+).*?(?:(\d+(?:\.\d+)?)\s*(?:fps|tb[rn]))",
            info,
            re.DOTALL,
        ):
            video_info_dict.update(
                {
                    "video_codec": video_stream_match.group(1),
                    "width": int(video_stream_match.group(2)),
                    "height": int(video_stream_match.group(3)),
                    "fps": float(video_stream_match.group(4)),
                }
            )
        else:
            logger.warning("未找到视频流信息")

        return video_info_dict
    except Exception as e:
        logger.exception(f"获取视频信息时出错: {str(e)}")
        return None
