#!/bin/bash
# VideoCaptioner Launcher for macOS/Linux

# Check Python installation
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "Error: Python not found. Please install Python 3.8+"
    echo "macOS: brew install python3"
    echo "Linux: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Determine Python command
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
else
    PYTHON_CMD="python"
    PIP_CMD="pip"
fi

# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo "Error: main.py not found. Please run from project root."
    exit 1
fi

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Check and install dependencies
if ! $PYTHON_CMD -c "import PyQt5" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# macOS specific checks
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v ffmpeg &> /dev/null; then
        echo "Warning: ffmpeg not found. Install with: brew install ffmpeg"
    fi
    if ! command -v aria2c &> /dev/null; then
        echo "Warning: aria2 not found. Install with: brew install aria2"
    fi
fi

# Run the application
echo "Starting VideoCaptioner..."
$PYTHON_CMD main.py