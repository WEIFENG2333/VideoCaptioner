"""Font discovery and loading utilities"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Union

from fontTools.ttLib import TTFont
from PIL import ImageFont

from app.config import FONTS_PATH
from app.core.utils.logger import setup_logger

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
                logger.debug(
                    f"Cannot get family name for {font_file.name}, using filename"
                )

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
            logger.info(f"Using fallback font: '{fallback}'")
            return font
        except Exception:
            continue

    logger.warning("All fallback fonts failed, using default")
    return ImageFont.load_default()


@lru_cache(maxsize=128)
def get_ass_to_pil_ratio(font_name: str) -> float:
    """
    Get ASS to PIL font size conversion ratio

    ASS uses Windows line height (usWinAscent + usWinDescent),
    PIL uses em square (unitsPerEm).

    For Noto Sans SC: ratio = 1.448
    This means: PIL_size = ASS_size / 1.448

    Returns:
        Conversion ratio (typically 1.4-1.5 for CJK fonts)
    """
    # Find font file
    font_path = None
    for ext in [".ttf", ".otf", ".ttc"]:
        candidates = list(FONTS_PATH.glob(f"**/{font_name}*{ext}"))
        if candidates:
            font_path = candidates[0]
            break

    if not font_path:
        candidates = list(FONTS_PATH.glob(f"**/*{font_name}*"))
        if candidates:
            font_path = candidates[0]

    # Default ratio for most CJK fonts
    if not font_path:
        logger.debug(f"Font file not found: {font_name}, using default ratio 1.448")
        return 1.448

    try:
        font = TTFont(str(font_path))
        units_per_em = font["head"].unitsPerEm  # type: ignore
        win_ascent = font["OS/2"].usWinAscent  # type: ignore
        win_descent = font["OS/2"].usWinDescent  # type: ignore
        ratio = (win_ascent + win_descent) / units_per_em
        logger.debug(f"Font metrics for {font_name}: ratio={ratio:.3f}")
        return ratio
    except Exception as e:
        logger.warning(f"Failed to read font metrics for {font_name}: {e}")
        return 1.448


def clear_font_cache():
    """Clear font cache"""
    get_builtin_fonts.cache_clear()
    get_font.cache_clear()
    get_ass_to_pil_ratio.cache_clear()
    logger.info("Font cache cleared")
