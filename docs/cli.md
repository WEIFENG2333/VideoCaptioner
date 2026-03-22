# VideoCaptioner CLI 使用文档

## 安装

```bash
pip install videocaptioner
```

## 快速开始

```bash
# 语音转字幕（免费，无需配置）
videocaptioner transcribe video.mp4 --asr bijian

# 翻译字幕（免费必应翻译）
videocaptioner subtitle input.srt --translator bing --target-language en

# 全流程处理
videocaptioner process video.mp4 --target-language ja
```

## 配置

```bash
videocaptioner config show              # 查看当前配置
videocaptioner config set <key> <value> # 设置配置项
videocaptioner config get <key>         # 获取配置项
videocaptioner config path              # 显示配置文件路径
videocaptioner config init              # 交互式初始化
```

配置优先级：命令行参数 > 环境变量 (`VIDEOCAPTIONER_*`) > 配置文件 > 默认值。

环境变量：

| 变量 | 说明 |
|------|------|
| `VIDEOCAPTIONER_LLM_API_KEY` | LLM API 密钥 |
| `VIDEOCAPTIONER_LLM_API_BASE` | LLM API 地址 |
| `VIDEOCAPTIONER_LLM_MODEL` | LLM 模型名 |
| `VIDEOCAPTIONER_WHISPER_API_KEY` | Whisper API 密钥（独立于 LLM） |

---

## 命令参考

### `videocaptioner transcribe` — 语音转字幕

```bash
videocaptioner transcribe <音视频文件> [选项]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--asr` | ASR 引擎：`faster-whisper` `whisper-api` `bijian`(免费) `jianying`(免费) `whisper-cpp` | `faster-whisper` |
| `--language` | 源语言，ISO 639-1 代码，如 `zh` `en` `ja`，或 `auto` | `auto` |
| `-o` | 输出文件或目录路径 | 同目录下同名 .srt |
| `--format` | 输出格式：`srt` `ass` `txt` `json` | `srt` |
| `--word-timestamps` | 输出词级时间戳 | 关闭 |

FasterWhisper 专用选项：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--fw-model` | 模型：`tiny` `base` `small` `medium` `large-v1` `large-v2` `large-v3` `large-v3-turbo` | `large-v3` |
| `--fw-device` | 设备：`auto` `cuda` `cpu` | `auto` |
| `--fw-vad-method` | VAD 方法：`silero-v4-fw` `pyannote-v3` 等 | `silero-v4-fw` |
| `--fw-vad-threshold` | VAD 阈值 0.0~1.0 | `0.5` |
| `--fw-voice-extraction` | 启用人声提取 | 关闭 |

Whisper API 专用选项：

| 选项 | 说明 |
|------|------|
| `--whisper-api-key` | Whisper API 密钥（独立于 LLM） |
| `--whisper-api-base` | Whisper API 地址 |
| `--whisper-model` | Whisper 模型名（默认 `whisper-1`） |

**示例：**

```bash
# 用必剪免费引擎转录
videocaptioner transcribe lecture.mp4 --asr bijian

# 用 FasterWhisper 本地转录，指定模型和语言
videocaptioner transcribe podcast.mp3 --asr faster-whisper --fw-model large-v3 --language en

# 输出到指定目录
videocaptioner transcribe video.mp4 --asr bijian -o /output/dir/
```

---

### `videocaptioner subtitle` — 字幕优化与翻译

```bash
videocaptioner subtitle <字幕文件> [选项]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--translator` | 翻译服务：`llm` `bing`(免费) `google`(免费) | `llm` |
| `--target-language` | 目标语言，BCP 47 代码：`zh-Hans` `en` `ja` `ko` `fr` `de` 等 | `zh-Hans` |
| `--no-optimize` | 跳过 LLM 字幕优化 | 开启优化 |
| `--no-translate` | 跳过翻译 | 不翻译 |
| `--no-split` | 跳过字幕重新断句 | 开启断句 |
| `--reflect` | 启用反思式翻译（更慢但更准，仅 LLM） | 关闭 |
| `--layout` | 双语布局：`target-above` `source-above` `target-only` `source-only` | `target-above` |
| `--prompt` | 自定义提示词（辅助优化和翻译） | 无 |
| `--prompt-file` | 从文件读取提示词 | 无 |
| `--max-cjk` | CJK 单行最大字数 | `18` |
| `--max-english` | 英文单行最大词数 | `12` |
| `--thread-num` | 并发线程数 | `4` |
| `--batch-size` | 批处理大小 | `10` |

LLM 选项（仅 `--translator llm` 或优化时需要）：

| 选项 | 说明 |
|------|------|
| `--api-key` | LLM API 密钥 |
| `--api-base` | LLM API 地址 |
| `--model` | LLM 模型名 |

**示例：**

```bash
# 用必应免费翻译成英文（无需 API Key）
videocaptioner subtitle input.srt --translator bing --target-language en --no-optimize

