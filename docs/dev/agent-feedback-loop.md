# Agent 反馈循环与验收规范

本文档定义 Agent 在 VideoCaptioner 中完成一次开发任务后的反馈循环。目标不是把测试做成形式，而是让每次改动都能被实际运行、实际点击、实际观察，并留下足够清楚的验收记录。

VideoCaptioner 同时有 CLI 和桌面 UI。底层能力、流程编排、配置、音视频处理、TTS/ASR/LLM 接入等改动，必须优先用 CLI 做可重复验证；页面、交互、布局、设置项、错误提示等改动，必须实际打开 UI、点击、截图、审查。

## 基本原则

1. 先确认改动影响面，再选择验收范围。
2. 先跑低成本、可重复的 CLI/单元测试，再跑耗时或需要网络/API 的真实流程。
3. UI 改动不能只靠代码审查，必须截图观察。
4. 截图必须保存在 `screenshots/<task-name>/` 下，命名要能看出页面、状态和轮次。
5. 每张截图至少主动指出 2 个问题；如果使用 subagent 审查，必须记录 subagent 的主要批评和处理结果。
6. 不要把测试产物、截图、临时音视频、API Key 提交到仓库，除非用户明确要求。
7. 用户要求“整体验收”时，不能只验局部；大重构也默认进入整体验收。
8. 用户只要求局部修改时，至少验该模块的直接功能、相邻入口和回归风险点。
9. 验收失败不应该被包装成“已完成”。要说明失败点、复现步骤、影响范围和下一步。
10. Agent 的最终回复必须写清楚实际运行过什么，而不是笼统说“已测试”。

## 验收分级

### Level 0：静态与快速反馈

适用场景：

- 文档改动。
- 小范围纯 Python 改动。
- 参数命名、配置映射、错误文案等低风险改动。

最低要求：

```bash
uv run python -m py_compile <changed-python-files>
uv run ruff check <changed-python-files>
```

如果改动涉及 CLI 参数、配置、解析器，还要跑：

```bash
uv run pytest tests/test_cli -q
uv run videocaptioner --help
uv run videocaptioner <command> --help
```

通过标准：

- 命令退出码为 0。
- 没有新增 traceback。
- CLI help 中用户关心的参数能看懂，高级/内部参数不应无必要暴露。
- 错误文案能告诉用户哪里错、影响什么、下一步怎么做。

### Level 1：模块功能反馈

适用场景：

- 修改单个 CLI 命令。
- 修改配音、字幕、翻译、ASR、下载、合成中的一个模块。
- 修改设置项或配置加载。
- 修复一个明确 bug。

最低要求：

1. 跑该模块对应测试。
2. 跑一条真实或接近真实的 CLI 命令。
3. 检查输出文件是否存在、大小是否合理、格式是否正确。
4. 检查错误路径：缺文件、缺 key、缺依赖、非法参数时是否有清楚提示。

示例：

```bash
uv run pytest tests/test_dubbing tests/test_tts -q
uv run videocaptioner doctor --json
```

配音局部验收示例：

```bash
cat > /tmp/vc-dub-sample.srt <<'EOF'
1
00:00:00,000 --> 00:00:01,200
你好，这是验收测试。

2
00:00:01,300 --> 00:00:02,600
我们正在检查配音流程。
EOF

uv run videocaptioner dub /tmp/vc-dub-sample.srt \
  --preset edge-cn-female \
  -o /tmp/vc-dub-sample.wav

ffprobe -hide_banner /tmp/vc-dub-sample.wav
```

通过标准：

- 输出音频存在且非空。
- 音频时长与字幕整体时长合理接近。
- 无截断、无空文件、无明显异常静音。
- 缺 API Key 的 provider 给出明确错误，不应刷重复 traceback。

### Level 2：页面反馈

适用场景：

- 修改 UI 页面、组件、布局、交互、设置页。
- 修改会影响用户操作路径的功能。
- 修改主窗口导航或页面之间跳转。

