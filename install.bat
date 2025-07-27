@echo off
:: VideoCaptioner 依赖安装脚本 (Windows)
:: 作者: Weifeng
:: 说明: 自动安装 VideoCaptioner 所需的所有依赖

echo ========================================
echo   VideoCaptioner 依赖安装器
echo ========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 某些依赖可能需要管理员权限安装
    echo 如遇到权限问题，请右键"以管理员身份运行"此脚本
    echo.
)

:: 检查Python是否已安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到Python安装！
    echo 请先安装Python 3.8或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 显示Python版本
echo [信息] 检测到Python版本:
python --version
echo.

:: 检查pip是否可用
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] pip未安装或不可用！
    echo 正在尝试修复...
    python -m ensurepip --default-pip
    if %errorlevel% neq 0 (
        echo [错误] pip安装失败！
        pause
        exit /b 1
    )
)

:: 更新pip到最新版本
echo [信息] 更新pip到最新版本...
python -m pip install --upgrade pip

:: 创建虚拟环境（如果不存在）
if not exist "venv" (
    echo.
    echo [信息] 创建Python虚拟环境...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败！
        pause
        exit /b 1
    )
    echo [信息] 虚拟环境创建成功！
)

:: 激活虚拟环境
echo [信息] 激活虚拟环境...
call venv\Scripts\activate.bat

:: 安装Python依赖
echo.
echo [信息] 安装Python依赖包...
echo ----------------------------------------
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [错误] Python依赖安装失败！
    pause
    exit /b 1
)

:: 检查系统工具
echo.
echo [信息] 检查系统工具...
echo ----------------------------------------

:: 检查ffmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未检测到ffmpeg！
    echo ffmpeg用于视频处理，强烈建议安装
    echo.
    echo 安装方法：
    echo 1. 访问 https://ffmpeg.org/download.html
    echo 2. 下载Windows版本
    echo 3. 解压并将bin目录添加到系统PATH
    echo.
    echo 或使用Chocolatey安装: choco install ffmpeg
    echo.
) else (
    echo [✓] ffmpeg 已安装
)

:: 检查aria2
aria2c --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未检测到aria2！
    echo aria2用于高速下载，建议安装
    echo.
    echo 安装方法：
    echo 1. 访问 https://aria2.github.io/
    echo 2. 下载Windows版本
    echo 3. 将aria2c.exe放到系统PATH中
    echo.
    echo 或使用Chocolatey安装: choco install aria2
    echo.
) else (
    echo [✓] aria2 已安装
)

:: 创建必要的目录
echo.
echo [信息] 创建必要的目录结构...
if not exist "AppData" mkdir AppData
if not exist "AppData\cache" mkdir AppData\cache
if not exist "AppData\logs" mkdir AppData\logs
if not exist "AppData\models" mkdir AppData\models
if not exist "work-dir" mkdir work-dir

:: 完成
echo.
echo ========================================
echo [成功] 依赖安装完成！
echo.
echo 现在可以运行 start.bat 启动程序
echo ========================================
echo.
pause