# ASR 长音频分块：ChunkedASR 与 ChunkMerger

> 长音频转录的完整链路：ChunkedASR 负责分块与并发转录，ChunkMerger 负责重叠区合并。两者配合使用，本文上下两部分分别说明。

---

## ChunkedASR 使用指南

## 概述

`ChunkedASR` 是一个装饰器类，为任何 `BaseASR` 实现添加音频分块转录能力。适用于长音频（>20分钟）的分块转录，避免 API 超时或内存溢出。

## 核心特性

- ✅ **装饰器模式** - 关注点分离，不污染 BaseASR
- ✅ **并发转录** - 使用 ThreadPoolExecutor 并发处理多个块
- ✅ **智能合并** - 使用 ChunkMerger 消除重叠区域的重复内容
- ✅ **进度回调** - 支持细粒度的进度追踪
- ✅ **自动判断** - 短音频自动跳过分块，直接转录

## 快速开始

### 基本用法

```python
from videocaptioner.core.asr import BcutASR, ChunkedASR

# 1. 创建基础 ASR 实例
base_asr = BcutASR(audio_path, need_word_time_stamp=True)

# 2. 用 ChunkedASR 包装
chunked_asr = ChunkedASR(
    base_asr,
    chunk_length=1200,    # 20 分钟/块
    chunk_overlap=10,     # 10 秒重叠
    chunk_concurrency=3   # 3 个并发
)

# 3. 运行转录
result = chunked_asr.run(callback=my_callback)
```

### 在 transcribe() 中自动使用

`transcribe()` 函数已经自动为 `BIJIAN` 和 `JIANYING` 启用了分块：

```python
from videocaptioner.core.asr import transcribe
from videocaptioner.core.entities import TranscribeConfig, TranscribeModelEnum

config = TranscribeConfig(
    transcribe_model=TranscribeModelEnum.BIJIAN,
    need_word_time_stamp=True
)

# 自动使用 ChunkedASR 包装（20 分钟/块）
result = transcribe(audio_path, config, callback)
```

## 参数说明

### `ChunkedASR.__init__`

| 参数                | 类型    | 默认值   | 说明                 |
| ------------------- | ------- | -------- | -------------------- |
| `base_asr`          | BaseASR | **必需** | 底层 ASR 实例        |
| `chunk_length`      | int     | 1200     | 每块长度（秒）       |
| `chunk_overlap`     | int     | 10       | 块之间重叠时长（秒） |
| `chunk_concurrency` | int     | 3        | 并发转录数量         |

### 参数选择建议

**chunk_length（分块长度）**

- **公益 API（BIJIAN/JIANYING）**: 1200 秒（20 分钟）- 避免超时
- **付费 API（Whisper API）**: 可更长，如 3600 秒（1 小时）
- **本地转录（FasterWhisper）**: 通常不需要分块

**chunk_overlap（重叠时长）**

- **推荐值**: 10 秒
- **作用**: 提供足够的上下文用于合并，避免丢失边界内容
- **注意**: 过长会增加计算量，过短可能导致合并不准确

**chunk_concurrency（并发数）**

- **公益 API**: 2-3（避免触发限流）
- **付费 API**: 5-10（根据账户配额调整）
- **本地转录**: 根据 CPU/GPU 资源调整

## 工作流程

```
┌──────────────┐
│  长音频文件   │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────┐
│  1. _split_audio()           │
│  - 使用 pydub 切割音频        │
│  - 每块 20 分钟，重叠 10 秒   │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│  2. _transcribe_chunks()     │
│  - ThreadPoolExecutor 并发   │
│  - 每块独立调用 base_asr.run()│
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│  3. _merge_results()         │
│  - ChunkMerger 合并结果      │
│  - 消除重叠区域的重复内容     │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────┐
│  ASRData 结果 │
└──────────────┘
```

## 高级用法

### 自定义进度回调

