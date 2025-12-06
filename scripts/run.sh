#!/bin/bash
# VideoCaptioner Installer & Launcher for macOS/Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/WEIFENG2333/VideoCaptioner/main/scripts/run.sh | bash

set -e

# Configuration
REPO_URL="https://github.com/WEIFENG2333/VideoCaptioner.git"
INSTALL_DIR="${VIDEOCAPTIONER_HOME:-$HOME/VideoCaptioner}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running from within the project directory
detect_project_dir() {
    # If main.py exists in current directory, use it
    if [ -f "main.py" ] && [ -f "pyproject.toml" ] && [ -d "app" ]; then
        INSTALL_DIR="$(pwd)"
        return 0
    fi

    # If script is run from scripts/ subdirectory, check parent
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PARENT_DIR="$(dirname "$SCRIPT_DIR")"
    
    if [ -f "$PARENT_DIR/main.py" ] && [ -f "$PARENT_DIR/pyproject.toml" ]; then
        INSTALL_DIR="$PARENT_DIR"
        return 0
    fi

    # If script is in project root
    if [ -f "$SCRIPT_DIR/main.py" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
        INSTALL_DIR="$SCRIPT_DIR"
        return 0
    fi

    return 1
}

# Install uv if not present
install_uv() {
    if command -v uv &> /dev/null; then
        print_success "uv is already installed: $(uv --version)"
        return 0
    fi

    print_info "Installing uv package manager..."

    if command -v curl &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget &> /dev/null; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        print_error "Neither curl nor wget found. Please install one of them first."
        exit 1
    fi

    # Add uv to PATH for current session
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v uv &> /dev/null; then
        print_success "uv installed successfully: $(uv --version)"
    else
        print_error "Failed to install uv. Please install manually: https://docs.astral.sh/uv/"
        exit 1
    fi
}

# Clone or update repository
setup_repository() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        print_info "Project found at $INSTALL_DIR"
        cd "$INSTALL_DIR"

        # Optional: pull latest changes
        if [ "${VIDEOCAPTIONER_AUTO_UPDATE:-false}" = "true" ]; then
            print_info "Checking for updates..."
            git pull --ff-only 2>/dev/null || print_warning "Could not update (local changes?)"
        fi
    else
        print_info "Cloning VideoCaptioner to $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        print_success "Repository cloned successfully"
    fi
}

# Install dependencies with uv
install_dependencies() {
    print_info "Installing dependencies with uv..."

    # Sync dependencies (creates .venv if needed)
    uv sync

    print_success "Dependencies installed"
}

# Check system dependencies
check_system_deps() {
    local missing_deps=()

    # Check ffmpeg
    if ! command -v ffmpeg &> /dev/null; then
        missing_deps+=("ffmpeg")
    fi

    # Check aria2 (optional, for faster downloads)
    if ! command -v aria2c &> /dev/null; then
        print_warning "aria2 not found (optional, for faster model downloads)"
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_warning "Missing system dependencies: ${missing_deps[*]}"

        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  Install with: brew install ${missing_deps[*]}"
        elif command -v apt &> /dev/null; then
            echo "  Install with: sudo apt install ${missing_deps[*]}"
        elif command -v dnf &> /dev/null; then
            echo "  Install with: sudo dnf install ${missing_deps[*]}"
        elif command -v pacman &> /dev/null; then
            echo "  Install with: sudo pacman -S ${missing_deps[*]}"
        fi
    fi
}

# Run the application
run_app() {
    print_info "Starting VideoCaptioner..."
    echo ""

    cd "$INSTALL_DIR"
    uv run python main.py
}

# Main
main() {
    echo ""
    echo "=================================="
    echo "  VideoCaptioner Installer"
    echo "=================================="
    echo ""

    # Try to detect if we're in project directory
    if detect_project_dir; then
        print_info "Running from project directory: $INSTALL_DIR"
    fi

    # Check git
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install git first."
        exit 1
    fi

    # Install uv
    install_uv

    # Setup repository (clone if needed)
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        setup_repository
    else
        cd "$INSTALL_DIR"
    fi

    # Install/update dependencies
    install_dependencies

    # Check system dependencies
    check_system_deps

    # Run the app
    run_app
}

main "$@"

