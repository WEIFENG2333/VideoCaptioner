"""字幕断行与颜色工具。

断行以「实际渲染像素宽」为唯一依据：先贪心求最少行数，再在该行数内
把各行宽度向均值靠拢（平衡断行），任何一行都不允许超过可用宽度。
CJK 与西文混排统一按 token 断：西文单词不可拆、CJK 逐字可断、
避头尾标点不落在行首/行尾。
"""

import re
from typing import Callable, List, Tuple

from videocaptioner.core.utils.text_utils import is_mainly_cjk

from .font_utils import FontType

__all__ = ["hex_to_rgba", "is_mainly_cjk", "wrap_text"]

# 无空格书写系统（逐字可断）：汉字、假名、谚文、全角符号、泰文等
_NO_SPACE_RANGES = "⺀-鿿぀-ヿ가-힯豈-﫿＀-￯฀-໿"
# token = 可选前导空白 + (单个无空格文字 | 连续的有空格语言词)
_TOKEN_RE = re.compile(rf"\s*(?:[{_NO_SPACE_RANGES}]|[^\s{_NO_SPACE_RANGES}]+)")
# 避头：不能出现在行首的标点，断行时并入前一行末尾
_NO_LINE_START = set("。，、！？；：）】」』》〉’”…‰·—～%,.!?;:)]}%")
# 避尾：不能出现在行尾的标点，断行时并入下一行开头
_NO_LINE_END = set("（【「『《〈‘“([{")

Measure = Callable[[str], float]


def hex_to_rgba(hex_color: str) -> Tuple[int, int, int, int]:
    """#RRGGBB / #RRGGBBAA -> RGBA 元组"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
            255,
        )
    if len(hex_color) == 8:
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
            int(hex_color[6:8], 16),
        )
    return (0, 0, 0, 255)


def wrap_text(
    text: str,
    font: FontType,
    max_width: float,
    spacing: float = 0.0,
) -> List[str]:
    """把一段文本折成不超过 max_width（像素）的多行，行宽尽量均衡。

    spacing 为逐字符附加间距（渲染端逐字绘制时传入同一值，保证测量与绘制一致）。
    """
    text = " ".join(text.split())
    if not text:
        return []
    measure = _make_measure(font, spacing)
    if measure(text) <= max_width:
        return [text]

    tokens = _split_oversized(_tokenize(text), measure, max_width)
    greedy = _fill_lines(tokens, measure, max_width, target=None, num_lines=None)
    if len(greedy) <= 1:
        return greedy

    target = measure(text) / len(greedy)
    balanced = _fill_lines(tokens, measure, max_width, target=target, num_lines=len(greedy))
    # 平衡是尽力而为：任何一行超宽或行数变多都回退贪心结果（贪心保证不超宽）
    if len(balanced) > len(greedy) or any(measure(line) > max_width for line in balanced):
        return greedy
    return balanced


def _make_measure(font: FontType, spacing: float) -> Measure:
    cache: dict[str, float] = {}

    def measure(s: str) -> float:
        s = s.strip()
        if not s:
            return 0.0
        if s not in cache:
            bbox = font.getbbox(s)
            width = float(bbox[2] - bbox[0])
            if spacing > 0 and len(s) > 1:
                width += spacing * (len(s) - 1)
            cache[s] = width
        return cache[s]

    return measure


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in _TOKEN_RE.findall(text):
        body = raw.strip()
        if tokens and body and all(ch in _NO_LINE_START for ch in body):
            tokens[-1] += raw
        elif tokens and tokens[-1].strip() and tokens[-1].strip()[-1] in _NO_LINE_END:
            tokens[-1] += raw
        else:
            tokens.append(raw)
    return tokens


def _split_oversized(tokens: List[str], measure: Measure, max_width: float) -> List[str]:
    """单个 token（超长单词/URL）都放不进一行时按字符硬切。"""
    out: List[str] = []
    for token in tokens:
        if measure(token) <= max_width:
            out.append(token)
            continue
        piece = ""
        for ch in token:
            if piece.strip() and measure(piece + ch) > max_width:
                out.append(piece)
                piece = ch
            else:
                piece += ch
        if piece.strip():
            out.append(piece)
    return out


def _fill_lines(
    tokens: List[str],
    measure: Measure,
    max_width: float,
    target: float | None,
    num_lines: int | None,
) -> List[str]:
    """逐 token 填行。target 为 None 时贪心塞满；否则每行填到最接近 target 处断行，
    但绝不超过 max_width，也绝不超过 num_lines 行（最后一行收下所有剩余）。"""
    lines: List[str] = []
    current: List[str] = []

    def line_text(parts: List[str]) -> str:
        return "".join(parts).strip()

    for token in tokens:
        if not current:
            current = [token]
            continue
        candidate = line_text(current + [token])
        width = measure(candidate)
        is_last = num_lines is not None and len(lines) == num_lines - 1

        if width > max_width and not is_last:
            lines.append(line_text(current))
            current = [token]
        elif (
            target is not None
            and not is_last
            and width >= target
            # 断在该 token 前还是后：取更接近目标宽度的一侧
            and (width - target) >= (target - measure(line_text(current)))
        ):
            lines.append(line_text(current))
            current = [token]
        else:
            current.append(token)

    if current:
        lines.append(line_text(current))
    return [line for line in lines if line]
