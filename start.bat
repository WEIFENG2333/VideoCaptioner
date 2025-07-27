@echo off
:: VideoCaptioner 启动脚本 (Windows)
:: 作者: Weifeng
:: 说明: 一键启动 VideoCaptioner 应用程序

echo ========================================
echo     VideoCaptioner 启动器
echo ========================================
echo.

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

:: 检查是否在正确的目录
if not exist "main.py" (
    echo [错误] 未找到main.py文件！
    echo 请确保在VideoCaptioner项目根目录运行此脚本
    pause
    exit /b 1
)

:: 检查虚拟环境是否存在
if exist "venv\Scripts\activate.bat" (
    echo [信息] 激活虚拟环境...
    call venv\Scripts\activate.bat
) else (
    echo [提示] 未检测到虚拟环境，使用系统Python
)

:: 检查依赖是否已安装
python -c "import PyQt5" >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 检测到缺少依赖包！
    echo 是否要自动安装依赖？(Y/N)
    set /p install_deps=
    if /i "%install_deps%"=="Y" (
        echo [信息] 正在安装依赖...
        pip install -r requirements.txt
        if %errorlevel% neq 0 (
            echo [错误] 依赖安装失败！
            pause
            exit /b 1
        )
    ) else (
        echo [警告] 跳过依赖安装，程序可能无法正常运行
    )
)

:: 启动应用程序
echo.
echo [信息] 正在启动 VideoCaptioner...
echo ========================================
python main.py

:: 如果程序异常退出，暂停以查看错误信息
if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出！
    pause
)