```python
def progress_callback(progress: int, message: str):
    print(f"[{progress}%] {message}")
    # 可以更新 UI 进度条、发送通知等

chunked_asr = ChunkedASR(base_asr)
result = chunked_asr.run(callback=progress_callback)
```

输出示例：

```
[5%] Chunk 1/5: uploading
[25%] Chunk 1/5: transcribing
[30%] Chunk 2/5: uploading
[50%] Chunk 2/5: transcribing
...
```

### 为其他 ASR 添加分块能力

```python
# 为 FasterWhisper 添加分块（处理超长音频）
from videocaptioner.core.asr import FasterWhisperASR, ChunkedASR

base_asr = FasterWhisperASR(
    audio_path,
    whisper_model="large-v3",
    language="zh"
)

# 用于处理 2 小时的音频
chunked_asr = ChunkedASR(
    base_asr,
    chunk_length=3600,   # 1 小时/块
    chunk_overlap=30,    # 30 秒重叠
    chunk_concurrency=2  # 2 个并发（避免显存不足）
)

result = chunked_asr.run()
```

## 注意事项

### 1. 音频格式要求

- ChunkedASR 依赖 `pydub` 进行音频切割
- 确保安装了 `ffmpeg`（pydub 的依赖）
- 支持所有 pydub 支持的格式（mp3, wav, m4a, flac 等）

### 2. 内存管理

- 每个并发块会临时占用内存
- `chunk_concurrency=3` 时，同时会有 3 个音频块在内存中
- 对于超大文件，适当降低并发数

### 3. 缓存行为

- ChunkedASR 本身不处理缓存
- 缓存由底层 `base_asr` 的 `run()` 方法处理
- 每个块会独立缓存（如果 `use_cache=True`）

### 4. 错误处理

- 如果某个块转录失败，整个任务会抛出异常
- 建议在外层捕获异常并进行重试

## 性能优化建议

### 1. 合理设置并发数

```python
# ❌ 不推荐：并发过高导致限流
chunked_asr = ChunkedASR(base_asr, chunk_concurrency=10)

# ✅ 推荐：根据 API 限制调整
chunked_asr = ChunkedASR(base_asr, chunk_concurrency=3)
```

### 2. 根据音频长度调整分块大小

```python
# 短音频（< 20 分钟）- 不使用分块
if audio_duration < 1200:
    result = base_asr.run()
else:
    # 长音频 - 使用分块
    result = ChunkedASR(base_asr).run()
```

### 3. 启用缓存避免重复转录

```python
# 为底层 ASR 启用缓存
base_asr = BcutASR(audio_path, use_cache=True)
chunked_asr = ChunkedASR(base_asr)

# 第一次转录会缓存每个块
result1 = chunked_asr.run()  # 调用 API

# 第二次转录直接读取缓存
result2 = chunked_asr.run()  # 从缓存读取
```

## 测试

运行测试验证 ChunkedASR 功能：

```bash
# 测试 BcutASR 和 JianYingASR（已自动使用 ChunkedASR）
uv run pytest tests/test_asr/test_bcut_asr.py -v
uv run pytest tests/test_asr/test_jianying_asr.py -v

# 测试分块相关功能
uv run pytest tests/test_asr/test_chunking.py -v
uv run pytest tests/test_asr/test_chunk_merger.py -v
```

## 常见问题

**Q: 短音频会被分块吗？**
A: 不会。ChunkedASR 会自动判断，如果音频短于 `chunk_length`，会直接调用 `base_asr.run()` 而不分块。

**Q: 分块会丢失内容吗？**
A: 不会。通过 `chunk_overlap` 保证块之间有重叠，ChunkMerger 会智能合并重叠区域，不会丢失内容。

**Q: 如何调试分块问题？**
A: 查看日志输出：

```python
import logging
logging.getLogger("chunked_asr").setLevel(logging.DEBUG)
```

**Q: 可以为本地 ASR 使用分块吗？**
A: 可以，但通常不推荐。本地 ASR（如 FasterWhisper）通常足够快，不需要分块。仅在处理超长音频（>2 小时）或显存不足时使用。

