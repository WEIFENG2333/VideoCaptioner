view/  目录结构：用户界面 (UI) 模块

下面是本软件的主要页面结构，方便开发者查看和修改。

```
├── main_window.py  ------------------  主窗口 (FluentWindow 外壳与导航)
│   │
│   └── 导航页面:
│       ├── home_interface.py -------- 主页 (工作流标签容器)
│       │   │
│       │   └── 包含以下工作流页面:
│       │       ├── task_creation_interface.py - 任务创建 (本地文件 / 链接下载)
│       │       ├── transcription_interface.py - 语音转录
│       │       ├── subtitle_interface.py ------ 字幕优化与翻译
│       │       └── video_synthesis_interface.py - 字幕视频合成
│       │
│       ├── batch_process_interface.py ------- 批量处理
│       ├── subtitle_style_interface.py ------ 字幕样式
│       ├── dubbing_interface.py ------------- 配音 (音色库与试听)
│       ├── llm_logs_interface.py ------------ 请求日志
│       ├── doctor_interface.py -------------- 诊断
│       └── setting_interface.py ------------- 设置 (全屏 chrome)
│
├── log_window.py -------------------- 日志窗口 (task_creation 的「查看日志」入口)
```

配套层次：

- `ui/components/workbench.py`：工作流页面共用的设计语言组件。
- `ui/components/app_dialog.py`：弹窗壳 `AppDialog` + 确认框 `ConfirmDialog`，
  应用内所有弹窗的统一基座（强制基于整个程序窗口居中）。
- `ui/components/model_manager_dialog.py`：本地模型管理弹窗（设置页入口）。
- `ui/thread/`：页面后台线程（`worker.py` 统一基类，协作式取消）。
