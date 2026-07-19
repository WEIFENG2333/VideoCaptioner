"""输出文件命名与任务工作目录的唯一定义处。

命名语法（CLI 与 GUI 从这里取同一套模板，保持完全一致）：

    {stem}.{tag}.{ext}

tag 只允许四类：目标语言码（zh-Hans / en / ja …，与 Bing 翻译码一致）、
``optimized``（仅校正/断句）、``subtitled``（带字幕视频）、``dubbed``
（配音音频或配音视频，由扩展名区分容器）。tag 按加工顺序可组合，
例如 ``video.dubbed.subtitled.mp4``。软/硬字幕、提供商、音色等参数
细节一律不进文件名。

目录规则：

- 成品永远落在源文件旁（或调用方显式指定的位置）；GUI 路径用
  :func:`unique_path` 自增 `` (2)`` 防覆盖，CLI 保持确定性覆盖。
- 一切中间产物进 ``{work_dir}/{task_type}/{YYYYMMDD-HHMMSS}-{stem}/`` 任务
  目录，按功能归类（task_type = transcribe / synthesis / batch / dubbing），
  文件名固定（transcript.srt / subtitle.ass / dubbing/…），由目录而不是文件名
  携带语义。成功后默认整目录删除（``app.keep_intermediates`` 打开时保留），
  失败保留供排查。
- TTS 原始分段是跨任务的内容寻址缓存，不属于任务目录，见
  ``core/dubbing/pipeline.py``。
"""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path
from typing import Optional, Union

from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.translate.types import BING_LANG_MAP, TargetLanguage

PathLike = Union[str, Path]

TAG_OPTIMIZED = "optimized"
TAG_SUBTITLED = "subtitled"
TAG_DUBBED = "dubbed"
TAG_HARDSUB = "hardsub"  # 从视频画面 OCR 提取出的字幕

# 任务目录按功能归类：{work_dir}/{task_type}/{时间戳}-{stem}/，由目录携带语义。
TASK_TRANSCRIBE = "transcribe"  # 主页转录→字幕→合成 一条龙
TASK_SYNTHESIS = "synthesis"    # 视频合成页
TASK_BATCH = "batch"            # 批量处理页
TASK_DUBBING = "dubbing"        # 独立配音（CLI / 无上游任务目录时）
TASK_HARDSUB = "hardsub"        # 硬字幕提取页
_TASK_TYPES = frozenset(
    {TASK_TRANSCRIBE, TASK_SYNTHESIS, TASK_BATCH, TASK_DUBBING, TASK_HARDSUB}
)

# 任务目录内的固定文件名：路径即语义，文件名不再编码阶段信息。
DOWNLOADS_DIR_NAME = "downloads"
TRANSCRIPT_FILE = "transcript.srt"
STYLED_SUBTITLE_FILE = "subtitle.ass"
DUBBING_DIR = "dubbing"
DUBBING_AUDIO_FILE = "audio.wav"
DUBBING_REPORT_FILE = "report.json"

_LANGUAGE_TAGS = frozenset(BING_LANG_MAP.values())
_KNOWN_TAGS = frozenset({TAG_OPTIMIZED, TAG_SUBTITLED, TAG_DUBBED, TAG_HARDSUB}) | _LANGUAGE_TAGS

_LAYOUT_FILE_KEYS = {
    SubtitleLayoutEnum.TRANSLATE_ON_TOP: "target-above",
    SubtitleLayoutEnum.ORIGINAL_ON_TOP: "source-above",
    SubtitleLayoutEnum.ONLY_TRANSLATE: "target-only",
    SubtitleLayoutEnum.ONLY_ORIGINAL: "source-only",
}

_TASK_DIR_STEM_MAX = 60


def language_tag(language: TargetLanguage) -> str:
    """目标语言的文件名 tag（BCP-47，播放器可识别为字幕语言）。"""
    return BING_LANG_MAP[language]


def product_path(
    source: PathLike,
    *tags: str,
    ext: Optional[str] = None,
    directory: Optional[PathLike] = None,
) -> Path:
    """成品路径：源文件旁的 ``{stem}.{tag}.{ext}``。

    stem 先剥掉已有 tag（对 ``video.zh-Hans.srt`` 再翻译不会叠成
    ``video.zh-Hans.en.srt``）。``ext`` 缺省沿用源扩展名；``directory``
    缺省为源文件所在目录。本函数不做防覆盖，GUI 调用方需配合
    :func:`unique_path`。
    """
    src = Path(source)
    if not src.name:
        raise ValueError(f"product_path needs a real source file, got {source!r}")
    for tag in tags:
        if tag not in _KNOWN_TAGS:
            raise ValueError(f"unknown output tag: {tag!r}")
    stem = strip_tags(src.stem)
    suffix = ext if ext is not None else src.suffix
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    name = stem + "".join(f".{tag}" for tag in tags) + suffix
    return Path(directory) / name if directory is not None else src.with_name(name)


def strip_tags(stem: str) -> str:
    """从 stem 末尾剥掉本模块词汇表内的 tag（链式处理取干净名）。"""
    while True:
        base, dot, last = stem.rpartition(".")
        if not dot or last not in _KNOWN_TAGS:
            return stem
        stem = base


def unique_path(path: PathLike) -> Path:
    """已存在则按 OS 惯例自增 ``name (2).ext``，永不静默覆盖成品。"""
    candidate = Path(path)
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        numbered = candidate.with_stem(f"{candidate.stem} ({index})")
        if not numbered.exists():
            return numbered
    raise FileExistsError(f"cannot find a free name for {candidate}")


def layout_copy_name(layout: SubtitleLayoutEnum) -> str:
    """任务目录里其余布局副本的文件名（layout-target-above.srt …）。"""
    return f"layout-{_LAYOUT_FILE_KEYS[layout]}.srt"


def downloads_dir(work_dir: PathLike) -> Path:
    """在线下载的统一落盘目录 ``{work_dir}/downloads``（会创建）。"""
    target = Path(work_dir) / DOWNLOADS_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def new_task_dir(work_dir: PathLike, source: PathLike, task_type: str) -> Path:
    """创建一次运行的任务目录：``{work_dir}/{task_type}/{时间戳}-{stem}``。

    按功能（transcribe/synthesis/batch/dubbing）分目录；时间戳保证排序且不同运行
    互不覆盖，stem 让人能认出来源。
    """
    if task_type not in _TASK_TYPES:
        raise ValueError(f"unknown task type: {task_type!r}")
    stem = re.sub(r'[<>:"/\\|?*\0-\x1f]', "_", Path(source).stem).strip(" .")
    stem = stem[:_TASK_DIR_STEM_MAX] or "task"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path(work_dir) / task_type
    candidate = root / f"{stamp}-{stem}"
    index = 2
    while candidate.exists():
        candidate = root / f"{stamp}-{stem}-{index}"
        index += 1
    candidate.mkdir(parents=True)
    return candidate


def cleanup_task_dir(task_dir: Optional[PathLike], *, keep: bool) -> None:
    """成功收尾时删除任务目录（keep=True 保留）。

    只删功能任务目录（父目录名是已知 task_type）：路径来自配置/信号链，误配时
    宁可留下垃圾也不能 rmtree 到用户目录。
    """
    if keep or not task_dir:
        return
    target = Path(task_dir)
    if target.parent.name not in _TASK_TYPES or not target.is_dir():
        return
    shutil.rmtree(target, ignore_errors=True)
