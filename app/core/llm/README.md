# LLM 统一客户端模块

统一管理项目中所有的 LLM API 调用，提供缓存和客户端复用功能。

## 功能特性

- ✅ 统一的 OpenAI 客户端管理（避免重复创建）
- ✅ 自动缓存 LLM 响应（基于 diskcache）
- ✅ 支持环境变量配置
- ✅ 类型安全的接口

## 使用方法

### 1. 获取 LLM 客户端

```python
from app.core.llm import get_llm_client

# 方式1：使用环境变量（OPENAI_BASE_URL, OPENAI_API_KEY）
client = get_llm_client()

# 方式2：显式传入参数
client = get_llm_client(
    base_url="https://api.openai.com/v1",
    api_key="sk-xxx"
)

# 使用客户端
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}]
)
```

### 2. 使用统一的 LLM 调用接口（推荐）

```python
from app.core.llm import call_llm

# 调用 LLM（自动缓存）
response = call_llm(
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "Translate this to Chinese"}
    ],
    model="gpt-4o-mini",
    temperature=0.7,
)

# 使用环境变量的简化调用
response = call_llm(
    messages=[...],
    model="gpt-4o-mini"
)

# 显式指定 base_url 和 api_key
response = call_llm(
    messages=[...],
    model="gpt-4o-mini",
    base_url="https://api.openai.com/v1",
    api_key="sk-xxx"
)
```

## 环境变量配置

在 `.env` 文件中配置：

```bash
# LLM 服务配置
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-api-key-here
```

## 缓存机制

`call_llm` 函数自动使用 `app/core/utils/cache.py` 的缓存机制：

- **缓存键**: 基于 messages, model, temperature 等参数的 MD5 哈希
- **缓存位置**: AppData/llm_cache/
- **验证器**: 自动验证 OpenAI 响应格式
- **异常处理**: 异常情况下不缓存

## 迁移指南

### 旧代码

```python
from openai import OpenAI

class MyTranslator:
    def __init__(self, base_url, api_key):
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def translate(self, text):
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": text}]
        )
        return response
```

### 新代码

```python
from app.core.llm import call_llm

class MyTranslator:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key

    def translate(self, text):
        response = call_llm(
            messages=[{"role": "user", "content": text}],
            model="gpt-4o-mini",
            base_url=self.base_url,
            api_key=self.api_key
        )
        return response
```

## 客户端复用

客户端会根据 `base_url` 和 `api_key` 自动缓存和复用：

```python
# 这两次调用会使用同一个客户端实例
client1 = get_llm_client("https://api.openai.com/v1", "sk-xxx")
client2 = get_llm_client("https://api.openai.com/v1", "sk-xxx")

assert client1 is client2  # True
```

## API 参考

### get_llm_client

```python
def get_llm_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None
) -> OpenAI
```

获取或创建 OpenAI 客户端实例。

**参数**:

- `base_url`: API 基础 URL（默认使用环境变量 OPENAI_BASE_URL）
- `api_key`: API 密钥（默认使用环境变量 OPENAI_API_KEY）

**返回**: OpenAI 客户端实例

**异常**: `ValueError` - 如果 base_url 或 api_key 未提供且环境变量未设置

### call_llm

```python
@cached(cache_instance=get_llm_cache(), validate=validate_openai_response)
def call_llm(
    messages: List[Dict[str, str]],
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.7,
    cache_ttl: Optional[int] = None,
    **kwargs: Any
) -> Any
```

调用 LLM API 并自动缓存结果。

**参数**:

- `messages`: 聊天消息列表（必需）
- `model`: 模型名称（必需）
- `base_url`: API 基础 URL（可选，默认使用环境变量）
- `api_key`: API 密钥（可选，默认使用环境变量）
- `temperature`: 采样温度（默认 0.7）
- `cache_ttl`: 缓存生存时间（可选，未来使用）
- `**kwargs`: 传递给 `client.chat.completions.create` 的其他参数

**返回**: API 响应对象

## 注意事项

1. **环境变量优先级**: 如果同时提供了参数和环境变量，参数优先
2. **缓存键生成**: 缓存键基于所有参数（messages, model, temperature等）
3. **客户端复用**: 相同的 base_url 和 api_key 会复用客户端实例
4. **异常处理**: API 调用失败时不会缓存结果
