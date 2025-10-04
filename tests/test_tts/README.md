# TTS 测试文档

## 概述

本目录包含 TTS（Text-To-Speech）模块的测试文件：

- **test_tts_core.py**: 单元测试（使用 mock，无需真实 API）
- **test_tts_integration.py**: 集成测试（调用真实 API，需要密钥）

## 单元测试 (test_tts_core.py)

### 运行方式

```bash
# 运行所有单元测试
pytest tests/test_tts/test_tts_core.py -v

# 运行特定测试类
pytest tests/test_tts/test_tts_core.py::TestOpenAIFmTTS -v
```

### 测试覆盖 (共34个测试)

- **TTSConfig**: 配置测试 (2个)
- **TTSData**: 数据结构测试 (2个)
- **TTSBatchResult**: 批量结果测试 (3个)
- **TTSStatus**: 状态枚举测试 (4个)
- **BaseTTS**: 基类功能测试 (5个)
- **SiliconFlowTTS**: SiliconFlow TTS 测试 (3个)
- **OpenAITTS**: OpenAI TTS 测试 (5个)
- **OpenAIFmTTS**: OpenAI.fm TTS 测试 (10个)

## 集成测试 (test_tts_integration.py)

### 步骤 1: 配置环境变量

创建或编辑项目根目录的 `.env` 文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件，取消注释并填入以下配置：

```bash
# SiliconFlow TTS 配置（需要 API Key）
OPENAI_TTS_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_TTS_API_KEY=sk-your-key-here
OPENAI_TTS_MODEL=FunAudioLLM/CosyVoice2-0.5B
OPENAI_TTS_VOICE=FunAudioLLM/CosyVoice2-0.5B:alex

# OpenAI TTS 配置（需要 OpenAI API Key）
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-your-openai-key
OPENAI_TTS_MODEL_NAME=tts-1  # 或 tts-1-hd
```

### 步骤 2: 安装依赖

```bash
uv sync --all-extras
```

### 步骤 3: 运行测试

```bash
# 运行所有集成测试
pytest tests/test_tts/test_tts_integration.py -v

# 运行 SiliconFlow 测试
pytest tests/test_tts/test_tts_integration.py::TestSiliconFlowIntegration -v

# 运行 OpenAI TTS 测试
pytest tests/test_tts/test_tts_integration.py::TestOpenAITTSIntegration -v

# 运行 OpenAI.fm 测试（免费，无需 API Key）
pytest tests/test_tts/test_tts_integration.py::TestOpenAIFmIntegration -v
```

### 测试覆盖 (共6个测试)

#### TestSiliconFlowIntegration (2个测试)

- `test_siliconflow_single_synthesis` - 单条语音合成
- `test_siliconflow_batch_synthesis` - 批量语音合成（带进度回调）

#### TestOpenAITTSIntegration (2个测试)

- `test_openai_single_synthesis` - 单条语音合成
- `test_openai_batch_synthesis` - 批量语音合成（带进度回调）

#### TestOpenAIFmIntegration (2个测试)

- `test_openai_fm_single_synthesis` - 单条语音合成
- `test_openai_fm_batch_synthesis` - 批量语音合成（带进度回调）

## 注意事项

### 集成测试跳过机制

- SiliconFlow 测试：如果缺少 `OPENAI_TTS_API_KEY` 会自动跳过
- OpenAI TTS 测试：如果缺少 `OPENAI_API_KEY` 会自动跳过
- OpenAI.fm 测试：免费服务，无需 API Key，但可能有限流

### API 限流

- OpenAI.fm 可能会返回 403 Forbidden（超出限流）
- 建议测试时添加适当的延迟
- 批量测试时注意 API 调用频率

### 缓存测试

- 所有 TTS 服务支持缓存功能
- 缓存默认 TTL: 2天
- 使用 `use_cache=True` 参数启用缓存

## 开发指南

### 添加新的 TTS Provider

1. 在 `app/core/tts/` 创建新的 provider 类
2. 继承 `BaseTTS` 并实现 `_synthesize()` 方法
3. 在 `test_tts_core.py` 添加单元测试
4. 在 `test_tts_integration.py` 添加集成测试（2个测试：single + batch）

### 测试模式

```python
# 单元测试：使用 Mock
@patch("requests.post")
def test_my_tts(mock_post):
    mock_post.return_value = Mock(status_code=200)
    # ...

# 集成测试：真实 API 调用
def test_my_tts_integration(my_config):
    tts = MyTTS(my_config)
    result = tts.synthesize("test", "output.mp3")
    assert result.audio_path == "output.mp3"
```

## 故障排查

### 测试失败常见原因

1. **API Key 错误**: 检查 `.env` 文件配置
2. **网络问题**: 确保可以访问 API 端点
3. **限流**: OpenAI.fm 免费服务可能限流，稍后重试
4. **文件权限**: 确保临时目录可写

### 查看详细日志

```bash
# 显示详细输出
pytest tests/test_tts/test_tts_integration.py -v -s

# 显示完整错误堆栈
pytest tests/test_tts/test_tts_integration.py -v --tb=long
```
