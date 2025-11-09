#!/bin/bash
# Extract translation strings from Python code to .ts files
# Auto-removes obsolete entries
# Usage: ./scripts/trans-extract.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TRANS_DIR="$PROJECT_ROOT/resource/translations"

echo "🔍 Extracting translation strings..."
echo ""

cd "$PROJECT_ROOT"

# Check if pylupdate5 is available
if ! command -v pylupdate5 &> /dev/null; then
    echo "❌ pylupdate5 not found"
    exit 1
fi

# Extract all tr() calls from Python files to .ts files
echo "📝 Scanning tr() calls in Python code..."
pylupdate5 -verbose \
    $(find app -name "*.py") \
    -ts "$TRANS_DIR/VideoCaptioner_zh_CN.ts" \
    -ts "$TRANS_DIR/VideoCaptioner_zh_HK.ts" \
    -ts "$TRANS_DIR/VideoCaptioner_en_US.ts"

# Remove obsolete translations
echo ""
echo "🧹 Cleaning obsolete translations..."

for ts_file in "$TRANS_DIR"/*.ts; do
    if [ -f "$ts_file" ]; then
        filename=$(basename "$ts_file")

        # Count obsolete entries before removal
        obsolete_count=$(grep -c 'type="obsolete"' "$ts_file" 2>/dev/null || echo "0")
        obsolete_count=$(echo "$obsolete_count" | head -1)  # Ensure single value

        if [ "$obsolete_count" -gt 0 ] 2>/dev/null; then
            # Create temp file and remove obsolete messages
            python3 << EOF
import re
from pathlib import Path

ts_path = Path("$ts_file")
content = ts_path.read_text(encoding='utf-8')

# Remove entire <message>...</message> blocks that contain type="obsolete"
# This regex matches from <message> to </message> if it contains type="obsolete"
pattern = r'    <message>.*?type="obsolete".*?</message>\n'
cleaned_content = re.sub(pattern, '', content, flags=re.DOTALL)

ts_path.write_text(cleaned_content, encoding='utf-8')
EOF

            echo "   ✓ $filename: Removed $obsolete_count obsolete entries"
        else
            echo "   ✓ $filename: No obsolete entries"
        fi
    fi
done

echo ""
echo "✅ Translation strings extracted and cleaned successfully!"
echo "📁 Translation files: resource/translations/"
echo ""
echo "💡 Next steps:"
echo "   1. Edit translations with Qt Linguist: linguist resource/translations/VideoCaptioner_en_US.ts"
echo "   2. Or compile directly: ./scripts/trans-compile.sh"
