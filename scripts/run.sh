#!/bin/bash
# VideoCaptioner Installer & Launcher for macOS/Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/WEIFENG2333/VideoCaptioner/main/scripts/run.sh | bash

set -e

# Configuration
REPO_URL="https://github.com/WEIFENG2333/VideoCaptioner.git"
INSTALL_DIR="${VIDEOCAPTIONER_HOME:-$HOME/VideoCaptioner}"
FASTER_WHISPER_XXL_LINUX_URL_MODERN="https://github.com/Purfview/whisper-standalone-win/releases/download/Faster-Whisper-XXL/Faster-Whisper-XXL_r245.4_linux.7z"
FASTER_WHISPER_XXL_LINUX_URL_LEGACY="https://github.com/Purfview/whisper-standalone-win/releases/download/Faster-Whisper-XXL/Faster-Whisper-XXL_r192.3.1_linux.7z"
FASTER_WHISPER_XXL_GLIBC_MIN="2.35"
FASTER_WHISPER_XXL_LINUX_URL="${FASTER_WHISPER_XXL_LINUX_URL:-}"

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

version_lt() {
    local v1="$1"
    local v2="$2"
    [ "$(printf '%s\n%s\n' "$v1" "$v2" | sort -V | head -n 1)" = "$v1" ] && [ "$v1" != "$v2" ]
}

get_glibc_version() {
    ldd --version 2>/dev/null | awk 'NR==1{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\.[0-9]+$/){print $i; exit}}'
}

resolve_faster_whisper_xxl_linux_url() {
    # 用户显式指定下载源时，优先使用
    if [ -n "$FASTER_WHISPER_XXL_LINUX_URL" ]; then
        echo "$FASTER_WHISPER_XXL_LINUX_URL"
        return 0
    fi

    local glibc_version
    glibc_version="$(get_glibc_version)"

    # glibc 低于 2.35 时，使用 legacy 版本避免 GLIBC_2.35 not found
    if [ -n "$glibc_version" ] && version_lt "$glibc_version" "$FASTER_WHISPER_XXL_GLIBC_MIN"; then
        print_warning "Detected GLIBC $glibc_version (< $FASTER_WHISPER_XXL_GLIBC_MIN), using legacy XXL package." >&2
        echo "$FASTER_WHISPER_XXL_LINUX_URL_LEGACY"
        return 0
    fi

    echo "$FASTER_WHISPER_XXL_LINUX_URL_MODERN"
}

xxl_binary_usable() {
    local binary="$1"
    [ -x "$binary" ] || return 1

    local output
    output="$("$binary" --help 2>&1 || true)"

    if echo "$output" | grep -qiE 'GLIBC_[0-9]+\.[0-9]+.*not found'; then
        return 1
    fi

    return 0
}

download_file() {
    local url="$1"
    local output="$2"

    if command -v curl &> /dev/null; then
        curl -L --fail --retry 2 --connect-timeout 10 -o "$output" "$url"
    elif command -v wget &> /dev/null; then
        wget -O "$output" "$url"
    else
        print_error "Neither curl nor wget found. Please install one of them first."
        return 1
    fi
}

extract_7z() {
    local archive="$1"
    local output_dir="$2"

    if command -v 7z &> /dev/null; then
        7z x "$archive" "-o$output_dir" -y >/dev/null
        return 0
    fi

    if command -v 7zz &> /dev/null; then
        7zz x "$archive" "-o$output_dir" -y >/dev/null
        return 0
    fi

    print_warning "7z not found. Using Python py7zr fallback via uv..."
    uv run --with py7zr python - "$archive" "$output_dir" <<'PY'
import pathlib
import sys

import py7zr

archive = pathlib.Path(sys.argv[1])
output_dir = pathlib.Path(sys.argv[2])
output_dir.mkdir(parents=True, exist_ok=True)

with py7zr.SevenZipFile(archive, mode="r") as zf:
    zf.extractall(path=output_dir)
PY
}

install_faster_whisper_xxl_linux() {
    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        return 0
    fi

    local bin_dir="$INSTALL_DIR/resource/bin"
    local xxl_dir="$bin_dir/Faster-Whisper-XXL"
    local xxl_bin="$xxl_dir/faster-whisper-xxl"
    local xxl_link="$bin_dir/faster-whisper-xxl"
    local selected_url
    selected_url="$(resolve_faster_whisper_xxl_linux_url)"
    local archive_path="$bin_dir/$(basename "$selected_url")"
    local need_install=1

    mkdir -p "$bin_dir"

    # 已经存在且可运行：不下载、不解压
    if [ -f "$xxl_bin" ]; then
        chmod +x "$xxl_bin"
        ln -sf "$xxl_bin" "$xxl_link"
        if xxl_binary_usable "$xxl_bin"; then
            print_success "Faster-Whisper-XXL already installed: $xxl_bin"
            need_install=0
        else
            print_warning "Existing binary is incompatible with current runtime, will reinstall: $xxl_bin"
        fi
    elif [ -x "$xxl_link" ]; then
        if xxl_binary_usable "$xxl_link"; then
            print_success "Faster-Whisper-XXL already installed: $xxl_link"
            need_install=0
        else
            print_warning "Existing binary is incompatible with current runtime, will reinstall: $xxl_link"
        fi
    fi

    if [ "$need_install" -eq 1 ]; then
        print_info "Installing Faster-Whisper-XXL (Linux)..."

        if [ -f "$archive_path" ]; then
            print_info "Found existing archive, skip download: $archive_path"
        else
            print_info "Download source: $selected_url"
            print_info "Archive path: $archive_path"
            download_file "$selected_url" "$archive_path"
        fi

        print_info "Extracting archive..."
        extract_7z "$archive_path" "$bin_dir"

        if [ ! -f "$xxl_bin" ]; then
            local detected_bin
            detected_bin="$(find "$bin_dir" -maxdepth 4 -type f -name "faster-whisper-xxl" | head -n 1 || true)"
            if [ -n "$detected_bin" ]; then
                mkdir -p "$xxl_dir"
                cp "$detected_bin" "$xxl_bin"
            fi
        fi

        if [ ! -f "$xxl_bin" ]; then
            print_error "Faster-Whisper-XXL install failed: binary not found after extraction."
            print_error "Expected path: $xxl_bin"
            exit 1
        fi

        chmod +x "$xxl_bin"
        ln -sf "$xxl_bin" "$xxl_link"

        if ! xxl_binary_usable "$xxl_bin"; then
            local glibc_version
            glibc_version="$(get_glibc_version)"
            print_error "Installed XXL binary is still not runnable on this system (GLIBC: ${glibc_version:-unknown})."
            print_error "Please set a compatible package URL via FASTER_WHISPER_XXL_LINUX_URL and rerun."
            exit 1
        fi

        print_success "Faster-Whisper-XXL installed: $xxl_bin"
    fi

    export PATH="$xxl_dir:$bin_dir:$PATH"
}

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
    # Check ffmpeg (required)
    if ! command -v ffmpeg &> /dev/null; then
        print_warning "FFmpeg not found (required for video synthesis)"

        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  Install with: brew install ffmpeg"
        elif command -v apt &> /dev/null; then
            echo "  Install with: sudo apt install ffmpeg"
        elif command -v dnf &> /dev/null; then
            echo "  Install with: sudo dnf install ffmpeg"
        elif command -v pacman &> /dev/null; then
            echo "  Install with: sudo pacman -S ffmpeg"
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

    # Install Faster-Whisper-XXL (Linux)
    install_faster_whisper_xxl_linux

    # Run the app
    run_app
}

main "$@"
