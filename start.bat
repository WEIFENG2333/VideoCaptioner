@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM VideoCaptioner 一键启动脚本（适用于 Windows）
REM 作者：VideoCaptioner 团队
REM 版本：v1.0

echo ========================================
echo     VideoCaptioner 一键启动脚本
echo ========================================
echo.

REM 检查 Python 是否安装
echo [检查] 正在检查 Python 安装...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8 或更高版本
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
) else (
    echo [成功] Python 已安装
)

REM 检查 FFmpeg 是否安装
echo [检查] 正在检查 FFmpeg 安装...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 FFmpeg，部分功能可能无法使用
    echo 下载地址：https://ffmpeg.org/download.html#build-windows
    echo 请将 ffmpeg.exe 添加到系统 PATH 环境变量中
    echo.
) else (
    echo [成功] FFmpeg 已安装
)

REM 创建虚拟环境
if not exist "venv" (
    echo [创建] 正在创建 Python 虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [成功] 虚拟环境创建完成
) else (
    echo [跳过] 虚拟环境已存在
)

REM 激活虚拟环境
echo [激活] 正在激活虚拟环境...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [错误] 激活虚拟环境失败
    pause
    exit /b 1
)

REM 升级 pip
echo [升级] 正在升级 pip...
python -m pip install --upgrade pip >nul 2>&1

REM 安装依赖
echo [安装] 正在安装 Python 依赖包...
if exist "requirements.txt" (
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 安装依赖失败
        pause
        exit /b 1
    )
    echo [成功] 依赖安装完成
) else (
    echo [错误] 未找到 requirements.txt 文件
    pause
    exit /b 1
)

REM 创建必要的目录
echo [创建] 正在创建必要的目录...
if not exist "AppData" mkdir AppData
if not exist "AppData\cache" mkdir AppData\cache
if not exist "AppData\logs" mkdir AppData\logs
if not exist "AppData\models" mkdir AppData\models
if not exist "work-dir" mkdir work-dir
if not exist "resource" mkdir resource
if not exist "resource\bin" mkdir resource\bin

REM 启动应用程序
echo [启动] 正在启动 VideoCaptioner...
echo.
if exist "main.py" (
    python main.py
) else (
    echo [错误] 未找到 main.py 文件
    pause
    exit /b 1
)

REM 程序结束后的处理
echo.
echo [完成] VideoCaptioner 已退出
pause