最低要求：

1. 实际实例化相关页面。
2. 实际点击主要按钮、开关、下拉、输入框。
3. 截图至少包含默认态、操作后状态、错误态或空态。
4. 每张截图至少列出 2 个问题并修复明显问题。
5. 如果用户对 UI 质量要求较高，必须用空白上下文 subagent 做严格审查。

推荐截图目录：

```text
screenshots/<task-name>/
  01-home-default.png
  02-synthesis-output-selected.png
  03-dubbing-provider-edge.png
  04-dubbing-provider-siliconflow-missing-key.png
  05-doctor-running.png
  06-doctor-finished.png
```

UI 截图检查维度：

- 页面第一眼是否知道这是做什么的。
- 是否有明确主操作。
- 禁用按钮是否说明原因。
- 空状态是否告诉用户下一步。
- 文字是否重叠、截断、溢出。
- 按钮文字、标题、标签字号是否统一。
- 浅色/深色主题是否都能读。
- 是否出现黑底白卡、白底白字、低对比度、像页面坏了的状态。
- 控件是否符合 qfluentwidgets 风格，避免原生 PyQt 拼凑感。
- 一页内是否存在过多同等级绿色按钮。
- 是否把 API Key、模型名、ffmpeg 等技术词过早暴露给普通用户。
- 页面是否有大面积无意义空白。
- 页面是否有“这里一坨、那里一坨”的割裂布局。

### Level 3：整体验收

适用场景：

- 大重构。
- 改动跨 CLI、core、UI 多层。
- 改动任务流程、配置系统、打包发布、音视频核心路径。
- 用户明确要求“完整跑一遍”“确保可用”。

最低要求：

1. Level 0 全部通过。
2. 相关模块测试通过。
3. `doctor --json` 通过或警告可解释。
4. 至少一个 CLI 端到端流程通过。
5. 至少一个 UI 流程通过。
6. 首页、设置、诊断、受影响页面截图审查。
7. 输出文件人工检查。
8. 记录所有失败、跳过和外部依赖限制。

整体验收建议命令：

```bash
uv run videocaptioner --help
uv run videocaptioner doctor --json
uv run pytest tests/test_cli -q
uv run pytest tests/test_dubbing tests/test_tts -q
uv run pytest tests/test_subtitle tests/test_translate tests/test_split -q
```

如果改动涉及 GUI：

```bash
QT_QPA_PLATFORM=offscreen uv run python - <<'PY'
import sys
from PyQt5.QtWidgets import QApplication
from videocaptioner.ui.view.task_creation_interface import TaskCreationInterface
from videocaptioner.ui.view.video_synthesis_interface import VideoSynthesisInterface
from videocaptioner.ui.view.dubbing_interface import DubbingInterface
from videocaptioner.ui.view.doctor_interface import DoctorInterface

app = QApplication(sys.argv)
for cls in [TaskCreationInterface, VideoSynthesisInterface, DubbingInterface, DoctorInterface]:
    w = cls()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    print(cls.__name__, "ok")
    w.close()
PY
```

注意：offscreen 截图只能用于结构和基本渲染检查，不能替代真实桌面观察。最终 UI 质量仍要看主窗口实际截图。

## CLI 验收标准

### 通用 CLI

每次涉及 CLI 的改动至少检查：

```bash
uv run videocaptioner --help
uv run videocaptioner <command> --help
```

检查点：

- 命令名称是否清晰。
- 必填参数是否明确。
- 高级参数是否被隐藏或降级。
- 错误参数是否有明确错误。
- 默认值是否符合普通用户预期。
- 配置优先级是否仍是：命令行参数 > 环境变量 > 配置文件 > 默认值。

### doctor

基础检查：

```bash
uv run videocaptioner doctor
uv run videocaptioner doctor --json
```

深度检查：

```bash
uv run videocaptioner doctor --check-api
```

检查点：

