# ASR 配置指南

语音识别（ASR）配置详解。

## 支持的 ASR 引擎

| 引擎 | 特点 | 推荐场景 |
|------|------|---------|
| **FasterWhisper** | 准确度高，支持GPU | 推荐使用 |
| **WhisperCpp** | 轻量级 | CPU环境 |
| **Whisper API** | 云端服务 | 无需本地模型 |
| **Qwen-ASR** | 开源本地/服务化，支持词级时间戳 | 中文、多语、可调 max token |
| **B接口/J接口** | 免费在线 | 快速测试 |

## Qwen-ASR 使用说明

1. 在「转录模型」选择 `Qwen-ASR ✨`。
2. 在设置卡中选择后端：
- `transformers`：本地推理（默认）
- `vllm`：服务化推理
3. 选择或手动填写 `ASR 模型`（默认 `Qwen/Qwen3-ASR-0.6B`）。
4. 如需词级时间戳，开启 `词级时间戳` 并设置 `对齐器模型`（默认 `Qwen/Qwen3-ForcedAligner-0.6B`）。
5. 通过 `Max New Tokens` 调整生成上限。

> 依赖安装：`pip install qwen-asr`

## 配置参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| 推理后端 | `transformers` / `vllm` | `transformers` |
| ASR 模型 | 主识别模型 | `Qwen/Qwen3-ASR-0.6B` |
| 对齐器模型 | 词级时间戳模型 | `Qwen/Qwen3-ForcedAligner-0.6B` |
| 词级时间戳 | 是否输出词/字级时间戳 | 开启 |
| Max New Tokens | 生成 token 上限 | `1024` |

---

相关文档：
- [快速开始](/guide/getting-started)
- [LLM 配置](/config/llm)
