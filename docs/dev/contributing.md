# 贡献指南

感谢你对 VideoCaptioner 的贡献！

## 开发环境设置

1. Fork 本仓库并克隆你的 Fork
2. 使用 [uv](https://docs.astral.sh/uv/) 安装依赖并运行

```bash
git clone https://github.com/YOUR_USERNAME/VideoCaptioner.git
cd VideoCaptioner
uv sync
uv run videocaptioner          # 运行 GUI
uv run videocaptioner --help   # 运行 CLI
```

## 代码检查与测试

```bash
uv run ruff check videocaptioner tests scripts   # 代码检查
uv run pyright                                    # 类型检查
uv run pytest tests/test_cli tests/test_application -q   # 快速测试
```

UI 改动请附带冒烟截图验证：

```bash
uv run python scripts/ui_smoke_check.py /tmp/vc-ui-check --theme dark
```

## 提交 Pull Request

1. 创建新分支
2. 提交你的修改（UI 改动附截图，运行时改动附测试或日志证据）
3. 推送到你的 Fork 并创建 Pull Request

## 注释要求

保持简洁清晰，只写必要的注释（解释"为什么"，而不是复述代码）。

---

相关文档：
- [架构设计](/dev/architecture)
- [API 文档](/dev/api)

更多信息请参考 [GitHub Issues](https://github.com/WEIFENG2333/VideoCaptioner/issues)。
