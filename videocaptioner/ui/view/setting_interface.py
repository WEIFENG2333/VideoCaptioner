from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from PyQt5.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QDesktopServices, QPainterPath, QRegion
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBar, Theme, setTheme, setThemeColor
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

from videocaptioner.config import (
    AUTHOR,
    FEEDBACK_URL,
    HELP_URL,
    MODEL_PATH,
    RELEASE_URL,
    VERSION,
    YEAR,
)
from videocaptioner.core.application import TaskBuilder
from videocaptioner.core.asr.check import check_transcribe
from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.download import (
    detect_program,
    iter_models,
    model_install_state,
)
from videocaptioner.core.dubbing import build_dubbing_config, get_dubbing_preset
from videocaptioner.core.entities import (
    LLMServiceEnum,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    TranslatorServiceEnum,
    transcribe_languages_for,
)
from videocaptioner.core.llm.check_llm import check_llm_connection, get_available_models
from videocaptioner.core.realtime.check import check_live_caption
from videocaptioner.core.realtime.config import LiveCaptionConfig
from videocaptioner.core.speech import (
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)
from videocaptioner.core.utils.cache import disable_cache, enable_cache
from videocaptioner.ui.common.app_icons import AppIcon
from videocaptioner.ui.common.config import (
    DEFAULT_THEME_COLOR,
    ThemeMode,
    cfg,
    source_language_options,
)
from videocaptioner.ui.common.dubbing_options import (
    get_provider_option,
    get_provider_voices,
    is_provider_default_base,
)
from videocaptioner.ui.common.model_options import (
    FUN_ASR_MODEL_OPTIONS,
    WHISPER_API_MODEL_OPTIONS,
)
from videocaptioner.ui.common.theme_tokens import app_palette
from videocaptioner.ui.components.model_manager_dialog import ModelManagerDialog
from videocaptioner.ui.components.settings_controls import (
    CONTROL_WIDTH,
    BoundComboBox,
    BoundEditableComboBox,
    BoundFloatSlider,
    BoundLineEdit,
    BoundSlider,
    BoundSwitch,
    ColorSwatchButton,
    FolderPickerControl,
    Option,
    SettingRow,
    SettingsGroup,
    SettingsShell,
    make_button,
    options_from,
)
from videocaptioner.ui.components.workbench import CompactButton, RoundIconButton

SETTINGS_PAGE_ALIASES = {
    "asr": "transcribe",
    "transcription": "transcribe",
    "transcribe": "transcribe",
    "llm": "llm",
    "model": "llm",
    "models": "llm",
    "translate-service": "translate-service",
    "translator": "translate-service",
    "translation-service": "translate-service",
    "translate": "translate",
    "translation": "translate",
    "optimize": "translate",
    "subtitle": "subtitle",
    "subtitle-synthesis": "subtitle",
    "video-synthesis": "subtitle",
    "dubbing": "dubbing",
    "tts": "dubbing",
    "voice": "dubbing",
    "save": "save",
    "output": "save",
    "personal": "personal",
    "appearance": "personal",
    "about": "about",
}


def normalize_settings_page_key(page_key: str) -> str:
    return SETTINGS_PAGE_ALIASES.get(str(page_key or "").strip().lower(), page_key)


def _to_qfluent_theme(theme: ThemeMode) -> Theme:
    if theme == ThemeMode.LIGHT:
        return Theme.LIGHT
    if theme == ThemeMode.AUTO:
        return Theme.AUTO
    return Theme.DARK