## 相关文档

- [ChunkMerger 使用指南](./CHUNK_MERGER_USAGE.md)
- [ASR 模块开发指南](./README.md)
- [测试指南](../../tests/test_asr/TEST_GUIDE.md)

---

## ChunkMerger 使用指南

## 概述

`ChunkMerger` 用于合并多个音频分块的 ASR（语音识别）结果。当处理长音频时，通常需要将音频分割成多个片段分别识别，然后合并结果。本模块使用精确文本匹配算法（基于 Groq API Cookbook）来智能处理重叠区域。

## 核心特性

- ✅ **精确文本匹配**：使用滑动窗口找最长公共序列，不使用模糊相似度
- ✅ **自动时间戳调整**：正确处理每个 chunk 的时间偏移
- ✅ **重叠区域智能处理**：自动检测和去除重复的识别内容
- ✅ **多语言支持**：支持中文、英文、混合文本等
- ✅ **词级/句子级时间戳**：两种时间戳类型均可正确处理

## 基本用法

### 示例 1：合并两个有重叠的音频片段

```python
from videocaptioner.core.asr.chunk_merger import ChunkMerger
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg

# 创建合并器
merger = ChunkMerger(min_match_count=2)

# Chunk 1: 0-30s 的识别结果
chunk1_segments = [
    ASRDataSeg("Hello", 0, 1000),
    ASRDataSeg("world", 1000, 2000),
    ASRDataSeg("this", 2000, 3000),
    # ... 更多片段
]
chunk1 = ASRData(chunk1_segments)

# Chunk 2: 20-50s 的识别结果（重叠 10s）
chunk2_segments = [
    ASRDataSeg("this", 0, 1000),      # 实际时间 20-21s
    ASRDataSeg("is", 1000, 2000),     # 实际时间 21-22s
    ASRDataSeg("test", 2000, 3000),   # 实际时间 22-23s
    # ... 更多片段
]
chunk2 = ASRData(chunk2_segments)

# 合并
merged = merger.merge_chunks(
    chunks=[chunk1, chunk2],
    chunk_offsets=[0, 20000],      # chunk2 实际从 20s 开始
    overlap_duration=10000         # 10s 重叠
)

print(f"合并后片段数: {len(merged.segments)}")
```

### 示例 2：合并多个音频片段

```python
# 模拟长音频：3 个 30s 的片段，每个重叠 10s
chunk1 = ASRData([...])  # 0-30s
chunk2 = ASRData([...])  # 20-50s
chunk3 = ASRData([...])  # 40-70s

# 一次性合并所有片段
merged = merger.merge_chunks(
    chunks=[chunk1, chunk2, chunk3],
    chunk_offsets=[0, 20000, 40000],
    overlap_duration=10000
)
```

### 示例 3：自动推断时间偏移

```python
# 如果不提供 chunk_offsets，会自动推断
merged = merger.merge_chunks(
    chunks=[chunk1, chunk2, chunk3],
    overlap_duration=10000  # 只需指定重叠时长
)
```

## 参数说明

### ChunkMerger 构造函数

```python
ChunkMerger(min_match_count: int = 2)
```

- `min_match_count`: 最小匹配词数阈值，低于此值视为无效匹配（默认 2）

### merge_chunks 方法

```python
merge_chunks(
    chunks: List[ASRData],
    chunk_offsets: Optional[List[int]] = None,
    overlap_duration: int = 10000
) -> ASRData
```

**参数**：

- `chunks`: ASRData 对象列表（必需）
- `chunk_offsets`: 每个 chunk 的起始时间（毫秒），如为 None 则自动推断
- `overlap_duration`: 重叠时长（毫秒），默认 10 秒

**返回**：

- 合并后的 `ASRData` 对象

## 算法原理

### 1. 精确文本匹配

