"""配置链路一致性回归（2026-06 代码质量审查 CF-M1/M2/H2/H3）。

锁住三件事，防止 DEFAULTS / SettingField / dataclass / CLI 适配器再次漂移：
- 曾经的孤儿键补进 DEFAULTS 后，`config set` 能按声明类型解析（CF-M2）；
- subtitle_mode 与 soft_subtitle 默认同义，CLI/GUI 出厂行为一致（CF-H2）；
- CLI 适配器在全新配置下产出的默认值与 config_store DEFAULTS 对齐（CF-M1）；
- CLI 适配器读取 faster_whisper.program / one_word，不再硬编码（CF-H3）。
"""

from pathlib import Path

import pytest

from videocaptioner.cli.config_adapter import app_config_from_cli
from videocaptioner.core.application.config_store import (
    DEFAULTS,
    build_config,
    get_nested,
    parse_value,
)
from videocaptioner.core.entities import (
    FasterWhisperModelEnum,
    SubtitleRenderModeEnum,
    VadMethodEnum,
    WhisperModelEnum,
)

# 用不存在的路径隔离用户/CI 本地配置，build_config 只剩 DEFAULTS(+env)。
_NONEXISTENT = Path("/tmp/vc-config-consistency-nonexistent.toml")


def _fresh_config() -> dict:
    return build_config(config_path=_NONEXISTENT)


class TestOrphanKeysParse:
    """CF-M2：6 个曾经的孤儿键补进 DEFAULTS 后，config set 按类型解析。"""

    @pytest.mark.parametrize(
        "key",
        [
            "ui.transcribe_panel_collapsed",
            "ui.subtitle_panel_collapsed",
            "ui.synthesis_panel_collapsed",
            "transcribe.word_timestamp",
        ],
    )
    def test_bool_orphan_keys_parse_as_bool(self, key):
        # 过去 parse_value 查不到键直接返回字符串 "false"，BoolValidator 当真 → 反向。
        assert get_nested(DEFAULTS, key) is False
        assert parse_value("false", key) is False
        assert parse_value("true", key) is True

    def test_batch_concurrency_parses_as_int(self):
        assert get_nested(DEFAULTS, "ui.batch_concurrency") == 1
        assert parse_value("2", "ui.batch_concurrency") == 2

    def test_batch_mode_present(self):
        assert get_nested(DEFAULTS, "ui.batch_mode") == "full"


class TestSubtitleModeConsistency:
    """CF-H2：subtitle_mode 与 soft_subtitle 默认同义（硬字幕）。"""

    def test_defaults_agree(self):
        assert get_nested(DEFAULTS, "synthesize.soft_subtitle") is False
        assert get_nested(DEFAULTS, "synthesize.subtitle_mode") == "hard"
        ac = app_config_from_cli(_fresh_config())
        assert ac.synthesis.soft_subtitle is False


class TestCliDefaultsMatchStore:
    """CF-M1：CLI 适配器在全新配置下产出默认值与 config_store DEFAULTS 对齐。"""

    def test_subtitle_defaults(self):
        ac = app_config_from_cli(_fresh_config())
        assert ac.subtitle.thread_num == get_nested(DEFAULTS, "subtitle.thread_num") == 10
        assert ac.subtitle.batch_size == get_nested(DEFAULTS, "subtitle.batch_size") == 10
        assert ac.subtitle.need_optimize is False
        # 断句默认开启：不断句 ASR 长句会得到超长字幕行（无 LLM 时规则回退）
        assert ac.subtitle.need_split is True
        assert ac.subtitle.max_word_count_cjk == 28
        assert ac.subtitle.max_word_count_english == 20

    def test_transcribe_defaults(self):
        ac = app_config_from_cli(_fresh_config())
        assert ac.transcribe.faster_whisper_model == FasterWhisperModelEnum.TINY
        assert ac.transcribe.whisper_model == WhisperModelEnum.TINY
        assert ac.transcribe.faster_whisper_vad_method == VadMethodEnum.SILERO_V4
        assert ac.transcribe.faster_whisper_vad_threshold == 0.4
        assert ac.transcribe.faster_whisper_device == "auto"

    def test_render_mode_default(self):
        ac = app_config_from_cli(_fresh_config())
        assert ac.synthesis.render_mode == SubtitleRenderModeEnum.ROUNDED_BG


class TestCliReadsFasterWhisperKeys:
    """CF-H3：CLI 适配器读取 faster_whisper.program / one_word（不再硬编码 True）。"""

    def test_program_and_one_word_from_config(self):
        cfg = _fresh_config()
        cfg["transcribe"]["faster_whisper"]["program"] = "custom-fw"
        cfg["transcribe"]["faster_whisper"]["one_word"] = False
        ac = app_config_from_cli(cfg)
        assert ac.transcribe.faster_whisper_program == "custom-fw"
        assert ac.transcribe.faster_whisper_one_word is False
