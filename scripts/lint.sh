#!/bin/bash
# Clean unused imports and sort import order in Python project

echo "🧹 Cleaning unused imports..."

# Remove unused imports (F401)
echo "📍 Step 1: Remove unused imports"
ruff check . --select F401 --fix

# Sort import order (I)
echo "📍 Step 2: Sort import order"
ruff check . --select I --fix

# Show statistics
echo ""
echo "✅ Done!"
echo "📊 Check other issues:"
ruff check . --statistics

echo ""
echo "💡 Tip: Run 'ruff check . --fix' to auto-fix most code style issues"