使用滑动窗口遍历所有可能的对齐方式，计算每个位置的精确匹配词数（要求连续匹配）：

```
Chunk1 末尾: ["and", "we", "need", "to", "find", "the", "best"]
Chunk2 开头: ["need", "to", "find", "the", "best", "solution"]

最佳匹配: ["need", "to", "find", "the", "best"] (5个词)
```

### 2. 时间戳调整

```python
# Chunk2 的时间戳加上偏移量
adjusted_time = original_time + chunk_offset
```

### 3. 合并策略

- **有匹配**：保留 chunk1 的重叠部分，丢弃 chunk2 的重叠部分
- **无匹配**：使用时间边界切分

## 实际应用场景

### 场景 1：长视频字幕生成

```python
# 60 分钟视频，每 30 秒一个片段，重叠 10 秒
chunks = []
offsets = []

for i in range(0, 3600, 20):  # 每 20s 一个起点（30s 片段 - 10s 重叠）
    audio_chunk = extract_audio(video_path, start=i, duration=30)
    asr_result = transcribe(audio_chunk)
    chunks.append(asr_result)
    offsets.append(i * 1000)  # 转换为毫秒

# 合并所有片段
final_result = merger.merge_chunks(
    chunks=chunks,
    chunk_offsets=offsets,
    overlap_duration=10000
)

# 保存字幕
final_result.save("output.srt")
```

### 场景 2：在线流式识别

```python
class StreamingASR:
    def __init__(self):
        self.merger = ChunkMerger()
        self.chunks = []
        self.offsets = []

    def on_chunk_received(self, chunk_audio, timestamp):
        # 识别当前片段
        asr_result = transcribe(chunk_audio)
        self.chunks.append(asr_result)
        self.offsets.append(timestamp)

        # 实时合并
        if len(self.chunks) >= 2:
            merged = self.merger.merge_chunks(
                chunks=self.chunks,
                chunk_offsets=self.offsets,
                overlap_duration=5000  # 5s 重叠
            )
            return merged
```

## 注意事项

### 1. 重叠时长建议

- **推荐**：10 秒重叠（足以捕获句子边界）
- **最小**：3-5 秒（太短可能匹配失败）
- **最大**：不超过 chunk 长度的 1/3

### 2. 匹配阈值

```python
# 对于短句子，可以降低阈值
merger = ChunkMerger(min_match_count=1)

# 对于长句子，可以提高阈值以提高准确性
merger = ChunkMerger(min_match_count=3)
```

### 3. 时间戳连续性

合并后，请验证时间戳的连续性：

```python
# 验证时间戳
for i in range(len(merged.segments) - 1):
    seg1 = merged.segments[i]
    seg2 = merged.segments[i + 1]
    gap = seg2.start_time - seg1.end_time
    if gap > 2000:  # 间隔超过 2s
        print(f"警告: 片段 {i} 和 {i+1} 之间有 {gap}ms 间隔")
```

## 测试

运行测试套件：

```bash
# 运行所有测试
uv run pytest tests/test_asr/test_chunk_merger.py -v

# 运行特定测试
uv run pytest tests/test_asr/test_chunk_merger.py::TestChunkMergerBasic -v
```

## 常见问题

### Q1: 合并后丢失了部分内容？

**A**: 检查重叠区域是否足够长，确保 `overlap_duration` 至少为 5 秒。

### Q2: 匹配失败，使用了时间边界切分？

**A**: 可能是重叠区域的文本差异太大（识别错误）。可以：

1. 降低 `min_match_count` 阈值
2. 增加重叠时长
3. 检查 ASR 质量

### Q3: 时间戳不连续？

**A**: 检查 `chunk_offsets` 是否正确，应该准确反映每个 chunk 的实际起始时间。

## 相关文档

- [ASRData 数据结构](../asr_data.py)
- [Groq Audio Chunking Tutorial](https://github.com/groq/groq-api-cookbook/blob/main/tutorials/audio-chunking/audio_chunking_tutorial.ipynb)
