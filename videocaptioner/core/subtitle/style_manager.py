"""Unified subtitle style management.

Single source of truth for loading, converting, and listing subtitle styles.
Both CLI and UI import from here.
"""

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class StyleMode(Enum):
    ASS = "ass"
    ROUNDED = "rounded"


@dataclass
class SecondaryStyle:
    """Secondary (bilingual) subtitle style for ASS mode."""

    font_name: str = "Arial"
    font_size: int = 30
    color: str = "#ffffff"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    spacing: float = 0.8


@dataclass
class SubtitleStyle:
    """Unified subtitle style definition.

    A single dataclass that covers both ASS and rounded modes.
    Fields irrelevant to the current mode are simply ignored.
    """

    # -- Metadata --
    name: str = ""
    description: str = ""
    mode: StyleMode = StyleMode.ASS

    # -- Common --
    font_name: str = "Noto Sans SC"
    font_size: int = 42

    # -- ASS mode fields --
    primary_color: str = "#65ff5a"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    bold: bool = True
    spacing: float = 3.2
    margin_bottom: int = 30
    secondary: Optional[SecondaryStyle] = None

    # -- Rounded mode fields --
    text_color: str = "#000000"
    bg_color: str = "#0de3ffe5"
    corner_radius: int = 14
    padding_h: int = 24
    padding_v: int = 18
    line_spacing: int = 12
    letter_spacing: int = 1
    margin_bottom_rounded: int = 40

    # ------------------------------------------------------------------ #
    # Conversion helpers
    # ------------------------------------------------------------------ #

    def to_ass_string(self) -> str:
        """Render as ASS V4+ Styles section (for FFmpeg)."""
        primary = _hex_to_ass(self.primary_color)
        outline = _hex_to_ass(self.outline_color)
        bold_flag = -1 if self.bold else 0

        sec = self.secondary or SecondaryStyle(
            font_name=self.font_name,
            font_size=int(self.font_size * 0.7),
        )
        sec_color = _hex_to_ass(sec.color)
        sec_outline = _hex_to_ass(sec.outline_color)

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
            f"{self.outline_width},0,2,10,10,{self.margin_bottom},1,\\q1"
        )
        secondary_line = (
            f"Style: Secondary,{sec.font_name},{sec.font_size},"
            f"{sec_color},&H000000FF,{sec_outline},&H00000000,"
            f"{bold_flag},0,0,0,100,100,{sec.spacing},0,1,"
            f"{sec.outline_width},0,2,10,10,{self.margin_bottom},1,\\q1"
        )
        return f"{header}\n{default_line}\n{secondary_line}"

    def to_rounded_dict(self) -> dict:
        """Return the dict expected by the rounded renderer."""
        return {
            "font_name": self.font_name,
            "font_size": self.font_size,
            "text_color": self.text_color,
            "bg_color": self.bg_color,
            "corner_radius": self.corner_radius,
            "padding_h": self.padding_h,
            "padding_v": self.padding_v,
            "margin_bottom": self.margin_bottom_rounded,
            "line_spacing": self.line_spacing,
            "letter_spacing": self.letter_spacing,
        }

    def to_json_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (for saving)."""
        d: dict = {"name": self.name, "description": self.description, "mode": self.mode.value}
        if self.mode == StyleMode.ROUNDED:
            d.update(self.to_rounded_dict())
        else:
            d.update({
                "font_name": self.font_name,
                "font_size": self.font_size,
                "primary_color": self.primary_color,
                "outline_color": self.outline_color,
                "outline_width": self.outline_width,
                "bold": self.bold,
                "spacing": self.spacing,
                "margin_bottom": self.margin_bottom,
            })
            if self.secondary:
                d["secondary"] = asdict(self.secondary)
        return d

    # ------------------------------------------------------------------ #
    # Factory methods
    # ------------------------------------------------------------------ #

    @classmethod
    def from_json(cls, data: dict) -> "SubtitleStyle":
        """Create from a parsed JSON dict. Auto-detects mode if not specified."""
        if "mode" in data:
            mode = StyleMode(data["mode"])
        elif any(k in data for k in ("bg_color", "text_color", "corner_radius")):
            mode = StyleMode.ROUNDED
        else:
            mode = StyleMode.ASS
        sec_data = data.get("secondary")
        secondary = SecondaryStyle(**sec_data) if isinstance(sec_data, dict) else None

        if mode == StyleMode.ROUNDED:
            return cls(
                name=data.get("name", ""),
                description=data.get("description", ""),
                mode=mode,
                font_name=data.get("font_name", cls.font_name),
                font_size=data.get("font_size", cls.font_size),
                text_color=data.get("text_color", cls.text_color),
                bg_color=data.get("bg_color", cls.bg_color),
                corner_radius=data.get("corner_radius", cls.corner_radius),
                padding_h=data.get("padding_h", cls.padding_h),
                padding_v=data.get("padding_v", cls.padding_v),
                margin_bottom_rounded=data.get("margin_bottom", cls.margin_bottom_rounded),
                line_spacing=data.get("line_spacing", cls.line_spacing),
                letter_spacing=data.get("letter_spacing", cls.letter_spacing),
            )

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            mode=mode,
            font_name=data.get("font_name", cls.font_name),
            font_size=data.get("font_size", cls.font_size),
            primary_color=data.get("primary_color", cls.primary_color),
            outline_color=data.get("outline_color", cls.outline_color),
            outline_width=data.get("outline_width", cls.outline_width),
            bold=data.get("bold", cls.bold),
            spacing=data.get("spacing", cls.spacing),
            margin_bottom=data.get("margin_bottom", cls.margin_bottom),
            secondary=secondary,
        )

    @classmethod
    def from_file(cls, path: Path) -> "SubtitleStyle":
        """Load from a file (.json or legacy .txt)."""
        content = path.read_text(encoding="utf-8")

        if path.suffix == ".json":
            return cls.from_json(json.loads(content))

        # Legacy .txt fallback: parse ASS V4+ Style lines
        if "[V4+ Styles]" in content or "Style:" in content:
            return _parse_ass_txt(content, path.stem)

        raise ValueError(f"Unrecognized style file format: {path}")

    @classmethod
    def from_rounded_dict(cls, data: dict) -> "SubtitleStyle":
        """Create a rounded style from a flat dict (used by UI config)."""
        data_with_mode = {**data, "mode": "rounded"}
        return cls.from_json(data_with_mode)


# ------------------------------------------------------------------ #
# Module-level helpers
# ------------------------------------------------------------------ #

def style_id_from_filename(filename: str) -> str:
    """Extract user-facing style ID from filename.

    'ass-default.json' -> 'default', 'rounded-dark.json' -> 'dark'
    """
    stem = Path(filename).stem
    for prefix in ("ass-", "rounded-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def list_styles(styles_dir: Optional[Path] = None) -> List[SubtitleStyle]:
    """List all available styles in the directory."""
    if styles_dir is None:
        styles_dir = _default_styles_dir()
    if not styles_dir.exists():
        return []

    result: List[SubtitleStyle] = []
    for f in sorted(styles_dir.glob("*.json")):
        try:
            style = SubtitleStyle.from_file(f)
            # Use filename-derived ID if name not set in JSON
            if not style.name:
                style.name = style_id_from_filename(f.name)
            result.append(style)
        except Exception:
            logger.warning("Failed to load style %s", f)
    return result


def load_style(
    name: str,
    styles_dir: Optional[Path] = None,
    mode: Optional[str] = None,
) -> Optional[SubtitleStyle]:
    """Load a style by name (e.g. 'default', 'anime', 'rounded').

    Args:
        name: Style preset name.
        styles_dir: Directory containing style JSON files.
        mode: Preferred render mode ('ass' or 'rounded'). When set, the
              matching prefix is tried first so that ``load_style("default",
              mode="rounded")`` finds ``rounded-default.json`` before
              ``ass-default.json``.

    Searches by: exact filename match, prefixed filename (ass-X, rounded-X),
    or JSON 'name' field.
    """
    if styles_dir is None:
        styles_dir = _default_styles_dir()
    if not styles_dir.exists():
        return None

    # Try exact filename: <name>.json
    exact = styles_dir / f"{name}.json"
    if exact.exists():
        try:
            return SubtitleStyle.from_file(exact)
        except Exception:
            pass

    # Try prefixed filenames: ass-<name>.json, rounded-<name>.json
    # When *mode* is given, try the preferred prefix first.
    prefixes = ["ass-", "rounded-"]
    if mode == "rounded":
        prefixes = ["rounded-", "ass-"]
    for prefix in prefixes:
        prefixed = styles_dir / f"{prefix}{name}.json"
        if prefixed.exists():
            try:
                return SubtitleStyle.from_file(prefixed)
            except Exception:
                pass

    # Fallback: scan all files and match by JSON 'name' field
    for f in styles_dir.glob("*.json"):
        try:
            style = SubtitleStyle.from_file(f)
            if style.name == name or style_id_from_filename(f.name) == name:
                return style
        except Exception:
            pass

    return None


def available_style_names(styles_dir: Optional[Path] = None) -> List[str]:
    """Return sorted list of unique style names."""
    names = []
    for s in list_styles(styles_dir):
        names.append(s.name)
    return sorted(set(names))


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _default_styles_dir() -> Path:
    from videocaptioner.config import SUBTITLE_STYLE_PATH
    return SUBTITLE_STYLE_PATH


def _hex_to_ass(hex_color: str) -> str:
    """Convert #RRGGBB to ASS &H00BBGGRR format. Only used for ASS style colors."""
    h = hex_color.lstrip("#")
    if len(h) == 8:
        # #AARRGGBB
        a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00ffffff"


def _ass_color_to_hex(ass_color: str) -> str:
    """Convert ASS &HAABBGGRR to #RRGGBB hex."""
    c = ass_color.strip().lstrip("&Hh")
    if len(c) == 8:
        b, g, r = c[2:4], c[4:6], c[6:8]
    elif len(c) == 6:
        b, g, r = c[0:2], c[2:4], c[4:6]
    else:
        return "#ffffff"
    return f"#{r}{g}{b}"


def _parse_ass_txt(content: str, stem: str = "") -> SubtitleStyle:
    """Parse a legacy .txt file containing ASS V4+ Style lines."""
    kwargs: dict = {"name": stem, "mode": StyleMode.ASS}
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
            secondary_kwargs["spacing"] = float(parts[13])
            secondary_kwargs["outline_width"] = float(parts[16])

    if secondary_kwargs:
        kwargs["secondary"] = SecondaryStyle(**secondary_kwargs)

    return SubtitleStyle(**kwargs)
