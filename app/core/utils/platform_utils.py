"""
跨平台工具函数
"""

import os
import platform
import subprocess


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
