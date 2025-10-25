# API 文档

核心 API 接口文档。

## ASR API

### `transcribe()`

```python
from app.core.asr import transcribe

result = transcribe(
    audio_path="video.mp4",
    config=TranscribeConfig(...)
)
```

## 字幕处理 API

待补充...

## 翻译 API

待补充...

---

详细 API 说明请参考源代码和 `CLAUDE.md` 文档。

相关文档：
- [架构设计](/dev/architecture)
- [贡献指南](/dev/contributing)
