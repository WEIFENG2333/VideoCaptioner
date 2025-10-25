# 贡献指南

感谢你对 VideoCaptioner 的贡献！

## 开发环境设置

1. Fork 本仓库
2. 克隆你的 Fork
3. 安装开发依赖

```bash
git clone https://github.com/YOUR_USERNAME/VideoCaptioner.git
cd VideoCaptioner
pip install -r requirements.txt
```

## 代码规范

- 使用 `pyright` 进行类型检查
- 使用 `ruff` 进行代码格式化

```bash
# 类型检查
uv run pyright

# 代码格式化
uv run ruff check --select I --fix .
```

## 提交 Pull Request

1. 创建新分支
2. 提交你的修改
3. 推送到你的 Fork
4. 创建 Pull Request

## 注释要求

保持简洁清晰，只需要必要的注释即可。

---

相关文档：
- [架构设计](/dev/architecture)
- [API 文档](/dev/api)

更多信息请参考 [GitHub Issues](https://github.com/WEIFENG2333/VideoCaptioner/issues)。
