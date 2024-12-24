import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Literal

from ..utils.logger import setup_logger

logger = setup_logger("video_utils")


def video2audio(input_file: str, output: str = "") -> bool:
    """使用ffmpeg将视频转换为音频"""    
    # 创建output目录
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output = str(output)
    cmd = [
        'ffmpeg',
        '-i', input_file,
        '-map', '0:a',
        '-ac', '1',
        '-ar', '16000',
        '-af', 'aresample=async=1',  # 处理音频同步问题
        '-y',
        output
    ]
    logger.info(f"转换为音频执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            check=True, 
            encoding='utf-8', 
            errors='replace', 
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
        if result.returncode == 0 and Path(output).is_file():
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
            ['ffmpeg', '-hwaccels'], 
            capture_output=True, 
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,

        )
        if 'cuda' not in result.stdout.lower():
            logger.info("CUDA不在支持的硬件加速器列表中")
            return False
            
        # 进一步检查CUDA设备信息
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-init_hw_device', 'cuda'], 
            capture_output=True, 
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        # 如果stderr中包含"Cannot load cuda" 或 "Failed to load"等错误信息，说明CUDA不可用
        if any(error in result.stderr.lower() for error in ['cannot load cuda', 'failed to load', 'error']):
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
            'ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'] = 'medium',
        vcodec: str = 'libx264',
        soft_subtitle: bool = False,
        progress_callback: callable = None
) -> None:
    assert Path(input_file).is_file(), "输入文件不存在"
    assert Path(subtitle_file).is_file(), "字幕文件不存在"

    # 移动到临时文件  Fix: 路径错误
    temp_dir = Path(tempfile.gettempdir()) / "VideoCaptioner"
    temp_dir.mkdir(exist_ok=True)
    temp_subtitle = temp_dir / "temp_subtitle.ass"
    shutil.copy2(subtitle_file, temp_subtitle)
    subtitle_file = str(temp_subtitle)

    # 如果是WebM格式，强制使用硬字幕
    if Path(output).suffix.lower() == '.webm':
        soft_subtitle = False
        logger.info("WebM格式视频，强制使用硬字幕")

    if soft_subtitle:
        # 添加软字幕
        cmd = [
            'ffmpeg',
            '-i', input_file,
            '-i', subtitle_file,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-c:s', 'mov_text',
            output,
            '-y'
        ]
        logger.info(f"添加软字幕执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
    else:
        logger.info("使用硬字幕")
        subtitle_file = Path(subtitle_file).as_posix().replace(':', r'\:')
        vf = f"subtitles='{subtitle_file}'"
        if Path(output).suffix.lower() == '.webm':
            vcodec = 'libvpx-vp9'
            logger.info("WebM格式视频，使用libvpx-vp9编码器")

        # 检查CUDA是否可用
        use_cuda = check_cuda_available()
        cmd = ['ffmpeg']
        if use_cuda:
            logger.info("使用CUDA加速")
            cmd.extend(['-hwaccel', 'cuda'])
        cmd.extend([
            '-i', input_file,
            '-acodec', 'copy',
            '-vcodec', vcodec,
            '-preset', quality,
            '-vf', vf,
            '-y',  # 覆盖输出文件
            output
        ])

        cmd_str = subprocess.list2cmdline(cmd)
        logger.info(f"添加硬字幕执行命令: {cmd_str}")

        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
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
                    duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})', output_line)
                    if duration_match:
                        h, m, s = map(float, duration_match.groups())
                        total_duration = h * 3600 + m * 60 + s
                        logger.info(f"视频总时长: {total_duration}秒")

                # 解析当前处理时间
                time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', output_line)
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
                logger.error(f"视频合成失败， {error_info}")
                raise Exception(return_code)
            logger.info("视频合成完成")

        except Exception as e:
            logger.exception(f"关闭 FFmpeg: {str(e)}")
            if process and process.poll() is None:  # 如果进程还在运行
                process.kill()  # 如果进程没有及时终止，强制结束它
            raise
        finally:
            # 删除临时文件
            if temp_subtitle.exists():
                temp_subtitle.unlink()

