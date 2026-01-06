"""
跨平台工具函数
"""

import os
import sys
import stat
import platform
import subprocess
from typing import TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from app.core.entities import TranscribeModelEnum


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
            print(f"无法在当前系统打开文件夹: {path}")


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
            subprocess.Popen(["start", path], shell=True)
    elif system == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", path])
    else:
        # 其他系统，尝试使用默认方式
        try:
            subprocess.Popen(["xdg-open", path])
        except (OSError, subprocess.SubprocessError):
            print(f"无法在当前系统打开文件: {path}")


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


def get_available_transcribe_models() -> list["TranscribeModelEnum"]:
    """
    获取当前平台可用的转录模型列表

    macOS 上不支持 FasterWhisper，因为它依赖 CUDA/CuDNN

    Returns:
        list[TranscribeModelEnum]: 可用的转录模型列表
    """
    from app.core.entities import TranscribeModelEnum

    all_models = list(TranscribeModelEnum)

    # macOS 上过滤掉 FasterWhisper
    if is_macos():
        return [
            model for model in all_models if model != TranscribeModelEnum.FASTER_WHISPER
        ]

    return all_models


def is_model_available(model: "TranscribeModelEnum") -> bool:
    """
    检查指定模型是否在当前平台可用

    Args:
        model: 要检查的转录模型

    Returns:
        bool: 如果模型可用返回 True，否则返回 False
    """
    from app.core.entities import TranscribeModelEnum

    # FasterWhisper 在 macOS 上不可用
    if is_macos() and model == TranscribeModelEnum.FASTER_WHISPER:
        return False

    return True


def ensure_executable(folder_path, binary_name):
    """
    确保指定目录下的二进制文件具有执行权限

    根据当前平台自动处理文件名后缀（Windows 下自动补全 .exe），
    并检查文件是否存在。如果在 Linux/macOS 下文件存在但无权限，
    会自动赋予执行权限 (chmod +x)。

    Args:
        folder_path: 二进制文件所在的目录路径
        binary_name: 程序名称 (建议传入不带后缀的名称，如 'faster-whisper-xxl')
    """
    target_name = binary_name

    # Windows 平台下，如果传入的名字没后缀，但在硬盘上必须有 .exe
    if sys.platform.startswith("win"):
        if not target_name.lower().endswith(".exe"):
            target_name += ".exe"

    target_path = folder_path / target_name

    # 检查文件是否存在
    if target_path.exists() and target_path.is_file():
        # Linux/Mac 需要赋予执行权限
        if not sys.platform.startswith("win"):
            st = os.stat(target_path)
            if not (st.st_mode & stat.S_IEXEC):
                print(f"正在赋予执行权限: {target_path}")
                os.chmod(target_path, st.st_mode | stat.S_IEXEC)
    else:
        # 这里只是警告，不抛异常，因为可能用户已经把它装在系统全局 PATH 里了，不在这个文件夹
        print(f"提示: 在 {folder_path} 下未找到 {target_name}，将尝试在系统 PATH 中查找。")