- JSON 可被 `python -m json.tool` 解析。
- 每个 check 有 name/status/message/fix。
- status 只能是 ok/warn/error 等约定值。
- 缺 key 是 warn 还是 error 要合理。
- 深度诊断需要真实请求 API 时必须提示可能产生费用。
- 诊断结果要能映射到 UI：问题、影响、下一步。

### config

涉及配置时检查：

```bash
uv run videocaptioner config show
uv run videocaptioner config path
uv run videocaptioner config init --print-template
```

检查点：

- 默认配置可用。
- 非交互模式对 Agent/CI 友好。
- 用户每视频都会变化的参数不要放成全局 onboarding 默认项。
- API Key、Base URL、模型、provider 能配置。
- 配置文件缺失时有创建提示。

### download

涉及下载时检查：

```bash
uv run videocaptioner download "<test-url>" -o /tmp/vc-download-test
```

检查点：

- 网络失败、cookie 缺失、yt-dlp 过旧时有明确提示。
- 输出目录可找到下载结果。
- 不应把下载中间错误吞掉。

在线视频可能受网络、cookie、地区限制影响。失败时要区分：

- URL 无效。
- cookie 缺失。
- yt-dlp 版本旧。
- 网络不可达。
- 站点限制。

### transcribe

涉及 ASR 时检查：

```bash
uv run videocaptioner transcribe tests/fixtures/audio/zh.mp3 --asr bijian -o /tmp/vc-transcribe.srt
```

如果使用本地模型或 API：

- 本地模型缺失要提示下载或切换 ASR。
- API Key 缺失要提示设置位置。
- 输出字幕要非空、有时间轴、有文本。

### subtitle

涉及字幕优化/翻译/断句时检查：

```bash
uv run videocaptioner subtitle tests/fixtures/subtitle/sample_en.srt \
  --translator bing \
  --target-language zh-Hans \
  -o /tmp/vc-subtitle.srt
```

检查点：

- 输出格式正确。
- 时间轴不乱。
- 文本不为空。
- 双语/单语布局符合设置。
- 大模型不可用时有降级或明确错误。

### dub

涉及配音时检查：

```bash
uv run videocaptioner dub tests/fixtures/subtitle/sample_en.srt \
  --preset edge-en-female \
  -o /tmp/vc-dub.wav
```

如果测试中文：

```bash
uv run videocaptioner dub tests/fixtures/audio/zh.srt \
  --preset edge-cn-female \
  -o /tmp/vc-dub-cn.wav
```

检查点：

- Edge 默认免 Key 可跑。
- Gemini/SiliconFlow 缺 Key 时错误清楚。
- 生成音频存在且可被 ffprobe 读取。
- 并发参数不导致乱序、漏句。
- 较长句子不会明显截断。
- 多说话人字幕格式仍能解析。

### synthesize

涉及视频合成时检查：

```bash
uv run videocaptioner synthesize <video.mp4> \
  -s <subtitle.srt> \
  --subtitle-mode hard \
  -o /tmp/vc-captioned.mp4
```

检查点：

- 输出视频存在。
- ffprobe 可读。
- 软字幕/硬字幕模式符合选择。
- 字幕样式、圆角背景、ASS 渲染没有崩。
- 缺视频、缺字幕时错误清楚。

### process

全流程 CLI：

```bash
uv run videocaptioner process <video.mp4> \
  --asr bijian \
  --translator bing \
  --target-language zh-Hans \
  --with-dubbing \
  --dub-preset edge-cn-female
```

检查点：

- 输出目录可找到最终结果。
- 中间字幕、翻译字幕、配音音频、最终视频命名清楚。
- 用户能知道失败发生在哪一步。
- 如果只生成部分结果，日志要说明。

## UI 验收标准

UI 验收不能只看是否启动。必须实际操作、截图、审查。

### 通用 UI 启动

入口：

```bash
uv run videocaptioner gui
uv run videocaptioner-gui
uv run videocaptioner
```

