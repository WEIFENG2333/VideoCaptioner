#!/usr/bin/env python3
"""VideoCaptioner UI 截图与冒烟检查工具。

两种典型用法：

1. 改完代码快速看效果（秒级，只截图、不跑断言）::

       # 只截某一页
       .venv/bin/python scripts/ui_smoke_check.py --pages dubbing
       # 截多页 + 浅色主题
       .venv/bin/python scripts/ui_smoke_check.py --pages home,subtitle --theme light
       # 全部页面截图（含设置子页），明暗两套一次出
       .venv/bin/python scripts/ui_smoke_check.py --shots-only --theme both
       # 查看可用页面名
       .venv/bin/python scripts/ui_smoke_check.py --list

2. 完整冒烟验收（截图 + 行为断言 + 紧凑窗口检查，CI / 验收用）::

       .venv/bin/python scripts/ui_smoke_check.py /tmp/vc-ui-check-dark --theme dark
       .venv/bin/python scripts/ui_smoke_check.py /tmp/vc-ui-check-light --theme light

约定：

- 指定 ``--pages`` 后自动进入"只截图"模式；设置页子页面写作
  ``setting-<key>``，例如 ``setting-dubbing``。
- 截图输出到 ``<output_dir>/<name>.png``，每张都会打印 ``shot=<路径>``，
  并生成 ``contact-sheet.png`` 缩略总览方便一眼扫完。
- 默认使用 offscreen 平台插件和隔离的临时 TOML 配置
  （``VIDEOCAPTIONER_CONFIG_FILE``），不会污染真实用户配置。
- 故意不启动 MainWindow：qframelesswindow 在 headless macOS 下可能直接
  abort，所以逐页单独构造 widget。主题初始化与 ``ui/main.py`` 保持一致
  （应用自有 ThemeMode -> qfluent Theme 的映射）。
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("/tmp/vc-ui-shots")

# ---------------------------------------------------------------------------
# 页面注册表：截图名 -> (模块路径, 类名)。
# 加新页面只需要在这里加一行，快速截图 / 完整冒烟 / contact sheet 都会带上。
# ---------------------------------------------------------------------------
PAGE_REGISTRY: dict[str, tuple[str, str]] = {
    "home": ("videocaptioner.ui.view.home_interface", "HomeInterface"),
    "task": ("videocaptioner.ui.view.task_creation_interface", "TaskCreationInterface"),
    "setting": ("videocaptioner.ui.view.setting_interface", "SettingInterface"),
    "dubbing": ("videocaptioner.ui.view.dubbing_interface", "DubbingInterface"),
    "live-caption": (
        "videocaptioner.ui.view.live_caption_interface",
        "LiveCaptionInterface",
    ),
    "video-synthesis": (
        "videocaptioner.ui.view.video_synthesis_interface",
        "VideoSynthesisInterface",
    ),
    "transcription": (
        "videocaptioner.ui.view.transcription_interface",
        "TranscriptionInterface",
    ),
    "subtitle": ("videocaptioner.ui.view.subtitle_interface", "SubtitleInterface"),
    "batch": ("videocaptioner.ui.view.batch_process_interface", "BatchProcessInterface"),
    "subtitle-style": (
        "videocaptioner.ui.view.subtitle_style_interface",
        "SubtitleStyleInterface",
    ),
    "doctor": ("videocaptioner.ui.view.doctor_interface", "DoctorInterface"),
    "llm-logs": ("videocaptioner.ui.view.llm_logs_interface", "LLMLogsInterface"),
}

# 设置页内部的子页 key（SettingInterface.setCurrentPage 的合法值）。
SETTING_PAGE_KEYS = [
    "transcribe",
    "llm",
    "translate-service",
    "translate",
    "subtitle",
    "dubbing",
    "live-caption",
    "save",
    "personal",
    "about",
]

PAGE_SIZE = (1280, 820)  # 常规截图窗口
COMPACT_SIZE = (960, 720)  # 紧凑窗口检查


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------


def _parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VideoCaptioner UI 截图与冒烟检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("约定：")[0],
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=None,
        help=f"截图输出目录（默认 {DEFAULT_OUTPUT_DIR}/<theme>）",
    )
    parser.add_argument(
        "--theme",
        choices=["dark", "light", "both"],
        default="dark",
        help="主题；both 会分别跑两个子进程，输出到 <output_dir>/dark 和 /light",
    )
    parser.add_argument(
        "--pages",
        default=None,
        metavar="NAME[,NAME...]",
        help="只截这些页面（自动进入只截图模式）；支持 setting-<key> 子页，见 --list",
    )
    parser.add_argument(
        "--shots-only",
        action="store_true",
        help="只截图，跳过行为断言和紧凑窗口检查（快速查看效果用）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出可用页面名后退出",
    )
    args = parser.parse_args(argv)
    if args.pages:
        args.shots_only = True
    return args


def _resolve_page_selection(raw: str) -> list[str]:
    """校验 --pages 选择，返回合法页面名列表（保持输入顺序、去重）。"""
    valid = set(PAGE_REGISTRY) | {f"setting-{key}" for key in SETTING_PAGE_KEYS}
    selected: list[str] = []
    for name in (part.strip() for part in raw.split(",")):
        if not name:
            continue
        if name not in valid:
            raise SystemExit(
                f"未知页面: {name!r}（用 --list 查看可用页面名）"
            )
        if name not in selected:
            selected.append(name)
    if not selected:
        raise SystemExit("--pages 至少要指定一个页面")
    return selected


def _print_page_list() -> None:
    print("主页面:")
    for name in PAGE_REGISTRY:
        print(f"  {name}")
    print("设置子页:")
    for key in SETTING_PAGE_KEYS:
        print(f"  setting-{key}")


# ---------------------------------------------------------------------------
# 环境与基础工具
# ---------------------------------------------------------------------------


def _prepare_environment(output_dir: Path) -> None:
    """offscreen 渲染 + 隔离 TOML 配置，保证可重复、不污染真实配置。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "VIDEOCAPTIONER_CONFIG_FILE" not in os.environ:
        config_path = output_dir / "ui-smoke-config.toml"
        if config_path.exists():
            config_path.unlink()
        os.environ["VIDEOCAPTIONER_CONFIG_FILE"] = str(config_path)
    os.environ.setdefault(
        "QT_LOGGING_RULES", "qt.qpa.fonts=false;qt.qpa.fonts.warning=false"
    )


def _apply_theme(theme_name: str) -> None:
    """与 ui/main.py 相同的主题初始化：应用 ThemeMode -> qfluent Theme。"""
    from qfluentwidgets import Theme, setTheme, setThemeColor

    from videocaptioner.ui.common.config import ThemeMode, cfg

    cfg.set(
        cfg.themeMode,
        ThemeMode.DARK if theme_name == "dark" else ThemeMode.LIGHT,
        save=False,
    )
    setTheme(Theme.DARK if theme_name == "dark" else Theme.LIGHT)
    setThemeColor(cfg.themeColor.value)


