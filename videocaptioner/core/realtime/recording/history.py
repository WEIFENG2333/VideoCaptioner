"""实时字幕历史记录的持久化（纯数据，无 Qt）。

每条记录一个文件夹 ``{root}/{id}/``（root 默认 ``{work_dir}/live-caption``，是用户工作产物）：
``transcript.json`` 存元信息+句子，``audio.wav`` 存可选录音。``id`` 是 ``YYYYMMDD-HHMMSS``，
唯一且天然按时间排序，是不可变主键。UI/CLI 只认 :class:`LiveCaptionRecord`，不直接碰文件布局。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from videocaptioner.config import APPDATA_PATH, WORK_PATH
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("live_caption_history")

# 历史曾放 APPDATA，现归入工作目录（属用户工作产物）；GUI 启动时一次性迁移，见 migrate_legacy_root。
_LEGACY_ROOT = APPDATA_PATH / "live_captions"
DEFAULT_DIR_NAME = "live-caption"


def default_root(work_dir: Optional[Union[str, Path]]) -> Path:
    """实时字幕历史目录 = ``{work_dir}/live-caption``；work_dir 空则回退应用默认工作目录。

    main.py 的迁移目标与 UI 的读写根都走这里，避免两处各拼一遍、字面量漂移导致「迁过去却读不到」。
    """
    wd = str(work_dir or "").strip()
    return (Path(wd) if wd else WORK_PATH) / DEFAULT_DIR_NAME


def migrate_legacy_root(new_root: Path) -> None:
    """把旧的 ``APPDATA/live_captions`` 一次性迁到 ``new_root``（实时字幕改放工作目录）。

    仅当新目录不存在、且旧目录有内容时迁移。可恢复：先 copytree 到临时目录、成功后原子改名，最后
    才删旧目录——任一步失败就清理临时目录、原样保留旧记录（new_root 仍不存在，下次启动可重试），
    绝不留半截。由 GUI 启动时调用，CLI/测试不触发，避免误动用户真实数据。
    """
    new_root = Path(new_root)
    if new_root == _LEGACY_ROOT or new_root.exists() or not _LEGACY_ROOT.is_dir():
        return
    staging = new_root.with_name(new_root.name + ".migrating")
    try:
        shutil.rmtree(staging, ignore_errors=True)  # 清掉上次可能残留的半截临时目录
        new_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_LEGACY_ROOT, staging)   # 先全量复制（跨盘也安全，非原子）
        os.replace(staging, new_root)            # 同盘原子改名成正式目录
        shutil.rmtree(_LEGACY_ROOT, ignore_errors=True)  # 仅在彻底成功后删旧
    except Exception:
        logger.warning("迁移实时字幕历史失败，保留原位置待下次重试", exc_info=True)
        shutil.rmtree(staging, ignore_errors=True)

_TRANSCRIPT = "transcript.json"
AUDIO_NAME = "audio.wav"


def _fmt_clock(seconds: float) -> str:
    """秒 → mm:ss（超过一小时用 h:mm:ss）。"""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@dataclass
class CaptionSegment:
    """一句字幕：相对音频起点的时间区间 + 原文 / 译文。"""

    start: float
    end: float
    source: str
    target: str = ""

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "source": self.source,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CaptionSegment":
        return cls(
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            source=str(d.get("source", "")),
            target=str(d.get("target", "")),
        )


@dataclass
class LiveCaptionRecord:
    """一次实时字幕会话的完整记录。"""

    id: str
    name: str
    source: str        # "系统声音" / "麦克风"
    translate: str     # "微软翻译" / "原文记录" / …
    created_at: float  # epoch 秒
    duration: float    # 秒
    audio: str = ""    # 音频文件名（空 = 无音频，不能回放）
    segments: List[CaptionSegment] = field(default_factory=list)
    dir: Optional[Path] = None  # 运行时填充，不入 JSON

    # ----- 序列化 -----

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "translate": self.translate,
            "created_at": self.created_at,
            "duration": round(self.duration, 3),
            "audio": self.audio,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict, dir: Optional[Path] = None) -> "LiveCaptionRecord":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            source=str(d.get("source", "")),
            translate=str(d.get("translate", "")),
            created_at=float(d.get("created_at", 0.0)),
            duration=float(d.get("duration", 0.0)),
            audio=str(d.get("audio", "")),
            segments=[CaptionSegment.from_dict(s) for s in d.get("segments", [])],
            dir=dir,
        )

    # ----- 展示便捷属性 -----

    @property
    def audio_path(self) -> Optional[Path]:
        if self.audio and self.dir is not None:
            p = self.dir / self.audio
            return p if p.is_file() else None
        return None

    @property
    def duration_label(self) -> str:
        return _fmt_clock(self.duration)

    @property
    def created_label(self) -> str:
        """列表用的相对时间：今天 → "今天 HH:MM"，否则 "MM-DD HH:MM"。"""
        try:
            lt = time.localtime(self.created_at)
            today = time.localtime()
            if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
                return time.strftime("今天 %H:%M", lt)
            return time.strftime("%m-%d %H:%M", lt)
        except Exception:
            return ""

    @property
    def summary(self) -> str:
        """副标题：``06:18 · 系统声音 · 微软翻译``。"""
        parts = [self.duration_label, self.source, self.translate]
        return " · ".join(p for p in parts if p)

    def matches(self, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return True
        if q in self.name.lower():
            return True
        return any(q in s.source.lower() or q in s.target.lower() for s in self.segments)

    # ----- 导出 -----

    def export_srt(self, bilingual: bool = True) -> str:
        lines: List[str] = []
        for i, seg in enumerate(self.segments, 1):
            body = seg.source
            if bilingual and seg.target and seg.target.strip() != seg.source.strip():
                body = f"{seg.source}\n{seg.target}"
            elif not seg.source and seg.target:
                body = seg.target
            lines.append(f"{i}\n{_srt_time(seg.start)} --> {_srt_time(seg.end)}\n{body}\n")
        return "\n".join(lines)

    def export_txt(self, bilingual: bool = True) -> str:
        out: List[str] = []
        for seg in self.segments:
            if seg.source:
                out.append(seg.source)
            if bilingual and seg.target and seg.target.strip() != seg.source.strip():
                out.append(seg.target)
            elif not seg.source and seg.target:
                out.append(seg.target)
        return "\n".join(out)


class LiveCaptionStore:
    """实时字幕记录目录的读写。线程：保存在工作线程、列出在 GUI 线程，互不共享状态。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else WORK_PATH / DEFAULT_DIR_NAME

    # ----- 路径 -----

    @staticmethod
    def make_id(when: Optional[float] = None) -> str:
        return time.strftime("%Y%m%d-%H%M%S", time.localtime(when if when is not None else time.time()))

    @staticmethod
    def display_name(when: Optional[float] = None) -> str:
        return time.strftime("%Y-%m-%d %H:%M 记录", time.localtime(when if when is not None else time.time()))

    def dir_for(self, record_id: str) -> Path:
        return self.root / record_id

    def create_dir(self, record_id: str) -> Path:
        d = self.dir_for(record_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ----- 读写 -----

    def save(self, record: LiveCaptionRecord) -> Path:
        d = self.create_dir(record.id)
        (d / _TRANSCRIPT).write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        record.dir = d
        return d

    def _load_dir(self, d: Path) -> Optional[LiveCaptionRecord]:
        f = d / _TRANSCRIPT
        if not f.is_file():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
        return LiveCaptionRecord.from_dict(data, dir=d)

    def load(self, record_id: str) -> Optional[LiveCaptionRecord]:
        return self._load_dir(self.dir_for(record_id))

    def list(self) -> List[LiveCaptionRecord]:
        """所有记录，按创建时间倒序（最新在前）。"""
        if not self.root.is_dir():
            return []
        out: List[LiveCaptionRecord] = []
        for d in self.root.iterdir():
            if d.is_dir():
                rec = self._load_dir(d)
                if rec is not None:
                    out.append(rec)
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    def search(self, query: str) -> List[LiveCaptionRecord]:
        return [r for r in self.list() if r.matches(query)]

    def delete(self, record_id: str) -> None:
        d = self.dir_for(record_id)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)

    def rename(self, record_id: str, new_name: str) -> Optional[LiveCaptionRecord]:
        """只改显示名（transcript.json 的 name），文件夹仍以时间戳 id 为不可变主键。

        返回更新后的记录；记录不存在 / 新名为空则返回 None（不动盘）。
        """
        name = (new_name or "").strip()
        rec = self.load(record_id)
        if rec is None or not name:
            return None
        rec.name = name
        self.save(rec)
        return rec
