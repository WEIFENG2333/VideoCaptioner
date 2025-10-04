# 翻译模块 (Translate Module)

多语言字幕翻译模块，支持多种翻译服务。

## 模块结构

```
app/core/translate/
├── __init__.py              # 模块导出
├── types.py                 # 翻译器类型枚举
├── base.py                  # 翻译器基类
├── llm_translator.py        # LLM 翻译器（使用 litellm）
├── google_translator.py     # Google 翻译器
├── bing_translator.py       # Bing 翻译器
├── deeplx_translator.py     # DeepLX 翻译器
└── factory.py               # 翻译器工厂
```

## 支持的翻译服务

### 1. LLM 翻译器 (OpenAI 兼容)

- 使用 `litellm` 直接调用 OpenAI 兼容 API
- 支持批量翻译和单条翻译
- 内置缓存机制
- 支持 Reflect 模式（反思优化翻译）
- 支持自定义 Prompt

### 2. Google 翻译器

- 免费翻译服务
- 支持多种语言
- 适合日常使用

### 3. Bing 翻译器

- Microsoft 翻译服务
- 批量翻译支持
- 自动 Token 管理

### 4. DeepLX 翻译器

- DeepL 的免费接口
- 高质量翻译
- 可自定义端点

## 使用示例

### 基础使用

```python
from app.core.translate import TranslatorFactory, TranslatorType

# 创建 LLM 翻译器
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.OPENAI,
    model="gpt-4o-mini",
    target_language="Chinese",
    temperature=0.7,
)

# 翻译字幕
result = translator.translate_subtitle("subtitle.srt")
```

### 使用 Google 翻译

```python
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.GOOGLE,
    target_language="简体中文",
)

result = translator.translate_subtitle("subtitle.srt")
```

### 使用 Bing 翻译

```python
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.BING,
    target_language="Chinese",
)

result = translator.translate_subtitle("subtitle.srt")
```

### 使用 DeepLX 翻译

```python
import os

# 设置 DeepLX 端点（可选）
os.environ["DEEPLX_ENDPOINT"] = "https://your-deeplx-endpoint.com/translate"

translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.DEEPLX,
    target_language="Chinese",
)

result = translator.translate_subtitle("subtitle.srt")
```

## 环境变量配置

### LLM 翻译器

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

### DeepLX 翻译器

```bash
export DEEPLX_ENDPOINT="https://api.deeplx.org/translate"
```

## 高级功能

### 并发翻译

```python
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.OPENAI,
    thread_num=10,      # 并发线程数
    batch_num=20,       # 每批处理数量
)
```

### 自定义 Prompt

```python
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.OPENAI,
    custom_prompt="请保持原文的语气和风格",
)
```

### 进度回调

```python
def on_progress(result):
    print(f"翻译进度: {result}")

translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.OPENAI,
    update_callback=on_progress,
)
```

### Reflect 模式（反思优化）

```python
translator = TranslatorFactory.create_translator(
    translator_type=TranslatorType.OPENAI,
    is_reflect=True,  # 启用反思模式
)
```

## 缓存机制

所有翻译器都内置了缓存支持：

- **LLM 翻译器**: 使用 `CacheManager` 缓存翻译结果
- **Google/Bing/DeepLX**: 使用 `CacheManager` 缓存翻译结果

缓存基于：

- 原文内容
- 目标语言
- 模型参数（LLM）
- Prompt 哈希（LLM）

## 扩展新的翻译器

1. 继承 `BaseTranslator`
2. 实现 `_translate_chunk` 方法
3. 在 `factory.py` 中注册

```python
from app.core.translate.base import BaseTranslator

class MyTranslator(BaseTranslator):
    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        # 实现翻译逻辑
        result = {}
        for idx, text in subtitle_chunk.items():
            result[idx] = my_translate_function(text)
        return result
```

## 注意事项

1. **LLM 翻译器**需要设置 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`
2. **批量大小**会影响翻译效率和 API 成本
3. **并发数量**应根据网络和 API 限制调整
4. 所有翻译器都支持 **停止**操作：`translator.stop()`
5. 翻译结果会自动保存到 `ASRData` 的 `translated_text` 字段

## 性能优化建议

- 使用缓存避免重复翻译
- 合理设置 `batch_num` 减少 API 调用
- 调整 `thread_num` 提高并发效率
- 对于大量字幕，使用 Google/Bing 等免费服务
- 对于高质量要求，使用 LLM 或 DeepLX
