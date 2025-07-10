#!/bin/bash

# VideoCaptioner 一键启动脚本（适用于 macOS 和 Linux）
# 作者：VideoCaptioner 团队
# 版本：v1.0

set -e

echo "========================================"
echo "    VideoCaptioner 一键启动脚本"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查操作系统
check_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "${GREEN}检测到 macOS 系统${NC}"
        OS="macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo -e "${GREEN}检测到 Linux 系统${NC}"
        OS="linux"
    else
        echo -e "${RED}错误：不支持的操作系统 $OSTYPE${NC}"
        exit 1
    fi
}

# 检查并安装依赖
check_dependencies() {
    echo -e "${BLUE}正在检查系统依赖...${NC}"
    
    missing_deps=()
    
    # 检查 Python
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi
    
    # 检查 FFmpeg
    if ! command -v ffmpeg &> /dev/null; then
        missing_deps+=("ffmpeg")
    fi
    
    # 检查 aria2
    if ! command -v aria2c &> /dev/null; then
        missing_deps+=("aria2")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo -e "${YELLOW}缺少以下依赖：${missing_deps[*]}${NC}"
        
        if [[ "$OS" == "macos" ]]; then
            if ! command -v brew &> /dev/null; then
                echo -e "${RED}错误：需要安装 Homebrew${NC}"
                echo "请访问 https://brew.sh 安装 Homebrew"
                exit 1
            fi
            
            echo -e "${BLUE}正在使用 Homebrew 安装依赖...${NC}"
            for dep in "${missing_deps[@]}"; do
                if [[ "$dep" == "python3" ]]; then
                    brew install python@3.11
                else
                    brew install "$dep"
                fi
            done
        elif [[ "$OS" == "linux" ]]; then
            echo -e "${BLUE}正在使用 apt 安装依赖...${NC}"
            sudo apt-get update
            for dep in "${missing_deps[@]}"; do
                if [[ "$dep" == "python3" ]]; then
                    sudo apt-get install -y python3 python3-pip
                else
                    sudo apt-get install -y "$dep"
                fi
            done
        fi
    else
        echo -e "${GREEN}所有依赖已安装${NC}"
    fi
}

# 检查并创建虚拟环境
setup_venv() {
    if [ ! -d "venv" ]; then
        echo -e "${BLUE}创建 Python 虚拟环境...${NC}"
        python3 -m venv venv
    fi
    
    echo -e "${BLUE}激活虚拟环境...${NC}"
    source venv/bin/activate
    
    echo -e "${BLUE}升级 pip...${NC}"
    pip install --upgrade pip
}

# 安装 Python 依赖
install_python_deps() {
    echo -e "${BLUE}安装 Python 依赖包...${NC}"
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        echo -e "${RED}错误：未找到 requirements.txt 文件${NC}"
        exit 1
    fi
}

# 检查目录权限
check_permissions() {
    echo -e "${BLUE}检查目录权限...${NC}"
    
    # 创建必要的目录
    mkdir -p AppData/cache
    mkdir -p AppData/logs
    mkdir -p AppData/models
    mkdir -p work-dir
    mkdir -p resource/bin
    
    # 设置可执行权限
    if [ -d "resource/bin" ]; then
        find resource/bin -type f -exec chmod +x {} \; 2>/dev/null || true
    fi
}

# 启动应用程序
start_app() {
    echo -e "${GREEN}启动 VideoCaptioner...${NC}"
    
    if [ -f "main.py" ]; then
        python main.py
    else
        echo -e "${RED}错误：未找到 main.py 文件${NC}"
        exit 1
    fi
}

# 错误处理函数
error_handler() {
    echo -e "${RED}脚本执行出错，请检查上述错误信息${NC}"
    echo "如需帮助，请访问：https://github.com/WEIFENG2333/VideoCaptioner/issues"
    exit 1
}

# 设置错误处理
trap error_handler ERR

# 主执行流程
main() {
    echo -e "${BLUE}开始检查和配置环境...${NC}"
    
    # 检查操作系统
    check_os
    
    # 检查系统依赖
    check_dependencies
    
    # 设置 Python 虚拟环境
    setup_venv
    
    # 安装 Python 依赖
    install_python_deps
    
    # 检查目录权限
    check_permissions
    
    echo -e "${GREEN}环境配置完成！${NC}"
    echo ""
    
    # 启动应用程序
    start_app
}

# 如果脚本被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi