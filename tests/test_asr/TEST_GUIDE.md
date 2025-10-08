# ChunkMerger 测试指南

本指南介绍如何为 `ChunkMerger` 编写测试，以及如何使用 `conftest.py` 中的工具函数简化测试代码。

## 文件结构

```
tests/test_asr/
├── conftest.py              # 共享 fixtures 和工具函数
├── test_chunk_merger.py     # ChunkMerger 测试（已使用 conftest 优化）
└── TEST_GUIDE.md            # 本文档
```

## conftest.py 提供的工具

### 1. Fixtures

```python
@pytest.fixture
def merger() -> ChunkMerger:
    """标准 ChunkMerger (min_match_count=2)"""

@pytest.fixture
def strict_merger() -> ChunkMerger:
    """严格 ChunkMerger (min_match_count=5)"""
```

### 2. 测试数据构建工具

```python
# 从词列表创建简单片段
create_word_segments(
    words: List[str],
    start_time: int = 0,
    word_duration: int = 500
) -> List[ASRDataSeg]

# 创建编号词序列（用于长序列测试）
create_numbered_words(
    start_idx: int,
    count: int,
    time_per_word: int = 10000
) -> List[ASRDataSeg]
```

### 3. 断言工具

```python
# 验证指定词只出现一次
assert_no_duplicates(segments: List[ASRDataSeg], words: List[str])

# 验证所有词都存在
assert_contains_all(segments: List[ASRDataSeg], required_words: List[str])

# 验证词序列顺序正确
assert_sequence_order(segments: List[ASRDataSeg], expected_sequence: List[str])

# 验证时间戳连续性
assert_time_continuity(segments: List[ASRDataSeg], max_gap: int = 2000)
```

## 使用示例

### 基础示例：简单重叠合并

```python
from conftest import (
    create_word_segments,
    assert_no_duplicates,
    assert_sequence_order,
)

def test_simple_overlap(merger):
    # 创建测试数据
    chunk1 = ASRData(create_word_segments(["Hello", "world", "this", "is"]))
    chunk2 = ASRData(create_word_segments(["this", "is", "a", "test"]))

    # 执行合并
    result = merger.merge_chunks(
        chunks=[chunk1, chunk2],
        chunk_offsets=[0, 1000],
        overlap_duration=1000,
    )

    # 验证
    assert_no_duplicates(result.segments, ["this", "is"])
    assert_sequence_order(result.segments, ["Hello", "world", "this", "is", "a", "test"])
```

### 进阶示例：长序列测试

```python
from conftest import create_numbered_words

def test_long_sequence(merger):
    # 创建 3 个 chunk，每个 60 个词，重叠 12 个词
    chunks = []
    overlap_count = 12

    for i in range(3):
        start_idx = i * (60 - overlap_count)
        segments = create_numbered_words(start_idx, 60, time_per_word=1000)
        chunks.append(ASRData(segments))

    offsets = [i * (60 - overlap_count) * 1000 for i in range(3)]

    result = merger.merge_chunks(
        chunks=chunks,
        chunk_offsets=offsets,
        overlap_duration=overlap_count * 1000,
    )

    texts = [seg.text for seg in result.segments]

    # 期望: 60 + 48 + 48 = 156 个词
    assert 150 <= len(texts) <= 160

    # 验证连续性（无跳跃）
    for i in range(len(texts) - 1):
        curr = int(texts[i].replace("word", ""))
        next_val = int(texts[i + 1].replace("word", ""))
        assert next_val == curr + 1
```

### 参数化测试