def get_video_info(filepath: str, thumbnail_path: str = "") -> dict:
    try:
        cmd = ["ffmpeg", "-i", filepath]
        logger.info(f"获取视频信息执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
        info = result.stderr

        video_info = {
            'file_name': Path(filepath).stem,
            'file_path': str( Path(filepath).parent ),
            'duration_seconds': 0,
            'bitrate_kbps': 0,
            'video_codec': '',
            'width': 0,
            'height': 0,
            'fps': 0,
            'audio_codec': '',
            'audio_sampling_rate': 0,
            'thumbnail_path': '',
        }

        # 提取时长
        if duration_match := re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', info):
            hours, minutes, seconds = map(float, duration_match.groups())
            video_info['duration_seconds'] = hours * 3600 + minutes * 60 + seconds
            logger.info(f"视频时长: {video_info['duration_seconds']}秒")

        # 提取比特率
        if bitrate_match := re.search(r'bitrate: (\d+) kb/s', info):
            video_info['bitrate_kbps'] = int(bitrate_match.group(1))

        # 提取视频流信息
        if video_stream_match := re.search(r'Stream #\d+:\d+.*Video: (\w+).*?, (\d+)x(\d+).*?, ([\d.]+) (?:fps|tb)',
                                           info, re.DOTALL):
            video_info.update({
                'video_codec': video_stream_match.group(1),
                'width': int(video_stream_match.group(2)),
                'height': int(video_stream_match.group(3)),
                'fps': float(video_stream_match.group(4))
            })
            
            if thumbnail_path:
                if extract_thumbnail(filepath, video_info['duration_seconds'] * 0.3, thumbnail_path):
                    video_info['thumbnail_path'] = thumbnail_path
        else:
            video_info['thumbnail_path'] = thumbnail_path
            logger.warning("未找到视频流信息")

        # 提取音频流信息
        if audio_stream_match := re.search(r'Stream #\d+:\d+.*Audio: (\w+).* (\d+) Hz', info):
            video_info.update({
                'audio_codec': audio_stream_match.group(1),
                'audio_sampling_rate': int(audio_stream_match.group(2))
            })

        return video_info
    except Exception as e:
        logger.exception(f"获取视频信息时出错: {str(e)}")
        return {k: '' if isinstance(v, str) else 0 for k, v in video_info.items()}


def extract_thumbnail(video_path: str, seek_time: float, thumbnail_path: str) -> bool:
    """
    使用 FFmpeg 提取视频缩略图
    
    :param video_path: 输入视频文件的路径
    :param seek_time: 提取缩略图的时间点（秒）
    :param thumbnail_path: 输出缩略图文件的路径
    :return: True 表示成功，False 表示失败
    """    
    if not Path(video_path).is_file():
        logger.error(f"视频文件不存在: {video_path}")
        return False

    try:
        timestamp = f"{int(seek_time // 3600):02}:{int((seek_time % 3600) // 60):02}:{seek_time % 60:06.3f}"
        # 确保输出目录存在
        Path(thumbnail_path).parent.mkdir(parents=True, exist_ok=True)

        # 转换路径为合适的格式
        video_path = Path(video_path).as_posix()
        thumbnail_path = Path(thumbnail_path).as_posix()

        cmd = [
            "ffmpeg",
            "-ss", timestamp,
            "-i",
            video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            thumbnail_path
        ]
        logger.info(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        success = result.returncode == 0
        return success

    except Exception as e:
        logger.exception(f"提取缩略图时出错: {str(e)}")
        return False


if __name__ == "__main__":
    video_path = r"C:\Users\weifeng\Videos\example_video.mp4"
    thumbnail_path = "e:/example_thumbnail.jpg"
    success = extract_thumbnail(video_path, 2, thumbnail_path)
