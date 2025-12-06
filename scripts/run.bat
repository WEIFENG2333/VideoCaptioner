@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: VideoCaptioner Installer & Launcher for Windows
:: Usage: Download and run this script, or run from project directory

:: Configuration
set "REPO_URL=https://github.com/WEIFENG2333/VideoCaptioner.git"
if not defined VIDEOCAPTIONER_HOME set "INSTALL_DIR=%USERPROFILE%\VideoCaptioner"
if defined VIDEOCAPTIONER_HOME set "INSTALL_DIR=%VIDEOCAPTIONER_HOME%"

echo.
echo ==================================
echo   VideoCaptioner Installer
echo ==================================
echo.

:: Check if running from project directory (current dir)
if exist "main.py" if exist "pyproject.toml" if exist "app" (
    set "INSTALL_DIR=%CD%"
    echo [INFO] Running from project directory: %INSTALL_DIR%
    goto :after_detect
)

:: Check if running from scripts/ subdirectory
set "SCRIPT_DIR=%~dp0"
set "PARENT_DIR=%SCRIPT_DIR%.."
if exist "%PARENT_DIR%\main.py" if exist "%PARENT_DIR%\pyproject.toml" (
    pushd "%PARENT_DIR%"
    set "INSTALL_DIR=%CD%"
    popd
    echo [INFO] Running from project directory: %INSTALL_DIR%
)

:after_detect

:: Check git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed. Please install git first.
    echo Download from: https://git-scm.com/download/win
    pause
    exit /b 1
)

:: Check and install uv
call :install_uv
if %errorlevel% neq 0 exit /b 1

:: Setup repository if needed
if not exist "%INSTALL_DIR%\main.py" (
    call :setup_repository
    if %errorlevel% neq 0 exit /b 1
)

cd /d "%INSTALL_DIR%"

:: Install dependencies
call :install_dependencies
if %errorlevel% neq 0 exit /b 1

:: Check system dependencies
call :check_system_deps

:: Run the application
call :run_app
exit /b 0

:: ============================================
:: Functions
:: ============================================

:install_uv
where uv >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('uv --version') do echo [OK] uv is already installed: %%i
    exit /b 0
)

echo [INFO] Installing uv package manager...

:: Try PowerShell installation
powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"

:: Add to PATH for current session
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
set "PATH=%LOCALAPPDATA%\uv\bin;%PATH%"

where uv >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('uv --version') do echo [OK] uv installed successfully: %%i
    exit /b 0
) else (
    echo [ERROR] Failed to install uv. Please install manually: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

:setup_repository
if exist "%INSTALL_DIR%\.git" (
    echo [INFO] Project found at %INSTALL_DIR%
    exit /b 0
)

echo [INFO] Cloning VideoCaptioner to %INSTALL_DIR%...
git clone "%REPO_URL%" "%INSTALL_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to clone repository
    pause
    exit /b 1
)
echo [OK] Repository cloned successfully
exit /b 0

:install_dependencies
echo [INFO] Installing dependencies with uv...
uv sync
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed
exit /b 0

:check_system_deps
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] ffmpeg not found. Some features may not work.
    echo   Install with: winget install ffmpeg
    echo   Or download from: https://ffmpeg.org/download.html
)

where aria2c >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] aria2 not found ^(optional, for faster model downloads^)
)
exit /b 0

:run_app
echo.
echo [INFO] Starting VideoCaptioner...
echo.
uv run python main.py
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error.
    pause
)
exit /b 0

