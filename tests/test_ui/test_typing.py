"""译文逐字动画步进 next_visible 契约：只前进、不回退、不缩短。

可见长度单调不减：公共前缀原位不动，改写过的尾字在原位被新值覆盖（不先删再打），新增字逐字
补出。这样行数只增不减、高度不会先塌再涨（删字回退会缩行、看着卡）。整句重译变短才直接对齐。
"""

from videocaptioner.ui.components.live_caption.typing import common_prefix_len, next_visible


def _converge(visible: str, full: str, max_steps: int = 500):
    seq = [visible]
    for _ in range(max_steps):
        if visible == full:
            break
        visible = next_visible(visible, full)
        seq.append(visible)
    assert visible == full  # 终会收敛到目标（不死循环）
    return seq


def _lengths_nondecreasing(seq):
    return all(len(seq[i]) <= len(seq[i + 1]) for i in range(len(seq) - 1))


def test_pure_append_types_forward():
    seq = _converge("", "你好世界")
    assert seq[0] == "" and seq[-1] == "你好世界"
    for s in seq:  # 全程是目标的前缀，逐字增长
        assert "你好世界".startswith(s)
    assert _lengths_nondecreasing(seq)


def test_tail_rewrite_overwrites_in_place_no_shrink():
    # 改写尾字：可见长度只增不减（不先删再打），公共前缀「我觉得」原位不动 → 不抖
    seq = _converge("我觉得很难", "我觉得非常困难")
    assert seq[0] == "我觉得很难" and seq[-1] == "我觉得非常困难"
    assert _lengths_nondecreasing(seq)               # 关键：全程不缩短
    assert all(s.startswith("我觉得") for s in seq)   # 公共前缀不动


def test_same_length_rewrite_is_in_place_one_step():
    # 等长改写：一步原位覆盖末尾，长度不变、不闪
    assert _converge("今天天气不错", "今天天气很好") == ["今天天气不错", "今天天气很好"]


def test_shorter_retranslation_aligns_directly():
    # 整句重译变短（少见）：直接对齐到更短目标（这一步会变短，容器由高度地板兜住不抖）
    assert _converge("你好世界啊哈", "你好世界") == ["你好世界啊哈", "你好世界"]


def test_big_rewrite_forward_only_accelerated():
    old = "这是上一句完全不同的旧内容" * 3
    new = "这是" + "全新改写后的另一段更长的内容" * 3
    seq = _converge(old, new)
    assert seq[-1] == new
    assert _lengths_nondecreasing(seq)  # 全程不缩短（new 比 old 长）
    assert len(seq) < len(new)          # 加速补 → 步数远少于纯逐字


def test_common_prefix_len():
    assert common_prefix_len("abc", "abd") == 2
    assert common_prefix_len("", "x") == 0
    assert common_prefix_len("abc", "abc") == 3
    assert common_prefix_len("abc", "abcd") == 3
