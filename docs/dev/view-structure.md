view/  目录结构：用户界面 (UI) 模块 

下面是本软件的一个主要页面结构，方便开发者查看和修改。


```
├── main_window.py  ------------------  主窗口 (应用程序框架)
│   │
│   └── 
│       ├── home_interface.py -------- 主页窗口 (程序主界面，包含核心功能)
│       │   │
│       │   └── 包含以下子功能模块:
│       │       ├── task_creation_interface.py - 任务创建窗口
│       │       ├── transcription_interface.py - 语音转录窗口
│       │       ├── subtitle_interface.py -------- 字幕优化窗口
│       │       └── video_synthesis_interface.py - 视频合成窗口
│       │
│       ├── batch_process_interface.py ------- 批量处理窗口
│       ├── subtitle_style_interface.py ------ 字幕样式窗口
│       └── setting_interface.py -------------- 设置窗口
│
├── log_window.py -------------------- 日志窗口 (独立窗口，集成在 home_interface)

```