def _settle_widget(widget, app) -> None:
    """等事件队列消化完，再等页面里可能存在的预览线程，避免截到半成品。"""
    for _ in range(12):
        app.processEvents()
    preview_threads = getattr(widget, "_preview_threads", None)
    if preview_threads is not None:
        for thread in list(preview_threads):
            thread.wait(3000)
        for _ in range(4):
            app.processEvents()


def _grab(widget, output_dir: Path, name: str, app) -> None:
    _settle_widget(widget, app)
    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(f"empty screenshot: {name}")
    path = output_dir / f"{name}.png"
    pixmap.save(str(path))
    print(f"shot={path}")


def _make_page(name: str):
    """按注册表延迟导入并实例化页面，避免单页截图时拖入全部页面依赖。"""
    import importlib

    module_path, class_name = PAGE_REGISTRY[name]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _write_reference_wav(path: Path) -> None:
    """生成 0.1 秒 440Hz 正弦波 wav，作为克隆参考音频的本地夹具。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        frames = []
        for i in range(1600):
            sample = int(12000 * math.sin(2 * math.pi * 440 * i / 16000))
            frames.append(struct.pack("<h", sample))
        wav_file.writeframes(b"".join(frames))


def _make_contact_sheet(
    output_dir: Path, names: list[str], filename: str = "contact-sheet.png"
) -> Path | None:
    """把多张截图拼成 2 列缩略总览；没装 Pillow 时静默跳过。"""
    if not names:
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    thumbs = []
    for name in names:
        image = Image.open(output_dir / f"{name}.png").convert("RGB")
        image.thumbnail((480, 300), Image.LANCZOS)
        canvas = Image.new("RGB", (500, 344), (31, 32, 32))
        canvas.paste(image, (10, 34))
        ImageDraw.Draw(canvas).text((10, 10), f"{name}.png", fill=(245, 247, 246))
        thumbs.append(canvas)

    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 500, rows * 344), (31, 32, 32))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * 500, (index // cols) * 344))

    output_path = output_dir / filename
    sheet.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# 截图过程（不含断言）
# ---------------------------------------------------------------------------


def _capture_page(name: str, output_dir: Path, app) -> None:
    """截一个主页面，或一个 setting-<key> 设置子页。"""
    if name.startswith("setting-"):
        widget = _make_page("setting")
        widget.resize(*PAGE_SIZE)
        widget.show()
        widget.setCurrentPage(name.removeprefix("setting-"))
    else:
        widget = _make_page(name)
        widget.resize(*PAGE_SIZE)
        widget.show()
    _grab(widget, output_dir, name, app)
    widget.close()


def _capture_settings_pages(output_dir: Path, app) -> list[str]:
    """完整模式下：复用一个 SettingInterface 把所有设置子页截一遍。"""
    widget = _make_page("setting")
    widget.resize(*PAGE_SIZE)
    widget.show()
    names = []
    for key in SETTING_PAGE_KEYS:
        name = f"setting-page-{key}"
        widget.setCurrentPage(key)
        _grab(widget, output_dir, name, app)
        names.append(name)
    widget.close()
    return names


# ---------------------------------------------------------------------------
# 行为断言（完整冒烟模式）。
# 每个 _check_* 覆盖一个页面的关键交互回归：状态切换、行可见性、
# 配置写入是否生效等。它们顺带产出若干"状态截图"加入总览。
# ---------------------------------------------------------------------------


def _assert_fits_parent(widget, label: str, tolerance: int = 4) -> None:
    """断言控件没有横向溢出父容器（紧凑窗口下的常见回归）。"""
    parent = widget.parentWidget()
    if parent is None:
        return
    if widget.geometry().right() > parent.width() + tolerance:
        raise AssertionError(
            f"{label} overflows parent: right={widget.geometry().right()} parent={parent.width()}"
        )


def _assert_unique_action_texts(menu, label: str) -> list[str]:
    """断言菜单非空且没有重复项（provider/枚举菜单的常见回归）。"""
    texts = [action.text() for action in menu.actions() if action.text()]
    if not texts:
        raise AssertionError(f"{label} has no visible menu actions")
    duplicates = sorted({text for text in texts if texts.count(text) > 1})
    if duplicates:
        raise AssertionError(f"{label} has duplicate menu actions: {duplicates}")
    return texts


def _check_navigation(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """导航栏在窄窗口下保持 EXPAND 模式且宽度符合约束。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget
    from qfluentwidgets import FluentIcon as FIF
    from qfluentwidgets import NavigationInterface
    from qfluentwidgets.components.navigation.navigation_panel import (
        NavigationDisplayMode,
    )

    from videocaptioner.ui.common.theme_tokens import app_palette
    from videocaptioner.ui.view.main_window import (
        NAV_EXPAND_WIDTH,
        NAV_MINIMUM_EXPAND_WIDTH,
        WINDOW_MINIMUM_WIDTH,
    )

    parent = QWidget()
    parent.resize(1050, 800)
    palette = app_palette()
    parent.setStyleSheet(
        f"background:{palette.bg}; QLabel {{ color:{palette.text}; font-size:24px; }}"
    )
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    navigation = NavigationInterface(parent)
    navigation.setExpandWidth(NAV_EXPAND_WIDTH)
    navigation.setMinimumExpandWidth(NAV_MINIMUM_EXPAND_WIDTH)
    for key, icon, text in [
        ("home", FIF.HOME, "主页"),
        ("batch", FIF.VIDEO, "批量处理"),
        ("style", FIF.FONT, "字幕样式"),
        ("dubbing", FIF.VOLUME, "配音"),
        ("doctor", FIF.SEARCH, "诊断"),
    ]:
        navigation.addItem(key, icon, text)
    content = QLabel("内容区域")
    content.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
    layout.addWidget(navigation)
    layout.addWidget(content, 1)

    parent.show()
    app.processEvents()
    navigation.expand(False)
    app.processEvents()
    assert 118 <= NAV_EXPAND_WIDTH <= 144
    assert WINDOW_MINIMUM_WIDTH >= 960
    assert navigation.panel.displayMode == NavigationDisplayMode.EXPAND
    assert navigation.panel.width() == NAV_EXPAND_WIDTH
    _grab(parent, output_dir, "navigation-compact", app)
    screenshot_names.append("navigation-compact")

    parent.resize(900, 800)
    app.processEvents()
    navigation.panel.collapse()
    app.processEvents()
    navigation.expand(False)
    app.processEvents()
    assert navigation.panel.displayMode == NavigationDisplayMode.EXPAND
    assert navigation.panel.width() == NAV_EXPAND_WIDTH
    parent.close()


