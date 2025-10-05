# Subtitle Processing Tests

测试 `SubtitleThread` 字幕处理线程的完整功能。

## 📁 测试文件

```
tests/test_subtitle/
└── test_subtitle_thread.py    # SubtitleThread 集成测试
```

## 🚀 运行测试

### 快速测试（免费 API）

```bash
# 只测试句子分割（无需 API）
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadSplit::test_split_sentence -v

# 测试 Google/Bing 翻译（免费API，可能不稳定）
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadTranslate::test_translate_google -v
uv run pytest tests/test_subtitle/test_subtitle_thread.py::TestSubtitleThreadTranslate::test_translate_bing -v
```

### 完整测试（需要 LLM API）

```bash
# 1. 配置环境变量
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-your-key

# 2. 运行所有测试
uv run pytest tests/test_subtitle/ -v

# 3. 跳过需要 API 的测试
uv run pytest tests/test_subtitle/ -m "not integration" -v
```

## 📊 测试覆盖

### 字幕分割测试 (`TestSubtitleThreadSplit`)

- ✅ `test_split_sentence` - 句子分割（无需API）
- 🔑 `test_split_semantic` - 语义分割（需要 LLM）

### 字幕优化测试 (`TestSubtitleThreadOptimize`)

- 🔑 `test_optimize_with_llm` - LLM优化（需要 LLM）

### 字幕翻译测试 (`TestSubtitleThreadTranslate`)

- 🌐 `test_translate_google` - Google翻译（免费API）
- 🌐 `test_translate_bing` - Bing翻译（免费API）
- 🔑 `test_translate_llm` - LLM翻译（需要 LLM）

### 完整流程测试 (`TestSubtitleThreadFullPipeline`)

- 🔑 `test_split_and_translate` - 分割+翻译
- 🔑 `test_optimize_and_translate` - 优化+翻译

### 错误处理测试 (`TestSubtitleThreadError`)

- ✅ `test_missing_file` - 文件不存在
- ✅ `test_no_translator_service` - 翻译服务未配置

**图例**:

- ✅ 无需配置即可运行
- 🌐 需要网络，免费API（可能不稳定）
- 🔑 需要 OPENAI_API_KEY

## ⚙️ 环境变量

### 本地开发

创建 `.env` 文件（已在 .gitignore 中）：

```bash
# LLM API（推荐使用 gpt-4o-mini）
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-your-api-key
```

### CI/CD

GitHub Actions 中通过 **Settings → Secrets** 配置：

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

## 📝 测试数据

### 测试字幕文件

- **路径**: `tests/fixtures/subtitle/sample_en.srt`
- **内容**: Python教程英文字幕（10段）
- **时长**: ~38秒
- **用途**: 所有字幕处理测试

### 自定义测试字幕

你可以添加自己的字幕文件到 `tests/fixtures/subtitle/` 并修改测试：

```python
@pytest.fixture
def subtitle_file():
    return "tests/fixtures/subtitle/your_custom.srt"
```

## 🔍 测试输出

测试会在临时目录创建输出文件，测试结束后自动清理。要查看实际输出：

```python
def test_split_sentence(self, subtitle_file, base_config):
    # ... 测试代码 ...

    # 调试：打印输出路径
    print(f"Output: {results['output']}")

    # 读取输出内容
    with open(results['output'], 'r') as f:
        print(f.read())
```

## 🐛 常见问题

### 测试被跳过

**原因**: 缺少 `OPENAI_API_KEY`

**解决**:

```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-your-key
```

### Google/Bing 测试失败

**原因**: 免费API不稳定或有频率限制

**解决**:

- 这是正常的，免费服务没有SLA保证
- 重点测试 LLM 翻译（更稳定）
- 使用 `-k "not google and not bing"` 跳过

### QEventLoop 超时

**原因**: 线程未正确结束

**解决**:

- 检查信号连接是否正确
- 确保 finished/error 信号被触发

## 📖 相关文档

- [字幕处理模块](../../app/core/split/)
- [翻译模块](../../app/core/translate/)
- [测试指南](../../docs/TESTING.md)
