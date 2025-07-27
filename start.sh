#!/bin/bash
# VideoCaptioner 启动脚本 (Unix/Linux/macOS)
# 作者: Weifeng
# 说明: 一键启动 VideoCaptioner 应用程序

echo "========================================"
echo "     VideoCaptioner 启动器"
echo "========================================"
echo ""

# 检查Python是否已安装
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[错误] 未检测到Python安装！"
    echo "请先安装Python 3.8或更高版本"
    
    # 根据系统提供安装建议
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macOS用户建议使用Homebrew安装: brew install python3"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "Linux用户请使用包管理器安装，例如:"
        echo "  Ubuntu/Debian: sudo apt-get install python3"
        echo "  Fedora: sudo dnf install python3"
    fi
    
    exit 1
fi

# 确定Python命令
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# 显示Python版本
echo "[信息] 检测到Python版本:"
$PYTHON_CMD --version

# 检查是否在正确的目录
if [ ! -f "main.py" ]; then
    echo "[错误] 未找到main.py文件！"
    echo "请确保在VideoCaptioner项目根目录运行此脚本"
    exit 1
fi

# 检查虚拟环境是否存在
if [ -f "venv/bin/activate" ]; then
    echo "[信息] 激活虚拟环境..."
    source venv/bin/activate
else
    echo "[提示] 未检测到虚拟环境，使用系统Python"
fi

# 检查依赖是否已安装
if ! $PYTHON_CMD -c "import PyQt5" 2>/dev/null; then
    echo "[警告] 检测到缺少依赖包！"
    echo -n "是否要自动安装依赖？(y/n): "
    read install_deps
    
    if [[ "$install_deps" == "y" ]] || [[ "$install_deps" == "Y" ]]; then
        echo "[信息] 正在安装依赖..."
        
        # 使用pip或pip3
        if command -v pip3 &> /dev/null; then
            PIP_CMD="pip3"
        else
            PIP_CMD="pip"
        fi
        
        $PIP_CMD install -r requirements.txt
        if [ $? -ne 0 ]; then
            echo "[错误] 依赖安装失败！"
            exit 1
        fi
    else
        echo "[警告] 跳过依赖安装，程序可能无法正常运行"
    fi
fi

# macOS特殊处理：检查ffmpeg是否安装
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v ffmpeg &> /dev/null; then
        echo "[警告] 未检测到ffmpeg！"
        echo "建议使用Homebrew安装: brew install ffmpeg"
        echo "是否继续运行？(y/n): "
        read continue_run
        if [[ "$continue_run" != "y" ]] && [[ "$continue_run" != "Y" ]]; then
            exit 1
        fi
    fi
    
    # macOS还需要检查aria2
    if ! command -v aria2c &> /dev/null; then
        echo "[警告] 未检测到aria2！"
        echo "建议使用Homebrew安装: brew install aria2"
    fi
fi

# 启动应用程序
echo ""
echo "[信息] 正在启动 VideoCaptioner..."
echo "========================================"
$PYTHON_CMD main.py

# 检查退出状态
if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 程序异常退出！"
    # 在某些终端中保持窗口打开
    read -n 1 -s -r -p "按任意键继续..."
fi