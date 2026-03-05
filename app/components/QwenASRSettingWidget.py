from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    InfoBar,
    InfoBarPosition,
    PushSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
    SwitchSettingCard,
)
from qfluentwidgets import FluentIcon as FIF

from ..common.config import cfg
from ..config import ASSETS_PATH
from ..core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from ..core.entities import TranscribeLanguageEnum
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .LineEditSettingCard import LineEditSettingCard
from .SpinBoxSettingCard import SpinBoxSettingCard

DEFAULT_QWEN_MODELS = [
    "Qwen/Qwen3-ASR-0.6B",
    "Qwen/Qwen3-ASR-1.7B",
]

DEFAULT_ALIGNER_MODELS = [
    "Qwen/Qwen3-ForcedAligner-0.6B",
]


class QwenASRSettingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self._connect_signals()
        self._update_backend_dependent_ui(cfg.qwen_asr_backend.value)

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        self.scrollArea = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)  # type: ignore
        self.scrollArea.setStyleSheet(
            "QScrollArea{background: transparent; border: none}"
        )

        self.container = QWidget(self)
        self.container.setStyleSheet("QWidget{background: transparent}")
        self.containerLayout = QVBoxLayout(self.container)

        self.setting_group = SettingCardGroup(self.tr("Qwen ASR 设置"), self)

        self.backend_card = ComboBoxSettingCard(
            cfg.qwen_asr_backend,
            FIF.CLOUD,
            self.tr("推理后端"),
            self.tr("transformers(本地) / vllm(服务)"),
            ["transformers", "vllm"],
            self.setting_group,
        )

        self.model_card = EditComboBoxSettingCard(
            cfg.qwen_asr_model,
            FIF.ROBOT,
            self.tr("ASR 模型"),
            self.tr("可直接输入 HuggingFace 模型名"),
            DEFAULT_QWEN_MODELS,
            self.setting_group,
        )

        self.aligner_model_card = EditComboBoxSettingCard(
            cfg.qwen_asr_aligner_model,
            FIF.TAG,
            self.tr("对齐器模型"),
            self.tr("词级时间戳使用的 ForcedAligner 模型"),
            DEFAULT_ALIGNER_MODELS,
            self.setting_group,
        )

        self.word_timestamp_card = SwitchSettingCard(
            FIF.UNIT,
            self.tr("词级时间戳"),
            self.tr("开启后输出词/字级时间戳（需 ForcedAligner）"),
            cfg.qwen_asr_word_timestamp,
            self.setting_group,
        )
        self.vocal_separation_card = SwitchSettingCard(
            FIF.MUSIC,
            self.tr("人声分离"),
            self.tr("转录前尝试分离人声（需安装 demucs）"),
            cfg.qwen_asr_vocal_separation,
            self.setting_group,
        )
        self.timestamp_mode_card = ComboBoxSettingCard(
            cfg.qwen_asr_timestamp_mode,
            FIF.HISTORY,
            self.tr("时间戳模式"),
            self.tr("forced_aligner_word(词级) / segment_only(分段)"),
            ["forced_aligner_word", "segment_only"],
            self.setting_group,
        )
        self.compute_dtype_card = ComboBoxSettingCard(
            cfg.qwen_asr_compute_dtype,
            FIF.FILTER,
            self.tr("计算精度"),
            self.tr("bfloat16(推荐) / float16(更快) / float32(更稳)"),
            ["bfloat16", "float16", "float32"],
            self.setting_group,
        )
        self.language_mode_card = ComboBoxSettingCard(
            cfg.qwen_asr_language_mode,
            FIF.LANGUAGE,
            self.tr("语言模式"),
            self.tr("auto(自动检测) / force(使用下方 Qwen 强制语言)"),
            ["auto", "force"],
            self.setting_group,
        )
        self.force_language_card = ComboBoxSettingCard(
            cfg.qwen_asr_force_language,
            FIF.LANGUAGE,
            self.tr("Qwen 强制语言"),
            self.tr("仅在语言模式为 force 时生效"),
            [lang.value for lang in TranscribeLanguageEnum],
            self.setting_group,
        )
        self.timestamp_rounding_card = ComboBoxSettingCard(
            cfg.qwen_asr_timestamp_rounding,
            FIF.FILTER,
            self.tr("时间戳取整"),
            self.tr("round(四舍五入) / floor(向下取整)"),
            ["round", "floor"],
            self.setting_group,
        )

        self.api_base_card = LineEditSettingCard(
            cfg.qwen_asr_api_base,
            FIF.LINK,
            self.tr("API Base URL"),
            self.tr("vllm/OpenAI 兼容地址，例: http://127.0.0.1:8000/v1"),
            "http://127.0.0.1:8000/v1",
            self.setting_group,
        )

        self.api_key_card = LineEditSettingCard(
            cfg.qwen_asr_api_key,
            FIF.FINGERPRINT,
            self.tr("API Key"),
            self.tr("vllm/OpenAI 兼容 API Key"),
            "EMPTY",
            self.setting_group,
        )

        self.prompt_card = LineEditSettingCard(
            cfg.qwen_asr_prompt,
            FIF.CHAT,
            self.tr("提示词"),
            self.tr("可选：术语上下文，提升专有名词识别"),
            "",
            self.setting_group,
        )

        self.max_tokens_card = SpinBoxSettingCard(
            cfg.qwen_asr_max_new_tokens,
            FIF.FILTER,
            self.tr("Max New Tokens"),
            self.tr("生成上限，过小可能截断，过大可能变慢"),
            minimum=16,
            maximum=8192,
            parent=self.setting_group,
        )
        self.check_connection_card = PushSettingCard(
            self.tr("测试连接"),
            FIF.CONNECT,
            self.tr("测试 Qwen ASR 连接"),
            self.tr("点击测试 vllm/OpenAI 兼容接口"),
            self.setting_group,
        )

        self.setting_group.addSettingCard(self.backend_card)
        self.setting_group.addSettingCard(self.model_card)
        self.setting_group.addSettingCard(self.aligner_model_card)
        self.setting_group.addSettingCard(self.word_timestamp_card)
        self.setting_group.addSettingCard(self.vocal_separation_card)
        self.setting_group.addSettingCard(self.timestamp_mode_card)
        self.setting_group.addSettingCard(self.compute_dtype_card)
        self.setting_group.addSettingCard(self.language_mode_card)
        self.setting_group.addSettingCard(self.force_language_card)
        self.setting_group.addSettingCard(self.timestamp_rounding_card)
        self.setting_group.addSettingCard(self.api_base_card)
        self.setting_group.addSettingCard(self.api_key_card)
        self.setting_group.addSettingCard(self.prompt_card)
        self.setting_group.addSettingCard(self.max_tokens_card)
        self.setting_group.addSettingCard(self.check_connection_card)

        self.containerLayout.addWidget(self.setting_group)
        self.containerLayout.addStretch(1)

        self.backend_card.comboBox.setMinimumWidth(200)
        self.model_card.comboBox.setMinimumWidth(200)
        self.aligner_model_card.comboBox.setMinimumWidth(200)
        self.timestamp_mode_card.comboBox.setMinimumWidth(200)
        self.compute_dtype_card.comboBox.setMinimumWidth(200)
        self.language_mode_card.comboBox.setMinimumWidth(200)
        self.force_language_card.comboBox.setMinimumWidth(200)
        self.timestamp_rounding_card.comboBox.setMinimumWidth(200)
        self.api_base_card.lineEdit.setMinimumWidth(200)
        self.api_key_card.lineEdit.setMinimumWidth(200)
        self.prompt_card.lineEdit.setMinimumWidth(200)

        self.scrollArea.setWidget(self.container)
        self.scrollArea.setWidgetResizable(True)
        self.main_layout.addWidget(self.scrollArea)

    def _connect_signals(self):
        self.backend_card.comboBox.currentTextChanged.connect(
            self._update_backend_dependent_ui
        )
        self.language_mode_card.comboBox.currentTextChanged.connect(
            self._update_language_mode_ui
        )
        self.check_connection_card.clicked.connect(self._on_check_connection)
        self._update_language_mode_ui(self.language_mode_card.comboBox.currentText())

    def _update_backend_dependent_ui(self, backend: str):
        is_vllm = backend == "vllm"
        self.api_base_card.setVisible(is_vllm)
        self.api_key_card.setVisible(is_vllm)
        self.prompt_card.setVisible(is_vllm)
        self.check_connection_card.setVisible(is_vllm)

    def _update_language_mode_ui(self, language_mode: str):
        self.force_language_card.setEnabled(language_mode == "force")

    def _on_check_connection(self):
        if self.backend_card.comboBox.currentText() != "vllm":
            InfoBar.warning(
                self.tr("当前后端不支持"),
                self.tr("仅 vllm 后端需要 API 连通性测试"),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
            return

        base_url = self.api_base_card.lineEdit.text().strip()
        api_key = self.api_key_card.lineEdit.text().strip()
        model = self.model_card.comboBox.currentText().strip()
        if not base_url or not api_key or not model:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr("请填写 API Base URL、API Key、模型名"),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
            return

        self.check_connection_card.button.setEnabled(False)
        self.check_connection_card.button.setText(self.tr("测试中..."))
        self.connection_thread = QwenConnectionThread(base_url, api_key, model)
        self.connection_thread.finished.connect(self._on_check_connection_finished)
        self.connection_thread.error.connect(self._on_check_connection_error)
        self.connection_thread.start()

    def _on_check_connection_finished(self, success: bool, message: str):
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))
        if success:
            InfoBar.success(
                self.tr("连接成功"),
                message,
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
        else:
            InfoBar.error(
                self.tr("连接失败"),
                message,
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )

    def _on_check_connection_error(self, message: str):
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))
        InfoBar.error(
            self.tr("连接错误"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.BOTTOM,
            parent=self.window(),
        )


class QwenConnectionThread(QThread):
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, base_url: str, api_key: str, model: str):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self):
        try:
            from openai import OpenAI

            from app.core.llm.client import normalize_base_url

            test_audio = Path(ASSETS_PATH) / "en.mp3"
            if not test_audio.exists():
                self.finished.emit(False, f"测试音频不存在: {test_audio}")
                return

            client = OpenAI(
                base_url=normalize_base_url(self.base_url),
                api_key=self.api_key,
                timeout=20,
            )
            with open(test_audio, "rb") as f:
                resp = client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )

            text = getattr(resp, "text", "") or "ok"
            self.finished.emit(True, f"API 可用，返回: {text[:50]}")
        except Exception as e:
            self.error.emit(str(e))
