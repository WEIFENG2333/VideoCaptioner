"""实时字幕的统一事件模型，即本项目自定义的协议。

- TranscriptSegment：后端 → 装配器。``text`` 是该段当前全文（后端负责分段与累积），纯转录、不带翻译。
- CaptionEntry：装配器 → UI 的一条双语字幕。``source_stable_len`` 区分已听准前缀与仍在修正的尾巴，驱动双色渲染。
- 两者都按 ``seg_id`` upsert：同一 id 多次发来即原地更新（生长 / 译文回填 / 定稿），不新建行。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class TranscriptSegment:
    """后端发给装配器的一个段落（后端无关）。分段是后端的职责，装配器只按 seg_id upsert。

    Attributes:
        seg_id: 段落标识。同 id=同段在生长，不同 id=不同段。
        text: 该段当前全文（后端改写，非纯追加）。
        is_final: 是否已定稿。
        start_time / end_time: 相对会话起点的音频时间区间（秒），后端给不出时为 None。
    """

    seg_id: str
    text: str
    is_final: bool
    start_time: Optional[float] = None
    end_time: Optional[float] = None


@dataclass(frozen=True)
class CaptionEntry:
    """装配器发给 UI 的一条双语字幕（一个段落），按 ``seg_id`` upsert。

    Attributes:
        seg_id: 段落唯一标识，形如 ``voxgate#3`` / ``funasr#1#12``。
        seq: 单调递增序号，供 UI 稳定排序。
        source_text: 原文（转录文本）。
        source_stable_len: 原文中已听准前缀的字符数，其后为仍在修正的尾巴。
        target_text: 译文，未翻译时为空串。
        is_final: 是否已落定。
        started_at: 段落首次出现的真实时刻（epoch 秒）。UI 用它显示 HH:MM 时钟、并算页内相对
            位置（``started_at - 会话起点``）；录制器仅在无音频时拿它做回退，正常时间轴用 WAV 偏移。
        start_time / end_time: 后端尽力给出的音频时间区间（秒），可能为 None 或不连续（如
            Fun-ASR 重连后每 task 从 0 重计），故录制时间轴不信它、改用已录 WAV 偏移。
    """

    seg_id: str
    seq: int
    source_text: str
    source_stable_len: int
    target_text: str
    is_final: bool
    started_at: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def with_target(self, target_text: str) -> "CaptionEntry":
        """回填/更新译文，其余不变。"""
        return replace(self, target_text=target_text)
