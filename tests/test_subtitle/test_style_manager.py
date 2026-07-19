from videocaptioner.core.subtitle.style_manager import (
    AssSecondaryStyle,
    AssSubtitleStyle,
    RoundedSubtitleStyle,
    StyleSource,
    SubtitleRenderer,
    SubtitleStylePreset,
    list_styles,
    load_style,
    normalize_style_id,
    preset_from_json,
    save_user_style,
)


def _ass_bold_flags(style: AssSubtitleStyle) -> tuple[str, str]:
    """返回 (主字幕 bold, 副字幕 bold) 两个 ASS Style 行的 Bold 字段。"""
    lines = style.to_ass_string().splitlines()
    default = next(line for line in lines if line.startswith("Style: Default,"))
    secondary = next(line for line in lines if line.startswith("Style: Secondary,"))
    return default.split(",")[7], secondary.split(",")[7]


def test_primary_and_secondary_bold_are_independent():
    style = AssSubtitleStyle(bold=True, secondary=AssSecondaryStyle(bold=False))
    assert _ass_bold_flags(style) == ("-1", "0")
    style = AssSubtitleStyle(bold=False, secondary=AssSecondaryStyle(bold=True))
    assert _ass_bold_flags(style) == ("0", "-1")


def test_legacy_style_secondary_bold_inherits_primary():
    # 老样式只存主字幕 bold（当时主副共用）；副字幕缺省时应沿用主字幕，渲染不变
    preset = preset_from_json(
        {"renderer": "ass", "bold": False, "secondary": {"font_size": 20}},
        source=StyleSource.USER,
    )
    assert preset.style.bold is False
    assert preset.style.secondary is not None
    assert preset.style.secondary.bold is False


def test_secondary_bold_round_trips_through_json():
    preset = preset_from_json(
        {"renderer": "ass", "bold": False, "secondary": {"font_size": 20, "bold": True}},
        source=StyleSource.USER,
    )
    assert preset.style.secondary.bold is True
    assert preset.to_json_dict()["secondary"]["bold"] is True


def test_builtin_styles_are_typed_and_grouped_by_renderer():
    ass_styles = list_styles(renderer="ass", include_user=False)
    rounded_styles = list_styles(renderer="rounded", include_user=False)

    assert {style.id for style in ass_styles} >= {
        "ass/default",
        "ass/anime",
        "ass/vertical",
    }
    assert {style.id for style in rounded_styles} >= {"rounded/default"}
    assert all(isinstance(style.style, AssSubtitleStyle) for style in ass_styles)
    assert all(isinstance(style.style, RoundedSubtitleStyle) for style in rounded_styles)


def test_prefixed_id_wins_over_conflicting_renderer_config():
    # 配置漂移场景：样式还是 ass/xxx，渲染模式已切到 rounded。
    # 无 renderer 要求时按前缀解析成功；显式要求另一渲染器时按未命中返回
    # None（调用方回退默认），而不是在错误列表里找不到导致空样式→乱码。
    assert load_style("ass/anime") is not None
    assert load_style("ass/anime", renderer=SubtitleRenderer.ROUNDED) is None
    assert load_style("ass/anime", renderer=SubtitleRenderer.ASS) is not None


def test_synthesis_config_never_uses_empty_style():
    from videocaptioner.core.application.app_config import AppConfig, SynthesisSettings
    from videocaptioner.core.application.task_builder import TaskBuilder
    from videocaptioner.core.entities import SubtitleRenderModeEnum

    config = AppConfig(
        synthesis=SynthesisSettings(
            render_mode=SubtitleRenderModeEnum.ROUNDED_BG, style_id="ass/anime"
        )
    )
    synth = TaskBuilder(config).create_synthesis_config()
    # 渲染管线跟随样式前缀（ass），并且样式串非空
    assert synth.render_mode == SubtitleRenderModeEnum.ASS_STYLE
    assert synth.ass_style.strip()


def test_load_style_uses_renderer_to_disambiguate_default():
    ass = load_style("default", renderer=SubtitleRenderer.ASS)
    rounded = load_style("default", renderer=SubtitleRenderer.ROUNDED)

    assert ass is not None
    assert rounded is not None
    assert ass.id == "ass/default"
    assert rounded.id == "rounded/default"
    assert isinstance(ass.style, AssSubtitleStyle)
    assert isinstance(rounded.style, RoundedSubtitleStyle)


def test_save_user_style_does_not_modify_builtin_styles(tmp_path):
    user_preset = SubtitleStylePreset(
        id="rounded/my-style",
        name="my-style",
        renderer=SubtitleRenderer.ROUNDED,
        source=StyleSource.USER,
        style=RoundedSubtitleStyle(font_name="Noto Sans SC", font_size=44),
    )

    saved = save_user_style(user_preset, styles_dir=tmp_path)
    loaded = load_style("rounded/my-style", styles_dir=tmp_path, renderer="rounded")
    builtin = load_style("rounded/default", styles_dir=tmp_path, renderer="rounded")

    assert saved == tmp_path / "rounded" / "my-style.json"
    assert loaded is not None
    assert loaded.source == StyleSource.USER
    assert loaded.to_rounded_dict()["font_size"] == 44
    assert builtin is not None
    assert builtin.source == StyleSource.BUILTIN


def test_normalize_style_id_accepts_legacy_names():
    assert normalize_style_id("default", "ass") == "ass/default"
    assert normalize_style_id("ass-default", "rounded") == "ass/default"
    assert normalize_style_id("rounded-default", "ass") == "rounded/default"
    assert normalize_style_id("rounded/default", "ass") == "rounded/default"
