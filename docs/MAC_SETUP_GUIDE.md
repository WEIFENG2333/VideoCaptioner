# VideoCaptioner macOS 设置指南

## 概述

VideoCaptioner 现已完全支持 macOS 系统，包括所有核心功能如语音转录、字幕优化、翻译和视频合成。本指南将帮助您在 macOS 上顺利安装和运行 VideoCaptioner。

## 系统要求

- **操作系统**: macOS 10.14 (Mojave) 或更高版本
- **处理器**: Intel 或 Apple Silicon (M1/M2/M3)
- **内存**: 建议 8GB RAM 或更多
- **存储空间**: 至少 2GB 可用空间
- **网络**: 稳定的互联网连接（用于在线功能）

## 安装方法

### 方法一：一键启动脚本（推荐）

这是最简单的安装方法，适合所有用户：

1. **克隆项目**
   ```bash
   git clone https://github.com/WEIFENG2333/VideoCaptioner.git
   cd VideoCaptioner
   ```

2. **运行一键启动脚本**
   ```bash
   ./start.sh
   ```

脚本将自动完成以下操作：
- 检测系统版本
- 安装必要的系统依赖
- 创建 Python 虚拟环境
- 安装 Python 依赖包
- 启动 VideoCaptioner

### 方法二：手动安装

如果您希望手动控制安装过程：

1. **安装 Homebrew**（如果尚未安装）
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **安装系统依赖**
   ```bash
   brew install python@3.11 ffmpeg aria2
   ```

3. **克隆并设置项目**
   ```bash
   git clone https://github.com/WEIFENG2333/VideoCaptioner.git
   cd VideoCaptioner
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **启动程序**
   ```bash
   python main.py
   ```

## 系统权限配置

### 1. 麦克风权限

如果您需要使用音频录制功能：

1. 打开"系统偏好设置" > "安全性与隐私" > "隐私"
2. 选择"麦克风"
3. 确保 Terminal 或您的终端应用程序已被选中

### 2. 文件访问权限

为了让程序能够访问您的文件：

1. 打开"系统偏好设置" > "安全性与隐私" > "隐私"
2. 选择"完全磁盘访问权限"
3. 添加 Terminal 应用程序

### 3. 网络权限

如果系统询问网络访问权限，请点击"允许"。

## 功能特性

### 完全支持的功能

✅ **语音转录**
- 支持 Faster Whisper（本地）
- 支持在线 API 接口
- 支持多种语言

✅ **字幕处理**
- 智能断句
- 内容优化
- 多语言翻译

✅ **视频处理**
- 字幕合成
- 多种格式支持
- 批量处理

✅ **用户界面**
- 完整的 PyQt5 界面
- 拖放支持
- 实时预览

### 平台特定优化

🍎 **macOS 专项优化**
- 原生文件夹打开支持
- 正确的可执行文件处理
- 优化的路径管理
- 支持 Apple Silicon 和 Intel 处理器

## 常见问题解决

### Q: 启动脚本提示权限被拒绝

**解决方案:**
```bash
chmod +x start.sh update.sh
```

### Q: Homebrew 安装失败

**解决方案:**
1. 检查网络连接
2. 尝试使用国内镜像：
   ```bash
   /bin/bash -c "$(curl -fsSL https://gitee.com/ineo6/homebrew-install/raw/master/install.sh)"
   ```

### Q: Python 依赖安装失败

**解决方案:**
1. 确保使用虚拟环境
2. 升级 pip：
   ```bash
   pip install --upgrade pip
   ```
3. 尝试使用国内镜像：
   ```bash
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

### Q: FFmpeg 不可用

**解决方案:**
```bash
# 重新安装 FFmpeg
brew uninstall ffmpeg
brew install ffmpeg

# 检查是否正确安装
ffmpeg -version
```

### Q: 模型下载失败

**解决方案:**
1. 检查网络连接
2. 尝试手动下载模型文件
3. 使用 VPN（如果在某些地区）

## 更新程序

使用一键更新脚本：

```bash
./update.sh
```

更新脚本会：
- 备份您的用户数据
- 拉取最新代码
- 更新依赖包
- 保留您的设置

## 性能优化建议

### 1. 使用 Apple Silicon 优化

如果您使用 M1/M2/M3 Mac：
- 确保使用 ARM64 版本的 Python
- 某些模型在 Apple Silicon 上运行更快

### 2. 内存优化

- 关闭不必要的应用程序
- 对于大型模型，建议至少 16GB RAM

### 3. 存储优化

- 定期清理缓存文件
- 将模型文件存储在 SSD 上

## 故障排除

### 查看日志

程序日志位于：
```
AppData/logs/
```

### 重置环境

如果遇到严重问题，可以重置环境：

```bash
# 删除虚拟环境
rm -rf venv

# 清理缓存
rm -rf AppData/cache

# 重新运行启动脚本
./start.sh
```

## 支持与反馈

如果您在 macOS 上使用 VideoCaptioner 时遇到任何问题：

1. 查看 [常见问题](https://github.com/WEIFENG2333/VideoCaptioner/issues)
2. 提交新的 [Issue](https://github.com/WEIFENG2333/VideoCaptioner/issues/new)
3. 在 Issue 中请包含：
   - macOS 版本
   - 错误信息
   - 日志文件内容

## 更新日志

### v1.3.3 - macOS 完全支持
- ✅ 添加跨平台支持
- ✅ 创建一键启动脚本
- ✅ 优化文件路径处理
- ✅ 修复权限问题
- ✅ 支持本地 Whisper 模型

---

感谢您使用 VideoCaptioner！如果这个指南对您有帮助，请给项目一个 ⭐️