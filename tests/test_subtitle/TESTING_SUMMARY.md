# SubtitleThread 测试总结

## ✅ 测试现状

### 通过的测试（无需API）

```bash
$ uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadError -v

✅ test_missing_file - 文件不存在错误处理
✅ test_no_translator_service - 翻译服务未配置错误处理

2 passed in 0.25s
```

### 需要API配置的测试（已跳过）

以下测试需要有效的 `OPENAI_API_KEY` 才能运行：

- `TestSubtitleThreadSplit::test_split_sentence` - 句子分割
- `TestSubtitleThreadOptimize::test_optimize_with_llm` - LLM优化
- `TestSubtitleThreadTranslate::test_translate_llm` - LLM翻译
- `TestSubtitleThreadFullPipeline::test_split_and_translate` - 分割+翻译
- `TestSubtitleThreadFullPipeline::test_optimize_and_translate` - 优化+翻译

### 免费API测试（可能不稳定）

- `TestSubtitleThreadTranslate::test_translate_google` - Google翻译
- `TestSubtitleThreadTranslate::test_translate_bing` - Bing翻译

**注意**: 这些测试使用免费API，可能因网络问题或频率限制失败。

## 🚀 如何运行完整测试

### 1. 配置环境变量

```bash
# 创建 .env 文件
cat > tests/.env << EOF
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-your-actual-api-key-here
EOF
```

### 2. 运行测试

```bash
# 只运行无需API的测试（快速验证）
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadError -v

# 运行所有测试（需要API）
uv run pytest tests/test_subtitle/test_subtitle_thread.py -v

# 跳过需要真实API的测试
uv run pytest tests/test_subtitle/ -m "not integration" -v

# 查看详细日志
uv run pytest tests/test_subtitle/test_subtitle_thread.py -v -s
```

## 📋 测试文件结构

```
tests/test_subtitle/
├── __init__.py                # 模块标识
├── conftest.py               # QApplication fixture（必需）
├── test_subtitle_thread.py   # 主测试文件
├── README.md                 # 使用文档
└── TESTING_SUMMARY.md        # 本文件

tests/fixtures/subtitle/
└── sample_en.srt             # 测试字幕文件（10段英文）
```

## 🔧 关键实现细节

### 1. QApplication Fixture

PyQt5 线程测试需要 QApplication 实例：

```python
# tests/test_subtitle/conftest.py
@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for testing Qt components."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
```

### 2. 超时保护

使用 `run_thread_with_timeout()` 辅助函数防止测试挂起：

```python
def run_thread_with_timeout(thread, timeout_ms=60000):
    """Run thread with timeout to prevent hanging tests."""
    # ... 设置信号处理
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    # ...
```

### 3. API配置模拟

需要LLM的测试必须提供完整配置：

```python
config.llm_model = "gpt-4o-mini"
config.base_url = os.getenv("OPENAI_BASE_URL")
config.api_key = os.getenv("OPENAI_API_KEY")
```

## 🐛 已知问题

### 1. 句子分割需要LLM API

**问题**: 即使是简单的句子分割也需要LLM API配置

**原因**: `SubtitleThread._setup_api_config()` 检查 `asr_data.is_word_timestamp()`，
如果字幕有词级时间戳就要求API（即使句子分割不需要LLM）

**影响**: 无法测试无API的句子分割场景

**代码位置**: `app/thread/subtitle_thread.py:89-101`

### 2. Google/Bing翻译输出路径问题

**问题**: 翻译后保存时文件扩展名为空

**错误**: `ValueError: Unsupported file extension:`

**原因**: 测试中未正确设置输出路径

**状态**: 需要进一步调试

## 📖 下一步

1. **添加真实API密钥** - 在CI/CD中配置secrets
2. **修复输出路径问题** - 确保翻译测试正确设置文件路径
3. **添加更多字幕文件** - 测试不同格式和内容
4. **Mock API调用** - 减少对真实API的依赖

## 💡 使用建议

### 开发时

```bash
# 快速验证基础功能
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadError -v
```

### CI/CD

```bash
# 配置secrets后运行完整测试
export OPENAI_BASE_URL=${{ secrets.OPENAI_BASE_URL }}
export OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
uv run pytest tests/test_subtitle/ -v
```

### 调试单个测试

```bash
# 运行特定测试并查看输出
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadError::test_missing_file -v -s

# 查看完整错误信息
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadTranslate::test_translate_google -v --tb=long
```

## ✨ 测试最佳实践

1. ✅ **始终使用 `run_thread_with_timeout()`** - 防止挂起
2. ✅ **检查 `"error"` 键** - 确保线程成功完成
3. ✅ **提供有意义的错误信息** - 使用 `f"Failed: {results.get('error')}"`
4. ✅ **适当跳过测试** - 使用 `pytest.skip()` 而不是让测试失败
5. ✅ **清理临时文件** - 使用 `tempfile.TemporaryDirectory()`

---

_最后更新: 2025-10-05_
