"""双语字幕文件的"行序即布局"契约测试（无需视频/LLM）。

回归防护：subtitle 步骤按 layout 把双语行序落盘（如 target-above → 译文在第 1 行）；
synthesize 读回后 text/translated_text 退化为"行1/行2"位置语义，若再套 TRANSLATE_ON_TOP
会二次翻转已排好版的文件。resolve_layout_from_file 把这种情况归一到文件行序。
"""

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import SubtitleLayoutEnum

# subtitle --layout target-above(译文在上) 落盘的样子：中文(译文)在第 1 行，英文在第 2 行。
_BILINGUAL_SRT = (
    "1\n00:00:01,000 --> 00:00:02,000\n嘿，大家今天怎么样？\nHey, how's everyone doing today?\n\n"
    "2\n00:00:02,000 --> 00:00:03,000\n会议还顺利吗？\nHaving a good conference so far?\n\n"
    "3\n00:00:03,000 --> 00:00:04,000\n谢谢你们留下来。\nThanks for sticking around.\n"
)


def _dialogue_by_style(ass_text: str, style: str) -> str:
    for line in ass_text.splitlines():
        if line.startswith("Dialogue:") and f",{style}," in line:
            return line
    return ""


class TestResolveLayoutFromFile:
    def _bilingual(self) -> ASRData:
        return ASRData(
            [ASRDataSeg("Hello", 0, 1000, translated_text="你好")]
        )

    def _monolingual(self) -> ASRData:
        return ASRData([ASRDataSeg("Hello", 0, 1000)])

    def test_bilingual_translate_on_top_collapses_to_file_order(self):
        data = self._bilingual()
        assert (
            data.resolve_layout_from_file(SubtitleLayoutEnum.TRANSLATE_ON_TOP)
            == SubtitleLayoutEnum.ORIGINAL_ON_TOP
        )

    def test_bilingual_other_layouts_pass_through(self):
        data = self._bilingual()
        for layout in (
            SubtitleLayoutEnum.ORIGINAL_ON_TOP,
            SubtitleLayoutEnum.ONLY_ORIGINAL,
            SubtitleLayoutEnum.ONLY_TRANSLATE,
        ):
            assert data.resolve_layout_from_file(layout) == layout

    def test_monolingual_passes_through(self):
        data = self._monolingual()
        assert (
            data.resolve_layout_from_file(SubtitleLayoutEnum.TRANSLATE_ON_TOP)
            == SubtitleLayoutEnum.TRANSLATE_ON_TOP
        )


class TestBilingualRoundTrip:
    def test_parsed_line1_becomes_source(self):
        data = ASRData.from_srt(_BILINGUAL_SRT)
        # 解析器按位置赋值：第 1 行(中文)→text，第 2 行(英文)→translated_text
        assert data.segments[0].text == "嘿，大家今天怎么样？"
        assert data.segments[0].translated_text == "Hey, how's everyone doing today?"

    def test_default_target_above_puts_line1_on_top_after_resolve(self):
        # 复现用户场景：中文在第 1 行的文件 + 默认 target-above(译文在上)。
        # 修复前会把英文提到 Default(上)；修复后归一到文件行序 → 中文在 Default(上)。
        data = ASRData.from_srt(_BILINGUAL_SRT)
        layout = data.resolve_layout_from_file(SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        ass_text = data.to_ass(layout=layout)

        default_line = _dialogue_by_style(ass_text, "Default")
        secondary_line = _dialogue_by_style(ass_text, "Secondary")
        # Default = 渲染在上；应为文件第 1 行的中文
        assert "嘿，大家今天怎么样？" in default_line
        assert "Hey, how's everyone doing today?" in secondary_line

    def test_without_resolve_would_flip(self):
        # 反向证明修复的必要性：不归一时 TRANSLATE_ON_TOP 会把英文放到 Default(上)。
        data = ASRData.from_srt(_BILINGUAL_SRT)
        ass_text = data.to_ass(layout=SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        default_line = _dialogue_by_style(ass_text, "Default")
        assert "Hey, how's everyone doing today?" in default_line
