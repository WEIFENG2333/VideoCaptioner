# ChunkMerger 使用指南

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
from app.core.asr.chunk_merger import ChunkMerger
from app.core.asr.asr_data import ASRData, ASRDataSeg

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
