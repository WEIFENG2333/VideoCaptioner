# voxgate `-f protocol` 原生协议调研

> 调研对象：`voxgate transcribe - --input-format pcm16 --stream -f protocol`
> 把 PCM 上行，把服务端下行的 send/recv 报文**逐条**打到 stdout（每行一个 JSON）。
>
> 复现命令（实时节奏喂一段真实录音，含停顿/错字/中英混说）：
>
> ```bash
> # 用既有录音当样例（16k/mono），按 100ms/块、每 100ms 一块的真实节奏喂送
> ffmpeg -i audio.wav -f s16le -ar 16000 -ac 1 - \
>   | <feeder 按实时节奏 write stdin> \
>   | voxgate transcribe - --input-format pcm16 --stream -f protocol -l zh
> ```
>
> 直接 `cat pcm | voxgate ... --realtime` 不会真正按实时节奏（管道一次性灌满，voxgate
> 秒处理完），看不到流式 interim；必须自己按 100ms 节奏喂 stdin。
>
> 本文依据 `/tmp/vox-rt4.tsv`（一段 ~31s、中间含停顿/错字/中英混说的真实录音）逐帧取证。

`-f`/`--format` 取值：`text|json|verbose_json|srt|vtt|ndjson|protocol`。我们用 **`protocol`**
（未消化的原始报文，信息最全：自带 `index` 分句 + 句级/词级时间戳）。

---

## 1. 报文信封（每行一条）

```jsonc
{
  "direction": "send" | "recv",          // 客户端发出 / 服务端下行
  "method_name": "StartTask",            // 仅 send：方法名
  "message_type": "TaskStarted",         // 仅 recv 控制消息：消息类型
  "request_id": "cccb303c-…",            // 整个连接一个
  "task_id": "297d8c38-…",               // 每条下行可能不同（服务端分配）
  "status_code": 20000000,               // 20000000 = OK
  "status_message": "OK",
  "time": "2026-06-19T11:36:13+08:00",   // 本地收/发时刻
  "payload": { … },                      // 仅部分 send（StartSession）
  "result_json": { … }                   // 仅 recv 的转录结果消息
}
```

`status_code == 20000000` 表示成功；其它值为错误（按错误处理，走 `on_error`）。

---

## 2. 会话生命周期

```text
send StartTask        → recv TaskStarted        (status 20000000，握手)
send StartSession     → recv SessionStarted     (带音频参数 + 业务开关)
（喂音频…服务端持续下行 result_json）
send FinishSession    → recv SessionFinished     (收尾，本次实测不带 result_json)
```

一次会话只有一对 Task / 一对 Session。中间全是 `result_json`。

### `StartSession.payload`（客户端上行的会话配置，了解即可，**我们不构造**）

```jsonc
{
  "audio_info": { "channel": 1, "format": "raw", "sample_rate": 16000 },
  "enable_punctuation": true,            // 自动标点
  "enable_speech_rejection": false,
  "extra": {
    "enable_asr_twopass": true,          // 二次（非流式）精修 → 文本会被改写
    "enable_asr_threepass": true,        // 三次精修
    "use_twopass_retry": true,
    "strong_ddc": true,                  // 强反流畅性修正（去口水词/规整）
    "remove_space_between_han_eng": true,// 中英之间去空格
    "remove_space_between_han_num": true,
    "input_mode": "tool", "app_name": "…", "did": "…", "context": "<base64>"
  }
}
```

> 关键：`enable_asr_twopass/threepass + strong_ddc` 就是**同一句文本被反复改写**的根因——
> 流式先出快稿，二/三次再回头精修（补标点、去口水词、纠错）。消费端必须按「会被改写」设计，
> 不能假定只追加。**但改写发生在同一个 `index` 内（见下），所以分句标识依然稳定。**

---

## 3. `result_json` 结构（新协议核心）

```jsonc
{
  "extra": {
    "audio_duration": 24300,             // 已处理音频毫秒数
    "model_avg_rtf": 0.0844,             // 实时率
    "model_total_process_time": 2053,
    "req_payload": { "end_smooth_silence_proportion": 0.9 },
    "speech_adaptation_version": "1"
  },
  "results": [ { …一句… }, … ] | null    // null = 心跳（无内容，跳过）
}
```