检查点：

- 启动无 traceback。
- 主窗口标题正常。
- 左侧导航图标可见。
- 页面切换不卡死。
- 深色/浅色主题都可读。
- 关闭窗口后没有残留进程。

### 首页/任务创建

必须检查：

1. 默认态。
2. 输入在线视频 URL。
3. 选择本地文件。
4. 拖拽文件。
5. 无效 URL 或无效文件。

验收流程：

- 打开首页。
- 观察标题是否说明“导入视频，生成字幕与配音”。
- 输入框是否说明支持粘贴链接/拖拽文件。
- 空输入时主按钮应是选择文件。
- 有输入时主按钮应变成开始处理。
- 点击日志、帮助等次要入口不应抢主流程。

失败标准：

- 用户不知道怎么开始。
- 只有图标没有文字。
- 输入框像禁用。
- 选择文件后没有下一步。
- 错误 URL 没有清晰提示。

### 主页全流程步骤

主页内部步骤：

1. 任务创建。
2. 语音转录。
3. 字幕优化与翻译。
4. 字幕视频合成。

必须检查：

- 每一步完成后是否跳到下一步。
- 进度是否更新。
- 错误是否停在正确步骤。
- 用户能不能返回查看结果。
- 全流程 task_id 不应混乱。

### 语音转录页

检查点：

- 音频/视频输入显示正确。
- 音轨选择可用。
- 开始按钮可用/禁用状态合理。
- 进度条更新。
- 输出字幕路径可找到。
- 失败时显示原因。

### 字幕优化与翻译页

检查点：

- 字幕表格内容不截断。
- 单击字幕行能定位/预览。
- 开始优化/翻译按钮状态合理。
- 取消按钮可用。
- 双语/单语输出符合设置。
- LLM/API 缺 key 时提示清楚。
- 长字幕、空字幕、特殊字符不破坏布局。

### 字幕视频合成页

必须检查：

1. 默认无输出选择。
2. 只选字幕视频。
3. 只选配音音轨。
4. 字幕视频 + 配音音轨都选。
5. 输入字幕但不输入视频。
6. 输入视频但不输入字幕。
7. 打开音色库。
8. 试听当前音色。
9. 点击生成。

验收标准：

- 用户能看到“导出内容”。
- 禁用按钮说明原因。
- 只配音时，字幕必填，视频可选。
- 字幕视频时，字幕和视频都应必填。
- 配音 + 视频时，输出应说明最终成片和配音音频。
- 生成后进度条、状态和输出位置清楚。

失败标准：

- 用户不知道要先选字幕视频还是配音音轨。
- 顶部工具栏和主面板状态不同步。
- 生成按钮能点但立即报缺文件。
- 输出模式显示与实际输出不一致。
- 文字重叠或按钮过多抢主操作。

### 配音页

必须检查：

1. Edge provider。
2. Gemini provider。
3. SiliconFlow provider。
4. 内置试听。
5. 文本试听。
6. 缺 Key 状态。
7. 去设置填写 Key。
8. 音色切换。
9. 克隆区输入不完整。
10. 克隆区输入完整后试听克隆。

验收标准：

- 用户知道 `试听` 是播放样例。
- 用户知道 `使用` 是选择最终导出音色。
- 右侧显示最终会使用哪个音色。
- 内置试听不要求 API Key。
- 文本试听对非 Edge provider 要求 Key，并提示去哪里配置。
- 缺 Key 按钮不能是死按钮，应能跳设置或给明确提示。
- 克隆区说明参考音频和原文用途。
- 克隆区有明确下一步，比如 `试听克隆`。
- 播放失败不应刷重复 traceback。

失败标准：

- 音色卡片空白。
- 只有小图标没有文字。
- 当前选中态不明显。
- 缺 Key 用户不知道怎么解决。
- 克隆区填完后不知道点什么。
- 浅色主题出现黑底异常。

### 字幕样式页