class SettingInterface(SettingsShell):
    """First-party settings page backed by the shared TOML config."""

    # 内嵌在 SettingsDialog 里时无法直接 self.window() 拿到主窗口跳转字幕样式 tab，
    # 改发信号由 SettingsDialog 接管（先关弹窗再切主窗口）。
    openStylePageRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(self.tr("设置"))
        self._threads: list[QThread] = []

        self._build_pages()
        self._connect_signals()
        self._refresh_transcribe_rows(cfg.transcribe_model.value)
        self._refresh_local_model_state()
        self._refresh_llm_rows(cfg.llm_service.value)
        self._refresh_translate_rows(cfg.translator_service.value)
        self._refresh_dubbing_rows(cfg.dubbing_provider.value)
        self._refresh_lc_rows(cfg.live_caption_provider.value)
        self._sync_theme_color_swatch(cfg.themeColor.value)
        self.setCurrentPage("transcribe")

    def _build_pages(self) -> None:
        self.transcribePage = self.addPage("transcribe", "转录配置")
        self.llmPage = self.addPage("llm", "LLM 配置")
        self.translateServicePage = self.addPage("translate-service", "翻译服务")
        self.translatePage = self.addPage("translate", "翻译与优化")
        self.subtitlePage = self.addPage("subtitle", "字幕合成配置")
        self.dubbingPage = self.addPage("dubbing", "配音配置")
        self.liveCaptionPage = self.addPage("live-caption", "实时字幕配置")
        self.savePage = self.addPage("save", "保存配置")
        self.personalPage = self.addPage("personal", "个性化")
        self.aboutPage = self.addPage("about", "关于")

        self._build_transcribe_page()
        self._build_llm_page()
        self._build_translate_service_page()
        self._build_translate_page()
        self._build_subtitle_page()
        self._build_dubbing_page()
        self._build_live_caption_page()
        self._build_save_page()
        self._build_personal_page()
        self._build_about_page()

    def setCurrentPage(self, key: str) -> bool:  # noqa: N802
        return super().setCurrentPage(normalize_settings_page_key(key))

    def _build_transcribe_page(self) -> None:
        group = SettingsGroup("", self.transcribePage.container)
        self.transcribeModelControl = BoundComboBox(
            cfg.transcribe_model,
            options_from(cfg.transcribe_model.validator.options),
            group,
        )
        self.transcribeModelRow = group.addRow(
            SettingRow(
                self.tr("转录模型"),
                self.tr("选择生成原始字幕时使用的语音识别服务。"),
                self.transcribeModelControl,
                group,
            )
        )

        self.transcribeOutputRow = group.addRow(
            SettingRow(
                self.tr("输出格式"),
                self.tr("转录完成后保存的字幕文件格式。"),
                BoundComboBox(
                    cfg.transcribe_output_format,
                    options_from(cfg.transcribe_output_format.validator.options),
                    group,
                ),
                group,
            )
        )
        self.transcribeLanguageControl = BoundComboBox(
            cfg.transcribe_language,
            options_from(cfg.transcribe_language.validator.options),
            group,
        )
        self.transcribeLanguageRow = group.addRow(
            SettingRow(
                self.tr("源语言"),
                self.tr("音视频中说话的语言，不确定时保持自动检测。"),
                self.transcribeLanguageControl,
                group,
            )
        )

        self.whisperApiBaseRow = group.addRow(
            SettingRow(
                self.tr("Whisper API Base URL"),
                self.tr("使用 Whisper API 时请求的服务地址。"),
                BoundLineEdit(cfg.whisper_api_base, "https://api.openai.com/v1", group),
                group,
            )
        )
        self.whisperApiKeyRow = group.addRow(
            SettingRow(
                self.tr("Whisper API Key"),
                self.tr("使用 Whisper API 转录时需要填写。"),
                BoundLineEdit(cfg.whisper_api_key, "sk-", group, password=True),
                group,
            )
        )
        self.whisperApiModelControl = BoundEditableComboBox(
            cfg.whisper_api_model,
            WHISPER_API_MODEL_OPTIONS,
            group,
        )
        self.whisperApiModelRow = group.addRow(
            SettingRow(
                self.tr("Whisper 模型"),
                self.tr("填写服务商支持的音频转录模型名。"),
                self.whisperApiModelControl,
                group,
            )
        )
        self.whisperApiPromptRow = group.addRow(
            SettingRow(
                self.tr("提示词"),
                self.tr("可选的转录提示词，默认空。"),
                BoundLineEdit(cfg.whisper_api_prompt, self.tr("未填写"), group),
                group,
            )
        )
        # 只列已下载的模型（下载入口在「管理模型」弹窗）；选项由
        # _refresh_model_choices 按本地文件动态过滤。
        self.whisperCppModelControl = BoundComboBox(
            cfg.whisper_model,
            options_from(cfg.whisper_model.validator.options),
            group,
        )
        self.whisperCppModelRow = group.addRow(
            SettingRow(
                self.tr("WhisperCpp 模型"),
                self.tr("选择已下载的 whisper.cpp 转录模型。"),
                self.whisperCppModelControl,
                group,
            )
        )
        # 程序安装与模型下载集中在「管理模型」弹窗；状态写进行描述，
        # 不与上方模型选择重复（需要行动时按钮转主题色）。
        self.whisperCppManageButton = make_button(self.tr("管理模型"), parent=group)
        self.whisperCppModelEntryRow = group.addRow(
            SettingRow(
                self.tr("本地模型"),
                self.tr("查看运行程序状态、下载和管理模型文件。"),
                self.whisperCppManageButton,
                group,
            )
        )

        self.fasterWhisperModelControl = BoundComboBox(
            cfg.faster_whisper_model,
            options_from(cfg.faster_whisper_model.validator.options),
            group,
        )
        self.fasterWhisperModelRow = group.addRow(
            SettingRow(
                self.tr("Faster Whisper 模型"),
                self.tr("选择已下载的 Faster Whisper 模型。"),
                self.fasterWhisperModelControl,
                group,
            )
        )
        self.fasterWhisperDirControl = FolderPickerControl(group, placeholder=self.tr("未选择"))
        self.fasterWhisperDirControl.setPath(str(cfg.faster_whisper_model_dir.value or ""))
        self.fasterWhisperDirRow = group.addRow(
            SettingRow(
                self.tr("模型目录"),
                self.tr("Faster Whisper 模型所在文件夹。"),
                self.fasterWhisperDirControl,
                group,
            )
        )
        self.fasterWhisperManageButton = make_button(self.tr("管理模型"), parent=group)
        self.fasterWhisperModelEntryRow = group.addRow(
            SettingRow(
                self.tr("本地模型"),
                self.tr("查看运行程序状态、下载和管理模型文件。"),
                self.fasterWhisperManageButton,
                group,
            )
        )
        self.fasterWhisperDeviceRow = group.addRow(
            SettingRow(
                self.tr("运行设备"),
                self.tr("模型运行设备，通常保持 auto。"),
                BoundComboBox(
                    cfg.faster_whisper_device,
                    options_from(cfg.faster_whisper_device.validator.options),
                    group,
                ),
                group,
            )
        )
        self.fasterWhisperVadFilterRow = group.addRow(
            SettingRow(
                self.tr("VAD 过滤"),
                self.tr("过滤无人声片段，减少识别幻觉。"),
                BoundSwitch(cfg.faster_whisper_vad_filter, group),
                group,
            )
        )
        self.fasterWhisperVadThresholdRow = group.addRow(
            SettingRow(
                self.tr("VAD 阈值"),
                self.tr("语音概率阈值，高于此值视为语音。"),
                BoundFloatSlider(cfg.faster_whisper_vad_threshold, 2, group),
                group,
            )
        )
        self.fasterWhisperVadMethodRow = group.addRow(
            SettingRow(
                self.tr("VAD 方法"),
                self.tr("选择语音活动检测方法。"),
                BoundComboBox(
                    cfg.faster_whisper_vad_method,
                    options_from(cfg.faster_whisper_vad_method.validator.options),
                    group,
                ),
                group,
            )
        )
        self.fasterWhisperVoiceExtractionRow = group.addRow(
            SettingRow(
                self.tr("人声分离"),
                self.tr("处理前分离人声和背景音乐。"),
                BoundSwitch(cfg.faster_whisper_ff_mdx_kim2, group),
                group,
            )
        )
        self.fasterWhisperOneWordRow = group.addRow(
            SettingRow(
                self.tr("单字时间戳"),
                self.tr("开启后生成单字级时间戳。"),
                BoundSwitch(cfg.faster_whisper_one_word, group),
                group,
            )
        )
        self.fasterWhisperPromptRow = group.addRow(
            SettingRow(
                self.tr("提示词"),
                self.tr("可选的转录提示词，默认空。"),
                BoundLineEdit(cfg.faster_whisper_prompt, self.tr("未填写"), group),
                group,
            )
        )

        self.funAsrKeyRow = group.addRow(
            SettingRow(
                self.tr("百炼 API Key"),
                self.tr("百炼 Fun-ASR 转录需要填写。"),
                BoundLineEdit(cfg.fun_asr_api_key, "sk-", group, password=True),
                group,
            )
        )
        self.funAsrModelControl = BoundEditableComboBox(
            cfg.fun_asr_model,
            FUN_ASR_MODEL_OPTIONS,
            group,
        )
        self.funAsrModelRow = group.addRow(
            SettingRow(
                self.tr("百炼 ASR 模型"),
                self.tr("填写百炼控制台里可用的语音识别模型 Code。"),
                self.funAsrModelControl,
                group,
            )
        )
        # 统一的真实转录测试：对所有服务（含 B/J 接口与本地模型）可用，
        # 与 doctor --check-api 共用 core 的 check_transcribe 入口。
        self.checkTranscribeButton = make_button(self.tr("测试转录"), parent=group)
        self.checkTranscribeRow = group.addRow(
            SettingRow(
                self.tr("测试转录"),
                self.tr("用内置短音频真实转录一次，验证当前服务能跑通。"),
                self.checkTranscribeButton,
                group,
            )
        )
        self.transcribePage.addGroup(group)

    def _build_llm_page(self) -> None:
        group = SettingsGroup("", self.llmPage.container)
        self.llmServiceControl = BoundComboBox(
            cfg.llm_service,
            options_from(cfg.llm_service.validator.options),
            group,
        )
        self.llmServiceRow = group.addRow(
            SettingRow(
                self.tr("LLM 提供商"),
                self.tr("用于字幕断句、校正和 LLM 翻译。"),
                self.llmServiceControl,
                group,
            )
        )

        self.llmProviderRows: dict[LLMServiceEnum, list[SettingRow]] = {}
        self.llmApiBaseRows: dict[LLMServiceEnum, SettingRow] = {}
        self.llmDefaultBases: dict[LLMServiceEnum, str] = {}
        self.llmProviderSpecs = self._llm_provider_specs()
        self.llmProviderControls: dict[LLMServiceEnum, dict[str, BoundLineEdit | BoundEditableComboBox]] = {}
        for service, provider in self.llmProviderSpecs.items():
            api_key = BoundLineEdit(provider["api_key"], "sk-", group, password=True)
            api_base = BoundLineEdit(provider["api_base"], provider["default_base"], group)
            model = BoundEditableComboBox(
                provider["model"],
                self._llm_model_options_for_provider(provider),
                group,
            )
            api_key_row = group.addRow(
                SettingRow(
                    self.tr("API Key"),
                    self.tr("{service} 调用大模型时使用。").format(service=service.value),
                    api_key,
                    group,
                )
            )
            api_base_row = group.addRow(
                SettingRow(
                    self.tr("Base URL"),
                    self.tr("仅 OpenAI 兼容或本地服务需要修改。"),
                    api_base,
                    group,
                )
            )
            model_row = group.addRow(
                SettingRow(
                    self.tr("模型"),
                    self.tr("用于断句、校正、翻译的大模型名称。"),
                    model,
                    group,
                )
            )
            rows = [api_key_row, api_base_row, model_row]
            self.llmApiBaseRows[service] = api_base_row
            self.llmDefaultBases[service] = str(provider["default_base"])
            self.llmProviderRows[service] = rows
            self.llmProviderControls[service] = {
                "api_key": api_key,
                "api_base": api_base,
                "model": model,
            }

        self.loadLLMModelsButton = make_button(self.tr("加载模型"), parent=group)
        self.checkLLMButton = make_button(self.tr("测试连接"), parent=group)
        self.checkLLMRow = group.addRow(
            SettingRow(
                self.tr("模型服务"),
                self.tr("先加载可用模型，再用当前模型测试连通性。"),
                self._two_controls(self.loadLLMModelsButton, self.checkLLMButton, group),
                group,
            )
        )
        self.llmPage.addGroup(group)

    def _build_translate_service_page(self) -> None:
        group = SettingsGroup("", self.translateServicePage.container)
        self.translatorServiceControl = BoundComboBox(
            cfg.translator_service,
            options_from(cfg.translator_service.validator.options),
            group,
        )
        self.translatorServiceRow = group.addRow(
            SettingRow(
                self.tr("翻译服务"),
                self.tr("选择字幕翻译使用的服务。"),
                self.translatorServiceControl,
                group,
            )
        )
        self.needReflectTranslateRow = group.addRow(
            SettingRow(
                self.tr("反思翻译"),
                self.tr("仅 LLM 翻译时使用，会增加模型调用量。"),
                BoundSwitch(cfg.need_reflect_translate, group),
                group,
            )
        )
        self.deeplxEndpointRow = group.addRow(
            SettingRow(
                self.tr("DeepLx 后端"),
                self.tr("选择 DeepLx 翻译时需要填写。"),
                BoundLineEdit(cfg.deeplx_endpoint, "https://api.deeplx.org/translate", group),
                group,
            )
        )
        self.batchSizeRow = group.addRow(
            SettingRow(
                self.tr("批处理大小"),
                self.tr("LLM 翻译每批处理的字幕数量。"),
                BoundSlider(cfg.batch_size, group),
                group,
            )
        )
        self.threadNumRow = group.addRow(
            SettingRow(
                self.tr("并发数"),
                self.tr("模型服务允许的情况下可以调高。"),
                BoundSlider(cfg.thread_num, group),
                group,
            )
        )
        self.translateServicePage.addGroup(group)

    def _build_translate_page(self) -> None:
        group = SettingsGroup("", self.translatePage.container)
        group.addRow(
            SettingRow(
                self.tr("字幕校正"),
                self.tr("处理字幕时修正识别错误和专有名词。"),
                BoundSwitch(cfg.need_optimize, group),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("字幕翻译"),
                self.tr("处理字幕时生成目标语言译文。"),
                BoundSwitch(cfg.need_translate, group),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("字幕断句"),
                self.tr("按字数和语义重新切分长字幕。"),
                BoundSwitch(cfg.need_split, group),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("目标语言"),
                self.tr("翻译字幕输出的目标语言。"),
                BoundComboBox(
                    cfg.target_language,
                    options_from(cfg.target_language.validator.options),
                    group,
                ),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("中文字幕长度"),
                self.tr("断句时每条字幕的中文最大字数。"),
                BoundSlider(cfg.max_word_count_cjk, group),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("英文字幕长度"),
                self.tr("断句时每条字幕的英文最大词数。"),
                BoundSlider(cfg.max_word_count_english, group),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("自定义提示词"),
                self.tr("补充给字幕校正和翻译的大模型提示。"),
                BoundLineEdit(cfg.custom_prompt_text, self.tr("未填写"), group),
                group,
            )
        )
        self.translatePage.addGroup(group)

    def _build_subtitle_page(self) -> None:
        synth_group = SettingsGroup("", self.subtitlePage.container)
        self.subtitleStyleButton = make_button(self.tr("打开样式页"), parent=synth_group)
        synth_group.addRow(
            SettingRow(
                self.tr("字幕样式"),
                self.tr("字体、颜色和预览图在样式页调整。"),
                self.subtitleStyleButton,
                synth_group,
            )
        )
        synth_group.addRow(
            SettingRow(
                self.tr("字幕布局"),
                self.tr("选择单语、双语以及原文译文位置。"),
                BoundComboBox(
                    cfg.subtitle_layout,
                    options_from(cfg.subtitle_layout.validator.options),
                    synth_group,
                ),
                synth_group,
            )
        )
        synth_group.addRow(
            SettingRow(
                self.tr("渲染模式"),
                self.tr("选择 ASS 样式或圆角背景渲染。"),
                BoundComboBox(
                    cfg.subtitle_render_mode,
                    options_from(cfg.subtitle_render_mode.validator.options),
                    synth_group,
                ),
                synth_group,
            )
        )
        synth_group.addRow(
            SettingRow(
                self.tr("合成视频"),
                self.tr("关闭后只输出字幕文件，不生成成片。"),
                BoundSwitch(cfg.need_video, synth_group),
                synth_group,
            )
        )
        synth_group.addRow(
            SettingRow(
                self.tr("软字幕"),
                self.tr("开启后字幕不烧录进画面。"),
                BoundSwitch(cfg.soft_subtitle, synth_group),
                synth_group,
            )
        )
        synth_group.addRow(
            SettingRow(
                self.tr("视频质量"),
                self.tr("硬字幕合成时使用的编码质量。"),
                BoundComboBox(
                    cfg.video_quality,
                    options_from(cfg.video_quality.validator.options),
                    synth_group,
                ),
                synth_group,
            )
        )
        self.subtitlePage.addGroup(synth_group)

    def _build_dubbing_page(self) -> None:
        group = SettingsGroup("", self.dubbingPage.container)
        group.addRow(
            SettingRow(
                self.tr("默认添加配音"),
                self.tr("开启后，全流程处理默认生成配音音轨。"),
                BoundSwitch(cfg.dubbing_enabled, group),
                group,
            )
        )
        self.dubbingProviderControl = BoundComboBox(
            cfg.dubbing_provider,
            [Option(option.key, option.title) for option in self._dubbing_provider_options()],
            group,
        )
        self.dubbingProviderRow = group.addRow(
            SettingRow(
                self.tr("配音提供商"),
                self.tr("Edge 免 Key；Gemini 和 SiliconFlow 需要 API Key。"),
                self.dubbingProviderControl,
                group,
            )
        )
        self.dubbingPresetControl = BoundComboBox(cfg.dubbing_preset, [], group)
        self.dubbingPresetRow = group.addRow(
            SettingRow(
                self.tr("默认音色"),
                self.tr("保存后会作为配音页和全流程的默认音色。"),
                self.dubbingPresetControl,
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("配音文本轨道"),
                self.tr("选择用原文、译文，或自动判断生成配音。"),
                BoundComboBox(
                    cfg.dubbing_text_track,
                    [
                        Option("auto", self.tr("自动选择")),
                        Option("first", self.tr("第一行")),
                        Option("second", self.tr("第二行")),
                    ],
                    group,
                ),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("时间对齐"),
                self.tr("控制配音语速与字幕时间轴的贴合程度。"),
                BoundComboBox(
                    cfg.dubbing_timing,
                    [
                        Option("natural", self.tr("自然")),
                        Option("balanced", self.tr("均衡")),
                        Option("strict", self.tr("严格")),
                        Option("none", self.tr("不变速")),
                    ],
                    group,
                ),
                group,
            )
        )
        group.addRow(
            SettingRow(
                self.tr("原声处理"),
                self.tr("生成视频时如何处理原视频声音。"),
                BoundComboBox(
                    cfg.dubbing_audio_mode,
                    [
                        Option("replace", self.tr("替换原声")),
                        Option("mix", self.tr("混合原声")),
                        Option("duck", self.tr("压低原声")),
                    ],
                    group,
                ),
                group,
            )
        )
        self.dubbingApiKeyControl = BoundLineEdit(
            cfg.dubbing_api_key, "sk-", group, password=True
        )
        self.dubbingApiKeyRow = group.addRow(
            SettingRow(
                self.tr("配音 API Key"),
                self.tr("Gemini 或 SiliconFlow 配音需要填写。"),
                self.dubbingApiKeyControl,
                group,
            )
        )
        self.dubbingModelControl = BoundEditableComboBox(cfg.dubbing_model, [], group)
        self.dubbingModelRow = group.addRow(
            SettingRow(
                self.tr("配音模型"),
                self.tr("当前配音提供商使用的文字转语音模型。"),
                self.dubbingModelControl,
                group,
            )
        )
        self.dubbingWorkersRow = group.addRow(
            SettingRow(
                self.tr("配音并发"),
                self.tr("同时合成的字幕行数。"),
                BoundSlider(cfg.dubbing_tts_workers, group),
                group,
            )
        )
        self.checkDubbingButton = make_button(self.tr("测试配音"), parent=group)
        self.checkDubbingRow = group.addRow(
            SettingRow(
                self.tr("配音测试"),
                self.tr("用当前音色合成一句试听音频。"),
                self.checkDubbingButton,
                group,
            )
        )
        self.dubbingPage.addGroup(group)

    def _build_live_caption_page(self) -> None:
        display_labels = {"bilingual": "双语", "target": "仅译文", "source": "仅原文"}
        bg_labels = {"translucent": "半透明", "black": "纯黑"}
        # 下拉项只显引擎名 / 模型名，不带括号解释（说明留给行副标题）。
        provider_labels = {"voxgate": "voxgate", "fun-asr": "Fun-ASR", "qwen-asr": "Qwen-ASR"}

        # 1) 转录引擎（Provider）：voxgate 本地免费无密钥；fun-asr 阿里云实时（需 Key，中英日更准）
        engine_group = SettingsGroup(self.tr("转录引擎"), self.liveCaptionPage.container)
        engine_group.addRow(
            SettingRow(
                self.tr("转录引擎"),
                self.tr("实时语音转文字所用的识别引擎。"),
                BoundComboBox(
                    cfg.live_caption_provider,
                    options_from(
                        cfg.live_caption_provider.validator.options,
                        lambda v: provider_labels.get(v, v),
                    ),
                    engine_group,
                ),
                engine_group,
            )
        )
        # voxgate：下载/检测本地程序
        deps_button = CompactButton(self.tr("下载 / 检测"), AppIcon.DOWNLOAD, engine_group)
        deps_button.clicked.connect(self._open_live_caption_deps)
        self.lcVoxgateRow = engine_group.addRow(
            SettingRow(
                self.tr("转录程序"),
                self.tr("voxgate 本地转录程序，未安装时点此下载或检测。"),
                deps_button,
                engine_group,
            )
        )
        # fun-asr / qwen-asr：API Key（复用百炼 Key）/ 模型 / 识别语言
        self.lcFunKeyRow = engine_group.addRow(
            SettingRow(
                self.tr("百炼 API Key"),
                self.tr("Fun-ASR / Qwen-ASR 调用阿里云百炼所需的密钥，与转录配置共用同一个。"),
                BoundLineEdit(cfg.fun_asr_api_key, "sk-", engine_group, password=True),
                engine_group,
            )
        )
        self.lcFunModelRow = engine_group.addRow(
            SettingRow(
                self.tr("识别模型"),
                self.tr("Fun-ASR 识别模型；多语种模型可自动识别多种语言。"),
                BoundComboBox(
                    cfg.live_caption_fun_asr_model,
                    options_from(cfg.live_caption_fun_asr_model.validator.options),
                    engine_group,
                ),
                engine_group,
            )
        )
        # 识别语言列表随引擎不同（voxgate 中/英、Fun-ASR 7 种、Qwen-ASR 27 种），由 _refresh_lc_rows
        # 按 provider 重填；这里按当前 provider 给初始项。三家都含 auto = 自动识别。
        langs = source_language_options(cfg.live_caption_provider.value)
        self.lcSourceLangCombo = BoundComboBox(
            cfg.live_caption_source_language,
            options_from([c for c, _ in langs], lambda v: dict(langs).get(v, v)),
            engine_group,
        )
        self.lcSourceLangRow = engine_group.addRow(
            SettingRow(
                self.tr("识别语言"),
                self.tr("你说话所用的语言；识别引擎据此进行转写。自动识别可让引擎按音频判定语言。"),
                self.lcSourceLangCombo,
                engine_group,
            )
        )
        # 统一的真实转录测试：对所选引擎（voxgate / Fun-ASR）用内置短音频真实跑一次，
        # 与转录配置页的「测试转录」同思路，但走实时后端（core.realtime.check）。
        self.checkLiveCaptionButton = make_button(self.tr("测试转录"), parent=engine_group)
        engine_group.addRow(
            SettingRow(
                self.tr("测试转录"),
                self.tr("用内置短音频真实转录一次，验证当前引擎能跑通。"),
                self.checkLiveCaptionButton,
                engine_group,
            )
        )
        self.liveCaptionPage.addGroup(engine_group)

        # 2) 翻译
        translate_group = SettingsGroup(self.tr("翻译"), self.liveCaptionPage.container)
        translate_group.addRow(
            SettingRow(
                self.tr("实时翻译"),
                self.tr("开启后对转录文本即时翻译；关闭则只显示原文。"),
                BoundSwitch(cfg.live_caption_translate, translate_group),
                translate_group,
            )
        )
        translate_group.addRow(
            SettingRow(
                self.tr("目标语言"),
                self.tr("译文翻译成的语言。"),
                BoundComboBox(
                    cfg.live_caption_target_language,
                    options_from(cfg.live_caption_target_language.validator.options),
                    translate_group,
                ),
                translate_group,
            )
        )
        translate_group.addRow(
            SettingRow(
                self.tr("翻译引擎"),
                self.tr("生成译文所用的翻译服务。"),
                BoundComboBox(
                    cfg.live_caption_translator_service,
                    options_from(cfg.live_caption_translator_service.validator.options),
                    translate_group,
                ),
                translate_group,
            )
        )
        self.liveCaptionPage.addGroup(translate_group)

        # 3) 浮窗显示
        overlay_group = SettingsGroup(self.tr("浮窗显示"), self.liveCaptionPage.container)
        overlay_group.addRow(
            SettingRow(
                self.tr("显示内容"),
                self.tr("浮窗默认显示的内容"),
                BoundComboBox(
                    cfg.live_caption_display_mode,
                    options_from(
                        cfg.live_caption_display_mode.validator.options,
                        lambda v: display_labels.get(v, v),
                    ),
                    overlay_group,
                ),
                overlay_group,
            )
        )
        overlay_group.addRow(
            SettingRow(
                self.tr("底色样式"),
                self.tr("浮窗底色风格"),
                BoundComboBox(
                    cfg.live_caption_bg_style,
                    options_from(
                        cfg.live_caption_bg_style.validator.options,
                        lambda v: bg_labels.get(v, v),
                    ),
                    overlay_group,
                ),
                overlay_group,
            )
        )
        overlay_group.addRow(
            SettingRow(
                self.tr("字号"),
                self.tr("浮窗译文字号"),
                BoundSlider(cfg.live_caption_font_scale, overlay_group),
                overlay_group,
            )
        )
        self.liveCaptionPage.addGroup(overlay_group)

    def _open_live_caption_deps(self) -> None:
        from videocaptioner.ui.components.dependency_download_dialog import (
            DependencyDownloadDialog,
        )

        DependencyDownloadDialog(parent=self._toast_parent()).exec()

    def _refresh_lc_rows(self, value: Any) -> None:
        """实时字幕转录引擎切换：voxgate 显本地程序行；fun-asr/qwen-asr 显 Key（共用百炼）；
        识别模型行仅 fun-asr（qwen 单模型）。识别语言三家都有（voxgate 中/英、Fun-ASR 7、
        Qwen-ASR 27），故该行恒显，列表随引擎重填。"""
        is_cloud = value in ("fun-asr", "qwen-asr")
        self.lcVoxgateRow.setVisible(not is_cloud)
        self.lcFunKeyRow.setVisible(is_cloud)
        self.lcFunModelRow.setVisible(value == "fun-asr")
        self.lcSourceLangRow.setVisible(True)
        # 识别语言随引擎重填；当前选择若不在新列表里则退回「自动识别」。
        langs = source_language_options(value)
        codes = {c for c, _ in langs}
        cur = cfg.live_caption_source_language.value
        self.lcSourceLangCombo.setOptions(
            options_from([c for c, _ in langs], lambda v: dict(langs).get(v, v)),
            keep_value=cur if cur in codes else "auto",
        )

    def _build_save_page(self) -> None:
        save_group = SettingsGroup("", self.savePage.container)
        self.workDirControl = FolderPickerControl(save_group)
        self.workDirControl.setPath(str(cfg.work_dir.value or ""))
        save_group.addRow(
            SettingRow(
                self.tr("工作目录"),
                self.tr("下载视频与处理任务的中间文件会写入这里。"),
                self.workDirControl,
                save_group,
            )
        )
        save_group.addRow(
            SettingRow(
                self.tr("保留中间文件"),
                self.tr("处理成功后保留任务目录里的原始转录、样式字幕等中间产物；默认跑完即清。"),
                BoundSwitch(cfg.keep_intermediates, save_group),
                save_group,
            )
        )
        save_group.addRow(
            SettingRow(
                self.tr("启用缓存"),
                self.tr("相同配置下复用 ASR、翻译和配音合成结果。"),
                BoundSwitch(cfg.cache_enabled, save_group),
                save_group,
            )
        )
        self.savePage.addGroup(save_group)

    def _build_personal_page(self) -> None:
        ui_group = SettingsGroup("", self.personalPage.container)
        self.themeControl = BoundComboBox(
            cfg.themeMode,
            [
                Option(option, text)
                for option, text in zip(
                    cfg.themeMode.validator.options,
                    [self.tr("浅色"), self.tr("深色"), self.tr("跟随系统")],
                )
            ],
            ui_group,
        )
        ui_group.addRow(
            SettingRow(
                self.tr("应用主题"),
                self.tr("切换浅色、深色或跟随系统。"),
                self.themeControl,
                ui_group,
            )
        )
        self.themeColorSwatch = ColorSwatchButton(
            cfg.themeColor.value if isinstance(cfg.themeColor.value, QColor) else QColor(str(cfg.themeColor.value)),
            ui_group,
        )
        self.themeColorResetButton = make_button(self.tr("恢复默认"), parent=ui_group)
        self.themeColorResetButton.setToolTip(self.tr("恢复为项目默认绿色"))
        ui_group.addRow(
            SettingRow(
                self.tr("主题颜色"),
                self.tr("影响按钮、高亮和选中状态。"),
                self._two_controls(self.themeColorSwatch, self.themeColorResetButton, ui_group),
                ui_group,
            )
        )
        self.zoomControl = BoundComboBox(
            cfg.dpiScale,
            [
                Option(1, "100%"),
                Option(1.25, "125%"),
                Option(1.5, "150%"),
                Option(1.75, "175%"),
                Option(2, "200%"),
                Option("Auto", self.tr("跟随系统")),
            ],
            ui_group,
        )
        ui_group.addRow(
            SettingRow(
                self.tr("界面缩放"),
                self.tr("修改后需要重启应用。"),
                self.zoomControl,
                ui_group,
            )
        )
        self.languageControl = BoundComboBox(
            cfg.language,
            [
                Option(option, text)
                for option, text in zip(
                    cfg.language.validator.options,
                    ["简体中文", "繁體中文", "English", self.tr("跟随系统")],
                )
            ],
            ui_group,
        )
        ui_group.addRow(
            SettingRow(
                self.tr("语言"),
                self.tr("修改后需要重启应用。"),
                self.languageControl,
                ui_group,
            )
        )
        self.personalPage.addGroup(ui_group)

    def _build_about_page(self) -> None:
        about_group = SettingsGroup("", self.aboutPage.container)
        self.helpButton = make_button(self.tr("打开帮助"), parent=about_group)
        about_group.addRow(
            SettingRow(
                self.tr("帮助"),
                self.tr("查看使用说明和常见问题。"),
                self.helpButton,
                about_group,
            )
        )
        self.feedbackButton = make_button(self.tr("提交反馈"), primary=True, parent=about_group)
        about_group.addRow(
            SettingRow(
                self.tr("反馈"),
                self.tr("遇到问题时提交反馈。"),
                self.feedbackButton,
                about_group,
            )
        )
        self.updateButton = make_button(self.tr("检查更新"), primary=True, parent=about_group)
        about_group.addRow(
            SettingRow(
                self.tr("版本"),
                f"© {YEAR}, {AUTHOR}. {self.tr('当前版本')} {VERSION}",
                self.updateButton,
                about_group,
            )
        )
        self.aboutPage.addGroup(about_group)

    def _connect_signals(self) -> None:
        cfg.appRestartSig.connect(self._show_restart_tip)
        cfg.themeChanged.connect(lambda theme: setTheme(_to_qfluent_theme(theme)))
        cfg.themeChanged.connect(lambda _theme: self._sync_visual_style())
        cfg.themeColorChanged.connect(self._apply_theme_color)
        cfg.themeColorChanged.connect(lambda _color: self._sync_visual_style())
        self.transcribeModelControl.currentValueChanged.connect(self._refresh_transcribe_rows)
        cfg.transcribe_model.valueChanged.connect(self._refresh_transcribe_rows)
        self.checkTranscribeButton.clicked.connect(self.check_transcribe_connection)
        self.fasterWhisperDirControl.changeRequested.connect(self._choose_faster_whisper_dir)

        self.llmServiceControl.currentValueChanged.connect(self._refresh_llm_rows)
        cfg.llm_service.valueChanged.connect(self._refresh_llm_rows)
        self.loadLLMModelsButton.clicked.connect(self.load_llm_models)
        self.checkLLMButton.clicked.connect(self.check_llm_connection)

        self.translatorServiceControl.currentValueChanged.connect(self._refresh_translate_rows)
        cfg.translator_service.valueChanged.connect(self._refresh_translate_rows)

        self.subtitleStyleButton.clicked.connect(self._open_subtitle_style_page)

        self.dubbingProviderControl.currentValueChanged.connect(self._refresh_dubbing_rows)
        cfg.dubbing_provider.valueChanged.connect(self._refresh_dubbing_rows)
        cfg.live_caption_provider.valueChanged.connect(self._refresh_lc_rows)
        self.checkLiveCaptionButton.clicked.connect(self.check_live_caption_connection)
        self.dubbingPresetControl.currentValueChanged.connect(self._on_dubbing_preset_changed)
        self.checkDubbingButton.clicked.connect(self.check_dubbing_connection)

        self.workDirControl.changeRequested.connect(self._choose_work_dir)
        cfg.work_dir.valueChanged.connect(
            lambda value: self.workDirControl.setPath(str(value or ""))
        )
        cfg.faster_whisper_model_dir.valueChanged.connect(
            lambda value: self.fasterWhisperDirControl.setPath(str(value or ""))
        )
        self.whisperCppManageButton.clicked.connect(
            lambda: self._open_model_manager("whisper-cpp")
        )
        self.fasterWhisperManageButton.clicked.connect(
            lambda: self._open_model_manager("faster-whisper")
        )
        cfg.whisper_model.valueChanged.connect(lambda _v: self._refresh_model_entries())
        cfg.faster_whisper_model.valueChanged.connect(lambda _v: self._refresh_model_entries())
        cfg.faster_whisper_model_dir.valueChanged.connect(
            lambda _v: self._refresh_local_model_state()
        )
        cfg.cache_enabled.valueChanged.connect(self._on_cache_enabled_changed)
        self.themeColorSwatch.clicked.connect(self._choose_theme_color)
        self.themeColorResetButton.clicked.connect(self._reset_theme_color)
        cfg.themeColor.valueChanged.connect(self._sync_theme_color_swatch)
        self.helpButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        self.feedbackButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        self.updateButton.clicked.connect(lambda: webbrowser.open(RELEASE_URL))

    def _refresh_transcribe_rows(self, value: Any) -> None:
        is_whisper_api = value == TranscribeModelEnum.WHISPER_API
        is_fun_asr = value == TranscribeModelEnum.BAILIAN_FUN_ASR
        is_whisper_cpp = value == TranscribeModelEnum.WHISPER_CPP
        is_faster_whisper = value == TranscribeModelEnum.FASTER_WHISPER
        for row in [
            self.whisperApiBaseRow,
            self.whisperApiKeyRow,
            self.whisperApiModelRow,
            self.whisperApiPromptRow,
        ]:
            row.setVisible(is_whisper_api)
        self.whisperCppModelRow.setVisible(is_whisper_cpp)
        self.whisperCppModelEntryRow.setVisible(is_whisper_cpp)
        for row in [
            self.fasterWhisperModelRow,
            self.fasterWhisperDirRow,
            self.fasterWhisperModelEntryRow,
            self.fasterWhisperDeviceRow,
            self.fasterWhisperVadFilterRow,
            self.fasterWhisperVadThresholdRow,
            self.fasterWhisperVadMethodRow,
            self.fasterWhisperVoiceExtractionRow,
            self.fasterWhisperOneWordRow,
            self.fasterWhisperPromptRow,
        ]:
            row.setVisible(is_faster_whisper)
        for row in [
            self.funAsrKeyRow,
            self.funAsrModelRow,
        ]:
            row.setVisible(is_fun_asr)
        if is_fun_asr and cfg.fun_asr_api_base.value.strip() != "https://dashscope.aliyuncs.com":
            cfg.set(cfg.fun_asr_api_base, "https://dashscope.aliyuncs.com")
        # 源语言按接口能力收窄：B/J 接口只识别中英，其余接口提供全语种。
        # 当前选择若不在新接口的支持集内，回落到自动检测。
        languages = transcribe_languages_for(value)
        if cfg.transcribe_language.value in languages:
            self.transcribeLanguageControl.setOptions(options_from(languages))
        else:
            self.transcribeLanguageControl.setOptions(
                options_from(languages), keep_value=TranscribeLanguageEnum.AUTO
            )
        # 模型行的最终可见性还取决于"有没有已下载的模型"
        self._refresh_model_choices()

    # ------------------------------------------------------------ 本地模型入口

    def _open_model_manager(self, kind: str) -> None:
        dialog = ModelManagerDialog(kind, self.window())
        dialog.modelsChanged.connect(self._refresh_local_model_state)
        dialog.exec()
        self._refresh_local_model_state()

    def _model_entry_target(self, kind: str) -> tuple[str, Path]:
        """入口行对应的当前模型名与模型目录。"""
        if kind == "whisper-cpp":
            name = getattr(cfg.whisper_model.value, "value", str(cfg.whisper_model.value))
            return str(name), Path(MODEL_PATH)
        name = getattr(
            cfg.faster_whisper_model.value, "value", str(cfg.faster_whisper_model.value)
        )
        return str(name), Path(cfg.faster_whisper_model_dir.value or MODEL_PATH)

    def _installed_model_options(self, kind: str) -> list[Any]:
        """已下载模型对应的枚举选项（按清单顺序）。"""
        _name, models_dir = self._model_entry_target(kind)
        installed = {
            spec.name
            for spec in iter_models(kind)
            if model_install_state(spec, models_dir)
        }
        field = cfg.whisper_model if kind == "whisper-cpp" else cfg.faster_whisper_model
        return [
            option
            for option in field.validator.options
            if getattr(option, "value", str(option)) in installed
        ]

    def _refresh_local_model_state(self) -> None:
        self._refresh_model_choices()
        self._refresh_model_entries()

    def _refresh_model_choices(self) -> None:
        """模型下拉只列已下载的；一个都没有时隐藏整行，由入口引导下载。"""
        is_cpp = cfg.transcribe_model.value == TranscribeModelEnum.WHISPER_CPP
        is_fw = cfg.transcribe_model.value == TranscribeModelEnum.FASTER_WHISPER
        for kind, control, row, provider_active in (
            ("whisper-cpp", self.whisperCppModelControl, self.whisperCppModelRow, is_cpp),
            ("faster-whisper", self.fasterWhisperModelControl, self.fasterWhisperModelRow, is_fw),
        ):
            options = self._installed_model_options(kind)
            row.setVisible(provider_active and bool(options))
            if not options:
                continue
            field = control.config_item
            current = field.value if field.value in options else options[0]
            control.setOptions(options_from(options), keep_value=current)

    def _refresh_model_entries(self) -> None:
        entries = {
            "whisper-cpp": (self.whisperCppModelEntryRow, self.whisperCppManageButton),
            "faster-whisper": (self.fasterWhisperModelEntryRow, self.fasterWhisperManageButton),
        }
        for kind, (row, button) in entries.items():
            _name, models_dir = self._model_entry_target(kind)
            if not detect_program(kind).installed:
                desc = self.tr("运行程序未安装，先在「管理模型」里完成安装。")
                needs_action = True
            elif not self._installed_model_options(kind):
                desc = self.tr("还没有下载模型，打开「管理模型」选择下载。")
                needs_action = True
            else:
                desc = self.tr("查看运行程序状态、下载和管理模型文件。")
                needs_action = False
            row.descLabel.setText(desc)
            button.setProperty("settingsPrimary", needs_action)
            row.syncStyle()  # 重新应用按钮主次样式
            button.setToolTip(str(models_dir))

    def _refresh_llm_rows(self, value: Any) -> None:
        current = value if isinstance(value, LLMServiceEnum) else LLMServiceEnum(str(value))
        custom_base_services = {LLMServiceEnum.OPENAI, LLMServiceEnum.OLLAMA, LLMServiceEnum.LM_STUDIO}
        for service, rows in self.llmProviderRows.items():
            for row in rows:
                row.setVisible(service == current)
            base_row = self.llmApiBaseRows.get(service)
            if base_row is not None:
                base_row.setVisible(service == current and service in custom_base_services)

        controls = self.llmProviderControls.get(current)
        if controls is not None:
            self._apply_llm_model_options(current, self._llm_model_options(current))
            if current not in custom_base_services:
                default_base = self.llmDefaultBases.get(current, "")
                api_base_control = controls["api_base"]
                if default_base and api_base_control.text().strip() != default_base:
                    cfg.set(api_base_control.config_item, default_base)
            if current == LLMServiceEnum.OLLAMA and not controls["api_key"].text():
                controls["api_key"].setText("ollama")
            elif current == LLMServiceEnum.LM_STUDIO and not controls["api_key"].text():
                controls["api_key"].setText("lm-studio")

    def _refresh_translate_rows(self, value: Any) -> None:
        service = value if isinstance(value, TranslatorServiceEnum) else TranslatorServiceEnum(str(value))
        is_llm = service == TranslatorServiceEnum.OPENAI
        is_deeplx = service == TranslatorServiceEnum.DEEPLX
        self.needReflectTranslateRow.setVisible(is_llm)
        self.batchSizeRow.setVisible(is_llm)
        self.threadNumRow.setVisible(is_llm)
        self.deeplxEndpointRow.setVisible(is_deeplx)

    def _refresh_dubbing_rows(self, provider: Any) -> None:
        provider_key = str(provider)
        option = get_provider_option(provider_key)
        voice_options = get_provider_voices(provider_key)
        preset_options = [Option(voice.preset, voice.title) for voice in voice_options]
        current = cfg.dubbing_preset.value
        if current not in {voice.preset for voice in voice_options}:
            current = voice_options[0].preset
        self.dubbingPresetControl.setOptions(preset_options, keep_value=current)
        self.dubbingModelControl.setItems(option.models)
        if cfg.dubbing_model.value not in option.models:
            cfg.set(cfg.dubbing_model, option.models[0] if option.models else "")
        if option.default_base:
            cfg.set(cfg.dubbing_api_base, option.default_base)
        for row in [self.dubbingApiKeyRow, self.dubbingModelRow]:
            row.setVisible(option.needs_api_key)
        # Edge 免费，并发由程序内部固定（pipeline.EDGE_TTS_WORKERS），不暴露给用户
        self.dubbingWorkersRow.setVisible(provider_key != "edge")
        self._on_dubbing_preset_changed(current)

    def _on_dubbing_preset_changed(self, preset_name: Any) -> None:
        try:
            preset = get_dubbing_preset(str(preset_name))
        except ValueError:
            return
        cfg.set(cfg.dubbing_provider, preset.provider)
        cfg.set(cfg.dubbing_voice, preset.voice)
        cfg.set(cfg.dubbing_model, preset.model)
        option = get_provider_option(preset.provider)
        if option.needs_api_key and is_provider_default_base(cfg.dubbing_api_base.value):
            cfg.set(cfg.dubbing_api_base, preset.api_base or option.default_base)

    def _choose_work_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("选择工作目录"), cfg.work_dir.value)
        if not folder:
            return
        cfg.set(cfg.work_dir, folder)

    def _choose_faster_whisper_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择 Faster Whisper 模型目录"),
            cfg.faster_whisper_model_dir.value or cfg.work_dir.value,
        )
        if not folder:
            return
        cfg.set(cfg.faster_whisper_model_dir, folder)

    def _on_cache_enabled_changed(self, enabled: bool) -> None:
        if enabled:
            enable_cache()
            InfoBar.success(
                self.tr("缓存已启用"),
                self.tr("后续任务会优先复用已有结果。"),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self._toast_parent(),
            )
        else:
            disable_cache()
            InfoBar.warning(
                self.tr("缓存已禁用"),
                self.tr("后续任务会重新生成结果。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )

    def _choose_theme_color(self) -> None:
        from videocaptioner.ui.components.color_picker import ColorPickerDialog

        color = ColorPickerDialog.get_color(
            cfg.themeColor.value, parent=self._toast_parent(), alpha=False, title=self.tr("选择主题颜色")
        )
        if color is None or not color.isValid():
            return
        cfg.set(cfg.themeColor, color)

    def _reset_theme_color(self) -> None:
        default_color = QColor(DEFAULT_THEME_COLOR)
        current_color = cfg.themeColor.value if isinstance(cfg.themeColor.value, QColor) else QColor(str(cfg.themeColor.value))
        if current_color.isValid() and current_color.name(QColor.HexRgb).lower() == default_color.name(QColor.HexRgb).lower():
            return
        cfg.set(cfg.themeColor, default_color)

    def _apply_theme_color(self, color: Any, attempt: int = 0) -> None:
        try:
            setThemeColor(color)
        except RuntimeError:
            if attempt >= 2:
                raise
            retry_color = QColor(color)
            QTimer.singleShot(0, lambda: self._apply_theme_color(retry_color, attempt + 1))

    def _sync_theme_color_swatch(self, value: Any) -> None:
        color = value if isinstance(value, QColor) else QColor(str(value))
        if not color.isValid():
            color = QColor(DEFAULT_THEME_COLOR)
        self.themeColorSwatch.setColor(color)
        self.themeColorSwatch.setToolTip(
            self.tr("点击选择主题颜色：{color}").format(color=color.name(QColor.HexRgb))
        )
        if hasattr(self, "themeColorResetButton"):
            default_color = QColor(DEFAULT_THEME_COLOR).name(QColor.HexRgb).lower()
            is_default = color.name(QColor.HexRgb).lower() == default_color
            self.themeColorResetButton.setEnabled(not is_default)
            self.themeColorResetButton.setToolTip(
                self.tr("当前已经是项目默认绿色")
                if is_default
                else self.tr("恢复为项目默认绿色")
            )

    def _sync_visual_style(self) -> None:
        self.syncStyle()
        if hasattr(self, "themeColorSwatch"):
            self._sync_theme_color_swatch(cfg.themeColor.value)

    def _open_subtitle_style_page(self) -> None:
        # 弹窗内：发信号让 SettingsDialog 关闭弹窗并切到主窗口的字幕样式 tab
        self.openStylePageRequested.emit()

    def _show_restart_tip(self) -> None:
        InfoBar.success(
            self.tr("更新成功"),
            self.tr("这项设置将在重启后生效。"),
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self._toast_parent(),
        )

    def check_llm_connection(self) -> None:
        service = cfg.llm_service.value
        controls = self.llmProviderControls.get(service)
        if controls is None:
            return
        api_base = controls["api_base"].text().strip()
        api_key = controls["api_key"].text().strip()
        model = controls["model"].currentText().strip()
        if not api_base or not api_key or not model:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请先填写当前提供商的 Base URL、API Key 和模型。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return
        self._run_button_thread(
            self.checkLLMButton,
            self.tr("测试连接"),
            self.tr("正在测试..."),
            LLMConnectionThread(api_base, api_key, model),
            self._on_llm_check_finished,
            self._on_llm_check_error,
        )

    def load_llm_models(self) -> None:
        service = cfg.llm_service.value
        controls = self.llmProviderControls.get(service)
        if controls is None:
            return
        api_base = controls["api_base"].text().strip()
        api_key = controls["api_key"].text().strip()
        if not api_base or not api_key:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请先填写当前提供商的 Base URL 和 API Key。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return
        self._run_button_thread(
            self.loadLLMModelsButton,
            self.tr("加载模型"),
            self.tr("正在加载..."),
            LLMModelLoadThread(service, api_base, api_key),
            self._on_llm_models_loaded,
            self._on_llm_models_load_error,
        )

    def _on_llm_check_finished(self, success: bool, message: str) -> None:
        if success:
            InfoBar.success(
                self.tr("LLM 连接成功"),
                message,
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self._toast_parent(),
            )
        else:
            InfoBar.error(
                self.tr("LLM 连接失败"),
                message,
                duration=INFOBAR_DURATION_ERROR,
                parent=self._toast_parent(),
            )

    def _on_llm_check_error(self, message: str) -> None:
        InfoBar.error(
            self.tr("LLM 连接错误"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            parent=self._toast_parent(),
        )

    def _on_llm_models_loaded(self, service: object, models: list[str]) -> None:
        try:
            service = service if isinstance(service, LLMServiceEnum) else LLMServiceEnum(str(service))
        except ValueError:
            service = cfg.llm_service.value
        models = self._clean_model_options(models)
        if not models:
            InfoBar.warning(
                self.tr("没有可用模型"),
                self.tr("没有从当前提供商获取到模型列表，请检查 Base URL 和 API Key。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return
        self._save_llm_model_options(service, models)
        if cfg.llm_service.value == service:
            self._apply_llm_model_options(service, models)
        InfoBar.success(
            self.tr("模型已加载"),
            self.tr("已加载 {count} 个模型。").format(count=len(models)),
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self._toast_parent(),
        )

    def _on_llm_models_load_error(self, message: str) -> None:
        InfoBar.error(
            self.tr("模型加载失败"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            parent=self._toast_parent(),
        )

    def check_transcribe_connection(self) -> None:
        """统一测试转录：先做提供商必填项快检，再真实跑短音频。"""
        missing = self._transcribe_check_missing()
        if missing:
            InfoBar.warning(
                self.tr("配置不完整"),
                missing,
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return
        from videocaptioner.ui.config_adapter import app_config_from_ui

        config = TaskBuilder(app_config_from_ui(cfg)).create_transcribe_config(
            need_word_timestamp=False
        )
        self._run_button_thread(
            self.checkTranscribeButton,
            self.tr("测试转录"),
            self.tr("正在转录..."),
            TranscribeCheckThread(config),
            self._on_transcribe_check_finished,
            self._on_transcribe_check_error,
        )

    def _transcribe_check_missing(self) -> str:
        """当前转录服务缺少的必填配置；齐全返回空串。"""
        model = cfg.transcribe_model.value
        if model == TranscribeModelEnum.WHISPER_API:
            if not (
                cfg.whisper_api_base.value.strip()
                and cfg.whisper_api_key.value.strip()
                and cfg.whisper_api_model.value.strip()
            ):
                return self.tr("请先填写 Whisper Base URL、API Key 和模型。")
        elif model == TranscribeModelEnum.BAILIAN_FUN_ASR:
            if not cfg.fun_asr_api_key.value.strip():
                return self.tr("请先填写百炼 API Key。")
        elif model == TranscribeModelEnum.WHISPER_CPP:
            if not self._installed_model_options("whisper-cpp"):
                return self.tr("还没有可用的本地模型，请先在「管理模型」中下载。")
        elif model == TranscribeModelEnum.FASTER_WHISPER:
            if not self._installed_model_options("faster-whisper"):
                return self.tr("还没有可用的本地模型，请先在「管理模型」中下载。")
        return ""

    def _on_transcribe_check_finished(self, success: bool, detail: str) -> None:
        if success:
            text = detail if len(detail) <= 80 else detail[:79] + "…"
            InfoBar.success(
                self.tr("转录测试成功"),
                self.tr("识别结果：{}").format(text),
                duration=INFOBAR_DURATION_SUCCESS,
                parent=self._toast_parent(),
            )
        else:
            InfoBar.error(
                self.tr("转录测试失败"),
                detail,
                duration=INFOBAR_DURATION_ERROR,
                parent=self._toast_parent(),
            )

    def _on_transcribe_check_error(self, message: str) -> None:
        InfoBar.error(
            self.tr("转录测试错误"), message, duration=INFOBAR_DURATION_ERROR, parent=self._toast_parent()
        )

    def check_live_caption_connection(self) -> None:
        if cfg.live_caption_provider.value in ("fun-asr", "qwen-asr") and not cfg.fun_asr_api_key.value.strip():
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请先填写百炼 API Key。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return
        config = LiveCaptionConfig(
            backend=cfg.live_caption_provider.value,
            voxgate_binary=cfg.live_caption_voxgate_binary.value,
            api_key=str(cfg.fun_asr_api_key.value or "").strip(),
            asr_model=cfg.live_caption_fun_asr_model.value,
            source_language=cfg.live_caption_source_language.value,
            translate_enabled=False,
        )
        self._run_button_thread(
            self.checkLiveCaptionButton,
            self.tr("测试转录"),
            self.tr("正在转录..."),
            LiveCaptionCheckThread(config),
            self._on_transcribe_check_finished,
            self._on_transcribe_check_error,
        )

    def check_dubbing_connection(self) -> None:
        preset_name = str(cfg.dubbing_preset.value)
        try:
            preset = get_dubbing_preset(preset_name)
        except ValueError as exc:
            InfoBar.error(self.tr("配音配置错误"), str(exc), duration=INFOBAR_DURATION_ERROR, parent=self._toast_parent())
            return

        api_key = cfg.dubbing_api_key.value.strip()
        api_base = cfg.dubbing_api_base.value.strip() or preset.api_base
        model = cfg.dubbing_model.value.strip() or preset.model
        if preset.provider != "edge" and not api_key:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("当前配音提供商需要 API Key。"),
                duration=INFOBAR_DURATION_WARNING,
                parent=self._toast_parent(),
            )
            return

        output_dir = Path(cfg.work_dir.value) / "dubbing-test"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{preset_name}.wav"
        self._run_button_thread(
            self.checkDubbingButton,
            self.tr("测试配音"),
            self.tr("正在测试..."),
            DubbingConnectionThread(
                provider=preset.provider,
                api_key=api_key if preset.provider != "edge" else "",
                api_base=api_base if preset.provider != "edge" else "",
                model=model if preset.provider != "edge" else preset.model,
                voice=preset.voice,
                output_path=str(output_path),
                style_prompt=preset.style_prompt,
            ),
            self._on_dubbing_check_finished,
            self._on_dubbing_check_error,
        )

    def _on_dubbing_check_finished(self, audio_path: str, provider: str) -> None:
        InfoBar.success(
            self.tr("配音测试成功"),
            self.tr("{provider} 已生成试听音频：{path}").format(provider=provider, path=audio_path),
            duration=INFOBAR_DURATION_SUCCESS,
            parent=self._toast_parent(),
        )

    def _on_dubbing_check_error(self, message: str) -> None:
        InfoBar.error(self.tr("配音测试失败"), message, duration=INFOBAR_DURATION_ERROR, parent=self._toast_parent())

    def _toast_parent(self):
        """toast / 弹窗的 parent。

        设置页是覆盖主窗口的子级遮罩（MaskDialogBase，非顶层窗口）。toast 必须 parent
        到这个遮罩才能盖在它之上、铺满整窗：parent 到主窗口会被遮罩盖住，parent 到内容
        卡片（self）则被裁在卡片右上角（贴着关闭叉）。独立使用时回退到 window()/self。
        """
        node = self.parent()
        while node is not None:
            if isinstance(node, MaskDialogBase):
                return node
            node = node.parent()
        return self.window() or self

    def _run_button_thread(
        self,
        button,
        idle_text: str,
        busy_text: str,
        thread: QThread,
        finished_slot,
        error_slot,
    ) -> None:
        button.setEnabled(False)
        button.setText(busy_text)

        def restore_button(*_args):
            button.setEnabled(True)
            button.setText(idle_text)
            if thread in self._threads:
                self._threads.remove(thread)

        thread.finished.connect(restore_button)
        thread.finished.connect(finished_slot)
        thread.error.connect(restore_button)
        thread.error.connect(error_slot)
        self._threads.append(thread)
        thread.start()

    def closeEvent(self, event):
        # 退出时停掉所有检查网络线程（LLM/转录/配音，分钟级）：main_window.closeEvent
        # 会 close() 本页，running QThread 被销毁触发 qFatal。只读网络线程，terminate 安全。
        for thread in list(self._threads):
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)
        self._threads.clear()
        super().closeEvent(event)

    @staticmethod
    def _llm_provider_specs() -> dict[LLMServiceEnum, dict[str, Any]]:
        return {
            LLMServiceEnum.OPENAI: {
                "api_key": cfg.openai_api_key,
                "api_base": cfg.openai_api_base,
                "model": cfg.openai_model,
                "model_options": cfg.openai_model_options,
                "default_base": "https://api.openai.com/v1",
                "models": [
                    "gemini-2.5-pro",
                    "gpt-5",
                    "claude-sonnet-4-5-20250929",
                    "gemini-2.5-flash",
                    "claude-haiku-4-5-20251001",
                ],
            },
            LLMServiceEnum.SILICON_CLOUD: {
                "api_key": cfg.silicon_cloud_api_key,
                "api_base": cfg.silicon_cloud_api_base,
                "model": cfg.silicon_cloud_model,
                "model_options": cfg.silicon_cloud_model_options,
                "default_base": "https://api.siliconflow.cn/v1",
                "models": ["moonshotai/Kimi-K2-Instruct-0905", "deepseek-ai/DeepSeek-V3"],
            },
            LLMServiceEnum.DEEPSEEK: {
                "api_key": cfg.deepseek_api_key,
                "api_base": cfg.deepseek_api_base,
                "model": cfg.deepseek_model,
                "model_options": cfg.deepseek_model_options,
                "default_base": "https://api.deepseek.com/v1",
                "models": ["deepseek-chat", "deepseek-reasoner"],
            },
            LLMServiceEnum.OLLAMA: {
                "api_key": cfg.ollama_api_key,
                "api_base": cfg.ollama_api_base,
                "model": cfg.ollama_model,
                "model_options": cfg.ollama_model_options,
                "default_base": "http://localhost:11434/v1",
                "models": ["qwen3:8b"],
            },
            LLMServiceEnum.LM_STUDIO: {
                "api_key": cfg.lm_studio_api_key,
                "api_base": cfg.lm_studio_api_base,
                "model": cfg.lm_studio_model,
                "model_options": cfg.lm_studio_model_options,
                "default_base": "http://localhost:1234/v1",
                "models": ["qwen3:8b"],
            },
            LLMServiceEnum.GEMINI: {
                "api_key": cfg.gemini_api_key,
                "api_base": cfg.gemini_api_base,
                "model": cfg.gemini_model,
                "model_options": cfg.gemini_model_options,
                "default_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash-lite"],
            },
            LLMServiceEnum.CHATGLM: {
                "api_key": cfg.chatglm_api_key,
                "api_base": cfg.chatglm_api_base,
                "model": cfg.chatglm_model,
                "model_options": cfg.chatglm_model_options,
                "default_base": "https://open.bigmodel.cn/api/paas/v4",
                "models": ["glm-4-plus", "glm-4-air-250414", "glm-4-flash"],
            },
        }

    def _llm_model_options(self, service: LLMServiceEnum) -> list[str]:
        provider = self.llmProviderSpecs.get(service)
        if provider is None:
            return []
        return self._llm_model_options_for_provider(provider)

    def _llm_model_options_for_provider(self, provider: dict[str, Any]) -> list[str]:
        cached = self._clean_model_options(provider["model_options"].value)
        if cached:
            return cached
        return self._clean_model_options(provider["models"])

    def _apply_llm_model_options(self, service: LLMServiceEnum, models: list[str]) -> None:
        controls = self.llmProviderControls.get(service)
        if controls is None:
            return
        model_control = controls["model"]
        current = model_control.currentText().strip()
        model_control.setItems(models)
        if not current and models:
            model_control.setValue(models[0])
            cfg.set(model_control.config_item, models[0])

    def _save_llm_model_options(self, service: LLMServiceEnum, models: list[str]) -> None:
        provider = self.llmProviderSpecs.get(service)
        if provider is None:
            return
        cfg.set(provider["model_options"], self._clean_model_options(models))

    @staticmethod
    def _clean_model_options(models: Any) -> list[str]:
        if not isinstance(models, list):
            return []
        options: list[str] = []
        seen: set[str] = set()
        for item in models:
            model = str(item or "").strip()
            if not model or model in seen:
                continue
            seen.add(model)
            options.append(model)
        return options

    @staticmethod
    def _dubbing_provider_options():
        from videocaptioner.ui.common.dubbing_options import DUBBING_PROVIDERS

        return DUBBING_PROVIDERS

    @staticmethod
    def _two_controls(left, right, parent):
        container = QWidget(parent)
        # 容器必须显式透明，否则在 qfluent 暗色样式下被涂成黑块，
        # 两个控件之间会露出一条黑色背景缝。
        container.setObjectName("settingsControlPair")
        container.setAttribute(Qt.WA_StyledBackground, True)  # type: ignore[arg-type]
        container.setStyleSheet(
            "QWidget#settingsControlPair { background: transparent; }"
        )
        container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if left.objectName() == "settingsValueLabel" and left.maximumWidth() > 10000:
            left.setFixedWidth(CONTROL_WIDTH)
        left.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(left)
        layout.addWidget(right)
        return container


class DubbingConnectionThread(QThread):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(
        self,
        provider: str,
        api_key: str,
        api_base: str,
        model: str,
        voice: str,
        output_path: str,
        style_prompt: str = "",
    ):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.voice = voice
        self.output_path = output_path
        self.style_prompt = style_prompt

    def run(self) -> None:
        try:
            core_config = build_dubbing_config(
                provider=self.provider,
                api_key=self.api_key,
                api_base=self.api_base,
                model=self.model,
                voice=self.voice,
                style_prompt=self.style_prompt,
            )
            response_format = core_config.response_format
            if core_config.provider == "gemini":
                response_format = "wav"
            elif core_config.provider == "edge":
                response_format = "mp3"
            synthesizer = create_speech_synthesizer(
                SpeechProviderConfig(
                    provider=core_config.provider,
                    api_key=core_config.api_key,
                    base_url=core_config.base_url,
                    model=core_config.model,
                    default_voice=core_config.voice,
                    response_format=response_format,
                    sample_rate=core_config.sample_rate,
                    speed=core_config.speed,
                    gain=core_config.gain,
                    timeout=core_config.timeout,
                    style_prompt=core_config.style_prompt,
                )
            )
            result = synthesizer.synthesize(
                SynthesisRequest(
                    text="你好，这是卡卡字幕助手的配音测试。",
                    output_path=self.output_path,
                    voice=core_config.voice,
                    style_prompt=core_config.style_prompt or None,
                )
            )
            self.finished.emit(result.output_path, core_config.provider)
        except Exception as exc:
            self.error.emit(str(exc))


class TranscribeCheckThread(QThread):
    """跑一次真实短音频转录（core.asr.check.check_transcribe）。"""

    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            result = check_transcribe(self.config)
            self.finished.emit(result.success, result.detail)
        except Exception as exc:
            self.error.emit(str(exc))


class LiveCaptionCheckThread(QThread):
    """跑一次真实短音频实时转录（core.realtime.check.check_live_caption）。"""

    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            result = check_live_caption(self.config)
            self.finished.emit(result.success, result.detail)
        except Exception as exc:
            self.error.emit(str(exc))


class LLMConnectionThread(QThread):
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, api_base: str, api_key: str, model: str):
        super().__init__()
        self.api_base = api_base
        self.api_key = api_key
        self.model = model

    def run(self) -> None:
        try:
            success, message = check_llm_connection(self.api_base, self.api_key, self.model)
            self.finished.emit(success, message)
        except Exception as exc:
            self.error.emit(str(exc))


class LLMModelLoadThread(QThread):
    finished = pyqtSignal(object, list)
    error = pyqtSignal(str)

    def __init__(self, service: LLMServiceEnum, api_base: str, api_key: str):
        super().__init__()
        self.service = service
        self.api_base = api_base
        self.api_key = api_key

    def run(self) -> None:
        try:
            models = get_available_models(self.api_base, self.api_key)
            self.finished.emit(self.service, models)
        except Exception as exc:
            self.error.emit(str(exc))


class SettingsDialog(MaskDialogBase):
    """设置弹窗：为设置定制的大尺寸 modal（不复用通用确认框 AppDialog/ConfirmDialog）。

    遮罩 + 居中大卡片，卡片内嵌 SettingInterface（左侧分类侧栏 + 右侧滚动内容）。
    侧栏顶部「返回应用」即关闭；Esc 同样关闭。长生命周期单例复用：保证内部 check
    线程的 closeEvent 终止契约（见 SettingInterface.closeEvent）继续有效。
    """

    CARD_RADIUS = 16

    def __init__(self, parent=None):
        main_window = parent.window() if parent is not None else None
        super().__init__(main_window)
        self._main_window = main_window
        # 卡片阴影是静态的（淡入/淡出只动遮罩、不动卡片，见 showEvent/done），
        # 不再每帧重栅格，因此可以用更柔和的大 blur 让卡片更有浮起感。
        self.setShadowEffect(48, (0, 12), QColor(0, 0, 0, 130))
        self.setMaskColor(QColor(0, 0, 0, 150))
        self.setClosableOnMaskClicked(True)  # 点遮罩空白处关闭设置弹窗
        # 卡片按固定尺寸居中，而非被遮罩拉满
        self._hBoxLayout.setAlignment(self.widget, Qt.AlignCenter)  # type: ignore[arg-type]

        card = self.widget
        card.setObjectName("settingsDialogCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.settingInterface = SettingInterface(card)
        self.settingInterface.backRequested.connect(lambda: self.done(0))
        self.settingInterface.openStylePageRequested.connect(self._go_subtitle_style)
        layout.addWidget(self.settingInterface)
        # 右上角关闭叉（更普适）：覆盖在内容之上，点它 / Esc / 点遮罩都能关
        self.closeButton = RoundIconButton(AppIcon.CLOSE, parent=card)
        self.closeButton.clicked.connect(lambda: self.done(0))
        self._sync_card_style()

    def _go_subtitle_style(self) -> None:
        """关闭设置弹窗并切到主窗口的字幕样式 tab。"""
        self.done(0)
        target = getattr(self._main_window, "subtitleStyleInterface", None)
        switch_to = getattr(self._main_window, "switchTo", None)
        if target is not None and callable(switch_to):
            switch_to(target)

    def open_at(self, page_key: str) -> bool:
        """切到指定分类并弹出；分类无效则不弹、返回 False。"""
        if not self.settingInterface.setCurrentPage(page_key):
            return False
        self.exec()
        return True

    def showEvent(self, event):  # noqa: N802
        self._resize_card()
        # 关键优化：不走 MaskDialogBase 的「整窗淡入」——它给整窗（遮罩 + 940x680
        # 卡片 + 阴影）套一个 opacity 动画，每帧都要把大卡片重栅格化（实测约 9ms/帧，
        # 淡入期间累计重栅格 ≈100ms+），表现为「右侧内容像是慢慢才加载出来」。
        # 改为只淡入遮罩（纯色矩形，约 0.4ms/帧），卡片即时满不透明出现：内容立刻可见、
        # 开/关都跟手。
        QDialog.showEvent(self, event)
        self._fade_mask(0.0, 1.0, 150)

    def done(self, code):  # noqa: N802
        # 关闭同理：只淡出遮罩，不对大卡片做 opacity 动画（点遮罩空白处关闭也因此跟手）。
        self._fade_mask(1.0, 0.0, 110, on_finish=lambda: QDialog.done(self, code))

    def _fade_mask(self, start: float, end: float, duration: int, on_finish=None) -> None:
        effect = QGraphicsOpacityEffect(self.windowMask)
        self.windowMask.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: self.windowMask.setGraphicsEffect(None))
        if on_finish is not None:
            animation.finished.connect(on_finish)
        animation.start()
        self._mask_animation = animation  # 持引用，防止动画被回收中断

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._resize_card()

    def _resize_card(self) -> None:
        host = self.parent()
        if host is not None and host.width() > 0:
            pw, ph = host.width(), host.height()
        else:
            pw, ph = self.width() or 1050, self.height() or 800
        w = max(720, min(940, int(pw * 0.88)))
        h = max(520, min(680, int(ph * 0.90)))
        self.widget.setFixedSize(w, h)
        # 等效 overflow:hidden——圆角裁剪，使内嵌内容的直角不戳出卡片圆角
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), self.CARD_RADIUS, self.CARD_RADIUS)
        self.widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
        # 关闭叉钉在右上角，始终压在最上层
        self.closeButton.move(w - self.closeButton.width() - 14, 14)
        self.closeButton.raise_()

    def _sync_card_style(self) -> None:
        palette = app_palette()
        self.widget.setStyleSheet(
            f"QWidget#settingsDialogCard {{ background: {palette.bg};"
            f" border-radius: {self.CARD_RADIUS}px; }}"
        )
