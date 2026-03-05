# VideoCaptioner × Qwen ASR 契合度调研与部署报告

- 日期：2026-03-02
- 项目：VideoCaptioner（master）
- 结论先行：**高契合（推荐优先走“OpenAI 兼容接入”）**

## 1. 调研范围与依据

本报告基于以下两类事实来源：

1) 项目代码与配置（本地仓库）
- ASR 统一入口与模型分发：`app/core/asr/transcribe.py`
- OpenAI 兼容 ASR 适配器：`app/core/asr/whisper_api.py`
- 转录模型枚举与语言能力：`app/core/entities.py`
- 转录配置项：`app/common/config.py`
- Whisper API 设置界面：`app/components/WhisperAPISettingWidget.py`
- Whisper 连通性测试：`app/core/llm/check_whisper.py`

2) Qwen ASR 公开资料（2026-03-02 检索）
- Qwen3-ASR 模型页（HF）
- Qwen3-ASR Toolkit
- 阿里云 Model Studio（Fun-ASR 实时 WebSocket 文档）

## 2. 项目现状（与接入相关）

### 2.1 现有 ASR 架构特征

- `transcribe()` 通过 `TranscribeModelEnum` 分发到不同 ASR 实现。
- `WhisperAPI` 已支持 OpenAI SDK 的 `audio.transcriptions.create()` 调用。
- 结果统一转为 `ASRData/ASRDataSeg`，后续断句、优化、翻译、渲染复用同一数据结构。
- 长音频统一通过 `ChunkedASR` 切块并合并，天然适配 API 限制场景。

### 2.2 对“可替换 ASR”的关键接口要求

- 必须可返回 `verbose_json` 风格结果，至少包含：
  - `segments[*].text/start/end`
  - 可选 `words[*].word/start/end`（用于词级时间戳）
- 需要支持语言参数（空值时可自动检测）
- 建议支持提示词（术语上下文）

## 3. Qwen ASR 能力画像（对接视角）

### 3.1 能力亮点（与本项目强相关）

- 支持多语种与方言识别。
- 支持流式/离线统一推理。
- 支持长音频处理能力（官方 toolkit 也专门面向长音频并行切分）。
- 可通过 forced aligner 获取更细粒度时间戳（需额外部署）。

### 3.2 可部署形态（对接可选）

- 形态 A：本地/私有化 `qwen-asr`（transformers/vLLM）
- 形态 B：vLLM 服务化，并走 OpenAI 风格接口
- 形态 C：DashScope（含实时 WebSocket 方案）

## 4. 契合度评估

### 4.1 评分（10 分制）

- 接口兼容性：**9/10**（已有 OpenAI 兼容通道）
- 工程改造成本：**8/10**（最小可做到零代码）
- 字幕链路适配性：**8/10**（核心取决于时间戳字段一致性）
- 运维复杂度：**7/10**（本地 GPU 与模型管理有门槛）
- 综合：**8.0/10（高契合）**

### 4.2 关键判断

- **短期最优路径**：直接复用现有 `Whisper [API]` 通道，把 Qwen ASR 服务端当作 OpenAI 兼容 ASR 端点。
- **中期最优路径**：新增 `QWEN_ASR` 模型枚举与专属设置页，沉淀为一等公民能力。
- **实时字幕路径**：若要“边播边出字”，再引入 DashScope WebSocket 或 vLLM streaming 独立链路。

## 5. 完整部署思路（推荐方案）

> 目标：先“低风险可用”，再“稳定提效”，最后“实时化”。

### Phase 0：基线与验收口径（半天）

- 选 3 类测试集：
  - 普通中文讲解（10-20 分钟）
  - 中英夹杂技术内容（10-20 分钟）
  - 噪声/背景音乐明显样本（5-10 分钟）
- 固定验收指标：
  - WER/CER（可抽样）
  - 时间戳偏差（句级 P50/P95）
  - 端到端耗时（音频时长 vs 处理时长）
  - 失败率与重试率

### Phase 1：零代码接入（1 天，推荐先做）

#### 1) 部署 Qwen ASR 服务（vLLM/OpenAI 兼容）

- 以官方 `qwen-asr` / `vLLM` 路径拉起服务。
- 对外暴露 `http://<host>:<port>/v1`。
- 使用模型名如 `Qwen/Qwen3-ASR-1.7B`（或 0.6B）。

#### 2) 在 VideoCaptioner 中配置

