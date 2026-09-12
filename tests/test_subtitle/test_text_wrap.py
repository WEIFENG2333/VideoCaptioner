"""断行核心与 ASS 换行链路的回归测试。

宽度断言全部基于 PIL 实测像素宽——断行正确性的唯一标准是
「每行实测宽 ≤ 可用宽」，行数与断点位置只锁行为特征。
"""

import pytest

from videocaptioner.core.subtitle.ass_utils import auto_wrap_ass_file, parse_ass_info
from videocaptioner.core.subtitle.font_utils import get_ass_to_pil_ratio, get_font
from videocaptioner.core.subtitle.text_utils import wrap_text

FONT = get_font(40, "LXGW WenKai")

CN_LONG = (
    "数学，是书写宇宙规律的语言，也是人类理性思维最璀璨的结晶，它贯穿了整个科学发展的历史进程。"
)
EN_LONG = (
    "Mathematics is the language in which the laws of the universe are written, "
    "the finest crystallization of human reason."
)
MIXED = "我们使用 Transformer 架构进行 self-attention 计算，效率提升了大约 300% 左右。"
URL = "https://github.com/WEIFENG2333/VideoCaptioner/releases/download/v2.3.0/app.zip"


def line_width(line: str, spacing: float = 0.0) -> float:
    bbox = FONT.getbbox(line)
    width = bbox[2] - bbox[0]
    if spacing > 0 and len(line) > 1:
        width += spacing * (len(line) - 1)
    return width


@pytest.mark.parametrize("text", [CN_LONG, EN_LONG, MIXED, URL])
@pytest.mark.parametrize("max_width", [400, 700, 1200])
def test_no_line_exceeds_max_width(text, max_width):
    lines = wrap_text(text, FONT, max_width)
    assert lines
    for line in lines:
        assert line_width(line) <= max_width, f"越界: {line!r}"


def test_spacing_participates_in_measurement():
    spacing = 6.0
    lines = wrap_text(CN_LONG, FONT, 700, spacing=spacing)
    for line in lines:
        assert line_width(line, spacing) <= 700


def test_short_text_stays_single_line():
    assert wrap_text("短文本", FONT, 1000) == ["短文本"]


def test_balanced_lines_are_similar_width():
    lines = wrap_text(CN_LONG, FONT, 900)
    assert len(lines) >= 2
    widths = [line_width(line) for line in lines]
    # 平衡断行：最窄行不应低于最宽行的 55%（贪心散行时尾行常常 <30%）
    assert min(widths) / max(widths) > 0.55


def test_no_line_starts_with_closing_punctuation():
    for max_width in (300, 500, 800, 1100):
        for line in wrap_text(CN_LONG, FONT, max_width):
            assert line[0] not in "。，、！？；：）」』", f"避头失败: {line!r}"


def test_english_words_not_split_when_avoidable():
    lines = wrap_text(EN_LONG, FONT, 700)
    for line in lines:
        for word in line.split():
            assert word in EN_LONG, f"单词被拆: {word!r}"


def test_oversized_token_is_hard_split():
    lines = wrap_text(URL, FONT, 400)
    assert len(lines) >= 2
    for line in lines:
        assert line_width(line) <= 400


def test_wenkai_ratio_uses_real_font_metrics():
    # 文楷实测比值 1.317，家族名与文件名不同——按文件名找会错落到 1.448
    ratio = get_ass_to_pil_ratio("LXGW WenKai")
    assert abs(ratio - 1.317) < 0.02


ASS_DOC = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,LXGW WenKai,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0.2,0,1,2.0,0,2,54,54,28,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,{cn}
Dialogue: 0,0:00:02.00,0:00:04.00,Default,,200,200,0,,{cn}
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,已有换行的\\N保持不动
Dialogue: 0,0:00:06.00,0:00:08.00,Default,,0,0,0,,{{\\pos(100,100)}}带标签的不动
"""


def test_auto_wrap_respects_margins(tmp_path):
    src = tmp_path / "in.ass"
    src.write_text(ASS_DOC.format(cn=CN_LONG), encoding="utf-8")
    auto_wrap_ass_file(str(src))
    content = src.read_text(encoding="utf-8")
    dialogues = [ln for ln in content.splitlines() if ln.startswith("Dialogue:")]

    info = parse_ass_info(content)
    style = info.get_style("Default")
    ratio = get_ass_to_pil_ratio(style.font_name)
    font = get_font(int(round(style.font_size / ratio)), style.font_name)

    def widths(dialogue_line: str, spacing: float):
        text = dialogue_line.split(",", 9)[9]
        for line in text.split("\\N"):
            bbox = font.getbbox(line)
            yield bbox[2] - bbox[0] + spacing * max(0, len(line) - 1)

    # 样式边距：可用宽 1080-54*2；Dialogue 覆写边距：1080-200*2
    for w in widths(dialogues[0], style.spacing):
        assert w <= 1080 - 54 * 2
    for w in widths(dialogues[1], style.spacing):
        assert w <= 1080 - 200 * 2
    assert "\\N" in dialogues[1]

    assert dialogues[2].endswith("已有换行的\\N保持不动")
    assert dialogues[3].endswith("带标签的不动")
