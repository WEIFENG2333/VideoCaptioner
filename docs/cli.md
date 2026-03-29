# VideoCaptioner CLI

## 安装

```bash
pip install videocaptioner          # CLI（轻量，无 GUI 依赖）
pip install videocaptioner[gui]     # CLI + GUI 桌面版
```

免费功能（转录、必应/谷歌翻译）无需任何配置，安装后直接使用。

---

## 快速开始

```bash
# 语音转字幕（免费）
videocaptioner transcribe video.mp4 --asr bijian

# 翻译字幕（免费必应翻译）
videocaptioner subtitle input.srt --translator bing --target-language en

# 全流程：转录 → 优化 → 翻译 → 合成
videocaptioner process video.mp4 --asr bijian --translator bing --target-language ja

# 给视频加字幕
videocaptioner synthesize video.mp4 -s subtitle.srt --subtitle-mode hard
```

---

## 命令

### `transcribe` — 语音转字幕

将音视频文件转为字幕文件。支持 mp3/wav/mp4/mkv 等格式，视频自动提取音频。

```bash
videocaptioner transcribe <文件> [选项]
```

| 选项 | 说明 |
|------|------|
| `--asr` | ASR 引擎：`bijian`(默认,免费) `jianying`(免费) `whisper-api` `whisper-cpp`。bijian/jianying 仅支持中英文，其他语言用 whisper-api 或 whisper-cpp |
| `--language CODE` | 源语言 ISO 639-1 代码，如 `zh` `en` `ja`，或 `auto`（默认） |
| `--word-timestamps` | 输出词级时间戳（配合字幕断句使用） |
| `--whisper-api-key` | Whisper API 密钥（仅 `--asr whisper-api`） |
| `--whisper-api-base` | Whisper API 地址 |
| `--whisper-model` | Whisper 模型名（whisper-api 默认 whisper-1，whisper-cpp 默认 large-v2） |
| `-o PATH` | 输出文件或目录路径 |
| `--format` | 输出格式：`srt`(默认) `ass` `txt` `json` |

---

### `subtitle` — 字幕优化与翻译

处理字幕文件，支持三个步骤：

1. **断句** — 按语义重新分割字幕（LLM）
2. **优化** — 修正 ASR 错误、标点、格式（LLM）
3. **翻译** — 翻译到其他语言（LLM / 必应 / 谷歌）

默认开启优化和断句，翻译默认关闭。指定 `--translator` 或 `--target-language` 自动开启翻译。

```bash
videocaptioner subtitle <字幕文件> [选项]
```

| 选项 | 说明 |
|------|------|
| `--translator` | 翻译服务：`llm`(默认) `bing`(免费) `google`(免费) |
| `--target-language CODE` | 目标语言 BCP 47 代码：`zh-Hans` `en` `ja` `ko` `fr` `de` 等 |
| `--no-optimize` | 跳过优化 |
| `--no-translate` | 跳过翻译 |
| `--no-split` | 跳过断句 |
| `--reflect` | 反思式翻译（仅 LLM，质量更高但更慢） |
| `--layout` | 双语布局：`target-above` `source-above` `target-only` `source-only` |
| `--prompt TEXT` | 自定义提示词（辅助 LLM 优化/翻译） |
| `--api-key` | LLM API 密钥（或设置 `OPENAI_API_KEY` 环境变量） |
| `--api-base` | LLM API 地址（或设置 `OPENAI_BASE_URL` 环境变量） |
| `--model` | LLM 模型名（如 gpt-4o-mini） |

---

### `synthesize` — 字幕合成到视频

将字幕烧录到视频中，支持美观的样式化字幕。

```bash
videocaptioner synthesize <视频> -s <字幕> [选项]
```

| 选项 | 说明 |
|------|------|
| `-s FILE` | **必填**，字幕文件 |
| `--subtitle-mode` | `soft`(默认,嵌入轨道) 或 `hard`(烧录画面) |
| `--quality` | 视频质量：`ultra`(CRF18) `high`(CRF23) `medium`(默认,CRF28) `low`(CRF32) |
| `--layout` | 双语字幕布局 |
| `--style NAME` | 样式预设（运行 `videocaptioner style` 查看） |
| `--style-override JSON` | 内联 JSON 覆盖样式字段，如 `'{"outline_color": "#ff0000"}'` |
| `--render-mode` | 渲染模式：`ass`(默认,描边样式) 或 `rounded`(圆角背景) |
| `--font-file PATH` | 自定义字体文件 (.ttf/.otf) |

#### 字幕样式

VideoCaptioner 支持两种渲染模式，让字幕更美观：

**ASS 模式**（默认）— 传统描边/阴影样式，支持自定义字体、颜色、描边宽度：
```bash
# 使用动漫风格预设
videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard --style anime

# 自定义红色描边
videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard \
  --style-override '{"outline_color": "#ff0000", "font_size": 48}'
```

**圆角背景模式** — 现代圆角矩形背景，支持自定义背景色、圆角半径、内边距：
```bash
# 使用圆角背景
videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard --render-mode rounded

# 自定义白字红底
videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard \
  --style-override '{"text_color": "#ffffff", "bg_color": "#ff000099", "corner_radius": 12}'
```

运行 `videocaptioner style` 查看所有预设及其参数。样式选项仅对硬字幕（`--subtitle-mode hard`）生效。

---

### `process` — 全流程处理

一键完成：转录 → 断句 → 优化 → 翻译 → 合成。支持上述所有命令的参数。

```bash
videocaptioner process <音视频文件> [选项]
```

额外选项：

| 选项 | 说明 |
|------|------|
| `--no-synthesize` | 跳过视频合成（只输出字幕） |

音频文件自动跳过合成步骤。

---

### `download` — 下载在线视频

```bash
videocaptioner download <URL> [-o 目录]
```

支持 YouTube、B站等 yt-dlp 支持的平台。

---

### `style` — 查看字幕样式

```bash
videocaptioner style
```

列出所有可用样式预设及其配置参数，包括 ASS 和圆角背景两种模式。

---

### `config` — 配置管理

```bash
videocaptioner config show              # 查看配置
videocaptioner config set <key> <value> # 设置配置项
videocaptioner config get <key>         # 获取配置项
videocaptioner config path              # 配置文件路径
videocaptioner config init              # 交互式初始化
```

---

## 配置

配置优先级：命令行参数 > 环境变量 > 配置文件 > 默认值。

### 环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | LLM API 地址 |
| `OPENAI_MODEL` | LLM 模型名 |

### 配置文件

位置：`~/.config/videocaptioner/config.toml`（macOS/Linux）

```toml
[llm]
api_key = "sk-xxx"
api_base = "https://api.openai.com/v1"
model = "gpt-4o-mini"

[transcribe]
asr = "bijian"
language = "auto"

[subtitle]
optimize = true
translate = false

[translate]
service = "llm"
target_language = "zh-Hans"
```

运行 `videocaptioner config show` 查看完整配置项。

---

## 通用选项

| 选项 | 说明 |
|------|------|
| `-v` / `--verbose` | 详细输出 |
| `-q` / `--quiet` | 静默模式，仅输出结果路径（适合管道使用） |
| `--config FILE` | 指定配置文件 |

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数/配置错误 |
| 3 | 输入文件不存在 |
| 4 | 依赖缺失（FFmpeg 等） |
| 5 | 运行时错误（API 失败等） |
