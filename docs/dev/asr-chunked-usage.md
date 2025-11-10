# ChunkedASR 使用指南

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
from app.core.asr import BcutASR, ChunkedASR

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
from app.core.asr import transcribe
from app.core.entities import TranscribeConfig, TranscribeModelEnum

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
from app.core.asr import FasterWhisperASR, ChunkedASR

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
