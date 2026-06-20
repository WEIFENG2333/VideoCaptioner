"""实时转录后端（无 Qt）。

- ``base``：:class:`LiveTranscriber` 抽象 + 音频契约常量（SAMPLE_RATE 等）+ 回调类型。
- ``voxgate`` / ``fun_asr`` / ``qwen_asr``：三个具体后端，各自连接、按句切分、回调统一协议。
- ``languages``：每个 provider 支持的识别语言（单一事实来源）。

刻意不在此处 re-export 各后端类：工厂只在 ``build_backend`` 命中对应 ``cfg.backend`` 分支时才
import 走 WS 的 fun-asr / qwen-asr，避免未用到的后端把 ``websocket`` 拉进启动路径（voxgate 走子进程、
不依赖 websocket，故由工厂顶部直接 import）。需要哪个后端就从对应子模块直接 import。
"""
