#!/bin/bash
# Compile .ts translation files to .qm binary files
# Usage: ./scripts/trans-compile.sh [language_code]
#   ./scripts/trans-compile.sh         # Compile all languages
#   ./scripts/trans-compile.sh en_US   # Compile English only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TRANS_DIR="$PROJECT_ROOT/resource/translations"

# Check for lrelease tool
check_lrelease() {
    if command -v lrelease &> /dev/null; then
        echo "lrelease"
    elif command -v lrelease-qt5 &> /dev/null; then
        echo "lrelease-qt5"
    else
        echo ""
    fi
}

LRELEASE=$(check_lrelease)

if [ -z "$LRELEASE" ]; then
    echo "❌ lrelease tool not found"
    echo ""
    echo "Please install Qt toolchain:"
    echo "  macOS:   brew install qt@5"
    echo "  Linux:   sudo apt-get install qttools5-dev-tools"
    echo ""
    echo "Then add lrelease to PATH:"
    echo "  export PATH=\"/opt/homebrew/opt/qt@5/bin:\$PATH\""
    exit 1
fi

echo "🔨 Compiling translation files..."
echo ""

# Compile specific language if provided
if [ -n "$1" ]; then
    LANG_CODE="$1"
    TS_FILE="$TRANS_DIR/VideoCaptioner_$LANG_CODE.ts"

    if [ ! -f "$TS_FILE" ]; then
        echo "❌ Translation file not found: $TS_FILE"
        exit 1
    fi

    echo "📦 Compiling $LANG_CODE..."
    $LRELEASE "$TS_FILE" -qm "$TRANS_DIR/VideoCaptioner_$LANG_CODE.qm"
else
    # Compile all translation files
    for ts_file in "$TRANS_DIR"/*.ts; do
        if [ -f "$ts_file" ]; then
            filename=$(basename "$ts_file" .ts)
            echo "📦 Compiling $filename..."
            $LRELEASE "$ts_file" -qm "$TRANS_DIR/$filename.qm"
        fi
    done
fi

echo ""
echo "✅ Compilation completed!"
echo "📁 Output files: resource/translations/*.qm"