# 用 LLM 优化 + 翻译成日语
videocaptioner subtitle input.srt --target-language ja --api-key sk-xxx

# 只优化不翻译，带自定义提示词
videocaptioner subtitle raw.srt --no-translate --prompt "这是一个机器学习课程"
```

---

### `videocaptioner synthesize` — 字幕烧录到视频

```bash
videocaptioner synthesize <视频文件> -s <字幕文件> [选项]
```

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `-s`, `--subtitle` | **必填**，字幕文件路径 | — |
| `--subtitle-mode` | `soft`（内嵌字幕轨）或 `hard`（烧录到画面） | `soft` |
| `--quality` | 视频质量：`ultra`(CRF18) `high`(CRF23) `medium`(CRF28) `low`(CRF32) | `medium` |
| `-o` | 输出视频路径 | 同目录 |

**示例：**

```bash
# 软字幕（速度快，可切换）
videocaptioner synthesize video.mp4 -s subtitle.srt

# 硬字幕 + 高质量
videocaptioner synthesize video.mp4 -s subtitle.ass --subtitle-mode hard --quality high
```

---

### `videocaptioner process` — 全流程处理

```bash
videocaptioner process <音视频文件> [选项]
```

等价于依次运行 `transcribe` → `subtitle` → `synthesize`，支持上述所有命令的选项，额外选项：

| 选项 | 说明 |
|------|------|
| `--no-optimize` | 跳过字幕优化 |
| `--no-translate` | 跳过翻译 |
| `--no-synthesize` | 跳过视频合成（只输出字幕） |

**示例：**

```bash
# 全流程：必剪转录 + 必应翻译成英文
videocaptioner process video.mp4 --asr bijian --translator bing --target-language en

# 只转录 + 翻译，不合成视频
videocaptioner process audio.mp3 --target-language ja --no-synthesize
```

---

### `videocaptioner download` — 下载在线视频

```bash
videocaptioner download <URL> [-o 目录]
```

支持 YouTube、B站等 yt-dlp 支持的所有平台。

**示例：**

```bash
videocaptioner download "https://youtube.com/watch?v=xxx"
videocaptioner download "https://www.bilibili.com/video/BVxxx" -o ./downloads/
```

---

## 通用选项

所有命令都支持：

| 选项 | 说明 |
|------|------|
| `-v`, `--verbose` | 详细输出（调试用） |
| `-q`, `--quiet` | 静默模式（只输出结果路径，适合管道使用） |
| `--config <文件>` | 指定配置文件路径 |

`-v` 和 `-q` 互斥，不能同时使用。

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数/配置错误 |
| 3 | 输入文件不存在 |
| 4 | 依赖缺失（FFmpeg、模型文件等） |
| 5 | 运行时错误（API 调用失败等） |

## 支持的目标语言代码

翻译目标语言使用 BCP 47 代码：

| 代码 | 语言 | 代码 | 语言 | 代码 | 语言 |
|------|------|------|------|------|------|
| `zh-Hans` | 简体中文 | `zh-Hant` | 繁体中文 | `en` | 英语 |
| `ja` | 日语 | `ko` | 韩语 | `fr` | 法语 |
| `de` | 德语 | `es` | 西班牙语 | `ru` | 俄语 |
| `pt` | 葡萄牙语 | `it` | 意大利语 | `ar` | 阿拉伯语 |
| `th` | 泰语 | `vi` | 越南语 | `id` | 印尼语 |

完整列表共 38 种语言，运行 `videocaptioner subtitle --help` 查看。
