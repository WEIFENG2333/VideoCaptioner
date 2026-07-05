# 打包与自动更新：现状评估 + 改造方案

> 调研日期 2026-06-22（5 维并行调研 + 真机实测交叉验证）。本文回答：现在还能不能打包/打出来能不能用、
> 单文件是否可行、目录设计是否合理、更新机制怎么重构成自动更新。两块强关联（打包形态决定更新落地方式、
> macOS 签名/公证既是「易安装」也是「自更新不被拦」的前提），一并给方案。

> **实现状态（2026-06-22）**：打包缺口已修（spec collect OCR/onnxruntime、CI `--extra ocr`、smoke 校验
> bundled 负载，mac 真打包实测 OCR/下载/实时字幕可用）。自动更新已落地为 `core/update`（manifest + 下载
> sha256 校验 + 退出后 helper 换装重启）+ 应用内「更新提示条」+ 设置页「检查更新」+ 实时公告 + CI
> `latest.json` 生成；旧 `vc.bkfeng.top` 轮询已删。
>
> **安装形态已补（2026-06-22）**：Windows 出 Inno Setup `Setup.exe`（`packaging/windows/VideoCaptioner.iss`
> + `scripts/build_windows_installer.py`，per-user 装到 `%LOCALAPPDATA%\Programs` → 自更新照常）；macOS 出
> 拖拽安装 `.dmg`（`scripts/build_macos_dmg.py`，ad-hoc 签名规避「已损坏」硬拦截）。便携 zip 仍是自动更新
> 下载源。**无 Apple 付费证书 → macOS 首次打开仍需右键→打开**（消除提示需证书 + 公证，本项目暂不做）。
> 架构索引见 `AGENTS.md` 的「Software Update」；下文为设计依据，按需查阅。

## 一、打包现状

PyInstaller **onedir**：`scripts/build_desktop.py` 驱动 `VideoCaptioner.spec` → `dist/VideoCaptioner/`（含 `_internal/`），
macOS 经 `BUNDLE` 另出 `.app` + zip。
- ffmpeg/ffprobe 由 `static-ffmpeg` 按平台下载（应用探测统一走 `ffmpeg -i`；ffprobe 仅为 pydub 配音链路保留）、`macsysaudio`(swift) 现编，staged 进 `RUNTIME_DIR/resource/bin` → spec 收进 `resource/bin`。
- datas 收 `resource/{assets,fonts,subtitle_styles,i18n}` + `core/prompts`；版本来自 git tag（hatch-vcs→`_version.py`）。
- CI `.github/workflows/build-desktop.yml`：tag `v*` 触发，矩阵 = **Windows x64 + macOS Intel(x86_64)**，`uv sync --frozen` → `uv run --with pyinstaller --with static-ffmpeg python scripts/build_desktop.py` → `gh release upload`。
- **零签名零公证**（spec `codesign_identity=None`）。

## 二、「加了新东西后还能打包/能用吗」——缺口清单

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | **硬字幕 OCR** | 🔴 包里不可用 | CI `uv sync --frozen` **不带 `--extra ocr`** → onnxruntime/rapidocr/rapidfuzz 根本不进构建环境；且 spec 未 `collect_data_files('rapidocr')`（config.yaml + 自带 8 个 PP-OCR `.onnx` ~46M）/`collect_dynamic_libs('onnxruntime')`。用户点硬字幕 → 「缺少 OCR 引擎依赖」，frozen 包无 pip 无法自救。**功能上线即坏。** |
| 2 | **voxgate 二进制** | 🟡 不随包 | build 只 stage ffmpeg+macsysaudio，voxgate 没收。实时字幕 voxgate 后端首启无引擎——但有运行时下载兜底（设置/诊断页点「下载」，`dependencies.py` 已注册）。fun-asr/qwen-asr 走 websocket 不受影响。 |
| 3 | **yt-dlp extractor** | 🟡 风险 | 943 个 extractor 动态加载，spec 仅 `hiddenimports=['yt_dlp']`、未 `collect_submodules('yt_dlp')` → 包里下载可能报 extractor 缺失。需真包验证。 |
| 4 | **opencv full** | 🟡 隐患 | 装的是 `opencv-python`(119M, 自带 Qt) 而非 pyproject 注释建议的 `opencv-python-headless`；体积大 + 可能与 PyQt5 的 Qt 冲突。 |
| 5 | **smoke 不覆盖新功能** | 🟡 | `smoke_desktop.py` 只测 version/style/doctor/synthesize；不验 OCR/sounddevice/voxgate/i18n → 所以 OCR 全缺 CI 也绿，缺陷潜伏。 |
| ✅ | i18n / sounddevice(PortAudio) / onnxruntime 原生库 / numpy / edge_tts / yt_dlp 纯 py / qfluentwidgets / 字体 | OK | 标准 hook / 现有 collect_submodules 覆盖（前提：依赖在构建环境里）。 |

