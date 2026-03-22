"""
跨平台工具函数
"""

import logging
import os
import platform
import subprocess

from videocaptioner.core.entities import TranscribeModelEnum

logger = logging.getLogger(__name__)


def open_folder(path):
    """
    跨平台打开文件夹

    Args:
        path: 要打开的文件夹路径
    """
    system = platform.system()

    if system == "Windows":
        if hasattr(os, "startfile"):
            getattr(os, "startfile")(path)
        else:
            subprocess.Popen(["explorer", path])
    elif system == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", path])
    else:
        # 其他系统，尝试使用默认方式
        try:
            subprocess.Popen(["xdg-open", path])
        except (OSError, subprocess.SubprocessError):
            logger.warning(f"无法在当前系统打开文件夹: {path}")


def reveal_in_explorer(file_path):
    """跨平台在文件管理器中显示并选中文件"""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", file_path])
        else:
            # Linux 没有统一的选中文件方式，打开父文件夹
            subprocess.Popen(["xdg-open", os.path.dirname(file_path)])
    except (OSError, subprocess.SubprocessError):
        logger.warning(f"can not reveal in explorer: {file_path}")


def open_file(path):
    """
    跨平台打开文件

    Args:
        path: 要打开的文件路径
    """
    system = platform.system()

    if system == "Windows":
        if hasattr(os, "startfile"):
            getattr(os, "startfile")(path)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", path])
    elif system == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", path])
    else:
        # 其他系统，尝试使用默认方式
        try:
            subprocess.Popen(["xdg-open", path])
        except (OSError, subprocess.SubprocessError):
            logger.warning(f"无法在当前系统打开文件: {path}")


def get_subprocess_kwargs():
    """
    获取跨平台的subprocess参数

    Returns:
        dict: subprocess参数字典
    """
    kwargs = {}

    # 仅在Windows上添加CREATE_NO_WINDOW标志
    if platform.system() == "Windows":
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return kwargs


def is_macos() -> bool:
    """
    检测是否为 macOS 系统

    Returns:
        bool: 如果是 macOS 返回 True，否则返回 False
    """
    return platform.system() == "Darwin"


def is_windows() -> bool:
    """
    检测是否为 Windows 系统

    Returns:
        bool: 如果是 Windows 返回 True，否则返回 False
    """
    return platform.system() == "Windows"


def is_linux() -> bool:
    """
    检测是否为 Linux 系统

    Returns:
        bool: 如果是 Linux 返回 True，否则返回 False
    """
    return platform.system() == "Linux"


def get_available_transcribe_models() -> list[TranscribeModelEnum]:
    """
    获取当前平台可用的转录模型列表

    macOS 上不支持 FasterWhisper，因为它依赖 CUDA/CuDNN

    Returns:
        list[TranscribeModelEnum]: 可用的转录模型列表
    """
    all_models = list(TranscribeModelEnum)

    # macOS 上过滤掉 FasterWhisper
    if is_macos():
        return [
            model for model in all_models if model != TranscribeModelEnum.FASTER_WHISPER
        ]

    return all_models


def is_model_available(model: TranscribeModelEnum) -> bool:
    """
    检查指定模型是否在当前平台可用

    Args:
        model: 要检查的转录模型

    Returns:
        bool: 如果模型可用返回 True，否则返回 False
    """
    # FasterWhisper 在 macOS 上不可用
    if is_macos() and model == TranscribeModelEnum.FASTER_WHISPER:
        return False

    return True
