# 常见问题

常见问题解答。

## 安装问题

### Q: 如何安装依赖？

A: 参考[快速开始](/guide/getting-started)中的安装步骤。

## 使用问题

### Q: 转录时出现幻觉或重复怎么办？

A: 
- 启用 VAD 过滤
- 更换更大的模型
- 尝试 Large-v2 而不是 Large-v3
- 在嘈杂环境中启用音频分离

### Q: LLM 请求失败怎么办？

A:
- 检查 API Key 是否正确
- 检查 Base URL 是否正确
- 降低线程数
- 检查网络连接
- 查看日志文件获取详细错误信息

### Q: 下载 YouTube 视频报错 "Requested format is not available" 怎么办？

A: 这是软件自带的 yt-dlp 版本过旧导致的。YouTube 会不断更新播放器签名算法，旧版 yt-dlp 无法提取到真实的视频/音频流，只剩缩略图格式，因此报"请求的格式不可用"。解决方法是在**程序实际使用的 Python 环境**中升级 yt-dlp：

- **安装版**：在软件安装目录下执行：

  ```powershell
  .\runtime\python.exe -m pip install -U yt-dlp
  ```

- **源码安装**：激活项目的 Python 虚拟环境后执行：

  ```bash
  pip install -U yt-dlp
  ```

升级后重启软件即可正常下载。注意不要升级到系统或其他环境的 Python 中，那样对软件不生效。

如果升级后提示 "Sign in to confirm you're not a bot"，说明 YouTube 要求登录验证：用浏览器扩展（如 "Get cookies.txt LOCALLY"）导出 YouTube 的 cookies，保存为软件目录下的 `AppData/cookies.txt`，软件会自动读取。

更多问题，请访问 [GitHub Issues](https://github.com/WEIFENG2333/VideoCaptioner/issues)。
