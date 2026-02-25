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

# Friendly error on unexpected exit
trap 'if [ $? -ne 0 ]; then echo ""; print_error "Installation failed at line $LINENO. Please check the output above."; fi' EXIT

# Check if running from within the project directory
detect_project_dir() {
    # If main.py exists in current directory, use it
    if [ -f "main.py" ] && [ -f "pyproject.toml" ] && [ -d "app" ]; then
        INSTALL_DIR="$(pwd)"
        return 0
    fi

    # Guard: BASH_SOURCE is empty when piped via curl | bash
    if [ -z "${BASH_SOURCE[0]}" ] || [ "${BASH_SOURCE[0]}" = "bash" ]; then
        return 1
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

# Install git if not present
install_git() {
    if command -v git &> /dev/null; then
        return 0
    fi

    print_info "Git not found, installing..."

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS: xcode-select triggers git installation
        xcode-select --install 2>/dev/null || true
        print_warning "Please complete the Xcode Command Line Tools installation, then re-run this script."
        exit 1
    elif command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y git
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y git
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm git
    else
        print_error "Could not install git automatically. Please install git manually."
        exit 1
    fi

    if ! command -v git &> /dev/null; then
        print_error "Git installation failed. Please install manually."
        exit 1
    fi
    print_success "Git installed successfully"
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

# Install ffmpeg if not present
install_ffmpeg() {
    if command -v ffmpeg &> /dev/null; then
        print_success "FFmpeg is already installed: $(ffmpeg -version 2>&1 | head -n1)"
        return 0
    fi

    print_info "Installing FFmpeg (required for video synthesis)..."

    if [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v brew &> /dev/null; then
            print_info "Homebrew not found, installing..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add brew to PATH for Apple Silicon and Intel
            [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
            [ -f /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
        fi
        brew install ffmpeg
    elif command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y ffmpeg
    elif command -v dnf &> /dev/null; then
        # Fedora: ffmpeg requires RPM Fusion
        if ! dnf repolist 2>/dev/null | grep -q rpmfusion-free; then
            print_info "Enabling RPM Fusion repository (required for FFmpeg on Fedora)..."
            FEDORA_VERSION=$(rpm -E %fedora)
            sudo dnf install -y \
                "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VERSION}.noarch.rpm"
        fi
        sudo dnf install -y ffmpeg
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm ffmpeg
    else
        print_error "Could not detect package manager. Please install FFmpeg manually."
        exit 1
    fi

    if command -v ffmpeg &> /dev/null; then
        print_success "FFmpeg installed successfully"
    else
        print_error "FFmpeg installation failed. Please install manually."
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
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
        print_success "Repository cloned successfully"
    fi
}

# Install dependencies with uv
install_dependencies() {
    print_info "Installing dependencies with uv..."
    uv sync
    print_success "Dependencies installed"
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

    install_git
    install_uv

    # Setup repository (clone if needed)
    if [ ! -f "$INSTALL_DIR/main.py" ]; then
        setup_repository
    else
        cd "$INSTALL_DIR"
    fi

    install_dependencies
    install_ffmpeg

    run_app
}

main "$@"
