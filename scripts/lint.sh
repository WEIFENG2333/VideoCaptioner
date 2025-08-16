#!/bin/bash
# 清理Python项目中未使用的导入并整理导入顺序

echo "🧹 开始清理未使用的导入..."

# 检查并修复未使用的导入 (F401)
echo "📍 步骤1: 移除未使用的导入"
ruff check . --select F401 --fix

# 整理导入顺序 (I)
echo "📍 步骤2: 整理导入顺序"
ruff check . --select I --fix

# 显示统计信息
echo ""
echo "✅ 清理完成！"
echo "📊 检查其他可能的问题:"
ruff check . --statistics

echo ""
echo "💡 提示: 使用 'ruff check . --fix' 可以自动修复大部分代码风格问题"