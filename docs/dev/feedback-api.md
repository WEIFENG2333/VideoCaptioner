# 反馈提交：客户端实现说明

> 「意见反馈」弹窗（`ui/components/feedback_dialog.py`）收集用户的描述 + 可选截图，附带
> 已脱敏的诊断信息和最近日志，POST 到反馈后端。
>
> **后端契约的唯一真相源是 `vc-backend` 仓库的 `api.md`**（端点、表单字段、落表字段、Telegram
> 通知、错误码语义都以那份为准）。本文件只记录**桌面客户端这一侧**的实现决定，方便在本仓库里
> 改反馈功能时对齐——不复述后端内部职责。

数据流：`桌面客户端 → 反馈后端 → 飞书多维表格（+ 维护者 Telegram 通知）`。

## 端点（写死，不可配）

端点写死在 [`videocaptioner/config.py`](../../videocaptioner/config.py) 的 `FEEDBACK_API_URL`：

```
POST https://vc-feedback-backend.weifeng.workers.dev/api/feedback
```

**不走环境变量、不走配置文件**。要换端点就改这个常量。客户端代码集中在
`videocaptioner/core/feedback/`（无 PyQt）+ `ui/components/feedback_dialog.py`（弹窗）+
`ui/thread/feedback_thread.py`（QThread 薄壳）。

## 请求：始终 multipart

后端只收 `multipart/form-data`，urlencoded 会被拒（`invalid_request`）。`requests` 在没有任何
文件时会把 `data=` 退化成 urlencoded，所以客户端把**每个文本字段也作为 multipart part**
（`(key, (None, value))`）发送，保证无截图/无日志时请求仍是 multipart。见
[`client.py`](../../videocaptioner/core/feedback/client.py) `FeedbackClient.submit`。

请求头：`X-App-Version` / `X-App-Platform` / `User-Agent`。不带 `Authorization`（后端本期
未启用鉴权）。`X-App-Platform` 只发契约枚举 `windows-x64` / `macos-x64` / `macos-arm64`
（`platform_tag()` 把 dev/linux、windows-arm64 收敛进来）。

### 表单字段（客户端实际发送）

| 字段 | 必填 | 说明 |
|---|---|---|
| `category` | 是 | `bug` / `feature` / `question` / `other` |
| `message` | 是 | 用户描述，1–5000 字符 |
| `contact` | 否 | 联系方式，≤200 字节（按字节算）；为空则不发 |
| `client_id` | 是 | 匿名设备 UUID，持久化到 `APPDATA/feedback_client_id`（不入配置文件） |
| `request_id` | 是 | 每次提交新生成的 UUID，仅供排查；**后端本期不做幂等**，重试会新建一条记录 |
| `diagnostics` | 否 | 环境诊断 JSON 字符串（见下），为空则不发 |
| `files` | 否 | 截图，0–3 个，重复字段；仅 `image/png` / `image/jpeg` |
| `logs` | 否 | 最近日志附件，独立于 `files` 与 `diagnostics`；默认开启（见下） |

### 响应

成功 HTTP 200 `{"ok": true, "id": "VC-0001"}`（`id` 是飞书自增编号，不回显给用户，本期也无
状态查询接口、无 `ticket_url`）。失败 `{"ok": false, "code", "error"}`。`_parse_response`
认错误码 `invalid_request` / `unauthorized` / `too_large` / `server_error`，并对非 JSON 体按
HTTP 状态兜底（400/401/413→对应码，其余→`server_error`）。**没有 429/限流码。**

## 诊断信息（默认附带，已脱敏）

[`diagnostics.py`](../../videocaptioner/core/feedback/diagnostics.py) `gather_diagnostics()`
**只读一个非敏感白名单**（provider/语言/模型名称），再过 `_is_safe` 兜底（值里含
`key`/`token`/`sk-`/`://` 等或超 64 字符即丢弃）。实际键：

```json
{
  "app_version": "...", "platform": "macos-arm64", "os": "...", "python": "...",
  "frozen": true, "ffmpeg": "ok", "language": "zh_Hans",
  "llm_service": "deepseek", "llm_model": "deepseek-chat",
  "translate_service": "bing", "translate_target": "简体中文",
  "dubbing_provider": "edge"
}
```

`gather_diagnostics` 是这些键的真相源；缺失字段后端容错。**绝不含 api_key / base_url。**

## 最近日志（默认附带、静默、已脱敏）

[`logs.py`](../../videocaptioner/core/feedback/logs.py) `collect_recent_logs()` 取 `app.log`
尾部（≤256KB），脱敏后作为**一个 `recent.log`（`text/plain`）** 走独立的 `logs` 表单字段
上传。提交时默认附带、**无 UI 开关、不在界面提示**。

发送前 `scrub_log_text` 按硬规则「logs 不得含 API key / base URL / access token」打码：
Bearer/Basic 凭据、`sk-` 与 Google `AIza` 密钥、`key=value` 与 query `?key=` 凭据、URL 内嵌
账密、`API Base:` / `base_url` / `endpoint` 后的地址。公共站点 URL（下载源/镜像等）保留以便
排查。改动可审计输出的字段时要同步扩展脱敏规则与 `tests/test_feedback/test_logs.py`。

## 本地预校验（后端上限的真超集）

[`models.py`](../../videocaptioner/core/feedback/models.py) `FeedbackReport.validate()`：类型
枚举、`message` 1–5000 字符、`contact` ≤200 字节、截图/日志各 ≤3 个且单个 ≤5MB、仅 PNG/JPEG
截图。整请求 ≤12MB 的 `total` **计入文本字段 + multipart 框架余量**，使本地校验严格覆盖后端的
整体请求大小检查（否则正好 12MB 二进制会被后端 413）。后端仍会二次校验，本地只为提前给出友好
提示。

## 后端行为（以 vc-backend/api.md 为准）

落表字段映射、飞书列名、Telegram 通知（展示截图+内容+环境摘要，**不含 logs**）、安全与防滥用、
未来扩展，都在 `vc-backend` 的 `api.md`。本仓库不复制，避免两边漂移。
