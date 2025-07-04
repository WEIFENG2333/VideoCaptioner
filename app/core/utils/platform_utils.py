"""
平台检测和跨平台工具模块
提供统一的平台检测和跨平台文件处理功能
"""

import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any


class PlatformUtils:
    """平台工具类，处理跨平台差异"""
    
    @staticmethod
    def get_platform() -> str:
        """获取当前平台标识
        
        Returns:
            str: 'windows', 'macos', 'linux'
        """
        system = platform.system().lower()
        if system == 'windows':
            return 'windows'
        elif system == 'darwin':
            return 'macos'
        elif system == 'linux':
            return 'linux'
        else:
            return 'unknown'
    
    @staticmethod
    def is_windows() -> bool:
        """是否为Windows平台"""
        return PlatformUtils.get_platform() == 'windows'
    
    @staticmethod
    def is_macos() -> bool:
        """是否为macOS平台"""
        return PlatformUtils.get_platform() == 'macos'
    
    @staticmethod
    def is_linux() -> bool:
        """是否为Linux平台"""
        return PlatformUtils.get_platform() == 'linux'
    
    @staticmethod
    def get_executable_suffix() -> str:
        """获取可执行文件后缀"""
        return '.exe' if PlatformUtils.is_windows() else ''
    
    @staticmethod
    def get_executable_name(base_name: str) -> str:
        """获取带平台后缀的可执行文件名
        
        Args:
            base_name: 基础文件名
            
        Returns:
            str: 带后缀的完整文件名
        """
        suffix = PlatformUtils.get_executable_suffix()
        return f"{base_name}{suffix}"
    
    @staticmethod
    def open_folder(path: str) -> bool:
        """跨平台打开文件夹
        
        Args:
            path: 文件夹路径
            
        Returns:
            bool: 是否成功打开
        """
        try:
            if PlatformUtils.is_windows():
                os.startfile(path)
            elif PlatformUtils.is_macos():
                subprocess.run(['open', path], check=True)
            elif PlatformUtils.is_linux():
                subprocess.run(['xdg-open', path], check=True)
            else:
                return False
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_download_links() -> Dict[str, Dict[str, Any]]:
        """获取各平台的下载链接配置"""
        return {
            'faster_whisper': {
                'windows': {
                    'gpu': {
                        'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/Faster-Whisper-XXL_r245.2_windows.7z',
                        'filename': 'faster-whisper-gpu.7z',
                        'executable': 'Faster-Whisper-XXL/faster-whisper-xxl.exe'
                    },
                    'cpu': {
                        'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster.exe',
                        'filename': 'faster-whisper.exe',
                        'executable': 'faster-whisper.exe'
                    }
                },
                'macos': {
                    'cpu': {
                        'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster-macos',
                        'filename': 'faster-whisper',
                        'executable': 'faster-whisper'
                    }
                },
                'linux': {
                    'cpu': {
                        'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster-linux',
                        'filename': 'faster-whisper',
                        'executable': 'faster-whisper'
                    }
                }
            },
            'whisper_cpp': {
                'windows': {
                    'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-cpp.exe',
                    'filename': 'whisper-cpp.exe'
                },
                'macos': {
                    'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-cpp-macos',
                    'filename': 'whisper-cpp'
                },
                'linux': {
                    'url': 'https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-cpp-linux',
                    'filename': 'whisper-cpp'
                }
            }
        }
    
    @staticmethod
    def get_required_tools() -> List[str]:
        """获取当前平台所需的工具列表"""
        tools = ['ffmpeg', 'python3']
        
        if PlatformUtils.is_windows():
            tools.extend(['aria2c'])
        else:
            tools.extend(['aria2'])
            
        return tools
    
    @staticmethod
    def check_tool_availability(tool: str) -> bool:
        """检查工具是否可用
        
        Args:
            tool: 工具名称
            
        Returns:
            bool: 是否可用
        """
        try:
            subprocess.run([tool, '--version'], 
                         capture_output=True, 
                         check=True,
                         timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    @staticmethod
    def get_installation_commands() -> Dict[str, List[str]]:
        """获取各平台的安装命令"""
        return {
            'macos': [
                'brew install ffmpeg',
                'brew install aria2',
                'brew install python@3.11'
            ],
            'linux': [
                'sudo apt-get update',
                'sudo apt-get install ffmpeg aria2 python3 python3-pip'
            ],
            'windows': [
                '请访问以下链接下载并安装:',
                'FFmpeg: https://ffmpeg.org/download.html',
                'Python: https://www.python.org/downloads/',
                'Aria2: https://aria2.github.io/'
            ]
        }
    
    @staticmethod
    def handle_long_path(path: str) -> str:
        """处理长路径问题（主要针对Windows）
        
        Args:
            path: 原始路径
            
        Returns:
            str: 处理后的路径
        """
        if PlatformUtils.is_windows():
            # 如果路径长度超过260个字符，添加\\?\前缀
            if len(path) > 260 and not path.startswith("\\\\?\\"):
                # 转换为绝对路径
                abs_path = os.path.abspath(path)
                return f"\\\\?\\{abs_path}"
        return path
    
    @staticmethod
    def get_python_executable() -> str:
        """获取Python可执行文件路径"""
        if PlatformUtils.is_windows():
            return 'python'
        else:
            return 'python3'
    
    @staticmethod
    def make_executable(file_path: str) -> bool:
        """使文件可执行（主要针对Unix系统）
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            if not PlatformUtils.is_windows():
                os.chmod(file_path, 0o755)
            return True
        except Exception:
            return False