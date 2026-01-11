import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Optional

from ..entities import (
    AudioStreamInfo,
    SubtitleLayoutEnum,
    SubtitleRenderModeEnum,
    VideoInfo,
)
from ..subtitle.ass_renderer import render_ass_video
from ..subtitle.ass_utils import auto_wrap_ass_file
from ..subtitle.rounded_renderer import render_rounded_video
from ..utils.logger import setup_logger

if TYPE_CHECKING:
    from app.core.asr.asr_data import ASRData

# FFmpeg preset 类型
PresetType = Literal[
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]

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


def video2audio(input_file: str, output: str = "", audio_track_index: int = 0) -> bool:
    """使用 ffmpeg 将视频转换为音频

    Args:
        input_file: 输入视频文件路径
        output: 输出音频文件路径
        audio_track_index: 要提取的音轨索引，默认为 0（第一条音轨）

    Returns:
        转换是否成功
    """
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = str(output_path)

    logger.info(f"提取音轨索引 {audio_track_index}")
    cmd = [
        "ffmpeg",
        "-i",
        input_file,
        "-map",
        f"0:a:{audio_track_index}",
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
    except subprocess.CalledProcessError as e:
        logger.error("== ffmpeg 执行失败 ==")
        logger.error(f"返回码: {e.returncode}")
        logger.error(f"命令: {' '.join(e.cmd)}")
        if e.stdout:
            logger.error(f"标准输出: {e.stdout}")
        if e.stderr:
            logger.error(f"标准错误: {e.stderr}")
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
    crf: int = 23,
    preset: Literal[
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
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )
                logger.info("软字幕添加成功")
            except subprocess.CalledProcessError as e:
                logger.error("== ffmpeg 添加软字幕失败 ==")
                logger.error(f"返回码: {e.returncode}")
                logger.error(f"命令: {' '.join(e.cmd)}")
                if e.stdout:
                    logger.error(f"标准输出: {e.stdout}")
                if e.stderr:
                    logger.error(f"标准错误: {e.stderr}")
                raise
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
                    "-crf",
                    str(crf),
                    "-preset",
                    preset,
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
                    logger.error("== ffmpeg 添加硬字幕失败 ==")
                    logger.error(f"返回码: {return_code}")
                    logger.error(f"命令: {cmd_str}")
                    if error_info:
                        logger.error(f"错误信息: {error_info}")
                    raise Exception(f"FFmpeg 返回码: {return_code}")
                logger.info("视频合成完成")

            except subprocess.SubprocessError as e:
                logger.error("== ffmpeg 进程执行异常 ==")
                logger.error(f"错误: {str(e)}")
                if process and process.poll() is None:
                    process.kill()
                raise
            except Exception as e:
                logger.error(f"视频合成过程出错: {str(e)}")
                if process and process.poll() is None:
                    process.kill()
                raise


def get_video_info(
    file_path: str, thumbnail_path: Optional[str] = None
) -> Optional["VideoInfo"]:
    """获取媒体文件信息（支持视频和音频文件）

    Args:
        file_path: 媒体文件路径（视频或音频）
        thumbnail_path: 缩略图保存路径（可选，仅对视频文件有效）

    Returns:
        VideoInfo 对象，失败返回 None
        对于纯音频文件，视频相关字段（width/height/fps）将为 0
    """
    try:
        # 执行 ffmpeg 获取视频信息
        result = subprocess.run(
            ["ffmpeg", "-i", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        info = result.stderr

        # 提取时长
        duration_seconds = 0.0
        if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
            hours, minutes, seconds = map(float, duration_match.groups())
            duration_seconds = hours * 3600 + minutes * 60 + seconds

        # 提取比特率
        bitrate_kbps = 0
        if bitrate_match := re.search(r"bitrate: (\d+) kb/s", info):
            bitrate_kbps = int(bitrate_match.group(1))

        # 提取视频流信息
        width, height, fps, video_codec = 0, 0, 0.0, ""
        has_video_stream = False
        if video_stream_match := re.search(
            r"Stream #.*?Video: (\w+)(?:\s*\([^)]*\))?.* (\d+)x(\d+).*?(?:(\d+(?:\.\d+)?)\s*(?:fps|tb[rn]))",
            info,
            re.DOTALL,
        ):
            video_codec = video_stream_match.group(1)
            width = int(video_stream_match.group(2))
            height = int(video_stream_match.group(3))
            fps = float(video_stream_match.group(4))
            has_video_stream = True

        # 提取第一条音频流信息（用于兼容性）
        audio_codec, audio_sampling_rate = "", 0
        if audio_stream_match := re.search(
            r"Stream #\d+:\d+.*Audio: (\w+).* (\d+) Hz", info
        ):
            audio_codec = audio_stream_match.group(1)
            audio_sampling_rate = int(audio_stream_match.group(2))

        # 提取所有音频流信息（用于多音轨选择）
        audio_streams: list[AudioStreamInfo] = []
        for match in re.finditer(
            r"Stream #\d+:(\d+)(?:\[0x[0-9a-fA-F]+\])?(?:\(([a-z]{3})\))?: Audio: (\w+)",
            info,
        ):
            audio_streams.append(
                AudioStreamInfo(
                    index=int(match.group(1)),
                    codec=match.group(3),
                    language=match.group(2) or "",
                )
            )

        if audio_streams:
            logger.info(f"检测到 {len(audio_streams)} 条音轨")

        # 验证文件是否包含有效的媒体流
        if not has_video_stream and not audio_streams:
            logger.error("文件既没有视频流也没有音频流，可能不是有效的媒体文件")
            return None

        # 提取缩略图（如果指定了路径且有视频流）
        final_thumbnail_path = ""
        if thumbnail_path and duration_seconds > 0 and has_video_stream:
            if _extract_thumbnail(file_path, duration_seconds * 0.3, thumbnail_path):
                final_thumbnail_path = thumbnail_path

        # 构造并返回 VideoInfo 对象
        return VideoInfo(
            file_name=Path(file_path).stem,
            file_path=file_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration_seconds,
            bitrate_kbps=bitrate_kbps,
            video_codec=video_codec,
            audio_codec=audio_codec,
            audio_sampling_rate=audio_sampling_rate,
            thumbnail_path=final_thumbnail_path,
            audio_streams=audio_streams,
        )
    except Exception as e:
        logger.exception(f"获取视频信息时出错: {str(e)}")
        return None


def _extract_thumbnail(video_path: str, seek_time: float, thumbnail_path: str) -> bool:
    """提取视频缩略图

    Args:
        video_path: 视频文件路径
        seek_time: 截取时间点（秒）
        thumbnail_path: 缩略图保存路径

    Returns:
        是否成功
    """
    if not Path(video_path).is_file():
        logger.error(f"视频文件不存在: {video_path}")
        return False

    try:
        timestamp = f"{int(seek_time // 3600):02}:{int((seek_time % 3600) // 60):02}:{seek_time % 60:06.3f}"
        Path(thumbnail_path).parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                "ffmpeg",
                "-ss",
                timestamp,
                "-i",
                Path(video_path).as_posix(),
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                Path(thumbnail_path).as_posix(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            ),
        )
        return result.returncode == 0

    except Exception as e:
        logger.exception(f"提取缩略图时出错: {str(e)}")
        return False


def add_subtitles_with_style(
    video_path: str,
    asr_data: "ASRData",
    output_path: str,
    render_mode: SubtitleRenderModeEnum,
    subtitle_layout: SubtitleLayoutEnum,
    ass_style: str = "",
    rounded_style: Optional[dict] = None,
    crf: int = 23,
    preset: PresetType = "medium",
    progress_callback: Optional[Callable] = None,
) -> None:
    """
    根据渲染模式选择合成方式

    Args:
        video_path: 输入视频路径
        asr_data: 字幕数据
        output_path: 输出视频路径
        render_mode: 渲染模式 (ASS_STYLE 或 ROUNDED_BG)
        subtitle_layout: 字幕布局
        ass_style: ASS 样式字符串 (仅 ASS_STYLE 模式使用)
        rounded_style: 圆角背景样式配置字典 (仅 ROUNDED_BG 模式使用)
        crf: 视频质量
        preset: FFmpeg 编码预设
        progress_callback: 进度回调
    """

    if render_mode == SubtitleRenderModeEnum.ROUNDED_BG:
        # 圆角背景模式
        render_rounded_video(
            video_path=video_path,
            asr_data=asr_data,
            output_path=output_path,
            rounded_style=rounded_style,
            layout=subtitle_layout,
            crf=crf,
            preset=preset,
            progress_callback=progress_callback,
        )
    else:
        # ASS 样式模式
        render_ass_video(
            video_path=video_path,
            asr_data=asr_data,
            output_path=output_path,
            style_str=ass_style,
            layout=subtitle_layout,
            crf=crf,
            preset=preset,
            progress_callback=progress_callback,
        )