必须检查：

- 样式列表显示。
- 选择样式后预览更新。
- 字体、颜色、描边、背景、位置修改后预览更新。
- 新建样式、打开样式目录可用。
- 长字幕预览不溢出。
- 竖屏/横屏背景都可预览。

失败标准：

- 预览图不更新。
- 控件值和配置不一致。
- 文字超出画面。
- 色彩对比不可读。

### 设置页

必须检查：

- 转录配置。
- LLM 配置。
- 翻译服务。
- 翻译与优化。
- 字幕合成配置。
- 配音配置。
- 保存配置。
- 个性化。
- 关于。

关键点击：

- 切换 ASR provider。
- 填写 API Base/API Key/Model。
- 测试 LLM 连接。
- 测试 Whisper 连接。
- 测试配音。
- 切换配音 provider。
- 选择配音音色。
- 修改配音并发。
- 修改缓存开关。
- 修改主题。

验收标准：

- Provider 先选，再显示该 provider 需要的字段。
- 不同 provider 的字段差异要清楚。
- 缺 key 时测试按钮给清楚提示。
- 设置后回到相关页面能同步。
- 用户每个视频都会变化的配置不应放在全局设置里。

### 诊断页

必须检查：

1. 初始态。
2. 自动快速检查中。
3. 快速检查完成。
4. 深度诊断点击前提示。
5. 深度诊断运行中。
6. 深度诊断完成。
7. 缺 key/缺依赖状态。

验收标准：

- 用户知道正在检查什么。
- 完成后知道哪些正常、哪些警告、哪些错误。
- 每个警告/错误要说明影响。
- 有下一步修复建议。
- 深度诊断说明会真实请求 API。
- 检查中不要使用成功色误导。
- 浅色/深色主题背景正常。

失败标准：

- 只有技术检查项，没有人话解释。
- 只有 ffmpeg/ffprobe 路径，用户不知道影响。
- 深度诊断按钮像禁用但不知道原因。
- 检查结果为空或一直检查中。

### 批量处理页

必须检查：

- 添加多个文件。
- 清空列表。
- 开始全部任务。
- 单个失败不阻塞其他任务。
- 每个任务状态、进度、输出清楚。
- 拖拽多个文件。

失败标准：

- 多任务状态串台。
- 清空后后台仍在跑。
- 失败没有定位到具体文件。

### 请求日志页

必须检查：

- 刷新日志。
- 清空日志。
- 翻页。
- 复制请求。
- 复制响应。
- 空日志状态。

失败标准：

- 日志包含完整 API Key。
- 大日志卡死。
- 复制按钮复制错内容。

## 全流程验收矩阵

### 本地媒体到字幕视频

输入：本地视频或音频。

流程：

1. 首页导入文件。
2. 转录生成字幕。
3. 字幕优化/翻译。
4. 合成字幕视频。
5. 打开输出目录。
6. ffprobe 检查最终视频。

检查：

- 输出视频存在。
- 字幕可见。
- 音频保留。
- 输出文件名清楚。

### 在线链接到字幕视频

输入：YouTube/Bilibili/TED 等链接。

流程：

1. 首页粘贴 URL。
2. 下载。
3. 转录或读取字幕。
4. 翻译/优化。
5. 合成。

检查：

- 下载失败时区分 cookie、网络、yt-dlp。
- 下载成功后文件位置清楚。
- 如果站点不可用，要记录原因，不要误判为功能失败。

### 字幕到配音音频

输入：SRT。

流程：

1. CLI 或合成页选择配音音轨。
2. 选择 Edge 音色。
3. 生成配音音频。
4. 播放检查。

检查：

- 输出 wav/mp3 存在。
- 无明显截断。
- 句子顺序正确。
- 时长合理。

### 视频 + 字幕到配音视频

输入：视频 + SRT。

流程：

1. 合成页选择配音音轨。
2. 输入字幕和视频。
3. 选择音色。
4. 生成。
5. 检查输出视频。

