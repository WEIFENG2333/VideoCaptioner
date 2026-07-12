"""Subtitle visual style registry.

This module owns the distinction between:

- subtitle file formats such as SRT/ASS/VTT;
- hard-subtitle renderers such as ASS and rounded boxes;
- visual style presets for each renderer.

The rest of the app should load styles through this module instead of reading
JSON files or resource directories directly.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class SubtitleRenderer(Enum):
    """Hard-subtitle rendering backend."""

    ASS = "ass"
    ROUNDED = "rounded"


class StyleSource(Enum):
    """Where a style preset comes from."""

    BUILTIN = "builtin"
    USER = "user"


# Backward-compatible names for older call sites. The values now describe a
# renderer, not a subtitle file format.
StyleMode = SubtitleRenderer

# 对齐字符串 -> ASS Alignment（数字小键盘布局，底部一行）。
_ASS_ALIGNMENT = {"left": 1, "center": 2, "right": 3}
# ASS 样式以 720p（约 1280 宽）为基准编写，渲染时再按视频高度缩放。
_ASS_REFERENCE_WIDTH = 1280


def _ass_margin_lr(max_width: int) -> int:
    """最大宽度百分比 -> ASS 左右边距（基准宽度像素）。100% 保留历史的 10px 安全边距。"""
    if max_width >= 100:
        return 10
    return int(_ASS_REFERENCE_WIDTH * (100 - max_width) / 200)


@dataclass(frozen=True)
class AssSecondaryStyle:
    """Secondary line style for bilingual ASS rendering."""

    font_name: str = "Noto Sans SC"
    font_size: int = 30
    color: str = "#ffffff"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    spacing: float = 0.8
    bold: bool = True


SecondaryStyle = AssSecondaryStyle


@dataclass(frozen=True)
class AssSubtitleStyle:
    """Visual fields used by the ASS hard-subtitle renderer."""

    font_name: str = "Noto Sans SC"
    font_size: int = 42
    primary_color: str = "#ffffff"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    bold: bool = True
    spacing: float = 0.0
    margin_bottom: int = 30
    max_width: int = 100  # 文本最大宽度（占画面宽度百分比）；100=不额外限制
    align: str = "center"  # 水平对齐：left / center / right
    line_gap: int = 0  # 主副字幕之间的额外间距（仅双语时生效，作用于上行）
    secondary: AssSecondaryStyle | None = None

    def to_ass_string(self) -> str:
        primary = _hex_to_ass(self.primary_color)
        outline = _hex_to_ass(self.outline_color)
        bold_flag = -1 if self.bold else 0
        align = _ASS_ALIGNMENT.get(self.align, 2)
        margin_lr = _ass_margin_lr(self.max_width)
        secondary = self.secondary or AssSecondaryStyle(
            font_name=self.font_name,
            font_size=max(8, int(self.font_size * 0.72)),
            bold=self.bold,
        )
        sec_bold_flag = -1 if secondary.bold else 0
        sec_color = _hex_to_ass(secondary.color)
        sec_outline = _hex_to_ass(secondary.outline_color)
        header = (
            "[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding"
        )
        default_line = (
            f"Style: Default,{self.font_name},{self.font_size},"
            f"{primary},&H000000FF,{outline},&H00000000,"
            f"{bold_flag},0,0,0,100,100,{self.spacing},0,1,"
            f"{self.outline_width},0,{align},{margin_lr},{margin_lr},{self.margin_bottom},1"
        )
        secondary_line = (
            f"Style: Secondary,{secondary.font_name},{secondary.font_size},"
            f"{sec_color},&H000000FF,{sec_outline},&H00000000,"
            f"{sec_bold_flag},0,0,0,100,100,{secondary.spacing},0,1,"
            f"{secondary.outline_width},0,{align},{margin_lr},{margin_lr},{self.margin_bottom},1"
        )
        return f"{header}\n{default_line}\n{secondary_line}"

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.secondary is None:
            data.pop("secondary", None)
        return data


@dataclass(frozen=True)
class RoundedSubtitleStyle:
    """Visual fields used by the rounded-background hard-subtitle renderer."""

    font_name: str = "Noto Sans SC"
    font_size: int = 52
    text_color: str = "#ffffff"
    bg_color: str = "#191919c8"
    corner_radius: int = 12
    padding_h: int = 28
    padding_v: int = 14
    margin_bottom: int = 60
    line_spacing: int = 10  # 主副两个气泡之间的间距（也用于块内换行）
    letter_spacing: int = 0
    max_width: int = 90  # 文本块最大宽度（占画面宽度百分比）
    align: str = "center"  # 水平对齐：left / center / right

    def to_dict(self) -> dict:
        return asdict(self)


StylePayload = Union[AssSubtitleStyle, RoundedSubtitleStyle]


@dataclass(frozen=True)
class SubtitleStylePreset:
    """A named visual style preset for one renderer."""

    id: str
    name: str
    renderer: SubtitleRenderer
    source: StyleSource
    style: StylePayload
    description: str = ""
    version: int = 1
    path: Path | None = None

    @property
    def mode(self) -> SubtitleRenderer:
        return self.renderer

    @property
    def editable(self) -> bool:
        return self.source == StyleSource.USER

    @property
    def short_id(self) -> str:
        return self.id.split("/", 1)[-1]

    def to_ass_string(self) -> str:
        if not isinstance(self.style, AssSubtitleStyle):
            raise TypeError(f"Style '{self.id}' is not an ASS style")
        return self.style.to_ass_string()

    def to_rounded_dict(self) -> dict:
        if not isinstance(self.style, RoundedSubtitleStyle):
            raise TypeError(f"Style '{self.id}' is not a rounded style")
        return self.style.to_dict()

    def to_json_dict(self) -> dict:
        data = {
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "renderer": self.renderer.value,
            "source": self.source.value,
        }
        data.update(self.style.to_dict())
        # Older callers expect a ``mode`` field. Keep it as an alias in files.
        data["mode"] = self.renderer.value
        return data


# Older call sites used SubtitleStyle as the object returned by load_style().
SubtitleStyle = SubtitleStylePreset


BUILTIN_STYLE_DATA: tuple[dict, ...] = (
    {
        "id": "ass/default",
        "name": "默认描边",
        "description": "通用白字黑边，适合多数横屏视频",
        "renderer": "ass",
        "font_name": "LXGW WenKai",
        "font_size": 40,
        "primary_color": "#ffffff",
        "outline_color": "#000000",
        "outline_width": 2.0,
        "bold": True,
        "spacing": 0.2,
        "margin_bottom": 28,
        "secondary": {
            "font_name": "Noto Sans SC",
            "font_size": 30,
            "color": "#ffffff",
            "outline_color": "#000000",
            "outline_width": 2.0,
            "spacing": 0.8,
        },
    },
    {
        "id": "ass/anime",
        "name": "暖色动漫",
        "description": "偏亮的暖色描边，适合二创和短视频",
        "renderer": "ass",
        "font_name": "Noto Sans SC",
        "font_size": 46,
        "primary_color": "#fff5f3",
        "outline_color": "#f58709",
        "outline_width": 2.6,
        "bold": True,
        "spacing": 2.6,
        "margin_bottom": 20,
        "secondary": {
            "font_name": "Noto Sans SC",
            "font_size": 26,
            "color": "#ffffff",
            "outline_color": "#f58709",
            "outline_width": 2.0,
            "spacing": 0.0,
        },
    },
    {
        "id": "ass/vertical",
        "name": "竖屏留白",
        "description": "更高底部边距，适合 9:16 视频",
        "renderer": "ass",
        "font_name": "Noto Sans SC",
        "font_size": 34,
        "primary_color": "#65ff5a",
        "outline_color": "#000000",
        "outline_width": 2.0,
        "bold": True,
        "spacing": 4.0,
        "margin_bottom": 182,
        "secondary": {
            "font_name": "Noto Sans SC",
            "font_size": 18,
            "color": "#ffffff",
            "outline_color": "#000000",
            "outline_width": 2.0,
            "spacing": 0.8,
        },
    },
    {
        "id": "rounded/default",
        "name": "圆角胶囊",
        "description": "半透明深色圆角背景，适合信息密度较高的视频",
        "renderer": "rounded",
        "font_name": "LXGW WenKai",
        "font_size": 52,
        "text_color": "#ffffff",
        "bg_color": "#191919c8",
        "corner_radius": 12,
        "padding_h": 28,
        "padding_v": 14,
        "margin_bottom": 60,
        "line_spacing": 10,
        "letter_spacing": 0,
    },
)


def normalize_renderer(value: object | None) -> SubtitleRenderer:
    if isinstance(value, SubtitleRenderer):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"ass", "ass_style", "ass-style", "ass 样式", "ass样式"}:
        return SubtitleRenderer.ASS
    if raw in {"rounded", "rounded_bg", "rounded-bg", "圆角背景"}:
        return SubtitleRenderer.ROUNDED
    return SubtitleRenderer.ASS


def normalize_style_id(
    style_id: str | None,
    renderer: SubtitleRenderer | str | None = None,
) -> str:
    renderer_enum = normalize_renderer(renderer)
    raw = str(style_id or "").strip()
    if not raw:
        return f"{renderer_enum.value}/default"
    raw = raw.replace("\\", "/")
    if raw.startswith("ass-"):
        return f"ass/{raw[4:]}"
    if raw.startswith("rounded-"):
        return f"rounded/{raw[8:]}"
    if "/" in raw:
        left, right = raw.split("/", 1)
        return f"{normalize_renderer(left).value}/{_slugify(right)}"
    return f"{renderer_enum.value}/{_slugify(raw)}"


def list_styles(
    styles_dir: Optional[Path] = None,
    renderer: SubtitleRenderer | str | None = None,
    include_builtin: bool = True,
    include_user: bool = True,
) -> list[SubtitleStylePreset]:
    """List available visual presets."""
    renderer_filter = normalize_renderer(renderer) if renderer is not None else None
    result: list[SubtitleStylePreset] = []
    if include_builtin:
        result.extend(_builtin_styles())
    if include_user:
        result.extend(_load_user_styles(styles_dir))
    if renderer_filter is not None:
        result = [style for style in result if style.renderer == renderer_filter]
    return sorted(result, key=lambda item: (item.renderer.value, item.source.value, item.short_id))


def load_style(
    name: str | None,
    styles_dir: Optional[Path] = None,
    mode: Optional[str] = None,
    renderer: SubtitleRenderer | str | None = None,
) -> Optional[SubtitleStylePreset]:
    """Load a style preset by full id or short name.

    ``mode`` is accepted as a compatibility alias for ``renderer``.
    """
    renderer_hint = renderer if renderer is not None else mode
    wanted_id = normalize_style_id(name, renderer_hint)
    renderer_filter = normalize_renderer(renderer_hint) if renderer_hint is not None else None
    candidates = list_styles(styles_dir, renderer_filter)

    # Prefer user styles when the full ID matches, but built-ins are read-only
    # and cannot be overwritten on disk.
    for source in (StyleSource.USER, StyleSource.BUILTIN):
        for preset in candidates:
            if preset.source == source and preset.id == wanted_id:
                return preset

    short = wanted_id.split("/", 1)[-1]
    for preset in candidates:
        if preset.short_id == short or preset.name == str(name or ""):
            return preset
    return None


def save_user_style(
    preset: SubtitleStylePreset,
    styles_dir: Optional[Path] = None,
) -> Path:
    """Persist a user-owned preset and return its path."""
    if preset.source != StyleSource.USER:
        preset = SubtitleStylePreset(
            id=preset.id,
            name=preset.name,
            renderer=preset.renderer,
            source=StyleSource.USER,
            style=preset.style,
            description=preset.description,
            version=preset.version,
        )
    styles_root = styles_dir or _user_styles_dir()
    target = styles_root / preset.renderer.value / f"{preset.short_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = preset.to_json_dict()
    data.pop("source", None)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def delete_user_style(style_id: str, styles_dir: Optional[Path] = None) -> bool:
    normalized = normalize_style_id(style_id)
    renderer, short = normalized.split("/", 1)
    path = (styles_dir or _user_styles_dir()) / renderer / f"{short}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def available_style_names(styles_dir: Optional[Path] = None) -> list[str]:
    return sorted({style.id for style in list_styles(styles_dir)})


def style_id_from_filename(filename: str) -> str:
    """Return a short style id from legacy or new filenames."""
    stem = Path(filename).stem
    for prefix in ("ass-", "rounded-"):
        if stem.startswith(prefix):
            return stem[len(prefix) :]
    return stem


def preset_from_json(
    data: dict,
    *,
    source: StyleSource,
    path: Path | None = None,
    renderer_hint: SubtitleRenderer | str | None = None,
) -> SubtitleStylePreset:
    renderer = normalize_renderer(data.get("renderer") or data.get("mode") or renderer_hint)
    raw_id = data.get("id") or (path.stem if path else "default")
    short_id = style_id_from_filename(str(raw_id))
    if "/" in short_id:
        style_id = normalize_style_id(short_id, renderer)
        short_id = style_id.split("/", 1)[-1]
    else:
        style_id = f"{renderer.value}/{_slugify(short_id)}"
    display_name = str(data.get("name") or short_id)
    description = str(data.get("description") or "")
    version = int(data.get("version") or 1)

    if renderer == SubtitleRenderer.ROUNDED:
        style = RoundedSubtitleStyle(
            font_name=str(data.get("font_name") or "Noto Sans SC"),
            font_size=int(data.get("font_size") or 52),
            text_color=str(data.get("text_color") or "#ffffff"),
            bg_color=str(data.get("bg_color") or "#191919c8"),
            corner_radius=int(data.get("corner_radius") or 12),
            padding_h=int(data.get("padding_h") or 28),
            padding_v=int(data.get("padding_v") or 14),
            margin_bottom=int(data.get("margin_bottom") or 60),
            line_spacing=int(data.get("line_spacing") or 10),
            letter_spacing=int(data.get("letter_spacing") or 0),
            max_width=int(data.get("max_width") or 90),
            align=str(data.get("align") or "center"),
        )
    else:
        primary_bold = bool(data.get("bold", True))
        secondary_data = data.get("secondary")
        if isinstance(secondary_data, dict):
            # 旧样式只存主字幕 bold（当时主副共用），副字幕缺省时沿用主字幕加粗，
            # 保证历史样式渲染不变；新样式可独立设置副字幕加粗。
            secondary_data = {"bold": primary_bold, **secondary_data}
            secondary = AssSecondaryStyle(**secondary_data)
        else:
            secondary = None
        style = AssSubtitleStyle(
            font_name=str(data.get("font_name") or "Noto Sans SC"),
            font_size=int(data.get("font_size") or 42),
            primary_color=str(data.get("primary_color") or "#ffffff"),
            outline_color=str(data.get("outline_color") or "#000000"),
            outline_width=float(data.get("outline_width") or 2.0),
            bold=primary_bold,
            spacing=float(data.get("spacing") or 0.0),
            margin_bottom=int(data.get("margin_bottom") or 30),
            max_width=int(data.get("max_width") or 100),
            align=str(data.get("align") or "center"),
            line_gap=int(data.get("line_gap") or 0),
            secondary=secondary,
        )

    return SubtitleStylePreset(
        id=style_id,
        name=display_name,
        renderer=renderer,
        source=source,
        style=style,
        description=description,
        version=version,
        path=path,
    )


def preset_from_file(path: Path, *, source: StyleSource) -> SubtitleStylePreset:
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        renderer_hint = path.parent.name if path.parent.name in {"ass", "rounded"} else None
        return preset_from_json(
            json.loads(content),
            source=source,
            path=path,
            renderer_hint=renderer_hint,
        )
    if "[V4+ Styles]" in content or "Style:" in content:
        return SubtitleStylePreset(
            id=f"ass/{_slugify(path.stem)}",
            name=path.stem,
            renderer=SubtitleRenderer.ASS,
            source=source,
            style=_parse_ass_txt(content),
            path=path,
        )
    raise ValueError(f"Unrecognized style file format: {path}")


def _builtin_styles() -> list[SubtitleStylePreset]:
    root = _builtin_styles_dir()
    if root.exists():
        presets: list[SubtitleStylePreset] = []
        for path in sorted(root.glob("*/*.json")):
            try:
                presets.append(preset_from_file(path, source=StyleSource.BUILTIN))
            except Exception:
                logger.warning("Failed to load builtin subtitle style %s", path, exc_info=True)
        if presets:
            return presets
    return [preset_from_json(data, source=StyleSource.BUILTIN) for data in BUILTIN_STYLE_DATA]


def _load_user_styles(styles_dir: Optional[Path] = None) -> list[SubtitleStylePreset]:
    root = styles_dir or _user_styles_dir()
    if not root.exists():
        return []
    files = sorted(root.glob("*/*.json")) + sorted(root.glob("*.json"))
    result: list[SubtitleStylePreset] = []
    for path in files:
        try:
            result.append(preset_from_file(path, source=StyleSource.USER))
        except Exception:
            logger.warning("Failed to load subtitle style %s", path, exc_info=True)
    return result


def _user_styles_dir() -> Path:
    from videocaptioner.config import USER_SUBTITLE_STYLE_PATH

    return USER_SUBTITLE_STYLE_PATH


def _builtin_styles_dir() -> Path:
    from videocaptioner.config import BUILTIN_SUBTITLE_STYLE_PATH

    return BUILTIN_SUBTITLE_STYLE_PATH


def _slugify(value: str) -> str:
    raw = value.strip().lower().replace("\\", "/").split("/")[-1]
    raw = re.sub(r"[^a-z0-9._-]+", "-", raw)
    raw = raw.strip("-._")
    return raw or "default"


def _hex_to_ass(hex_color: str) -> str:
    h = hex_color.strip().lstrip("#")
    if len(h) == 8:
        r, g, b, a = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00ffffff"


def _ass_color_to_hex(ass_color: str) -> str:
    c = ass_color.strip().lstrip("&Hh")
    if len(c) == 8:
        b, g, r = c[2:4], c[4:6], c[6:8]
    elif len(c) == 6:
        b, g, r = c[0:2], c[2:4], c[4:6]
    else:
        return "#ffffff"
    return f"#{r}{g}{b}"


def _parse_ass_txt(content: str) -> AssSubtitleStyle:
    kwargs: dict = {}
    secondary_kwargs: dict = {}

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Style: Default,"):
            parts = line.split(",")
            kwargs["font_name"] = parts[1]
            kwargs["font_size"] = int(parts[2])
            kwargs["primary_color"] = _ass_color_to_hex(parts[3])
            kwargs["outline_color"] = _ass_color_to_hex(parts[5])
            kwargs["bold"] = parts[7].strip() == "-1"
            kwargs["spacing"] = float(parts[13])
            kwargs["outline_width"] = float(parts[16])
            kwargs["margin_bottom"] = int(parts[21])
        elif line.startswith("Style: Secondary,"):
            parts = line.split(",")
            secondary_kwargs["font_name"] = parts[1]
            secondary_kwargs["font_size"] = int(parts[2])
            secondary_kwargs["color"] = _ass_color_to_hex(parts[3])
            secondary_kwargs["outline_color"] = _ass_color_to_hex(parts[5])
            secondary_kwargs["bold"] = parts[7].strip() == "-1"
            secondary_kwargs["spacing"] = float(parts[13])
            secondary_kwargs["outline_width"] = float(parts[16])

    if secondary_kwargs:
        kwargs["secondary"] = AssSecondaryStyle(**secondary_kwargs)
    return AssSubtitleStyle(**kwargs)


__all__ = [
    "AssSecondaryStyle",
    "AssSubtitleStyle",
    "RoundedSubtitleStyle",
    "SecondaryStyle",
    "StyleMode",
    "StyleSource",
    "SubtitleRenderer",
    "SubtitleStyle",
    "SubtitleStylePreset",
    "available_style_names",
    "delete_user_style",
    "list_styles",
    "load_style",
    "normalize_renderer",
    "normalize_style_id",
    "preset_from_file",
    "preset_from_json",
    "save_user_style",
    "style_id_from_filename",
]
