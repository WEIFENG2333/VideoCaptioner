"""style command -- list and manage subtitle style presets."""

from argparse import Namespace

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.core.subtitle.style_manager import StyleMode, list_styles


def _get_styles_dir():
    from videocaptioner.config import SUBTITLE_STYLE_PATH
    return SUBTITLE_STYLE_PATH


def run(args: Namespace, config: dict) -> int:
    action = getattr(args, "style_action", None)
    if not action:
        output.error("No action specified. Use: videocaptioner style")
        return EXIT.USAGE_ERROR

    if action == "list":
        return _list(args)

    output.error(f"Unknown action: {action}")
    return EXIT.USAGE_ERROR


def _list(args: Namespace) -> int:
    """List all available subtitle styles."""
    styles_dir = _get_styles_dir()
    styles = list_styles(styles_dir)

    if not styles:
        output.error("No styles found.")
        output.hint("Style directory: " + str(styles_dir))
        return EXIT.GENERAL_ERROR

    print("Available subtitle styles:\n")
    print(f"  {'NAME':<14} {'MODE':<10} {'DESCRIPTION'}")
    sep = "\u2500"
    print(f"  {sep * 14} {sep * 10} {sep * 40}")

    for style in styles:
        mode_str = style.mode.value
        if style.description:
            desc = style.description
        elif style.mode == StyleMode.ROUNDED:
            desc = f"font={style.font_name}, size={style.font_size}, bg={style.bg_color}"
        else:
            desc = f"font={style.font_name}, size={style.font_size}, color={style.primary_color}"
            if style.bold:
                desc += ", bold"

        print(f"  {style.name:<14} {mode_str:<10} {desc}")

        # Show detailed parameters for all styles
        if style.mode == StyleMode.ROUNDED:
            for k, v in style.to_rounded_dict().items():
                print(f"    {k}: {v}")
        else:
            details = style.to_json_dict()
            for k in ["font_name", "font_size", "primary_color", "outline_color",
                       "outline_width", "bold", "spacing", "margin_bottom"]:
                if k in details:
                    print(f"    {k}: {details[k]}")
            if style.secondary:
                print(f"    secondary: font={style.secondary.font_name}, size={style.secondary.font_size}, color={style.secondary.color}")
        print()

    print("\nUsage:")
    print("  videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard --style <name>")
    print("  videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard --style-override '{\"outline_color\": \"#ff0000\"}'")

    print("  videocaptioner synthesize video.mp4 -s sub.srt --subtitle-mode hard --render-mode rounded")
    print("\nCustom style JSON fields:")
    print("  ASS mode:     font_name, font_size, primary_color (#rrggbb), outline_color,")
    print("                outline_width, bold (bool), spacing, margin_bottom,")
    print("                secondary: {font_name, font_size, color}")
    print("  Rounded mode: font_name, font_size, text_color (#rrggbb), bg_color (#rrggbbaa),")
    print("                corner_radius, padding_h, padding_v, margin_bottom,")
    print("                line_spacing, letter_spacing")
    print("\n  Tip: The render mode is auto-detected from --style-override content.")
    print("       Unless specified, use default style -- customize only when needed.")
    print("\nNote: Styles only apply to hard subtitles (--subtitle-mode hard).")
    print("      Soft subtitles are rendered by the video player.")
    return EXIT.SUCCESS
