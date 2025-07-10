#!/bin/bash

# VideoCaptioner 一键更新脚本（适用于 macOS 和 Linux）
# 作者：VideoCaptioner 团队
# 版本：v1.0

set -e

echo "========================================"
echo "    VideoCaptioner 一键更新脚本"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查是否为 Git 仓库
check_git_repo() {
    if [ ! -d ".git" ]; then
        echo -e "${RED}错误：当前目录不是 Git 仓库${NC}"
        echo "请确保您是从 GitHub 克隆的项目，而不是下载的压缩包"
        echo "克隆命令：git clone https://github.com/WEIFENG2333/VideoCaptioner.git"
        exit 1
    fi
}

# 检查 Git 是否安装
check_git() {
    if ! command -v git &> /dev/null; then
        echo -e "${RED}错误：未安装 Git${NC}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "请安装 Xcode Command Line Tools：xcode-select --install"
        elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
            echo "请安装 Git：sudo apt-get install git"
        fi
        exit 1
    fi
}

# 备份用户数据
backup_user_data() {
    echo -e "${BLUE}备份用户数据...${NC}"
    
    # 创建备份目录
    BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # 备份用户配置和数据
    if [ -d "AppData" ]; then
        cp -r AppData "$BACKUP_DIR/" && echo -e "${GREEN}✓ 已备份 AppData${NC}"
    fi
    
    if [ -d "work-dir" ]; then
        cp -r work-dir "$BACKUP_DIR/" && echo -e "${GREEN}✓ 已备份 work-dir${NC}"
    fi
    
    if [ -f "venv" ]; then
        echo -e "${YELLOW}注意：虚拟环境将在更新后重新创建${NC}"
    fi
    
    echo -e "${GREEN}用户数据已备份到：$BACKUP_DIR${NC}"
}

# 获取当前版本信息
get_current_version() {
    CURRENT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
    echo -e "${BLUE}当前分支：$CURRENT_BRANCH${NC}"
    echo -e "${BLUE}当前提交：${CURRENT_COMMIT:0:8}${NC}"
}

# 检查远程更新
check_remote_updates() {
    echo -e "${BLUE}检查远程更新...${NC}"
    
    # 获取远程更新
    git fetch origin
    
    # 检查是否有更新
    LOCAL_COMMIT=$(git rev-parse HEAD)
    REMOTE_COMMIT=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)
    
    if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
        echo -e "${GREEN}您的代码已是最新版本！${NC}"
        echo "是否仍要继续更新？(y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            echo "更新已取消"
            exit 0
        fi
    else
        echo -e "${YELLOW}发现新的更新！${NC}"
        echo "远程版本：${REMOTE_COMMIT:0:8}"
    fi
}

# 检查本地更改
check_local_changes() {
    if ! git diff-index --quiet HEAD --; then
        echo -e "${YELLOW}检测到本地更改，这些更改将被保存：${NC}"
        git status --short
        echo ""
        echo "是否继续更新？本地更改将被暂存 (y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            echo "更新已取消"
            exit 0
        fi
        
        # 暂存本地更改
        echo -e "${BLUE}暂存本地更改...${NC}"
        git stash push -m "Auto-stash before update $(date)"
        STASHED=true
    else
        STASHED=false
    fi
}

# 执行更新
perform_update() {
    echo -e "${BLUE}正在更新代码...${NC}"
    
    # 确定主分支名称
    MAIN_BRANCH=$(git remote show origin | grep 'HEAD branch' | cut -d' ' -f5 2>/dev/null || echo "main")
    
    # 拉取最新代码
    git pull origin "$MAIN_BRANCH"
    
    echo -e "${GREEN}代码更新完成！${NC}"
}

# 恢复本地更改
restore_local_changes() {
    if [ "$STASHED" = true ]; then
        echo -e "${BLUE}恢复本地更改...${NC}"
        if git stash pop; then
            echo -e "${GREEN}本地更改已恢复${NC}"
        else
            echo -e "${YELLOW}警告：恢复本地更改时发生冲突，请手动解决${NC}"
            echo "使用 'git stash list' 查看暂存的更改"
            echo "使用 'git stash apply' 手动恢复更改"
        fi
    fi
}

# 更新依赖
update_dependencies() {
    echo -e "${BLUE}更新 Python 依赖...${NC}"
    
    if [ -d "venv" ]; then
        echo -e "${YELLOW}删除旧的虚拟环境...${NC}"
        rm -rf venv
    fi
    
    # 重新创建虚拟环境
    echo -e "${BLUE}创建新的虚拟环境...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    
    # 升级 pip
    pip install --upgrade pip
    
    # 安装依赖
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        echo -e "${GREEN}依赖更新完成${NC}"
    else
        echo -e "${YELLOW}警告：未找到 requirements.txt 文件${NC}"
    fi
}

# 清理临时文件
cleanup() {
    echo -e "${BLUE}清理临时文件...${NC}"
    
    # 清理 Python 缓存
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    
    # 清理应用缓存（保留用户数据）
    if [ -d "AppData/cache" ]; then
        rm -rf AppData/cache/*
        echo -e "${GREEN}✓ 已清理应用缓存${NC}"
    fi
}

# 显示更新结果
show_update_result() {
    echo ""
    echo -e "${GREEN}============ 更新完成 ============${NC}"
    
    NEW_COMMIT=$(git rev-parse HEAD)
    echo -e "${GREEN}新版本：${NEW_COMMIT:0:8}${NC}"
    
    # 显示更新日志
    if [ "$CURRENT_COMMIT" != "unknown" ] && [ "$CURRENT_COMMIT" != "$NEW_COMMIT" ]; then
        echo ""
        echo -e "${BLUE}更新日志：${NC}"
        git log --oneline "$CURRENT_COMMIT..$NEW_COMMIT" | head -10
    fi
    
    echo ""
    echo -e "${GREEN}更新成功！您现在可以运行 ./start.sh 启动程序${NC}"
}

# 错误处理函数
error_handler() {
    echo -e "${RED}更新过程中发生错误${NC}"
    echo "如需帮助，请访问：https://github.com/WEIFENG2333/VideoCaptioner/issues"
    
    # 如果有暂存的更改，提示用户恢复
    if [ "$STASHED" = true ]; then
        echo -e "${YELLOW}提示：您的本地更改已保存，可使用 'git stash pop' 恢复${NC}"
    fi
    
    exit 1
}

# 设置错误处理
trap error_handler ERR

# 主执行流程
main() {
    # 检查 Git 环境
    check_git
    check_git_repo
    
    # 获取当前版本信息
    get_current_version
    
    # 备份用户数据
    backup_user_data
    
    # 检查更新
    check_remote_updates
    check_local_changes
    
    # 执行更新
    perform_update
    restore_local_changes
    
    # 更新环境
    update_dependencies
    cleanup
    
    # 显示结果
    show_update_result
}

# 如果脚本被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi