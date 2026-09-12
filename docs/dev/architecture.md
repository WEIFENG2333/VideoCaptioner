# 架构设计

VideoCaptioner 的系统架构设计。

## 技术栈

- **UI 框架**: PyQt5 + 项目自研第一方组件层（qfluentwidgets 仅作底层控件/图标来源，正在逐步退场）
- **ASR 引擎**: B 接口（必剪）/ J 接口（剪映）/ 百炼 Fun-ASR / Whisper API / whisper-cpp / faster-whisper
- **LLM 集成**: OpenAI 兼容接口（OpenAI / DeepSeek / SiliconFlow / Gemini / Ollama 等）
- **配音 TTS**: Edge / Gemini TTS / SiliconFlow CosyVoice（含音色克隆）
- **视频处理**: FFmpeg（软字幕 / ASS 硬字幕 / 圆角背景字幕渲染）
- **在线下载**: yt-dlp（YouTube / 哔哩哔哩等）

## 核心模块

业务逻辑全部在 `videocaptioner/core/`，不依赖 PyQt：

### 1. ASR 模块 (`videocaptioner/core/asr/`)

语音识别。各引擎实现 `BaseASR`，由 `transcribe.py` 按 `TranscribeConfig`
组装成 `ChunkedASR`（长音频分块 + 合并）。`check.py` 提供统一的真实
短音频连通性检查（设置页「测试转录」与 `doctor --check-api` 共用）。

### 2. 字幕处理模块 (`core/split/`, `core/optimize/`, `core/subtitle/`)

字幕智能断句与 LLM 优化；`core/subtitle/` 负责样式与 ASS/圆角渲染。

### 3. 翻译模块 (`videocaptioner/core/translate/`)

字幕翻译，支持 LLM / 必应 / 谷歌等服务。

### 4. 配音模块 (`core/dubbing/`, `core/speech/`, `core/tts/`)

按字幕生成配音音轨或配音视频，预设 / 音色 / 克隆引用统一管理。

### 5. 下载模块 (`videocaptioner/core/download/`)

- 本地 ASR 模型与运行程序下载（多镜像兜底、断点续传、SHA1 校验）
- 在线视频下载的网络环境（`net.py`：按站点分流代理、B 站 buvid 风控
  缓解、错误翻译）与下载源诊断（`source_check.py`）

### 6. 应用配置 (`core/application/`)

共享 TOML 配置存储（`config_store.py`）、业务配置数据类
（`app_config.py`）、任务构建（`task_builder.py`）。CLI 与 GUI 各自
通过 adapter 转换到同一份 `AppConfig`。

### 7. UI 模块 (`videocaptioner/ui/view/`)

桌面界面。页面只负责组合交互，通用按钮、卡片、表单、弹窗
（`AppDialog`）、导航、提示和图标放在 `videocaptioner/ui/components/`
与 `videocaptioner/ui/common/`；长任务包装在 `videocaptioner/ui/thread/`。

## 数据流

```
视频/音频/链接 → (下载) → ASR → ASRData → 断句 → LLM 优化 → 翻译
  → 字幕文件 → (配音) → 视频合成（软字幕 / 硬字幕 / 配音视频）
```

详细约定请参考仓库根目录 `AGENTS.md`（`CLAUDE.md` 是它的符号链接）。

---

相关文档：
- [API 文档](/dev/api)
- [贡献指南](/dev/contributing)