检查：

- 原声处理符合当前策略。
- 配音轨和画面大致同步。
- 输出音量合理。

### 外语视频到中文配音视频

流程：

1. 导入外语视频。
2. 转录。
3. 翻译为中文。
4. 选择中文配音音色。
5. 生成配音视频。

检查：

- 翻译字幕完整。
- 中文配音没有明显截断。
- 长句处理合理。
- 输出文件容易找到。

## subagent UI 审查规范

当用户要求 UI 美观、体验、截图审查，或 Agent 自己改动了 UI 页面时，应使用空白上下文 subagent。

subagent 输入：

- 只给最新截图。
- 不给“我已经修好了”这类暗示。
- 明确要求严厉批评。
- 要求按 P0/P1/P2 分级。
- 要求每页至少指出具体问题。

推荐 prompt：

```text
你是一个没有项目历史上下文的严格 UI/UX 审查员。请只根据这些截图审查界面实际效果，不要假设代码正确。目标用户是普通非技术用户。请指出布局、空白、层级、字体大小、颜色、按钮主次、组件是否低质、用户是否知道下一步、是否有多余文字、是否有信息缺失。每张图至少给具体批评，并按 P0/P1/P2 给整改优先级。不要安慰，不要泛泛而谈。
```

Agent 必须处理 subagent 的 P0。P1 根据范围和风险判断，不能完全忽略。最终回复中要说明：

- subagent 看了哪些截图。
- 提了哪些 P0。
- 已修哪些。
- 哪些暂不修，为什么。

## 截图规范

目录：

```text
screenshots/<task-or-date>/
```

命名：

```text
01-home-default.png
02-home-url-entered.png
03-synthesis-empty.png
04-synthesis-output-selected.png
05-dubbing-edge.png
06-dubbing-siliconflow-missing-key.png
07-doctor-running.png
08-doctor-finished.png
```

要求：

- 不要覆盖旧截图。
- 每轮改动用新的目录或后缀。
- 最终回复告诉用户截图路径。
- 截图默认不提交。

## 失败判定

以下任一情况视为验收失败：

- 命令 traceback。
- UI 页面无法打开。
- 点击主按钮无反应且无提示。
- 输出文件不存在或为空。
- 生成视频/音频 ffprobe 不可读。
- 缺 key/缺依赖提示不清楚。
- 用户不知道下一步。
- 文字重叠、截断、按钮文字溢出。
- 浅色/深色主题不可读。
- API Key 出现在日志、截图、提交或错误弹窗中。
- 页面看起来像未加载、禁用、调试面板。

失败时最终回复必须包含：

- 失败命令或点击路径。
- 失败现象。
- 可能原因。
- 已尝试的排查。
- 当前影响范围。
- 下一步建议。

## 验收记录模板

每次任务完成后，Agent 最终回复建议包含：

```text
改动范围：
- ...

CLI 验收：
- uv run ...：通过/失败
- 输出文件：...

UI 验收：
- 截图目录：screenshots/...
- 点击路径：...
- 发现并修复的问题：...

subagent 审查：
- 使用/未使用，原因：
- P0：
- 处理结果：

未覆盖/跳过：
- ...

当前风险：
- ...
```

## 本文档编写时的实测基线

本文档编写时，以下命令已在当前项目中实际运行：

```bash
uv run videocaptioner --help
uv run videocaptioner doctor --json
uv run pytest tests/test_cli tests/test_dubbing tests/test_tts -q
```

结果：

- CLI help 正常列出 transcribe/gui/subtitle/dub/synthesize/process/download/config/doctor/style。
- `doctor --json` 可输出结构化检查结果。
- `tests/test_cli tests/test_dubbing tests/test_tts`：102 passed，4 skipped，1 warning。
- Edge 配音小样可生成非空 wav。

因此后续 Agent 可以把这些命令作为低成本基线，但具体任务仍要按影响面增加相应验收。
