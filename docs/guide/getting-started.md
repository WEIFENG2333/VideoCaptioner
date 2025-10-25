---
title: 快速开始 - VideoCaptioner
description: 快速安装和配置 VideoCaptioner，5分钟开始处理你的第一个视频字幕。支持 Windows、macOS、Linux 多平台。
head:
  - - meta
    - name: keywords
      content: VideoCaptioner安装,快速开始,视频字幕教程,Whisper安装,LLM配置,字幕处理入门
---

# 快速开始

本指南将帮助你快速上手 VideoCaptioner，开始处理你的第一个视频字幕。

## 系统要求

- **Windows**: Windows 10/11 (64位)
- **macOS**: macOS 10.15 或更高版本
- **Linux**: Ubuntu 20.04+ / Debian 11+ / Fedora 35+
- **Python**: Python 3.10 或更高版本（源码运行时需要）
- **内存**: 建议 4GB 以上（使用本地 Whisper 需要 8GB+）

## 安装方式

### Windows 用户（推荐使用打包版本）

软件较为轻量，打包大小不足 60M，已集成所有必要环境，下载后可直接运行。

1. 从 [Release](https://github.com/WEIFENG2333/VideoCaptioner/releases) 页面下载最新版本的可执行程序

   或者：[蓝奏盘下载](https://wwwm.lanzoue.com/ii14G2pdsbej)

2. 双击打开安装包进行安装

3. 首次运行会自动检测环境，无需额外配置

### macOS / Linux 用户

#### 使用自动安装脚本（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
cd VideoCaptioner

# 2. 运行安装脚本
chmod +x run.sh
./run.sh
```

脚本会自动：

- 检测 Python 环境
- 创建虚拟环境并安装依赖
- 检测系统工具（ffmpeg、aria2）
- 启动应用程序

::: tip 提示
macOS 用户需要先安装 [Homebrew](https://brew.sh/)
:::

#### 手动安装

<details>
<summary>点击展开手动安装步骤</summary>

**1. 安装系统依赖**

::: code-group

```bash [macOS]
brew install ffmpeg aria2 python@3.11
```

```bash [Ubuntu/Debian]
sudo apt update
sudo apt install ffmpeg aria2 python3.11 python3.11-venv python3-pip
```

```bash [Fedora]
sudo dnf install ffmpeg aria2 python3.11
```

:::

**2. 克隆项目并安装 Python 依赖**

```bash
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
cd VideoCaptioner

# 创建虚拟环境
python3.11 -m venv venv

# 激活虚拟环境
source venv/bin/activate  # macOS/Linux
# 或
.\venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

**3. 运行程序**

```bash
python main.py
```

</details>

### Docker 部署（实验性）

::: warning 注意
Docker 版本目前还比较基础，欢迎提交 PR 改进。
:::

```bash
# 1. 构建镜像
docker build -t video-captioner .

# 2. 运行容器
docker run -d \
  -p 8501:8501 \
  -v $(pwd)/temp:/app/temp \
  -e OPENAI_BASE_URL="Your API address" \
  -e OPENAI_API_KEY="Your API key" \
  --name video-captioner \
  video-captioner

# 3. 访问应用
# 打开浏览器访问 http://localhost:8501
```

## 基础配置

在开始处理视频之前，建议先完成以下基础配置：

### 1. LLM API 配置（可选但推荐）

LLM 用于字幕断句、优化和翻译。软件内置了基础模型，但配置自己的 API 可以获得更好的效果。

打开 **设置 → LLM 配置**，选择以下任一服务：

| 服务商           | 特点               | 推荐模型                                |
| ---------------- | ------------------ | --------------------------------------- |
| **OpenAI**       | 质量最好           | `gpt-4o-mini` (经济), `gpt-4o` (高质量) |
| **DeepSeek**     | 性价比高           | `deepseek-chat`                         |
| **SiliconCloud** | 国内可用，并发较低 | `Qwen/Qwen2.5-72B-Instruct`             |
| **Ollama**       | 本地运行，完全免费 | `llama3.1:8b`                           |

::: tip 推荐
如果需要高并发和优质模型，可使用本项目的 [LLM API 中转站](https://api.videocaptioner.cn)

配置方式：

- Base URL: `https://api.videocaptioner.cn/v1`
- API Key: 注册后在个人中心获取

推荐模型：

- 高质量：`gemini-2.0-flash-exp`、`claude-sonnet-4.5`
- 经济实惠：`gpt-4o-mini`、`gemini-2.0-flash-exp`
  :::

详细配置方法请查看 [LLM 配置指南](/config/llm)。

### 2. 语音识别配置

打开 **设置 → 转录配置**，选择语音识别引擎：

| 引擎                 | 支持语言 | 运行方式 | 推荐场景                      |
| -------------------- | -------- | -------- | ----------------------------- |
| **FasterWhisper** ⭐ | 99种语言 | 本地     | 最推荐，准确度高，支持GPU加速 |
| **B接口**            | 中英文   | 在线     | 快速测试，无需下载模型        |
| **J接口**            | 中英文   | 在线     | 备用选项                      |
| **WhisperCpp**       | 99种语言 | 本地     | 轻量级本地方案                |
| **Whisper API**      | 99种语言 | 在线     | 使用 OpenAI API               |

::: tip 推荐配置

- **中文视频**: FasterWhisper + Medium 模型或以上
- **英文视频**: FasterWhisper + Small 模型即可
- **其他语言**: FasterWhisper + Large-v2 模型

首次使用需要在软件内下载模型，国内网络可直接下载。
:::

详细配置方法请查看 [ASR 配置指南](/config/asr)。

### 3. 翻译配置（可选）

如果需要翻译字幕，打开 **设置 → 翻译配置**：

| 翻译服务        | 特点                 | 推荐场景     |
| --------------- | -------------------- | ------------ |
| **LLM 翻译** ⭐ | 质量最好，理解上下文 | 追求翻译质量 |
| **Bing 翻译**   | 速度快，免费         | 快速翻译     |
| **Google 翻译** | 速度快，需要科学上网 | 英语翻译     |
| **DeepLX**      | 质量好，需要自建服务 | 专业翻译     |

详细配置方法请查看 [翻译配置指南](/config/translator)。

## 开始处理视频

### 全流程处理（最简单）

这是最简单的方式，一键完成所有步骤：

1. 在主界面点击 **"任务创建"** 标签
2. 拖拽视频文件到窗口，或点击选择文件
   - 也可以输入 YouTube、B站等视频链接
3. 点击 **"开始全流程处理"** 按钮
4. 等待处理完成，输出文件保存在 `work-dir/` 目录

::: info 处理流程
全流程会依次执行：

1. 语音识别转录
2. 字幕智能断句（可选）
3. 字幕优化（可选）
4. 字幕翻译（可选）
5. 视频合成
   :::

### 分步处理

如果你需要更精细的控制，可以分步处理：

#### 步骤 1：语音识别转录

1. 切换到 **"语音转录"** 标签
2. 选择视频或音频文件
3. 配置转录参数：
   - 转录语言（自动检测或手动指定）
   - VAD 方法（建议保持默认）
   - 是否启用音频分离（嘈杂环境推荐）
4. 点击 **"开始转录"**
5. 转录完成后会生成字幕文件

#### 步骤 2：字幕优化与翻译

1. 切换到 **"字幕优化与翻译"** 标签
2. 加载字幕文件（自动加载或手动选择）
3. 配置处理选项：
   - **智能断句**：重新分段，阅读更流畅
   - **字幕校正**：修正错别字、优化格式
   - **字幕翻译**：翻译为目标语言
4. （可选）填写文稿提示，提升准确度
5. 点击 **"开始处理"**
6. 处理完成后可以实时预览和编辑

#### 步骤 3：字幕视频合成

1. 切换到 **"字幕视频合成"** 标签
2. 选择字幕样式（科普风、新闻风等）
3. 选择合成方式：
   - **硬字幕**：烧录到视频中
   - **软字幕**：内嵌字幕轨道（需要播放器支持）
4. 点击 **"开始合成"**
5. 输出视频保存在 `work-dir/` 目录

## 实用技巧

### 1. 提升字幕质量

- ✅ 使用 FasterWhisper Large-v2 模型
- ✅ 启用 VAD 过滤，减少幻觉
- ✅ 在嘈杂环境中启用音频分离
- ✅ 使用智能断句（语义分段）
- ✅ 填写文稿提示（术语表、原文稿等）

### 2. 加快处理速度

- ✅ 使用在线 ASR（B接口/J接口）跳过模型下载
- ✅ 提高 LLM 并发线程数（如果 API 支持）
- ✅ 使用软字幕合成（速度极快）
- ✅ 关闭不需要的功能（如翻译、优化）

### 3. 批量处理

如果需要处理多个视频：

1. 切换到 **"批量处理"** 标签
2. 选择处理类型（批量转录/字幕处理/视频合成）
3. 添加视频文件到队列
4. 点击 **"开始批量处理"**

详细说明请查看 [批量处理指南](/guide/batch-processing)。

## 常见问题

### 转录时出现幻觉或重复

::: details 解决方案

- 启用 VAD 过滤
- 更换更大的模型（如 Medium → Large）
- 尝试 Large-v2 而不是 Large-v3
- 在嘈杂环境中启用音频分离
  :::

### LLM 请求失败

::: details 解决方案

- 检查 API Key 是否正确
- 检查 Base URL 是否正确
- 降低线程数（某些服务商限制并发）
- 检查网络连接
- 查看日志文件获取详细错误信息
  :::

### 字幕时间轴不准确

::: details 解决方案

- 使用 FasterWhisper（时间轴最准确）
- 启用智能断句时使用语义分段模式
- 手动在字幕编辑界面调整
  :::

更多问题请查看 [常见问题解答](/guide/faq)。

## 下一步

- 📖 了解 [工作流程](/guide/workflow)
- ⚙️ 查看 [详细配置指南](/guide/configuration)
- 🎨 自定义 [字幕样式](/guide/subtitle-style)
- 📝 使用 [文稿匹配](/guide/manuscript) 提升准确度

---

如果在使用过程中遇到问题，欢迎提交 [Issue](https://github.com/WEIFENG2333/VideoCaptioner/issues) 或加入社区讨论。