**修复清单（让 onedir 包真能用）**
1. `build-desktop.yml`：`uv sync --frozen` → `uv sync --frozen --extra ocr`。
2. `VideoCaptioner.spec` 顶部 `from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules`，并补：
   - `datas += collect_data_files('rapidocr')`（yaml + 自带 onnx 模型；或决定走运行时下载模型以省 46M）
   - `binaries += collect_dynamic_libs('onnxruntime')`
   - `hiddenimports += collect_submodules('yt_dlp')`
   - `hiddenimports += ['onnxruntime','rapidocr','rapidfuzz','sounddevice','_sounddevice_data','cffi','_cffi_backend','websocket']`
3. `opencv-python` → `opencv-python-headless`（pyproject `ocr` extra 改）。
4. voxgate：二选一——发布前把各平台预编译 voxgate stage 进 `RUNTIME_DIR/resource/bin`（与 ffmpeg 同模式 + `verify_bundle` 软校验）；或接受「实时字幕首次用需下载引擎」写进发布说明。
5. `smoke_desktop.py` / `verify_bundle` 增：`import sounddevice` 烟测、（若随包）OCR/voxgate 存在校验。
6. 体积预期：onnxruntime ~68M + rapidocr 模型 ~46M + opencv → 包数百 MB；可接受或改运行时下载模型。
7. CI 矩阵建议加 `macos-14`(arm64)，给 Apple Silicon 原生包。
8. `pyproject.toml:53-54` 注释「模型首次从 ModelScope 下载」已过期（rapidocr 3.x 自带模型）——同步修。

## 三、单文件可行性

**结论：不推荐做成单文件 exe / 单 Mach-O。**
- **Windows onefile**：每次启动把整包（PyQt5 + 可能的 onnxruntime + ffmpeg + 字体）解压到 `%TEMP%` → 冷启动慢、临时盘翻倍、PyInstaller 自解压壳是 Defender/国产杀软**误报重灾区**；且 `_MEIPASS` 是每次新建/退出清理的临时目录，破坏「自带 bin」稳定性。
- **macOS 单 Mach-O**：Gatekeeper 不认、无法装订公证、双击被拦——mac「双击即用」的本质是**签名+公证的 `.app`/`.dmg`**，不是单文件。

**推荐形态（= 用户要的「单文件般轻松安装」）**
- **Windows**：维持 onedir + **Inno Setup**（或 NSIS）打成**单个 `.exe` 安装包**。用户感知就是「下一个文件、装好即用」，但运行时是解压好的目录 → 无 onefile 的解压/误报/启动慢。
- **macOS**：维持 `.app` + **Developer ID 签名 + 公证(notarytool) + 装订(stapler)** → 出 **`.dmg`**。这才是 mac 标准易装形态。

## 四、目录设计是否合理

**基本合理，无需大改。** `config.py` 已正确分层：
- **可写用户态**（`APPDATA` 的 cache/log/work/model/bin、`WORK_PATH`）全走 `platformdirs`，**不在包内** → onedir / onefile / .app 三形态都成立（模型、下载的 ffmpeg/voxgate、日志都写得进）。
- **只读资源**（`resource/*`）frozen 下走 `_MEIPASS/resource` → onedir/.app 稳定。
- **唯一注意点**：`BUNDLED_BIN_PATH = _MEIPASS/resource/bin` 仅在 **onedir** 下是稳定路径；onefile 下它是临时目录（每次变/被清）→ 又一个不该用 onefile 的理由。维持 onedir 则此设计无需改；规约里写明「自带 bin 仅 onedir 稳定，禁 onefile」。

## 五、更新机制现状

`version_checker_thread.py` 后台 GET `https://vc.bkfeng.top/api/version`（作者私有域名）→ `QVersionNumber` 比较 →
`main_window.onNewVersion` 弹框 → 点「立即更新」只 `QDesktopServices.openUrl(download_url)` **开浏览器**让用户手动下载重装。