- 转录模型选择：`Whisper [API] ✨`
- `Whisper API Base`：Qwen 服务地址（`.../v1`）
- `Whisper API Key`：按服务要求填写（本地可用占位）
- `Whisper 模型`：填写 Qwen 模型名
- 语言：先固定 `中文/英语` 做 A/B，再测试自动识别

#### 3) POC 验证重点

- 连通性：设置页“测试连接”通过
- 字段兼容性：确认 `verbose_json` 下 `segments/words` 可被当前解析器直接消费
- 长音频：确认 `ChunkedASR` 与服务端并行策略不会重复切分导致效率下降

### Phase 2：稳定性与性能优化（2-4 天）

- 模型分层策略：
  - 速度优先：0.6B
  - 质量优先：1.7B
- 资源策略：
  - GPU 显存水位（`gpu_memory_utilization`）
  - 并发与批次平衡（避免 OOM）
- 业务策略：
  - 噪声场景保持 VAD
  - 术语场景补充 prompt/context
- 可观测性：
  - 记录请求耗时、失败原因、切块数量、平均 chunk 时长

### Phase 3：产品化接入（3-5 天，可选）

新增 `QWEN_ASR` 原生模型选项，而不是借道 `Whisper API`：

- 新增枚举与配置分组：
  - `TranscribeModelEnum.QWEN_ASR`
  - `QwenASR` 专属配置（服务类型、本地/云端、模型、是否开启 aligner）
- 新增适配器：
  - `app/core/asr/qwen_asr.py`
  - 若接口仍为 OpenAI 兼容，可复用 `WhisperAPI` 基类逻辑
- 新增 UI：
  - 设置页模型切换时展示 Qwen 专属配置卡片
- 回归测试：
  - `transcribe.py` 分发逻辑
  - 词级时间戳路径
  - 失败重试与错误提示

### Phase 4：实时字幕（按需，1-2 周）

- 路线 A：DashScope WebSocket（官方实时）
- 路线 B：Qwen vLLM streaming
- 与现有离线链路并行共存：
  - “离线高质量”与“实时低延迟”双模式

## 6. 部署拓扑建议

### 6.1 单机版（MVP）

- VideoCaptioner（桌面端）
- Qwen ASR 服务（同机）
- 可选：独立 GPU

适合：个人或小团队，快速验证。

### 6.2 服务化版（团队）

- 前端桌面客户端（多端）
- 内网 Qwen ASR 网关（鉴权、限流、监控）
- 后端推理节点（vLLM + 模型仓）
- 对象存储（可选，缓存音频与结果）

适合：多人并发、成本可控、统一运维。

## 7. 风险与对策

1) **返回格式不完全兼容**
- 风险：`words/segments` 字段名或层级差异。
- 对策：在 `WhisperAPI._make_segments()` 增加“Qwen 返回格式兜底解析”。

2) **时间戳精度不达标**
- 风险：字幕切分后观感不佳。
- 对策：启用 forced aligner；或保留现有分句优化与时间轴后处理。

3) **GPU 资源波动/OOM**
- 风险：高峰期失败率上升。
- 对策：降低 batch、限制并发、按模型分级路由。

4) **长音频双重切分导致吞吐下降**
- 风险：客户端切块 + 服务端切块重复。
- 对策：只保留一层主切分策略（优先客户端 `ChunkedASR`）。

## 8. 验收标准（建议）

- 功能：
  - 可完成 60 分钟以内音频的稳定转录
  - 可输出可用 SRT，且时间轴连续无倒退
- 质量：
  - 中文样本 CER 相对现网不劣于 +5%
  - 中英混合术语误识率下降
- 性能：
  - 20 分钟音频端到端处理时间 < 8 分钟（参考 GPU 机型可调整）
- 稳定：
  - 20 次批量任务成功率 ≥ 95%

## 9. 落地执行清单（可直接排期）

- D1：POC 接入（零代码）+ 3 组样本回归
- D2：兼容性补丁（必要时）+ 指标采集
- D3-D4：性能调优 + 异常处理
- D5：是否进入 `QWEN_ASR` 原生化改造评审

## 10. 最终建议

- **建议立即执行 Phase 1（零代码接入）**，用最小成本验证质量和速度。
- 若 POC 通过，再进入 Phase 3 做“Qwen ASR 原生接入”，把它从“Whisper API 借道”升级为“产品内一等模型”。
- 实时字幕不是本轮必需项，建议在离线链路稳定后再立项。