### `results[]` —— **每条 = 一句，自带 `index`（句号）**

新协议**不再**是「`results[0]`=全局累积、`results[1:]`=分句」那套。现在每帧的 `results` 通常
**只有一条**，且自带 `index` 字段（0、1、2…）作为**句号**。同一句被多遍解码改写时**复用同一个
`index`**——**`index` 就是天然的稳定 seg_id**，分句与稳定标识服务端已替我们做好。

| 字段 | 类型 | 含义 |
|---|---|---|
| `index` | int | **句号 = 稳定 seg_id**。同句多次改写复用，跨帧不变 |
| `text` | string | 该句到此刻的**累积全文**（会被 twopass 改写，非纯追加） |
| `is_interim` | bool | `true`=临时（还会变）；`false`=本帧不再变（见下两种） |
| `is_vad_finished` | bool | **该句 VAD 停顿结束 = 真·定稿**（句边界信号，我们认它） |
| `is_force_finished` | bool | **同句 twopass 二次冲刷**，其后同 `index` 仍继续生长，**不是定稿** |
| `start_time` / `end_time` | float(秒) | 该句覆盖的音频时间区间（相对会话起点） |
| `confidence` | float | 置信度 |
| `alternatives` | array | 候选（见下，含词级时间戳） |

### `alternatives[0]` —— 含**词级时间戳**

```jsonc
{
  "start_time": 1.88, "end_time": 3.219,
  "text": "你好呀",
  "semantic_related_to_prev": null,
  "oi_decoding_info": { … },             // 内部解码信息，无需消费
  "words": [
    { "start_time": 1.88,  "end_time": 3.666, "word": "你" },
    { "start_time": 2.326, "end_time": 4.113, "word": "好" },
    { "start_time": 2.773, "end_time": 4.559, "word": "呀" }
  ]
}
```

`words[]` = 逐词时间戳。**坑**：① 每句开头常有一个垃圾占位 `{" ", -0.001, -0.001}`，需跳过；
② `word.end_time` 普遍 overshoot（超过句尾 `end_time`），是平滑估计，不能直接当词尾。

---

## 4. 一句的完整生命周期（实测，`/tmp/vox-rt4.tsv`）

以第 0 句为例（中文 + 英文混说）：

```text
index=0 is_interim=true                  "你好呀"                          ← 生长
index=0 is_interim=true                  "你好呀，你觉得今天的天气怎么样呢？我觉得今天的天气非常的不错" ← 继续长
index=0 is_force_finished=true interim=false  "…非常的不错"                ← twopass 冲刷（句子没结束！）
index=0 is_interim=true                  "…非常的不错。i think the weather today" ← 同 index 继续长出英文
index=0 is_vad_finished=true interim=false    "…very nice。"               ← 真·停顿，定稿
```

第 1 句紧随其后（`index=1`，`start_time` 跳到新句起点），同样生长到 `is_vad_finished` 定稿。
定稿帧还会**多带一条 `text:""` 的下一句占位**（`start/end=-0.001`），跳过空文本即可。

要点：
- **句边界 = `is_vad_finished`（真停顿）**，不按标点切——一句可含好几小句（如第 0 句中英各一段）。
- **`is_force_finished` 绝不能当定稿**：它是 twopass 对当前 chunk 的中途冲刷，其后**同一个
  `index` 还会继续生长**。据它定稿会把句子提前收尾、丢掉后半句（如丢掉英文部分）。
- 本次实测 `SessionFinished` **不带 result_json**，没有「整段 recap」帧；末句靠 `is_vad_finished`
  自然定稿，若末句没等到 VAD 就停，交装配器 `close()` 兜底。

---

## 4b. 🔴 连续语音的「滚动重置」（看视频/会议，无停顿）—— 致命坑

§4 是**短音频/带停顿**的理想情形（index 递增 + 每句 VAD）。但**连续语音**完全不同，实测取证
（`_debug/20260619-121546/backend_events.ndjson`，118s 看视频会话）：