问题：
- 只通知不下载、**无应用内安装**、**无 sha/签名校验**、单 `download_url` 不分平台/架构。
- 源是私有自建域名（单点不可控，失效=全员收不到更新；被劫持则 openUrl 无防护）。
- dev 版 `VERSION=0.0.0-dev` 被判永远过期 → 开发期每次误弹。
- 强制更新只禁 home/batch 两页、仍只能跳浏览器，半禁用可绕过。
- 与产物形态脱节（onedir/.app zip，无增量、无原地更新、无回滚）。

## 六、更新重构方案（自动后台下载 + 应用内一键安装）

**核心优势：项目已有可复用基建**，自更新 90% 是它们的组合，**不必引入 Sparkle/velopack/tufup**（且 mac 零签名，那些框架依赖签名生态）：
- `core/download/downloader.py`：多镜像兜底 + Range 续传 + 校验 + 进度 + 取消。
- `core/download/dependencies.py`：os×arch 矩阵 + GitHub Release + ghproxy 镜像 + 解压落地。
- GitHub Release 发布管线已就绪。

**设计**
1. **manifest** `latest.json` 挂在 GitHub Release（与资产同源、天然可回滚）：
   ```json
   {"version":"1.5.0","pub_date":"...","notes":"...","mandatory":false,"min_supported":"1.0.0",
    "platforms":{"windows-x64":{"url":"...","sha256":"...","size":123,"kind":"onedir-zip"},
                 "macos-x64":{"url":"...","sha256":"...","kind":"app-zip"},
                 "macos-arm64":{"...回落 x64 或原生..."}}}
   ```
   CI 在 `archive()` 后用脚本算 sha256/size 自动生成并 `gh release upload`。
2. **客户端**：`VersionChecker` 改拉 manifest → 比版本 → 后台 QThread 复用 `download_file` 静默下载本平台 zip 到 `CACHE/updates`（sha256 校验 + 进度 + 取消）→ UI 按钮态 **「更新可用 → 下载中(进度) → 重启并安装」**（复用 `ConfirmDialog`/`InfoBar`/线程薄壳）。
3. **应用阶段**（onedir → 「替换 + 重启」，运行中不能原地覆盖自身）：
   - **Windows**：解压到临时目录 → 写 helper `.cmd`（等主进程退出 → `robocopy` 换 `_internal`+exe → 重启）→ `QApplication.quit()`。
   - **macOS**：解压 `-app.zip` → `xattr -dr com.apple.quarantine` 新 `.app` → 替换原 `.app`（以当前运行可执行实际路径为基准）→ 重启。
4. 配套：`downloader` 加 sha256 分支；dev 版跳过检查；`onNewVersion` 删「跳浏览器」改 manifest 流程；公告 `expire` 语义核对；强制更新给下载进度 + 失败退路。

**分阶段**
- **MVP**：manifest + per-platform 下载 + sha256 + 「重启并安装」（Win 批处理换目录 / mac 解压换 .app + 清 quarantine）。
- **完善**：失败回滚（换前备份旧目录，新版自检失败则还原）、强制更新打磨、CI 加 macos-arm64、申请 Apple 签名+公证（彻底解决 Gatekeeper/quarantine，mac 自更新长期正解）、视体积上增量(zsync/bsdiff)。
- **先不要**：Sparkle/velopack/tufup（与现状打包/签名形态错配）；改 onefile（牺牲 onedir 可增量替换 + 现有 verify）。

## 七、关键风险
- macOS 零签名零公证：自更新替换后的新 `.app` 带 `com.apple.quarantine` 可能被拦/打不开；MVP 必须替换后 `xattr -dr` 清除，长期正解是签名+公证。一旦公证，bundle 内 voxgate/macsysaudio/ffmpeg 也须一并签名（macsysaudio 还需 ScreenCaptureKit entitlement）。
- onedir 运行中无法原地覆盖：靠 helper 在主进程退出后替换+重启；helper 健壮性（中文/空格路径、权限、被杀）是失败高发区，需回滚兜底。
- 安装位置权限：Win 装 Program Files / mac 装 /Applications 替换需提权；以「当前运行可执行实际路径」为基准，不硬编码。
- Apple Silicon 当前无原生包（CI 只产 Intel）；manifest 的 macos-arm64 暂回落 Intel(Rosetta)。
- 更新源建议与资产同源（GitHub Release），避免「版本声明 vs 实际可下文件」不一致。