def _check_task_creation(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """任务创建页：输入形态派生（空/文件/链接/无效）与按钮、详情区联动。"""
    from videocaptioner.ui.view.task_creation_interface import InputKind

    widget = _make_page("task")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 空态：选择文件；详情区固定占位（高度恒定）
    assert widget._input_kind() == InputKind.EMPTY
    assert widget.primaryButton.toolTip() == "选择文件"
    assert widget.detailStack.height() == 118
    hero_y = widget.heroTitle.mapTo(widget, widget.heroTitle.rect().topLeft()).y()
    input_y = widget.inputCard.mapTo(widget, widget.inputCard.rect().topLeft()).y()

    # URL：开始处理 + 可开始
    widget.inputField.edit.setText("https://www.bilibili.com/video/BV1xx411c7mD")
    app.processEvents()
    assert widget._input_kind() == InputKind.URL
    assert widget.primaryButton.toolTip() == "开始处理"
    assert widget.statusPill.text() == "可开始"
    _grab(widget, output_dir, "task-url-state", app)
    screenshot_names.append("task-url-state")

    # 本地文件：详情面板出现，元信息胶囊渲染
    media = output_dir / "task-media.mp4"
    media.write_bytes(b"\0" * 2048)
    widget.inputField.edit.setText(str(media))
    app.processEvents()
    assert widget._input_kind() == InputKind.FILE
    assert widget.detailStack.currentWidget() is widget.mediaHost

    # 确认面板：模拟解析完成 -> 清晰度档位与确认按钮就位
    from videocaptioner.ui.view.task_creation_interface import PageState

    widget.inputField.edit.setText("https://www.bilibili.com/video/BV1xx411c7mD")
    app.processEvents()
    widget.state = PageState.PROBING
    widget._on_probed(
        {
            "title": "演示视频",
            "site": "BiliBili",
            "uploader": "UP 主",
            "duration": "12:18",
            "qualities": [1080, 720, 360],
            "has_subtitle": True,
        }
    )
    app.processEvents()
    assert widget.state == PageState.CONFIRM
    assert widget.detailStack.currentWidget() is widget.confirmHost
    assert widget.confirmPanel.qualitySelect.items() == ["最佳", "1080p", "720p", "360p"]
    assert widget.statusPill.text() == "待确认"
    _grab(widget, output_dir, "task-confirm-state", app)
    screenshot_names.append("task-confirm-state")
    widget.confirmPanel.qualitySelect.setCurrentText("720p")
    assert widget.confirmPanel.selectedHeight() == 720
    widget._cancel_download()
    app.processEvents()

    # 无效输入：错误卡 + 失败胶囊；hero/输入卡位置不随详情切换跳动
    widget.inputField.edit.setText("not-a-video")
    app.processEvents()
    assert widget._input_kind() == InputKind.INVALID
    assert widget.detailStack.currentWidget() is widget.errorHost
    assert widget.statusPill.text() == "输入无效"
    assert widget.heroTitle.mapTo(widget, widget.heroTitle.rect().topLeft()).y() == hero_y
    assert widget.inputCard.mapTo(widget, widget.inputCard.rect().topLeft()).y() == input_y
    _grab(widget, output_dir, "task-invalid-state", app)
    screenshot_names.append("task-invalid-state")
    widget.inputField.edit.clear()
    app.processEvents()
    assert widget._input_kind() == InputKind.EMPTY
    assert widget.primaryButton.toolTip() == "选择文件"
    widget.close()


def _check_settings(app) -> None:
    """设置页核心回归：provider 切换的行可见性、模型选项缓存、key 去空白、主题色重置。"""
    from PyQt5.QtGui import QColor

    import videocaptioner.ui.view.setting_interface as setting_module
    from videocaptioner.core.entities import (
        LLMServiceEnum,
        SubtitleRenderModeEnum,
        TranscribeModelEnum,
        TranslatorServiceEnum,
    )
    from videocaptioner.ui.common.config import DEFAULT_THEME_COLOR, cfg
    from videocaptioner.ui.view.setting_interface import SettingInterface

    widget = SettingInterface()
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 设置已改为弹窗（SettingsDialog），侧栏不再有「返回应用」按钮；关闭走右上角 X / Esc / 遮罩。
    assert not hasattr(widget, "backButton")

    # 翻译服务：LLM 类显示反思/批量/线程行，DeepLx 显示 endpoint 行。
    widget.setCurrentPage("translate-service")
    widget.translatorServiceControl.setCurrentText(TranslatorServiceEnum.OPENAI.value)
    app.processEvents()
    assert cfg.translator_service.value == TranslatorServiceEnum.OPENAI
    assert widget.needReflectTranslateRow.isVisible()
    assert widget.batchSizeRow.isVisible()
    assert widget.threadNumRow.isVisible()
    assert not widget.deeplxEndpointRow.isVisible()

    widget.translatorServiceControl.setCurrentText(TranslatorServiceEnum.DEEPLX.value)
    app.processEvents()
    assert cfg.translator_service.value == TranslatorServiceEnum.DEEPLX
    assert not widget.needReflectTranslateRow.isVisible()
    assert widget.deeplxEndpointRow.isVisible()

    widget.setCurrentPage("subtitle")
    cfg.set(cfg.subtitle_render_mode, SubtitleRenderModeEnum.ASS_STYLE)
    app.processEvents()
    assert cfg.subtitle_render_mode.value == SubtitleRenderModeEnum.ASS_STYLE

    # LLM 页："加载模型"与"测试连接"分离；模型选项按 provider 隔离缓存。
    widget.setCurrentPage("llm")
    widget.llmServiceControl.setCurrentText(LLMServiceEnum.SILICON_CLOUD.value)
    app.processEvents()
    assert widget.loadLLMModelsButton.text() == "加载模型"
    assert widget.checkLLMButton.text() == "测试连接"
    widget._save_llm_model_options(
        LLMServiceEnum.SILICON_CLOUD,
        ["  cached-model-a  ", "cached-model-a", "cached-model-b"],
    )
    widget._refresh_llm_rows(LLMServiceEnum.SILICON_CLOUD)
    app.processEvents()
    silicon_model_control = widget.llmProviderControls[LLMServiceEnum.SILICON_CLOUD]["model"]
    assert cfg.silicon_cloud_model_options.value == ["cached-model-a", "cached-model-b"]
    assert silicon_model_control.findText("cached-model-a") >= 0
    assert silicon_model_control.findText("cached-model-b") >= 0
    widget._save_llm_model_options(LLMServiceEnum.OPENAI, ["openai-cached-model"])
    widget._refresh_llm_rows(LLMServiceEnum.OPENAI)
    app.processEvents()
    openai_model_control = widget.llmProviderControls[LLMServiceEnum.OPENAI]["model"]
    assert openai_model_control.findText("openai-cached-model") >= 0
    assert openai_model_control.findText("cached-model-a") < 0
    widget._refresh_llm_rows(LLMServiceEnum.SILICON_CLOUD)
    app.processEvents()
    assert silicon_model_control.findText("cached-model-a") >= 0
    assert silicon_model_control.findText("openai-cached-model") < 0
    _assert_llm_threads_are_split(setting_module)

    # 转录页：Whisper API 与 WhisperCpp 互斥显示各自的行。
    widget.setCurrentPage("transcribe")
    widget.transcribeModelControl.setCurrentText(
        TranscribeModelEnum.WHISPER_API.value.replace(" ✨", "")
    )
    app.processEvents()
    assert cfg.transcribe_model.value == TranscribeModelEnum.WHISPER_API
    assert widget.whisperApiKeyRow.isVisible()
    assert not widget.whisperCppModelRow.isVisible()

    widget.transcribeModelControl.setCurrentText(TranscribeModelEnum.WHISPER_CPP.value)
    app.processEvents()
    assert cfg.transcribe_model.value == TranscribeModelEnum.WHISPER_CPP
    # The model selector is visible only when at least one local whisper.cpp
    # model is installed. Without downloaded models, the management row is the
    # expected user-facing entry point.
    assert widget.whisperCppModelRow.isVisible() or widget.whisperCppModelEntryRow.isVisible()
    assert not widget.whisperApiKeyRow.isVisible()

    # 配音页：SiliconFlow 显示 key/model 行，Edge 隐藏；key 输入去首尾空白和换行
    # （历史上曾导致 `Bearer ...\n` 无效请求头）。
    widget.setCurrentPage("dubbing")
    widget.dubbingProviderControl.setCurrentText("SiliconFlow CosyVoice")
    app.processEvents()
    assert cfg.dubbing_provider.value == "siliconflow"
    assert widget.dubbingApiKeyRow.isVisible()
    assert widget.dubbingModelRow.isVisible()
    # 付费提供商可设并发；Edge 免费则并发写死、不暴露给用户
    assert widget.dubbingWorkersRow.isVisible()
    assert widget.dubbingPresetControl.count() > 0
    widget.dubbingApiKeyControl.setText("  sk-smoke-test\n")
    app.processEvents()
    assert cfg.dubbing_api_key.value == "sk-smoke-test"
    assert widget.dubbingApiKeyControl.text() == "sk-smoke-test"

    widget.dubbingProviderControl.setCurrentText("Edge 免费配音")
    app.processEvents()
    assert cfg.dubbing_provider.value == "edge"
    assert not widget.dubbingApiKeyRow.isVisible()
    assert not widget.dubbingWorkersRow.isVisible()

    # 个性化页：主题色色块联动 + 重置按钮回到默认色。
    widget.setCurrentPage("personal")
    cfg.set(cfg.themeColor, QColor("#336699"))
    app.processEvents()
    assert widget.themeColorSwatch.color().name(QColor.HexRgb) == "#336699"
    assert widget.themeColorResetButton.isEnabled()
    widget.themeColorResetButton.click()
    app.processEvents()
    default_theme_color = QColor(DEFAULT_THEME_COLOR).name(QColor.HexRgb).lower()
    assert cfg.themeColor.value.name(QColor.HexRgb).lower() == default_theme_color
    assert widget.themeColorSwatch.color().name(QColor.HexRgb).lower() == default_theme_color
    assert not widget.themeColorResetButton.isEnabled()
    widget.close()


def _assert_llm_threads_are_split(setting_module) -> None:
    """"加载模型"和"测试连接"必须是两条独立线程路径，互不混用。"""
    original_check = setting_module.check_llm_connection
    original_load = setting_module.get_available_models
    calls: list[str] = []

    def fake_check(api_base: str, api_key: str, model: str):
        calls.append(f"check:{api_base}:{api_key}:{model}")
        return True, "ok"

    def fake_load(api_base: str, api_key: str):
        calls.append(f"load:{api_base}:{api_key}")
        return ["model-a", "model-b"]

    setting_module.check_llm_connection = fake_check
    setting_module.get_available_models = fake_load
    try:
        check_results = []
        check_thread = setting_module.LLMConnectionThread(
            "https://example.test/v1", "sk-test", "model-a"
        )
        check_thread.finished.connect(
            lambda success, message: check_results.append((success, message))
        )
        check_thread.run()
        assert check_results == [(True, "ok")]
        assert calls == ["check:https://example.test/v1:sk-test:model-a"]

        calls.clear()
        load_results = []
        load_thread = setting_module.LLMModelLoadThread(
            setting_module.LLMServiceEnum.OPENAI,
            "https://example.test/v1",
            "sk-test",
        )
        load_thread.finished.connect(
            lambda service, models: load_results.append((service, models))
        )
        load_thread.run()
        assert load_results == [
            (setting_module.LLMServiceEnum.OPENAI, ["model-a", "model-b"])
        ]
        assert calls == ["load:https://example.test/v1:sk-test"]
    finally:
        setting_module.check_llm_connection = original_check
        setting_module.get_available_models = original_load


def _check_settings_navigation(app) -> None:
    """其他页面（诊断/转录/字幕）跳转设置页时落到正确子页，别名也能解析。"""
    from PyQt5.QtWidgets import QVBoxLayout, QWidget

    from videocaptioner.ui.view.doctor_interface import DoctorInterface, ItemAction
    from videocaptioner.ui.view.setting_interface import SettingInterface
    from videocaptioner.ui.view.subtitle_interface import SubtitleInterface
    from videocaptioner.ui.view.transcription_interface import TranscriptionInterface

    class SettingsHost(QWidget):
        """模拟 MainWindow 的 openSettingsPage/switchTo 接口。"""

        def __init__(self):
            super().__init__()
            self.opened_pages: list[str] = []
            self.current_interface = None
            self.layout = QVBoxLayout(self)
            self.settingInterface = SettingInterface(self)
            self.layout.addWidget(self.settingInterface)

        def openSettingsPage(self, page_key: str) -> bool:  # noqa: N802
            if not self.settingInterface.setCurrentPage(page_key):
                return False
            self.current_interface = self.settingInterface
            self.opened_pages.append(self.settingInterface.currentPageKey())
            return True

        def switchTo(self, interface):
            self.current_interface = interface

    host = SettingsHost()
    host.resize(*PAGE_SIZE)
    host.show()
    app.processEvents()

    doctor = DoctorInterface(host)
    for action, page_key in [
        (ItemAction.TRANSCRIBE_SETTINGS, "transcribe"),
        (ItemAction.LLM_SETTINGS, "llm"),
        (ItemAction.TRANSLATE_SETTINGS, "translate-service"),
        (ItemAction.DUBBING_SETTINGS, "dubbing"),
    ]:
        doctor._handle_action(action)
        app.processEvents()
        assert host.opened_pages[-1] == page_key
        assert host.settingInterface.currentPageKey() == page_key
        assert host.current_interface is host.settingInterface

    for alias, page_key in [
        ("asr", "transcribe"),
        ("tts", "dubbing"),
        ("voice", "dubbing"),
        ("models", "llm"),
        ("translation-service", "translate-service"),
        ("video-synthesis", "subtitle"),
    ]:
        assert host.openSettingsPage(alias)
        app.processEvents()
        assert host.opened_pages[-1] == page_key
        assert host.settingInterface.currentPageKey() == page_key

    transcription = TranscriptionInterface(host)
    transcription._open_transcribe_settings()
    app.processEvents()
    assert host.opened_pages[-1] == "transcribe"
    assert host.settingInterface.currentPageKey() == "transcribe"
    transcription.close()

    subtitle = SubtitleInterface(host)
    subtitle.show_subtitle_settings()
    app.processEvents()
    assert host.opened_pages[-1] == "translate"
    assert host.settingInterface.currentPageKey() == "translate"
    subtitle.close()

    doctor.close()
    host.close()


def _check_transcription(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """转录页（单文件工作台）：六状态切换、参数与配置同步、按钮状态。"""
    from videocaptioner.core.entities import (
        AudioStreamInfo,
        TranscribeModelEnum,
        TranscribeOutputFormatEnum,
        VideoInfo,
    )
    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.view.transcription_interface import PageState

    widget = _make_page("transcription")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 空态：按钮禁用，左侧为拖放区。
    assert widget.state == PageState.EMPTY
    assert not widget.paramsPanel.startButton.isEnabled()
    assert widget.paramsPanel.startButton.text() == "等待文件"
    assert not widget.paramsPanel.trackRow.isVisible()

    # 服务选择与共享配置双向同步（菜单无重复项）。
    items = widget.paramsPanel.serviceSelect.items()
    assert items and len(set(items)) == len(items)
    widget.paramsPanel.serviceSelect.setCurrentText("B 接口")
    app.processEvents()
    assert cfg.transcribe_model.value == TranscribeModelEnum.BIJIAN
    # 提供商不再用头部胶囊表达（服务卡片已说明），平时隐藏。
    assert not widget.paramsPanel.statusPill.isVisibleTo(widget.paramsPanel)
    # B 接口没有模型概念：模型行隐藏。
    assert not widget.paramsPanel.modelRow.isVisibleTo(widget.paramsPanel)
    cfg.set(cfg.transcribe_model, TranscribeModelEnum.BAILIAN_FUN_ASR)
    app.processEvents()
    assert widget.paramsPanel.serviceSelect.currentText() == "Fun-ASR"
    # Fun-ASR 有模型行：选择写回 fun_asr_model。
    assert widget.paramsPanel.modelRow.isVisibleTo(widget.paramsPanel)
    widget.paramsPanel.modelSelect.setCurrentText("fun-asr-mtl")
    app.processEvents()
    assert cfg.fun_asr_model.value == "fun-asr-mtl"

    # 输出格式同步。
    widget.paramsPanel.outputSelect.setCurrentText(TranscribeOutputFormatEnum.TXT.value)
    app.processEvents()
    assert cfg.transcribe_output_format.value == TranscribeOutputFormatEnum.TXT
    widget.paramsPanel.outputSelect.setCurrentText(TranscribeOutputFormatEnum.SRT.value)
    app.processEvents()
    assert cfg.transcribe_output_format.value == TranscribeOutputFormatEnum.SRT

    # 文件就绪：媒体信息填充后按钮可用、音轨行可见。
    fake_media = output_dir / "transcription-fake.mp4"
    fake_media.write_bytes(b"\0")
    info = VideoInfo(
        file_name="transcription-fake.mp4",
        file_path=str(fake_media),
        width=1920,
        height=1080,
        fps=30.0,
        duration_seconds=624,
        bitrate_kbps=4000,
        video_codec="h264",
        audio_codec="aac",
        audio_sampling_rate=44100,
        thumbnail_path="",
        audio_streams=[AudioStreamInfo(index=0, codec="aac", language="zh")],
    )
    widget._media_path = str(fake_media)
    widget._apply_state(PageState.READY)
    widget._on_media_loaded(info)
    app.processEvents()
    assert widget.state == PageState.READY
    assert widget.paramsPanel.startButton.isEnabled()
    assert widget.paramsPanel.startButton.text() == "开始转录"
    assert widget.paramsPanel.trackRow.isVisible()
    assert widget.paramsPanel.trackSelect.currentText() == "音轨 1 · 中文"

    # 右栏折叠：紧凑主按钮与状态同步，展开还原。
    widget.sideHost.setCollapsed(True, animate=False)
    app.processEvents()
    assert cfg.transcribe_panel_collapsed.value
    assert widget.fileCompactStart.isVisibleTo(widget.filePanel)
    assert widget.fileCompactStart.text() == "开始转录"
    widget.sideHost.setCollapsed(False, animate=False)
    app.processEvents()
    assert not cfg.transcribe_panel_collapsed.value

    _grab(widget, output_dir, "transcription-ready-state", app)
    screenshot_names.append("transcription-ready-state")

    # 转录中：按钮禁用、进度卡可见、可取消但不可换文件。
    widget._apply_state(PageState.RUNNING)
    widget.progressCard.setProgress(62)
    app.processEvents()
    assert not widget.paramsPanel.startButton.isEnabled()
    assert widget.progressCard.isVisible()
    assert not widget.replaceLink.isVisible()
    assert widget.cancelLink.isVisible()
    assert widget.progressCard.percentLabel.text() == "62%"

    # 取消转录：回到就绪态，文件保留。
    widget._cancel_transcription()
    app.processEvents()
    assert widget.state == PageState.READY
    assert widget.paramsPanel.startButton.isEnabled()
    assert not widget.cancelLink.isVisible()
    widget._apply_state(PageState.RUNNING)
    app.processEvents()

    # 失败：错误面板 + 重新转录。
    widget._on_transcript_failed("smoke 测试失败原因")
    app.processEvents()
    assert widget.state == PageState.FAILED
    assert widget.errorBanner.isVisible()
    assert widget.errorBanner.text() == "smoke 测试失败原因"
    assert widget.paramsPanel.startButton.text() == "重新转录"
    assert widget.paramsPanel.statusPill.text() == "未连通"
    _grab(widget, output_dir, "transcription-failed-state", app)
    screenshot_names.append("transcription-failed-state")

    # 完成：SRT 表格 + 结果操作面板。
    widget.subtitlePreview.setSegments([(0, 1200, "第一条"), (1300, 2400, "第二条")])
    widget.resultPanel.setResult(
        title="transcription-fake", chips=["Fun-ASR", "10:24", "SRT"], file_name="x.srt"
    )
    widget._apply_state(PageState.DONE)
    app.processEvents()
    assert widget.subtitlePreview.pill.text() == "2 条"
    assert len(widget.subtitlePreview.rows) == 2
    assert widget.rightStack.currentWidget() is widget.resultPanel
    _grab(widget, output_dir, "transcription-done-state", app)
    screenshot_names.append("transcription-done-state")
    widget.close()


def _check_subtitle(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """字幕页（两栏审校）：选项与配置双向同步、加载与状态切换、行编辑。"""
    from videocaptioner.core.entities import SubtitleLayoutEnum
    from videocaptioner.core.translate.types import TargetLanguage
    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.view.subtitle_interface import PageState

    widget = _make_page("subtitle")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 空态：按钮禁用，选项卡片可见。
    assert widget.state == PageState.EMPTY
    assert not widget.sidePanel.primaryButton.isEnabled()
    assert widget.sidePanel.primaryButton.text() == "等待字幕"

    layout_items = widget.sidePanel.layoutSelect.items()
    language_items = widget.sidePanel.languageSelect.items()
    assert set(layout_items) == {layout.value for layout in SubtitleLayoutEnum}
    assert len(set(language_items)) == len(language_items)
    assert TargetLanguage.ENGLISH.value in language_items

    # 选项与共享配置双向同步。
    widget.sidePanel.layoutSelect.setCurrentText(SubtitleLayoutEnum.ONLY_ORIGINAL.value)
    app.processEvents()
    assert cfg.subtitle_layout.value == SubtitleLayoutEnum.ONLY_ORIGINAL

    widget.sidePanel.translateSwitch.setChecked(True)
    widget.sidePanel.languageSelect.setCurrentText(TargetLanguage.ENGLISH.value)
    app.processEvents()
    assert cfg.need_translate.value
    assert cfg.target_language.value == TargetLanguage.ENGLISH
    assert widget.sidePanel.languageCard.isVisible()

    widget.sidePanel.translateSwitch.setChecked(False)
    app.processEvents()
    assert not cfg.need_translate.value
    assert not widget.sidePanel.languageCard.isVisible()
    widget.sidePanel.translateSwitch.setChecked(True)

    # 加载真实字幕夹具 -> 就绪态。
    # 注意要用临时副本：开始处理会把表格内容写回源文件，不能污染仓库夹具。
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/audio/zh.srt"
    fixture_copy = output_dir / "subtitle-fixture.srt"
    fixture_copy.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    widget.load_subtitle_file(str(fixture_copy))
    app.processEvents()
    assert widget.state == PageState.READY
    assert widget.sidePanel.primaryButton.isEnabled()
    assert widget.sidePanel.primaryButton.text() == "开始处理"
    assert widget.tablePanel.bottomBar.infoLabel.text() == "共 1 条"
    assert widget.tablePanel.bottomBar.rightPill.text() == "已加载"
    _grab(widget, output_dir, "subtitle-ready-state", app)
    screenshot_names.append("subtitle-ready-state")

    # 表格行操作：合并 / 删除（模型层）。
    widget.model.replace_all(
        {
            "1": {"start_time": 0, "end_time": 1000, "original_subtitle": "甲", "translated_subtitle": ""},
            "2": {"start_time": 1000, "end_time": 2000, "original_subtitle": "乙", "translated_subtitle": ""},
            "3": {"start_time": 2000, "end_time": 3000, "original_subtitle": "丙", "translated_subtitle": ""},
        }
    )
    widget._merge_rows([0, 1])
    assert widget.model.rowCount() == 2
    assert widget.model.raw()["1"]["original_subtitle"] == "甲 乙"
    widget._delete_rows([1])
    assert widget.model.rowCount() == 1

    # 右栏折叠：窄条 + 表头主按钮出现，展开后还原，状态写入配置。
    widget.sideHost.setCollapsed(True, animate=False)
    app.processEvents()
    assert widget.sideHost.isCollapsed()
    assert cfg.subtitle_panel_collapsed.value
    assert widget.tablePanel.headStartButton.isVisibleTo(widget.tablePanel)
    widget.sideHost.setCollapsed(False, animate=False)
    app.processEvents()
    assert not cfg.subtitle_panel_collapsed.value
    assert not widget.tablePanel.headStartButton.isVisibleTo(widget.tablePanel)

    # 配置未就绪态（断句开启但 LLM 未配置）。
    cfg.set(cfg.need_split, True)
    widget._start_processing()
    app.processEvents()
    assert widget.state == PageState.FAILED
    assert widget.sidePanel.errorCard.isVisible()
    assert widget.sidePanel.primaryButton.text() == "打开处理配置"
    cfg.set(cfg.need_split, False)
    _grab(widget, output_dir, "subtitle-blocked-state", app)
    screenshot_names.append("subtitle-blocked-state")
    widget.close()


def _check_subtitle_style(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """字幕样式页（三栏）：样式库加载、ASS/圆角分页切换重建参数面板、显示内容分段控双语顺序行显隐。"""
    widget = _make_page("subtitle-style")
    widget.resize(*PAGE_SIZE)
    widget.show()
    _settle_widget(widget, app)

    # 样式库有卡片，参数面板已构建
    assert widget._cards, "subtitle style library has no cards"
    assert widget._ass or widget._rounded, "inspector controls not built"
    _grab(widget, output_dir, "subtitle-style-ass", app)
    screenshot_names.append("subtitle-style-ass")

    # 显示内容切到"原文"时，双语顺序行应隐藏；切回"双语"恢复
    widget.contentSeg.setCurrent("source")
    _settle_widget(widget, app)
    assert not widget.orderRow.isVisible()
    widget.contentSeg.setCurrent("bilingual")
    _settle_widget(widget, app)
    assert widget.orderRow.isVisible()

    # 切到圆角背景：参数面板重建为圆角控件集
    widget.modeTabs.setCurrent("rounded")
    _settle_widget(widget, app)
    assert widget._rounded and "bg_color" in widget._rounded
    _grab(widget, output_dir, "subtitle-style-rounded", app)
    screenshot_names.append("subtitle-style-rounded")

    widget.modeTabs.setCurrent("ass")
    _settle_widget(widget, app)

    # 大窗回归守卫：自绘卡片/参数行若漏设透明背景，深色主题下会露出 Qt 白底。
    # 采样左栏样式库下方空白区 + 右栏参数区，断言必须是深色（亮度 < 80）。
    # 仅在深色主题下有意义——浅色主题底色本就接近白，跑此断言会误报。
    from videocaptioner.ui.common.theme_tokens import is_dark_theme

    if is_dark_theme():
        widget.resize(1900, 1400)
        _settle_widget(widget, app)
        image = widget.grab().toImage()
        w_px, h_px = image.width(), image.height()
        samples = {
            "library-empty": (90, int(h_px * 0.7)),
            "inspector-area": (w_px - 180, int(h_px * 0.45)),
        }
        for where, (x, y) in samples.items():
            color = image.pixelColor(x, y)
            lum = (color.red() + color.green() + color.blue()) // 3
            if lum >= 80:
                raise AssertionError(
                    f"subtitle-style {where} 在深色主题下发白（亮度 {lum} @ {x},{y}）："
                    "自绘组件可能漏设透明背景，露出了 Qt 默认白底。"
                )
    widget.close()


def _check_dubbing(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """配音页：三个 provider 切换后声线表非空、克隆区只在 SiliconFlow 显示，
    性别筛选生效，设置/清除克隆参考音频联动播放按钮。"""
    from videocaptioner.ui.common.config import cfg

    reference_wav = output_dir / "reference.wav"
    _write_reference_wav(reference_wav)

    widget = _make_page("dubbing")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()
    for provider in ["edge", "gemini", "siliconflow"]:
        widget._on_provider_changed(provider)
        app.processEvents()
        assert cfg.dubbing_provider.value == provider
        assert len(widget.voiceTable.rows) > 0
        assert widget.previewPanel.cloneSection.isVisible() == (provider == "siliconflow")
        for key, card in widget.providerCards.items():
            assert card.isActive() == (key == provider)

    # 回归：切换提供商必须中止进行中的试听播放，并复位按钮文案（避免「停止」标签残留、点击行为相反）
    play_btn = widget.previewPanel.customPreviewButton
    widget._playing_button = play_btn
    widget._set_preview_button(play_btn, "playing")
    assert play_btn.text() == "停止"
    widget._on_provider_changed("siliconflow")
    app.processEvents()
    assert widget._playing_button is None, "切换提供商后未停止播放"
    assert play_btn.text() != "停止", "切换提供商后按钮文案仍是「停止」"

    widget._on_gender_filter("女声")
    app.processEvents()
    assert widget.voiceTable.rows
    assert all("女声" in row.voice.tags for row in widget.voiceTable.rows)

    cfg.set(cfg.dubbing_clone_audio, str(reference_wav), save=False)
    widget.previewPanel.setAudioPath(str(reference_wav))
    widget.previewPanel.setCloneText("这是一段用于克隆测试的参考音频。")
    app.processEvents()
    assert widget.bodyPanel.height() >= widget.sidePanel.sizeHint().height()
    assert widget.previewPanel.playButton.isEnabled()
    assert widget.previewPanel.cloneTextInput.isVisible()
    _grab(widget, output_dir, "dubbing-clone-state", app)
    screenshot_names.append("dubbing-clone-state")

    widget._clear_clone_audio()
    app.processEvents()
    assert not cfg.dubbing_clone_audio.value
    assert not widget.previewPanel.playButton.isEnabled()
    widget.close()


def _check_video_synthesis(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """视频合成页（组合开关工作台）：开关组合、文件就绪度、预检与状态切换。"""
    from videocaptioner.core.entities import VideoQualityEnum
    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.view.video_synthesis_interface import (
        SUBTITLE_MODE_LABELS,
        PageState,
    )

    widget = _make_page("video-synthesis")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 默认：字幕视频开、配音关、空态等待文件。
    cfg.set(cfg.need_video, True)
    cfg.set(cfg.dubbing_enabled, False)
    widget._refresh()
    app.processEvents()
    assert widget.state == PageState.IDLE
    assert not widget.generatePanel.primaryButton.isEnabled()
    assert widget.generatePanel.subtitleCard.isChecked()
    assert not widget.generatePanel.dubbingCard.isChecked()

    # 字幕方式互锁：软字幕不烧录样式，渲染模式和样式入口都应隐藏/锁定。
    widget.generatePanel.subtitleModeSelect.setCurrentText(SUBTITLE_MODE_LABELS[True])
    app.processEvents()
    assert cfg.soft_subtitle.value
    assert not widget.generatePanel.renderModeSelect.isEnabled()
    assert not widget.generatePanel.renderModeCard.isVisible()
    assert not widget.generatePanel.stylePageCard.isVisible()
    widget.generatePanel.subtitleModeSelect.setCurrentText(SUBTITLE_MODE_LABELS[False])
    app.processEvents()
    assert not cfg.soft_subtitle.value
    assert widget.generatePanel.renderModeSelect.isEnabled()
    assert widget.generatePanel.renderModeCard.isVisible()
    assert widget.generatePanel.stylePageCard.isVisible()

    # 质量选择与配置同步。
    widget.generatePanel.qualitySelect.setCurrentText(VideoQualityEnum.LOW.value)
    app.processEvents()
    assert cfg.video_quality.value == VideoQualityEnum.LOW

    # 文件就绪 -> 可生成；输出开关联动按钮文案。
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/audio/zh.srt"
    subtitle_copy = output_dir / "synthesis-subtitle.srt"
    subtitle_copy.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    fake_video = output_dir / "synthesis-video.mp4"
    fake_video.write_bytes(b"\0")
    widget.set_subtitle_file(str(subtitle_copy))
    app.processEvents()
    assert not widget.generatePanel.primaryButton.isEnabled()  # 还缺视频
    widget.set_video_file(str(fake_video))
    app.processEvents()
    assert widget.generatePanel.primaryButton.isEnabled()
    assert widget.generatePanel.primaryButton.text() == "生成字幕视频"

    cfg.set(cfg.dubbing_provider, "edge")
    widget.generatePanel.dubbingCard.setChecked(True)
    app.processEvents()
    assert cfg.dubbing_enabled.value
    assert widget.generatePanel.primaryButton.text() == "生成成片"
    _grab(widget, output_dir, "video-ready-state", app)
    screenshot_names.append("video-ready-state")

    # 预检拦截：非 Edge 音色缺 Key -> 错误卡 + 禁用。
    cfg.set(cfg.dubbing_provider, "siliconflow")
    cfg.set(cfg.dubbing_api_key, "")
    widget._refresh()
    app.processEvents()
    assert not widget.generatePanel.primaryButton.isEnabled()
    assert widget.generatePanel.errorCard.isVisible()
    _grab(widget, output_dir, "video-blocked-state", app)
    screenshot_names.append("video-blocked-state")
    cfg.set(cfg.dubbing_provider, "edge")
    widget.close()


def _check_batch(output_dir: Path, app, screenshot_names: list[str]) -> None:
    """批量处理页（队列工作台）：加文件、模式过滤、状态行渲染与清空。"""
    from videocaptioner.ui.common.config import cfg
    from videocaptioner.ui.view.batch_process_interface import JobStatus, PageState

    widget = _make_page("batch")
    widget.resize(*PAGE_SIZE)
    widget.show()
    app.processEvents()

    # 空态：拖放区可见、主按钮禁用、模式卡选中持久化值。
    cfg.set(cfg.batch_mode, "full")
    widget._switch_mode("full")
    app.processEvents()
    assert widget._page_state() == PageState.EMPTY
    assert widget.queueStack.currentIndex() == 0
    assert not widget.primaryButton.isEnabled()
    assert not widget.clearButton.isEnabled()
    active_cards = [card for card in widget.modeCards if card._active]
    assert len(active_cards) == 1 and active_cards[0].key == "full"

    # 加入两个媒体文件 + 一个不支持的扩展名 -> 只收两个，进入 READY。
    batch_dir = output_dir / "batch-files"
    batch_dir.mkdir(exist_ok=True)
    media_a = batch_dir / "课程 p01.mp4"
    media_a.write_bytes(b"\0")
    media_b = batch_dir / "课程 p02.mp3"
    media_b.write_bytes(b"\0")
    (batch_dir / "notes.txt").write_text("x", encoding="utf-8")
    widget.add_paths([str(batch_dir)])
    app.processEvents()
    assert len(widget.controller.jobs) == 2
    assert widget._page_state() == PageState.READY
    assert widget.queueStack.currentIndex() == 1
    assert widget.primaryButton.isEnabled()
    assert widget.countPill.text() == "2 个任务"
    assert len(widget._rows) == 2
    # 行内文字必须套用调色板（历史 bug：syncStyle 未调用导致默认黑字）
    assert "color:" in widget._rows[0].styleSheet()
    # 过滤分段固定高度，不允许被头部行拉伸贴边
    assert widget.filterTabs.height() <= 40

    # 行状态渲染：模拟完成 / 失败，失败行主按钮变成重试。
    jobs = widget.controller.jobs
    jobs[0].status = JobStatus.COMPLETED
    jobs[0].progress = 100
    jobs[0].note = "已输出 课程 p01.subtitled.mp4"
    jobs[1].status = JobStatus.FAILED
    jobs[1].note = "LLM API Key 缺失"
    jobs[1].error = "字幕处理：LLM API Key 缺失"
    widget.controller.jobChanged.emit(0)
    widget.controller.jobChanged.emit(1)
    widget._batch_ran = True
    widget._refresh()
    app.processEvents()
    assert widget._page_state() == PageState.DONE
    assert widget._rows[1].primaryButton.toolTip() == "重试任务"
    assert widget.primaryButton.isEnabled()  # 有失败可重跑

    # 过滤 tab：失败筛选只显示失败行。
    widget.filterTabs.setCurrent("failed")
    app.processEvents()
    assert not widget._rows[0].isVisible()
    assert widget._rows[1].isVisible()
    widget.filterTabs.setCurrent("all")
    app.processEvents()
    _grab(widget, output_dir, "batch-done-state", app)
    screenshot_names.append("batch-done-state")

    # 模式切换过滤：切到批量字幕翻译，媒体文件被移出队列。
    widget._switch_mode("subtitle")
    app.processEvents()
    assert not widget.controller.jobs
    assert widget._page_state() == PageState.EMPTY
    srt = batch_dir / "字幕.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    widget.add_paths([str(srt)])
    app.processEvents()
    assert len(widget.controller.jobs) == 1

    # 清空恢复空态；并发选择写回配置。
    widget._on_clear_clicked()
    app.processEvents()
    assert widget._page_state() == PageState.EMPTY
    widget.concurrencySelect.setCurrentText("并发 2")
    app.processEvents()
    assert int(cfg.batch_concurrency.value) == 2
    widget.concurrencySelect.setCurrentText("并发 1")
    app.processEvents()
    widget._switch_mode("full")
    widget.close()


def _capture_compact_states(output_dir: Path, app) -> list[str]:
    """960x720 紧凑窗口下的布局回归：关键面板不溢出、克隆区完整可见。"""
    from videocaptioner.ui.common.config import cfg

    names: list[str] = []

    dubbing = _make_page("dubbing")
    dubbing.resize(*COMPACT_SIZE)
    dubbing.show()
    dubbing._on_provider_changed("edge")
    _settle_widget(dubbing, app)
    _assert_fits_parent(dubbing.providerPanel, "compact dubbing provider")
    _assert_fits_parent(dubbing.voiceTable.header, "compact dubbing filter")
    _assert_fits_parent(dubbing.bodyPanel, "compact dubbing body")
    _grab(dubbing, output_dir, "compact-dubbing-edge", app)
    names.append("compact-dubbing-edge")

    reference_wav = output_dir / "compact-reference.wav"
    _write_reference_wav(reference_wav)
    dubbing._on_provider_changed("siliconflow")
    cfg.set(cfg.dubbing_clone_audio, str(reference_wav), save=False)
    dubbing.previewPanel.setAudioPath(str(reference_wav))
    dubbing.previewPanel.setCloneText("这是一段用于克隆测试的参考音频。")
    _settle_widget(dubbing, app)
    assert dubbing.previewPanel.cloneSection.isVisible()
    assert dubbing.bodyPanel.height() >= dubbing.sidePanel.sizeHint().height()
    _assert_fits_parent(dubbing.sidePanel, "compact dubbing side")
    _grab(dubbing, output_dir, "compact-dubbing-clone", app)
    names.append("compact-dubbing-clone")
    dubbing.close()

    synthesis = _make_page("video-synthesis")
    synthesis.resize(*COMPACT_SIZE)
    synthesis.show()
    cfg.set(cfg.need_video, True)
    cfg.set(cfg.dubbing_enabled, True)
    synthesis._refresh()
    _settle_widget(synthesis, app)
    _assert_fits_parent(synthesis.workspace, "compact synthesis workspace")
    _assert_fits_parent(synthesis.sideHost, "compact synthesis side host")
    _grab(synthesis, output_dir, "compact-video-synthesis", app)
    names.append("compact-video-synthesis")
    synthesis.close()

    settings = _make_page("setting")
    settings.resize(*COMPACT_SIZE)
    settings.show()
    settings.setCurrentPage("dubbing")
    _settle_widget(settings, app)
    assert settings.dubbingProviderRow.isVisible()
    _grab(settings, output_dir, "compact-setting-dubbing", app)
    names.append("compact-setting-dubbing")
    settings.close()

    for name, page in [
        ("compact-transcription", "transcription"),
        ("compact-subtitle-style", "subtitle-style"),
    ]:
        widget = _make_page(page)
        widget.resize(*COMPACT_SIZE)
        widget.show()
        _grab(widget, output_dir, name, app)
        names.append(name)
        widget.close()

    return names


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _run_both_themes(args: argparse.Namespace) -> int:
    """--theme both：每个主题各跑一个子进程，输出到 <output_dir>/<theme>。"""
    base_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    exit_code = 0
    for theme in ["dark", "light"]:
        cmd = [sys.executable, __file__, str(base_dir / theme), "--theme", theme]
        if args.shots_only:
            cmd.append("--shots-only")
        if args.pages:
            cmd.extend(["--pages", args.pages])
        result = subprocess.run(cmd)
        exit_code = exit_code or result.returncode
    return exit_code


def main() -> int:
    args = _parse_cli(sys.argv[1:])
    if args.list:
        _print_page_list()
        return 0
    if args.theme == "both":
        return _run_both_themes(args)

    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR / args.theme
    output_dir.mkdir(parents=True, exist_ok=True)
    _prepare_environment(output_dir)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication([])
    _apply_theme(args.theme)

    if args.shots_only:
        # 快速模式：只截图，不跑断言。
        selected = (
            _resolve_page_selection(args.pages)
            if args.pages
            else list(PAGE_REGISTRY) + [f"setting-{key}" for key in SETTING_PAGE_KEYS]
        )
        for name in selected:
            _capture_page(name, output_dir, app)
        contact_sheet = _make_contact_sheet(output_dir, selected)
        if contact_sheet:
            print(f"contact_sheet={contact_sheet}")
        print(f"screenshots={output_dir}")
        print(f"theme={args.theme}")
        print("ui-shots=ok")
    else:
        # 完整模式：全页截图 + 设置子页 + 行为断言 + 紧凑窗口检查。
        screenshot_names: list[str] = []
        for name in PAGE_REGISTRY:
            _capture_page(name, output_dir, app)
            screenshot_names.append(name)

        settings_screenshot_names = _capture_settings_pages(output_dir, app)
        _check_navigation(output_dir, app, screenshot_names)
        _check_task_creation(output_dir, app, screenshot_names)
        _check_settings(app)
        _check_settings_navigation(app)
        _check_transcription(output_dir, app, screenshot_names)
        _check_subtitle(output_dir, app, screenshot_names)
        _check_subtitle_style(output_dir, app, screenshot_names)
        _check_dubbing(output_dir, app, screenshot_names)
        _check_video_synthesis(output_dir, app, screenshot_names)
        _check_batch(output_dir, app, screenshot_names)
        compact_screenshot_names = _capture_compact_states(output_dir, app)

        contact_sheet = _make_contact_sheet(output_dir, screenshot_names)
        settings_contact_sheet = _make_contact_sheet(
            output_dir, settings_screenshot_names, "settings-contact-sheet.png"
        )
        compact_contact_sheet = _make_contact_sheet(
            output_dir, compact_screenshot_names, "compact-contact-sheet.png"
        )
        if contact_sheet:
            print(f"contact_sheet={contact_sheet}")
        if settings_contact_sheet:
            print(f"settings_contact_sheet={settings_contact_sheet}")
        if compact_contact_sheet:
            print(f"compact_contact_sheet={compact_contact_sheet}")
        print(f"screenshots={output_dir}")
        print(f"theme={args.theme}")
        print("ui-smoke=ok")

    QTimer.singleShot(0, app.quit)
    app.exec_()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
