"""
跨平台工具函数
"""
import os
import platform
import subprocess
import sys


def open_folder(path):
    """
    跨平台打开文件夹
    
    Args:
        path: 要打开的文件夹路径
    """
    system = platform.system()
    
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", path])
    else:
        # 其他系统，尝试使用默认方式
        try:
            subprocess.Popen(["xdg-open", path])
        except:
            print(f"无法在当前系统打开文件夹: {path}")


def open_file(path):
    """
    跨平台打开文件
    
    Args:
        path: 要打开的文件路径
    """
    system = platform.system()
    
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":  # macOS
        subprocess.Popen(["open", path])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", path])
    else:
        # 其他系统，尝试使用默认方式
        try:
            subprocess.Popen(["xdg-open", path])
        except:
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
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    
    return kwargs