"""Font discovery and loading utilities"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Union

from fontTools.ttLib import TTFont
from PIL import ImageFont

from videocaptioner.config import FONTS_PATH
from videocaptioner.core.utils.logger import setup_logger

FontType = Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]

logger = setup_logger("subtitle.font")


def _get_font_family_name(font_path: Path, font_index: int = 0) -> Optional[str]:
    """Extract font family name from font file (cross-platform)"""
    try:
        font = TTFont(str(font_path), fontNumber=font_index)
        name_table = font.get("name")
        if not name_table:
            return None

        # nameID 16: Typographic Family (preferred)
        # nameID 1: Font Family (fallback)
        for name_id in [16, 1]:
            for record in name_table.names:
                if record.nameID == name_id and record.platformID == 3:
                    try:
                        family_name = record.toUnicode()
                        return family_name.split(",")[0].strip()
                    except Exception:
                        continue

        for name_id in [16, 1]:
            for record in name_table.names:
                if record.nameID == name_id:
                    try:
                        family_name = record.toUnicode()
                        return family_name.split(",")[0].strip()
                    except Exception:
                        continue

        return None
    except Exception as e:
        logger.debug(f"Failed to parse font {font_path.name} (index={font_index}): {e}")
        return None


@lru_cache(maxsize=1)
def get_builtin_fonts() -> tuple[Dict[str, str], ...]:
    """Get built-in fonts list with actual family names"""
    builtin_fonts = []

    if FONTS_PATH.exists():
        for font_file in FONTS_PATH.glob("*.[ot]tf*"):
            family_name = _get_font_family_name(font_file)
            if family_name:
                builtin_fonts.append({"name": family_name, "path": str(font_file)})
                logger.debug(f"Built-in font: {font_file.name} -> {family_name}")
            else:
                display_name = font_file.stem
                builtin_fonts.append({"name": display_name, "path": str(font_file)})
                logger.debug(f"Cannot get family name for {font_file.name}, using filename")

    return tuple(builtin_fonts)


@lru_cache(maxsize=64)
def get_font(size: int, font_name: str = "") -> FontType:
    """Get font object (built-in fonts first, then system fonts)"""
    if font_name:
        builtin_fonts = get_builtin_fonts()
        for builtin in builtin_fonts:
            if builtin["name"] == font_name:
                try:
                    font = ImageFont.truetype(builtin["path"], size)
                    logger.debug(f"Loaded built-in font: '{font_name}'")
                    return font
                except Exception as e:
                    logger.warning(f"Failed to load built-in font: {e}")
                    break

        try:
            font = ImageFont.truetype(font_name, size)
            logger.debug(f"Loaded system font: '{font_name}'")
            return font
        except (OSError, IOError):
            logger.warning(f"Cannot load font '{font_name}', using fallback")

    fallback_fonts = [f["name"] for f in get_builtin_fonts()]
    fallback_fonts.extend(
        [
            "PingFang SC",
            "Hiragino Sans GB",
            "Microsoft YaHei",
            "SimHei",
            "Arial Unicode MS",
            "Arial",
            "Helvetica",
        ]
    )

    for fallback in fallback_fonts:
        try:
            font = ImageFont.truetype(fallback, size)
            logger.debug(f"Using fallback font: '{fallback}'")
            return font
        except Exception:
            continue

    logger.warning("All fallback fonts failed, using default")
    return ImageFont.load_default()


@lru_cache(maxsize=128)
def get_ass_to_pil_ratio(font_name: str) -> float:
    """ASS 字号 → PIL 字号的换算比：PIL_size = ASS_size / ratio。

    libass 兼容 VSFilter，把字号解释为 Windows 行高（usWinAscent+usWinDescent），
    PIL 的字号是 em 高（unitsPerEm）。比值经 libass 实测校准：文楷 1.317 实测
    1.327、Noto Sans SC 1.448 实测 1.452，误差 <1%。

    字体文件必须经 get_font 的加载结果定位（家族名 ≠ 文件名，按文件名 glob
    会找不到而落到错误的默认值）。
    """
    font = get_font(100, font_name)
    font_path = getattr(font, "path", None)
    if not font_path:
        logger.debug(f"No font file for {font_name}, using default ratio 1.448")
        return 1.448
    try:
        tt = TTFont(font_path, fontNumber=0)
        units_per_em = tt["head"].unitsPerEm  # type: ignore
        win_ascent = tt["OS/2"].usWinAscent  # type: ignore
        win_descent = tt["OS/2"].usWinDescent  # type: ignore
        return (win_ascent + win_descent) / units_per_em
    except Exception as e:
        logger.warning(f"Failed to read font metrics for {font_name}: {e}")
        return 1.448


def clear_font_cache():
    """Clear font cache"""
    get_builtin_fonts.cache_clear()
    get_font.cache_clear()
    get_ass_to_pil_ratio.cache_clear()
    logger.debug("Font cache cleared")