```text
整场 176 个 result 帧：index 自始至终只有 0；is_vad_finished 仅 1 次（结尾）；
index=0 的 text 涨到 ~118 字后骤跌回 1~5 字、再涨…… 共重置 7 次。
```

在连续语音下**不递增 index、整场不触发 VAD**，把整场当「一句」；但单句有 ~118 字累积上限，
到顶就**滚动重置 `text`**（丢前面、从最近重新累积）却仍复用 `index=0`。

**后果**：若直接拿 `index` 当 seg_id（只按 index upsert），同一句被覆盖 176 次，最后只定稿那一次
（结尾残段）——整场 118s 只存下 1 句，前面全丢。这正是用户报的「到一定长度又重置、不另开分句、
最终只剩一句」。

---

## 5. 我们怎么接

**不能拿 `index` 当 seg_id。** 后端维护自己的全局句号 `_sentence_no`，把「`index` 变化 OR
文本滚动重置」都当句边界——边界处把在途上一段补定稿、开新句：

```python
def _is_reset(old, new):  # 滚动重置：只看长度腰斩（绝不看前缀——twopass 改写会误判）
    return bool(old) and len(new) * 2 < len(old)

for r in results:
    text = r.get("text") or ""
    if not text.strip():                          # 跳过 text:"" 空占位
        continue
    idx, is_final = r.get("index", 0), bool(r.get("is_vad_finished"))
    if (last_index is not None and idx != last_index) or _is_reset(cur_text, text):
        if cur_text.strip():                      # 边界：在途上一段补定稿，开新句
            emit(seg_id=f"voxgate#{n}", text=cur_text, is_final=True, ...);  n += 1; cur_text = ""
    last_index = idx
    emit(seg_id=f"voxgate#{n}", text=text, is_final=is_final, start=..., end=...)
    if is_final: n += 1; cur_text = ""            # 自带 VAD 定稿：开新句
    else:        cur_text = text
```

回放验证：118s 中文连续语音 dump → **8 句**、英文 dump → **5 句、零重复**、`vox-rt4` 短音频 → 仍 **2 句**。
**`_is_reset` 只看长度腰斩，绝不看前缀**：twopass 改写（whose fault→who spots、改/补标点）会让前缀变、
长度只降一两字，若据前缀切会把同一句的生长前缀重复定稿成多句（线上「英文开头 3 句重复」真因，dump 实测
45→43→53… 全是 vad=0 生长帧，不是 VAD 触发）。

| 用途 | 取哪 |
|---|---|
| 句号 / seg_id | **自维护 `_sentence_no`**（不是 `index`！）；边界 = index 变化 OR 滚动重置 |
| 当前正在说（浮窗双色） | 同句 interim 更新；装配器用最长公共前缀算双色 |
| 句定稿（落历史 + 句子时间轴） | `is_vad_finished` 帧 或 边界处补定稿：`text` + `[start_time,end_time]` |
| 词级时间戳（详情页逐词高亮，**暂未消费**） | `alternatives[0].words[]`（注意去开头占位 + end_time overshoot） |
| 跳过 | `results==null` 心跳；`text:""` 占位；`is_force_finished`（不定稿） |

**与旧协议对比**：旧形态（`results[0]`=全局、`stream_asr_finish`、`nonstream_result`、三条
并行流、cover-count）已**全部作废**。新二进制把分句 + 稳定 `index` + 句/词级时间戳都做进了协议，
消费端从「全局累积 + 偏移切段 / cover-count 防重复分段」简化成「按 index upsert」一行逻辑。

> ⚠️ 二进制必须由本仓库源码编译并放进 `resource/bin/voxgate`（BUNDLED_BIN_PATH 优先于 PATH）。
> 旧构建若被 PATH 命中、协议对不上（仍发旧的 `stream_asr_finish` 形态）会整链行为错乱。

回归测试：`tests/test_realtime/test_voxgate_backend.py`（按 index upsert / force≠定稿 / VAD 定稿 /
空占位跳过）、`test_caption.py`（双色/定稿守卫）。真实帧回放：把 `/tmp/vox-rt4.tsv` 喂
`VoxgateBackend._dispatch` → `CaptionAssembler`，应产出**恰好 2 段、零重复、时间正确**。
