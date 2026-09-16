# ASR 配置指南

语音识别（ASR）配置详解。

## 支持的 ASR 引擎

| 引擎 | 特点 | 推荐场景 |
|------|------|---------|
| **FasterWhisper** | 准确度高，支持GPU | 推荐使用 |
| **WhisperCpp** | 轻量级 | CPU环境 |
| **Whisper API** | 云端服务 | 无需本地模型 |
| **MiniMax ASR** | 官方云端 `asr-1.0` | 无需本地模型，支持多语言 |
| **B接口/J接口** | 免费在线 | 快速测试 |

## MiniMax ASR

```bash
videocaptioner config set minimax_api.api_key <your-key>
videocaptioner transcribe input.mp4 --asr minimax --language zh -o output.srt
```

默认 API Base 为 `https://api.minimaxi.com/v1`，模型为 `asr-1.0`。VideoCaptioner 请求官方 SRT 输出，并支持句级或词级时间戳。根据 MiniMax 官方限制，单次音频不超过 500 秒和 50 MB，因此长音频会自动按 480 秒、单并发分块后合并。`--language auto` 会省略语言提示，让 MiniMax 自动识别。

## 模型下载

待补充...

## 配置参数

待补充...

---

相关文档：
- [快速开始](/guide/getting-started)
- [LLM 配置](/config/llm)