```python
@pytest.mark.parametrize(
    "word_count,overlap_count,chunk_count,expected_total",
    [
        (50, 10, 3, 130),   # 50 + 40 + 40 = 130
        (100, 20, 2, 180),  # 100 + 80 = 180
        (30, 5, 5, 130),    # 30 + 25*4 = 130
    ],
)
def test_various_configs(merger, word_count, overlap_count, chunk_count, expected_total):
    chunks = []
    for i in range(chunk_count):
        start_idx = i * (word_count - overlap_count)
        segments = create_numbered_words(start_idx, word_count, time_per_word=1000)
        chunks.append(ASRData(segments))

    offsets = [i * (word_count - overlap_count) * 1000 for i in range(chunk_count)]

    result = merger.merge_chunks(
        chunks=chunks,
        chunk_offsets=offsets,
        overlap_duration=overlap_count * 1000,
    )

    # 允许 ±5% 误差
    tolerance = int(expected_total * 0.05)
    assert expected_total - tolerance <= len(result.segments) <= expected_total + tolerance
```

## 测试类组织

建议按场景组织测试类：

```python
class TestChunkMergerBasics:
    """基础功能测试"""
    def test_simple_merge(self, merger): ...
    def test_no_overlap(self, merger): ...


class TestRealWorldScenarios:
    """真实场景测试"""
    def test_podcast(self, merger): ...
    def test_long_content(self, merger): ...
    def test_chinese_content(self, merger): ...


class TestEdgeCases:
    """边缘情况测试"""
    def test_asr_error(self, merger): ...
    def test_mixed_languages(self, merger): ...


class TestStrictMerger:
    """测试严格模式"""
    def test_requires_more_matches(self, strict_merger): ...
```

## 最佳实践

### 1. 使用工具函数简化代码

❌ **不推荐**：手动创建大量片段

```python
chunk1_segments = [
    ASRDataSeg("Hello", 0, 500),
    ASRDataSeg("world", 500, 1000),
    ASRDataSeg("this", 1000, 1500),
    # ... 很多重复代码
]
```

✅ **推荐**：使用工具函数

```python
chunk1 = ASRData(create_word_segments(["Hello", "world", "this", "is"]))
```

### 2. 使用断言工具提高可读性

❌ **不推荐**：手动验证

```python
texts = [seg.text for seg in result.segments]
for word in ["Hello", "world", "test"]:
    assert word in texts, f"Missing {word}"
    assert texts.count(word) == 1, f"{word} duplicated"
```

✅ **推荐**：使用断言工具

```python
assert_no_duplicates(result.segments, ["Hello", "world", "test"])
assert_contains_all(result.segments, ["Hello", "world", "test"])
```

### 3. 测试数据设计原则

- **避免词重复**：如果测试重叠去重，确保非重叠区域的词不重复
- **时间合理性**：确保时间偏移和重叠时长匹配实际场景
- **真实场景**：基于实际使用场景（播客、vlog、教学视频等）设计测试

### 4. 测试命名清晰

```python
# ✅ 清晰的测试名称
def test_podcast_with_natural_pauses(self, merger): ...
def test_long_form_content_six_chunks(self, merger): ...
def test_chinese_content_semantic_overlap(self, merger): ...

# ❌ 模糊的测试名称
def test_case1(self, merger): ...
def test_merge(self, merger): ...
```

## 运行测试

```bash
# 运行所有 chunk_merger 测试
uv run pytest tests/test_asr/test_chunk_merger*.py -v

# 运行特定测试类
uv run pytest tests/test_asr/test_chunk_merger_refactored.py::TestRealWorldScenarios -v

# 运行特定测试
uv run pytest tests/test_asr/test_chunk_merger_refactored.py::test_parametrized_merges -v

# 使用 -k 过滤测试
uv run pytest tests/test_asr/ -k "chinese" -v
```

## 总结

使用 `conftest.py` 中的工具函数可以：

- ✅ **减少代码量**：避免重复的片段创建代码
- ✅ **提高可读性**：测试意图更清晰
- ✅ **提高可维护性**：统一的工具函数易于修改
- ✅ **提高一致性**：所有测试使用相同的数据构建方式

参考 [test_chunk_merger.py](test_chunk_merger.py) 查看实际应用示例。
