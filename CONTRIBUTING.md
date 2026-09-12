# Contributing to VideoCaptioner

完整贡献指南见在线文档：
https://weifeng2333.github.io/VideoCaptioner/dev/contributing

快速开始：

```bash
git clone https://github.com/YOUR_USERNAME/VideoCaptioner.git
cd VideoCaptioner
uv sync
uv run videocaptioner                                     # GUI
uv run ruff check videocaptioner tests scripts            # Lint
uv run pytest tests/test_cli tests/test_application -q    # Tests
```

开发约定（架构边界、UI 设计语言、测试标准）见仓库根目录的 `AGENTS.md`。
