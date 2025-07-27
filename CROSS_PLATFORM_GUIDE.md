# 跨平台使用指南

本文档说明如何在不同操作系统上运行 VideoCaptioner。

## 支持的操作系统

- Windows 10/11
- macOS 10.15 (Catalina) 或更高版本
- Linux (Ubuntu 20.04+, Fedora, Arch Linux等)

## 快速开始

### Windows

1. **安装依赖**

   ```cmd
   install.bat
   ```

2. **启动程序**
   ```cmd
   start.bat
   ```

### macOS / Linux

1. **安装依赖**

   ```bash
   chmod +x install.sh
   ./install.sh
   ```

2. **启动程序**
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

## 系统要求

### 基础要求

- Python 3.8 或更高版本
- 4GB 或更多内存
- 10GB 可用磁盘空间（用于模型存储）

### 系统工具

#### 必需工具

- **ffmpeg**: 用于视频处理
  - Windows: 从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载或使用 `choco install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: 使用系统包管理器安装 (apt/dnf/pacman)

#### 可选工具

- **aria2**: 用于高速下载
  - Windows: 从 [aria2.github.io](https://aria2.github.io/) 下载或使用 `choco install aria2`
  - macOS: `brew install aria2`
  - Linux: 使用系统包管理器安装

## 已知差异

### 文件路径

- Windows 使用反斜杠 `\`，Unix系统使用正斜杠 `/`
- 程序已自动处理路径差异

### 二进制程序

- Whisper 模型在所有平台通用
- Faster-Whisper 程序需要针对不同平台下载对应版本

### 界面显示

- 字体渲染可能因系统而异
- 建议 Linux 用户安装中文字体以正确显示界面

## 故障排除

### macOS 特殊说明

1. **权限问题**
   - 首次运行可能需要在"系统偏好设置 > 安全性与隐私"中允许程序运行
   - 如遇到"无法打开...因为它来自身份不明的开发者"，请右键点击程序选择"打开"

2. **Python 版本**
   - macOS 自带的 Python 可能版本过旧
   - 建议使用 Homebrew 安装最新版本：`brew install python3`

### Linux 特殊说明

1. **依赖包**
   - Ubuntu/Debian: 可能需要安装 `python3-venv` 包
   - 某些发行版可能需要安装额外的开发包

2. **显示问题**
   - 如界面显示异常，请确保安装了 Qt5 相关包
   - 可能需要设置环境变量 `export QT_QPA_PLATFORM=xcb`

### 通用问题

1. **虚拟环境激活失败**
   - Windows: 确保执行策略允许运行脚本
   - Unix: 确保脚本有执行权限

2. **依赖安装失败**
   - 检查网络连接
   - 尝试使用国内镜像源：
     ```bash
     pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
     ```

## 性能优化建议

### GPU 加速

- Windows/Linux: 支持 CUDA 加速（需要 NVIDIA 显卡）
- macOS: 支持 Metal Performance Shaders (MPS) 加速

### 内存管理

- 大文件处理时建议关闭其他应用
- 可在设置中调整并发线程数以适应系统性能

## 反馈与支持

如遇到跨平台相关问题，请在 [GitHub Issues](https://github.com/WEIFENG2333/VideoCaptioner/issues) 提交反馈，并注明：

- 操作系统版本
- Python 版本
- 错误信息截图或日志
