@echo off
:: VideoCaptioner Launcher for Windows

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found. Please install Python 3.8+
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check if main.py exists
if not exist "main.py" (
    echo Error: main.py not found. Please run from project root.
    pause
    exit /b 1
)

:: Create virtual environment if not exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Check and install dependencies
python -c "import PyQt5" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

:: Create required directories
if not exist "AppData" mkdir AppData
if not exist "AppData\cache" mkdir AppData\cache
if not exist "AppData\logs" mkdir AppData\logs
if not exist "AppData\models" mkdir AppData\models
if not exist "work-dir" mkdir work-dir

:: Run the application
echo Starting VideoCaptioner...
python main.py

:: Pause on error
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error.
    pause
)