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
if exist "pyproject.toml" if exist "pyproject.toml" if exist "videocaptioner" (
    set "INSTALL_DIR=!CD!"
    echo [INFO] Running from project directory: !INSTALL_DIR!
    goto :after_detect
)

:: Check if running from scripts/ subdirectory
set "SCRIPT_DIR=%~dp0"
set "PARENT_DIR=%SCRIPT_DIR%.."
if exist "%PARENT_DIR%\pyproject.toml" (
    pushd "%PARENT_DIR%"
    set "INSTALL_DIR=!CD!"
    popd
    echo [INFO] Running from project directory: !INSTALL_DIR!
)

:after_detect

:: Install git if needed
call :install_git
if !errorlevel! neq 0 exit /b 1

:: Install uv if needed
call :install_uv
if !errorlevel! neq 0 exit /b 1

:: Setup repository if needed
if not exist "%INSTALL_DIR%\pyproject.toml" (
    call :setup_repository
    if !errorlevel! neq 0 exit /b 1
)

cd /d "%INSTALL_DIR%"

:: Install dependencies
call :install_dependencies
if !errorlevel! neq 0 exit /b 1

:: Install ffmpeg if needed
call :install_ffmpeg

:: Run the application
call :run_app
exit /b 0

:: ============================================
:: Functions
:: ============================================

:install_git
where git >nul 2>&1
if !errorlevel! equ 0 exit /b 0

echo [INFO] Git not found, installing...

where winget >nul 2>&1
if !errorlevel! equ 0 (
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    :: Refresh PATH to pick up newly installed git
    call :refresh_path
    where git >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Git installed successfully
        exit /b 0
    )
)

echo [ERROR] Failed to install Git automatically.
echo   Download from: https://git-scm.com/download/win
pause
exit /b 1

:install_uv
where uv >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=*" %%i in ('uv --version') do echo [OK] uv is already installed: %%i
    exit /b 0
)

echo [INFO] Installing uv package manager...

:: Try PowerShell installation
powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"

:: Add to PATH for current session
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%PATH%"

where uv >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=*" %%i in ('uv --version') do echo [OK] uv installed successfully: %%i
    exit /b 0
) else (
    echo [ERROR] Failed to install uv. Please install manually: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

:install_ffmpeg
where ffmpeg >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=*" %%i in ('ffmpeg -version 2^>^&1 ^| findstr /r "ffmpeg version"') do echo [OK] FFmpeg is already installed: %%i
    exit /b 0
)

echo [INFO] Installing FFmpeg (required for video synthesis)...

where winget >nul 2>&1
if !errorlevel! equ 0 (
    winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
    call :refresh_path
    where ffmpeg >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] FFmpeg installed successfully
        exit /b 0
    )
)

echo [WARN] Could not install FFmpeg automatically.
echo   Install with: winget install Gyan.FFmpeg
echo   Or download from: https://ffmpeg.org/download.html
exit /b 0

:setup_repository
if exist "%INSTALL_DIR%\.git" (
    echo [INFO] Project found at %INSTALL_DIR%
    exit /b 0
)

echo [INFO] Cloning VideoCaptioner to %INSTALL_DIR%...
git clone --depth 1 "%REPO_URL%" "%INSTALL_DIR%"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to clone repository
    pause
    exit /b 1
)
echo [OK] Repository cloned successfully
exit /b 0

:install_dependencies
echo [INFO] Installing dependencies with uv...
uv sync
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed
exit /b 0

:run_app
echo.
echo [INFO] Starting VideoCaptioner...
echo.
uv run videocaptioner
if !errorlevel! neq 0 (
    echo.
    echo Application exited with error.
    pause
)
exit /b 0

:: Refresh PATH from registry to pick up newly installed programs
:refresh_path
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%b"
set "PATH=!SYS_PATH!;!USR_PATH!"
:: Re-add uv paths in case they were lost
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;!PATH!"
exit /b 0
