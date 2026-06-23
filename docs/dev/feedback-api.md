# VideoCaptioner 反馈接口规范（后端实现文档）

> 给后端实现者的自包含契约。VideoCaptioner 桌面客户端（Windows / macOS）在「意见反馈」页
> 收集用户的问题描述 + 截图，POST 到本接口。**本接口只负责接收并落库到多维表格**（飞书 Base
> 等）。**当前阶段不要自动创建 GitHub issue**（避免 issue 泛滥）——issue 留作以后的可选开关，
> 见 [§8](#八未来扩展可选不在本期)。
>
> 数据流：`桌面客户端 → 本接口 → 多维表格（+ 图片对象存储）`。
>
> 客户端与本接口共享本文件为唯一契约；改字段要两边同步。

---

## 一、端点与方法

```
POST  https://<your-domain>/api/feedback
Content-Type: multipart/form-data
```

- 只有这一个写接口。无需 GET / 状态回查（本期）。
- 桌面客户端发起，**无浏览器、无需 CORS**。
- 端点 URL 由客户端配置（环境变量 / 配置文件），你只需给我最终 URL。

---

## 二、请求头（Headers）

| Header | 必填 | 示例 | 说明 |
|---|---|---|---|
| `Content-Type` | 是 | `multipart/form-data; boundary=…` | 标准 multipart |
| `X-App-Version` | 是 | `2.1.0` | 客户端版本，便于按版本筛选/防滥用 |
| `X-App-Platform` | 是 | `windows-x64` | 枚举见下 |
| `User-Agent` | 是 | `VideoCaptioner/2.1.0 (windows-x64)` | 可用于基础校验 |
| `Authorization` | 否 | `Bearer <app_token>` | 可选，见 [§7 安全](#七安全与防滥用) |

`X-App-Platform` 取值枚举：`windows-x64` | `macos-x64` | `macos-arm64`。

---

## 三、请求体（multipart/form-data 字段）

| 字段名 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `category` | string | 是 | 枚举 | `bug`＝问题报告 / `feature`＝功能建议 / `question`＝使用问题 / `other`＝其他 |
| `message` | string | 是 | 1–5000 字符 | 用户问题描述（纯文本，可含换行） |
| `contact` | string | 否 | ≤200 字符 | 用户留的联系方式（邮箱/微信/QQ，自由文本，可能为空） |
| `client_id` | string | 是 | UUID | 匿名设备 ID，客户端本地随机生成并持久化。**非个人信息**，用于去重/同一用户多次反馈归并/限流 |
| `request_id` | string | 是 | UUID | **每次提交**生成一个；客户端失败重试会带同一个 `request_id` → 后端据此**幂等去重**，避免重复落库 |
| `diagnostics` | string | 否 | JSON 字符串 | 客户端环境诊断，需 `JSON.parse`。Schema 见 [§3.1](#31-diagnostics-json-schema)。密钥已在客户端剥离 |
| `files` | file（可重复）| 否 | 见下 | 截图。多张时**重复 `files` 字段**（若你的框架要求 `files[]` 请告知，客户端会对齐） |

**`files` 约束**（客户端已先行校验，后端必须再次校验，勿信任客户端）：
- 数量：0–3 张。
- 单张：≤ 5 MB。
- 总大小：≤ 12 MB（含表单其它字段）。
- 类型：仅 `image/png`、`image/jpeg`。**按文件内容嗅探**真实类型，勿只看扩展名/`Content-Type`。

### 3.1 `diagnostics` JSON Schema

客户端采集的运行环境（**保证不含 API key / base_url / 任何密钥**）。字段可能缺失，后端容错处理：

```json
{
  "app_version": "2.1.0",
  "platform": "windows-x64",
  "os": "Windows 11 (10.0.22631)",
  "python": "3.12.7",
  "frozen": true,
  "asr_provider": "fun-asr",
  "llm_provider": "deepseek",
  "translate_provider": "bing",
  "tts_provider": "edge",
  "ffmpeg": "ok",
  "language": "zh_Hans",
  "logs": "可选，最近若干行日志（已脱敏），可能不存在或很长"
}
```

- 全部字段均为可选（除非客户端有 bug）；后端按存在与否落库。
- `*_provider` 只是**名称**，无凭据。
- `logs` 仅在用户勾选「附带日志」时出现，可能较长——**硬截断**到 ≤ 32 KB 落库或转存附件，勿整段塞进窄字段。
- **整个 `diagnostics` 原始串先限长再解析**：≤ 64 KB，超出直接按 `invalid_request` 拒；解析时限制 JSON 深度（≤ 8 层）与键数量（≤ 100），防解析放大 DoS。
- **解析失败要容错、不要丢反馈**：`diagnostics` 缺失 → 跳过；存在但**不是合法 JSON** → **不要返回 400**，把原始串存进「诊断(原始)」列、解析列留空、继续正常落库（不能因为诊断坏了就吞掉用户反馈）。

---

## 四、响应

统一 JSON。**成功 HTTP 200**，失败用对应 4xx/5xx。

**成功：**
```json
{
  "ok": true,
  "id": "FB-20260623-0001",
  "ticket_url": null
}
```
- `id`：后端生成的反馈编号（人类可读，回显给用户）。规则自定，建议 `FB-{日期}-{序号}` 或直接用多维表格记录 ID。
- `ticket_url`：可选，留作以后接 issue/工单时回填记录链接；**本期固定返回 `null` 或省略**。

**失败：**
```json
{
  "ok": false,
  "code": "too_large",
  "error": "图片超过大小限制（单张 ≤5MB）"
}
```
- `error`：**人类可读中文**，客户端会直接展示给用户，请写清楚原因。
- `code`：机器可读，枚举如下。

| HTTP | `code` | 含义 |
|---|---|---|
| 400 | `invalid_request` | 缺必填字段 / `category` 非法 / `message` 为空或超长 / 图片类型不对 |
| 413 | `too_large` | 单张或总大小超限 |
| 401 | `unauthorized` | 开了鉴权但 token 不对（若启用鉴权） |
| 429 | `rate_limited` | 触发限流，建议响应头带 `Retry-After` 秒数 |
| 500 | `server_error` | 落库/存储等内部错误 |

**校验顺序（多个错误同时命中时返回哪个）**：按 ① 鉴权（若启用）→ ② 请求总大小 → ③ 单图大小 → ④ 必填/枚举/长度 → ⑤ 图片真实类型 的顺序，**命中即返回第一个**，避免歧义。即：体积类问题（②③）优先报 `413 too_large`，再报 `400 invalid_request`。总大小超 12 MB 一律 `413 too_large`，无论是图片还是文本字段撑大的。

客户端行为：成功→显示「已收到，编号 {id}」；失败→显示 `error` 文案 + 「重试」按钮（重试带同一 `request_id`）。

---

## 五、后端处理职责

1. **校验**：必填字段、枚举、长度、图片数量/大小/真实类型（顺序见 [§4 校验顺序](#四响应)）。不通过 → 400/413。
2. **幂等**（见 5.1）。
3. **存图片**：把 `files` 上传到你的对象存储（飞书附件 / OSS / S3 等），得到可访问 URL 或附件 token（**存储键规则见 [§7](#七安全与防滥用)，勿用客户端文件名**）。
4. **落多维表格**：写一行，字段映射见 [§6](#六多维表格字段映射建议)。
5. **返回** `{ ok, id, ticket_url }`。
6. **不创建 GitHub issue**（本期）。

### 5.1 幂等（务必照此实现）

- **去重键**：`request_id`（客户端每次提交一个 UUID，失败重试沿用同一个）。
- **窗口**：以**首次收到**为起点，**24 小时**内的同 `request_id` 视为重复。
- **重复时返回什么**：必须返回**与首次完全相同**的 `{ ok:true, id, ticket_url }`（HTTP 200）。
  因此 dedup 存储**不能只存一个布尔标志（SETNX 不够）**，要持久化 `request_id → {id, ticket_url}`
  （或给多维表格行的 `request_id` 建唯一索引、重复时回查那一行）。
- **并发重复**（两个同 `request_id` 几乎同时到）：靠唯一约束/唯一索引，**只允许一行落库**，
  另一个回查并返回首条结果，**绝不写第二行**。
- **超窗重试**（>24h 后才重发同 `request_id`）：当作新提交处理（会新建一行）——这是可接受的极端情况。
  若想彻底杜绝，用"表里 `request_id` 唯一索引"方案即等价于永久去重。

---

## 六、多维表格字段映射建议

| 表格列 | 来源 | 备注 |
|---|---|---|
| 编号 | 后端生成 `id` | 主键/可读编号 |
| 提交时间 | 服务端接收时间 | 别信客户端时间 |
| 类型 | `category` | bug/feature/question/other（可做成单选） |
| 问题描述 | `message` | 多行文本列 |
| 联系方式 | `contact` | 可空 |
| 截图 | 上传后的图片 URL/附件 | 多张 |
| 版本 | `diagnostics.app_version` 或 `X-App-Version` | |
| 平台 | `X-App-Platform` | |
| 系统 | `diagnostics.os` | |
| Provider | `diagnostics.{asr,llm,translate,tts}_provider` | 便于定位是不是某家服务的问题 |
| 诊断(原始) | 整个 `diagnostics` JSON | 存一列备查（可折叠/长文本） |
| 设备ID | `client_id` | 归并同一用户 |
| 状态 | 默认「待处理」| 你们人工流转 |

---

## 七、安全与防滥用

- **必须服务端二次校验**所有大小/类型/长度限制，不信任客户端。
- **存储键绝不用客户端文件名**：multipart 的 `filename` 是不可信输入，可能含 `../`、绝对路径、奇异字符 →
  路径穿越 / 覆盖 / URL 注入。**服务端自己生成随机键**，如 `{request_id}/{uuid}.{ext}`（ext 取自嗅探出的
  真实 MIME，不取客户端扩展名），并去除任何路径分隔符；最终 URL 必须落在你自己的存储域名下。
- **图片安全**：按**内容嗅探**真实 MIME（不看扩展名/`Content-Type`），拒绝非 png/jpeg。
  **防解压炸弹（硬要求，非建议）**：在**完全解码前**先读图像头判尺寸，拒绝超大像素图（如 > 8000×8000 或 > 50 MP），
  给解码器设内存上限，并**强制重新编码**为安全格式后再存（剥离 EXIF/恶意分块）。
- **`diagnostics` 防滥用**：它是完全由客户端控制的串——先限长（≤ 64 KB）再解析，限 JSON 深度/键数，
  malformed 则容错不崩（见 [§3.1](#31-diagnostics-json-schema)）。
- **多维表格写入防公式注入**：`message`、`contact` 是自由文本，若值以 `=`、`+`、`-`、`@` 开头，导出 Excel/CSV 时会被当公式执行。
  写入 Base 前**中和**这些前导字符（加安全前缀或强制纯文本存储）。`contact` 另按**字节**限长（≤200 字节，防多字节绕过）。
- **限流**：按 `client_id` + 源 IP 双维度，例如**单 client_id ≤ 5 条/小时、单 IP ≤ 20 条/小时**，超限 429 + `Retry-After`。这是防泛滥的主要手段。
- **鉴权（可选）**：客户端可带 `Authorization: Bearer <app_token>`。
  - **默认关闭**（你不给 token 就当不启用，请求照常处理）——这样后端不必等 token 就能先上线。
  - **启用后**：缺少 Authorization 头**或** token 不对，**都**返回 `401 unauthorized`；关闭时则忽略该头、放行。
  - 注意**桌面客户端里写死的 token 不算真正保密**（能被逆向提取），只能挡"完全不带 token 的脚本"，真正防刷靠限流。
- **无 PII 强约束**：`contact` 是用户自愿填的；`client_id` 是随机 UUID 非身份信息。请勿额外采集用户身份。
- 不需要 CORS（桌面客户端非浏览器）。

---

## 八、未来扩展（可选，不在本期）

- **GitHub issue 联动**：以后可加"挑选某些反馈 → 手动/半自动建 issue"，建后把链接回填到 `ticket_url` 和表格「状态」。**本期不做自动建 issue**，避免泛滥。
- **状态回查接口**：`GET /api/feedback/{id}` 让客户端查处理进度（本期不需要）。
- **附件直传**：图片大时改"客户端先问后端要预签名 URL → 直传对象存储 → 提交时只带 URL"。本期图片小，multipart 直传即可。

---

## 九、示例

**请求（curl 模拟客户端）：**
```bash
curl -X POST "https://<your-domain>/api/feedback" \
  -H "X-App-Version: 2.1.0" \
  -H "X-App-Platform: windows-x64" \
  -H "User-Agent: VideoCaptioner/2.1.0 (windows-x64)" \
  -F "category=bug" \
  -F "message=导出硬字幕时报 FFmpeg 234 错误，附截图" \
  -F "contact=user@example.com" \
  -F "client_id=4f9c2b1e-7a3d-4e2a-9c1d-1a2b3c4d5e6f" \
  -F "request_id=9b1d...uuid" \
  -F 'diagnostics={"app_version":"2.1.0","platform":"windows-x64","os":"Windows 11","ffmpeg":"ok","llm_provider":"deepseek"}' \
  -F "files=@/path/shot1.png;type=image/png" \
  -F "files=@/path/shot2.png;type=image/png"
```

**成功响应：**
```json
{ "ok": true, "id": "FB-20260623-0001", "ticket_url": null }
```

**失败响应（图片过大）：**
```json
{ "ok": false, "code": "too_large", "error": "图片过大，单张需 ≤5MB" }
```

---

## 十、交付给后端的清单（我这边需要你回填的）

1. 最终端点 URL。
2. 是否启用 `Authorization`；启用的话给 token（默认关闭）。
3. 大小上限：**单图最大 / 张数 / 请求总大小**（我默认 5MB / 3 张 / 12MB，可调）。
4. 确认响应字段用本文档的 `{ ok, id, ticket_url, code, error }`；要改字段名请告知，客户端对齐。
5. 限流阈值（我默认 client_id 5/h、IP 20/h，可调）。
6. 幂等窗口（我默认首次起 24h；或用 `request_id` 唯一索引＝永久去重）。

字段名/响应格式以本文件为准；任何一方改动都更新本文件。
