#!/bin/bash
# VideoCaptioner 依赖安装脚本 (Unix/Linux/macOS)
# 作者: Weifeng
# 说明: 自动安装 VideoCaptioner 所需的所有依赖

echo "========================================"
echo "   VideoCaptioner 依赖安装器"
echo "========================================"
echo ""

# 检测操作系统
OS="Unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="Linux"
    # 检测Linux发行版
    if [ -f /etc/debian_version ]; then
        DISTRO="Debian/Ubuntu"
        PKG_MANAGER="apt-get"
    elif [ -f /etc/redhat-release ]; then
        DISTRO="RedHat/Fedora"
        PKG_MANAGER="dnf"
    elif [ -f /etc/arch-release ]; then
        DISTRO="Arch"
        PKG_MANAGER="pacman"
    else
        DISTRO="Unknown"
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macOS"
    PKG_MANAGER="brew"
fi

echo "[信息] 检测到操作系统: $OS"
if [[ "$OS" == "Linux" ]]; then
    echo "[信息] Linux发行版: $DISTRO"
fi
echo ""

# 检查Python是否已安装
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[错误] 未检测到Python安装！"
    echo ""
    
    if [[ "$OS" == "macOS" ]]; then
        echo "请使用Homebrew安装Python:"
        echo "  brew install python3"
    elif [[ "$OS" == "Linux" ]]; then
        case "$PKG_MANAGER" in
            apt-get)
                echo "请运行: sudo apt-get update && sudo apt-get install python3 python3-pip python3-venv"
                ;;
            dnf)
                echo "请运行: sudo dnf install python3 python3-pip"
                ;;
            pacman)
                echo "请运行: sudo pacman -S python python-pip"
                ;;
            *)
                echo "请使用系统包管理器安装python3"
                ;;
        esac
    fi
    
    exit 1
fi

# 确定Python命令
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
else
    PYTHON_CMD="python"
    PIP_CMD="pip"
fi

# 显示Python版本
echo "[信息] 检测到Python版本:"
$PYTHON_CMD --version
echo ""

# 检查pip是否可用
if ! command -v $PIP_CMD &> /dev/null; then
    echo "[错误] pip未安装！"
    echo "正在尝试安装pip..."
    
    if [[ "$OS" == "Linux" ]]; then
        case "$PKG_MANAGER" in
            apt-get)
                sudo apt-get install python3-pip
                ;;
            dnf)
                sudo dnf install python3-pip
                ;;
            pacman)
                sudo pacman -S python-pip
                ;;
        esac
    elif [[ "$OS" == "macOS" ]]; then
        $PYTHON_CMD -m ensurepip --default-pip
    fi
    
    if ! command -v $PIP_CMD &> /dev/null; then
        echo "[错误] pip安装失败！"
        exit 1
    fi
fi

# 更新pip
echo "[信息] 更新pip到最新版本..."
$PYTHON_CMD -m pip install --upgrade pip

# 检查venv模块
if ! $PYTHON_CMD -m venv --help &> /dev/null; then
    echo "[警告] venv模块未安装，正在安装..."
    if [[ "$OS" == "Linux" ]] && [[ "$PKG_MANAGER" == "apt-get" ]]; then
        sudo apt-get install python3-venv
    fi
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo ""
    echo "[信息] 创建Python虚拟环境..."
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo "[错误] 虚拟环境创建失败！"
        exit 1
    fi
    echo "[信息] 虚拟环境创建成功！"
fi

# 激活虚拟环境
echo "[信息] 激活虚拟环境..."
source venv/bin/activate

# 安装Python依赖
echo ""
echo "[信息] 安装Python依赖包..."
echo "----------------------------------------"
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[错误] Python依赖安装失败！"
    exit 1
fi

# 检查和安装系统工具
echo ""
echo "[信息] 检查系统工具..."
echo "----------------------------------------"

# 安装系统依赖的函数
install_system_deps() {
    local package=$1
    local brew_package=${2:-$package}
    
    if ! command -v $package &> /dev/null; then
        echo "[信息] 正在安装 $package..."
        
        if [[ "$OS" == "macOS" ]]; then
            if command -v brew &> /dev/null; then
                brew install $brew_package
            else
                echo "[警告] Homebrew未安装，请先安装Homebrew："
                echo "/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                return 1
            fi
        elif [[ "$OS" == "Linux" ]]; then
            case "$PKG_MANAGER" in
                apt-get)
                    sudo apt-get update && sudo apt-get install -y $package
                    ;;
                dnf)
                    sudo dnf install -y $package
                    ;;
                pacman)
                    sudo pacman -S --noconfirm $package
                    ;;
                *)
                    echo "[警告] 请手动安装 $package"
                    return 1
                    ;;
            esac
        fi
    else
        echo "[✓] $package 已安装"
    fi
}

# 检查ffmpeg
install_system_deps "ffmpeg"

# 检查aria2
if [[ "$OS" == "macOS" ]]; then
    install_system_deps "aria2c" "aria2"
else
    install_system_deps "aria2c" "aria2"
fi

# macOS特殊：安装其他可能需要的工具
if [[ "$OS" == "macOS" ]]; then
    echo ""
    echo "[信息] macOS额外配置..."
    
    # 检查命令行工具
    if ! xcode-select -p &> /dev/null; then
        echo "[信息] 安装Xcode命令行工具..."
        xcode-select --install
    fi
fi

# 创建必要的目录
echo ""
echo "[信息] 创建必要的目录结构..."
mkdir -p AppData/cache
mkdir -p AppData/logs
mkdir -p AppData/models
mkdir -p work-dir

# 设置权限
chmod -R 755 AppData
chmod -R 755 work-dir

# 完成
echo ""
echo "========================================"
echo "[成功] 依赖安装完成！"
echo ""
echo "现在可以运行 ./start.sh 启动程序"
echo "========================================"
echo ""