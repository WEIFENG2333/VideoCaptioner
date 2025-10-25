# LLM API 配置指南

本指南将帮助你配置大语言模型（LLM）API，用于字幕的智能断句、优化和翻译。

## 为什么需要配置 LLM？

VideoCaptioner 使用 LLM 提供以下核心功能：

- **智能断句** - 根据语义自动分割字幕，而不是简单按时长切割
- **字幕优化** - 纠正语音识别的错误，统一专业术语
- **高质量翻译** - 提供符合语境的翻译，而不是机器直译

:::tip 费用说明
处理一个 14 分钟的视频，使用 `gpt-4o-mini` 模型，总费用约为 **¥0.01**（不到一分钱）
:::

## 配置方式

目前有两种主流配置方式：

1. [国内 API 服务商](#国内-api-服务商)（推荐新手）
2. [OpenAI 官方或中转站](#openai-官方或中转站)

---

## 国内 API 服务商

### 使用 SiliconCloud

[SiliconCloud](https://cloud.siliconflow.cn/i/onCHcaDx) 集成了国内多家大模型厂商，注册即送测试额度。

#### 1. 注册并获取 API Key

访问 [SiliconCloud 设置页面](https://cloud.siliconflow.cn/account/ak) 获取 API Key

![获取 API Key](https://h1.appinn.me/file/1731487405884_get_api.png)

#### 2. 在软件中配置

打开 VideoCaptioner，进入 **设置 → LLM 服务配置**

填写以下信息：

| 配置项           | 值                               |
| ---------------- | -------------------------------- |
| **API 接口地址** | `https://api.siliconflow.cn/v1`  |
| **API Key**      | 粘贴你从 SiliconCloud 获取的密钥 |
| **模型**         | 推荐 `deepseek-ai/DeepSeek-V3`   |

![SiliconCloud 配置示例](https://h1.appinn.me/file/1731487405884_api-setting.png)

#### 3. 验证连接

点击 **检查连接** 按钮，如果配置正确：

- 软件会自动填充所有支持的模型名称
- 你可以从下拉菜单中选择需要的模型

:::warning 并发限制
SiliconCloud 对并发请求有限制，建议将 **线程数** 设置为 **5 或以下**
:::

:::info 实名要求
自 2025 年 2 月 6 日起，DeepSeek-V3 模型要求实名认证才能获得更多调用次数。未实名用户每日最多请求 100 次。
:::

---

## OpenAI 官方或中转站

### 使用项目推荐的中转站

如果你需要使用 OpenAI、Claude 或 Gemini 模型，可以使用中转服务。

#### 1. 注册账号

访问 [本项目的中转站](https://api.videocaptioner.cn/register?aff=UrLB)，通过此链接注册默认赠送 **$0.4** 测试余额。

#### 2. 获取 API Key

登录后访问 [https://api.videocaptioner.cn/token](https://api.videocaptioner.cn/token) 获取你的 API Key

#### 3. 在软件中配置

打开 VideoCaptioner，进入 **设置 → LLM 服务配置**

填写以下信息：

| 配置项           | 值                                 |
| ---------------- | ---------------------------------- |
| **API 接口地址** | `https://api.videocaptioner.cn/v1` |
| **API Key**      | 粘贴你获取的密钥                   |
| **模型**         | 见下方推荐                         |

![中转站配置示例](https://h1.appinn.me/file/1731487405884_api-setting-2.png)

#### 4. 模型选择建议

根据质量和成本需求选择：

| 质量层级        | 推荐模型                              | 成本比例 | 适用场景               |
| --------------- | ------------------------------------- | -------- | ---------------------- |
| 🏆 **高质量**   | `claude-3-5-sonnet-20241022`          | 3        | 专业内容、重要视频     |
| ⭐ **较高质量** | `gemini-2.0-flash`<br>`deepseek-chat` | 1        | 日常使用、质量要求较高 |
| 💰 **性价比**   | `gpt-4o-mini`<br>`gemini-1.5-flash`   | 0.15     | 大量视频、成本敏感     |

:::tip 性能优势
本中转站支持超高并发，软件中 **线程数可以拉满**，处理速度非常快！
:::

:::info 成本建议
如果条件有限，直接使用 `gpt-4o-mini` 即可。这个模型便宜且速度快，处理一个视频只需几分钱，**建议不要折腾本地部署了**。
:::

---

## 使用 OpenAI 官方 API

如果你有 OpenAI 官方账号，可以直接使用官方 API。

#### 1. 获取 API Key

访问 [OpenAI API Keys](https://platform.openai.com/api-keys) 创建 API Key

#### 2. 在软件中配置

| 配置项           | 值                          |
| ---------------- | --------------------------- |
| **API 接口地址** | `https://api.openai.com/v1` |
| **API Key**      | 粘贴你的 OpenAI API Key     |
| **模型**         | `gpt-4o-mini` 或 `gpt-4o`   |

---

## 常见问题

### 如何选择线程数？

**线程数**决定了并发处理字幕的速度：

- **SiliconCloud**: 建议 5 或以下（有并发限制）
- **中转站**: 可以拉满（支持高并发）
- **OpenAI 官方**: 建议 10-20（取决于账号等级）

### 如何降低成本？

1. 选择更便宜的模型（如 `gpt-4o-mini`）
2. 禁用字幕优化功能（只保留翻译）
3. 使用本地 Whisper 模型进行转录，只用 LLM 做翻译

### API Key 安全吗？

- 所有 API Key 都保存在本地 `AppData/settings.json` 文件中
- 不会上传到任何服务器
- 建议定期轮换 API Key

### 连接失败怎么办？

检查以下几点：

1. API 接口地址是否正确（注意末尾的 `/v1`）
2. API Key 是否正确复制（没有多余空格）
3. 网络是否能访问 API 服务器
4. 账号余额是否充足

---

## 下一步

配置完成后，你可以：

- 查看 [快速开始指南](./getting-started.md) 处理你的第一个视频
- 了解 [字幕优化功能](./subtitle-optimization.md)
- 探索 [批量处理功能](./batch-processing.md)
