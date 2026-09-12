"""synthesize command -- burn subtitles into video."""

import json
from argparse import Namespace
from pathlib import Path
from typing import Literal, Optional

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.cli.validators import validate_synthesize
from videocaptioner.core.application.config_store import get
from videocaptioner.core.subtitle.style_manager import (
    StyleSource,
    SubtitleRenderer,
    available_style_names,
    load_style,
    normalize_style_id,
    preset_from_json,
)

EncodePreset = Literal[
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]

# Quality presets: name -> (crf, ffmpeg preset)
_QUALITY_MAP: dict[str, tuple[int, EncodePreset]] = {
    "ultra": (18, "slow"),
    "high": (23, "medium"),
    "medium": (28, "medium"),
    "low": (32, "fast"),
}

def _resolve_style(config: dict, verbose: bool) -> tuple:
    """Resolve style settings from config.

    Returns (render_mode, ass_style_str, rounded_style_dict, font_file, style_obj).
    """
    render_mode = get(config, "synthesize.render_mode", "ass")
    style_name = get(config, "synthesize.style", "default")
    style_override_str = get(config, "synthesize.style_override", None)
    font_file = get(config, "synthesize.font_file", None)

    # Validate font_file
    if font_file and not Path(font_file).exists():
        output.error(f"Font file not found: {font_file}")
        return None, None, None, None, None

    # Parse --style-override JSON
    override_dict: dict = {}
    if style_override_str:
        try:
            override_dict = json.loads(style_override_str)
            if not isinstance(override_dict, dict):
                output.error("--style-override must be a JSON object, e.g. '{\"font_size\": 48}'")
                return None, None, None, None, None
        except json.JSONDecodeError as e:
            output.error(f"Invalid --style-override JSON: {e}")
            output.hint('Example: --style-override \'{"outline_color": "#ff0000", "font_size": 48}\'')
            return None, None, None, None, None

    # Load base style from preset. 样式 id 的渲染器前缀是唯一真源：
    # 带前缀时渲染管线跟随前缀，render_mode 只给无前缀的名字补默认。
    style_id = normalize_style_id(style_name, render_mode)
    style = load_style(style_id)
    if style is not None:
        render_mode = "rounded" if style.renderer == SubtitleRenderer.ROUNDED else "ass"
        renderer = style.renderer
    if style is None:
        names = available_style_names()
        output.error(f"Style preset not found: '{style_name}'")
        if names:
            output.hint(f"Available presets: {', '.join(names)}")
        output.hint("Run 'videocaptioner style' to see all options")
        return None, None, None, None, None

    # Apply --style-override on top of base style
    if override_dict:
        # Auto-detect mode from override fields
        if any(k in override_dict for k in ("bg_color", "text_color", "corner_radius")):
            if render_mode == "ass":
                render_mode = "rounded"
                renderer = SubtitleRenderer.ROUNDED
                style = load_style("rounded/default", renderer=renderer) or style
        base = style.to_json_dict()
        base.update(override_dict)
        base["id"] = normalize_style_id(base.get("id") or style.id, render_mode)
        style = preset_from_json(base, source=StyleSource.USER, renderer_hint=renderer)

    # Print final style config
    if verbose:
        final = style.to_json_dict()
        output.info(f"Render mode: {render_mode}")
        output.info(f"Style config: {json.dumps(final, ensure_ascii=False)}")

    # Build output
    if render_mode == "rounded":
        rounded_dict = style.to_rounded_dict()
        if font_file:
            rounded_dict["font_name"] = _get_font_family_name(font_file)
        return render_mode, "", rounded_dict, font_file, style

    # ASS mode
    ass_style = style.to_ass_string()
    if font_file:
        ass_style = _override_ass_font(ass_style, font_file, None)
    return render_mode, ass_style, None, font_file, style


def _get_font_family_name(font_path: str) -> str:
    """Read the font family name from a TTF/OTF file's name table."""
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(font_path)
        name_table = font["name"]
        # nameID 1 = Font Family Name
        for record in name_table.names:
            if record.nameID == 1 and record.platformID in (0, 3):
                return str(record)
        # Fallback to any nameID 1
        for record in name_table.names:
            if record.nameID == 1:
                return str(record)
    except Exception:
        pass
    # Last resort: use filename without extension
    return Path(font_path).stem


def _override_ass_font(ass_style: str, font_file: Optional[str], font_size: Optional[int]) -> str:
    """Override font name/size in ASS style string."""
    font_name = _get_font_family_name(font_file) if font_file else None
    lines = ass_style.splitlines()
    result = []
    for line in lines:
        if line.startswith("Style:"):
            parts = line.split(",")
            if font_name and len(parts) > 1:
                parts[1] = font_name
            if font_size and len(parts) > 2:
                parts[2] = str(font_size)
            line = ",".join(parts)
        result.append(line)
    return "\n".join(result)


def run(args: Namespace, config: dict) -> int:
    video_path = Path(args.video)
    subtitle_path = Path(args.subtitle)

    if not video_path.exists():
        output.error(f"Video file not found: {video_path}")
        return EXIT.FILE_NOT_FOUND
    if not subtitle_path.exists():
        output.error(f"Subtitle file not found: {subtitle_path}")
        return EXIT.FILE_NOT_FOUND

    from videocaptioner.cli.validators import validate_video_input
    err = validate_video_input(video_path)
    if err is not None:
        return err

    if not validate_synthesize(config):
        return EXIT.DEPENDENCY_MISSING

    subtitle_mode = get(config, "synthesize.subtitle_mode", "soft")
    quality = get(config, "synthesize.quality", "medium")
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)

    crf, preset = _QUALITY_MAP.get(quality, (28, "medium"))
    soft = subtitle_mode == "soft"

    # Warn if user explicitly passed style options with soft mode
    style_arg = getattr(args, "style", None)
    override_arg = getattr(args, "style_override", None)
    render_arg = getattr(args, "render_mode", None)
    if soft and any([style_arg, override_arg, render_arg]):
        output.warn("Style options are ignored in soft subtitle mode (player controls rendering)")

    # Output path：软/硬是参数不是产物角色，统一 {stem}.subtitled.{ext}
    if args.output:
        output_path = args.output
    else:
        from videocaptioner.core.application import output_paths

        output_path = str(
            output_paths.product_path(video_path, output_paths.TAG_SUBTITLED)
        )

    # Check input != output
    if Path(output_path).resolve() == video_path.resolve():
        output.error("Output path is the same as input video. Use -o to specify a different output.")
        return EXIT.USAGE_ERROR

    if verbose:
        output.info(f"Mode: {'soft (embedded track)' if soft else 'hard (burned in)'}")
        output.info(f"Quality: {quality} (CRF={crf}, preset={preset})")

    progress = None if quiet else output.ProgressLine(f"Synthesizing video [{subtitle_mode}]").start()

    def progress_callback(*cb_args) -> None:
        if progress and cb_args:
            try:
                progress.update(int(float(cb_args[0])), f"Encoding [{subtitle_mode}]")
            except (ValueError, TypeError):
                pass

    try:
        if soft:
            # Soft subtitle: embed as track (no style control)
            from videocaptioner.core.utils.video_utils import add_subtitles
            add_subtitles(
                input_file=str(video_path),
                subtitle_file=str(subtitle_path),
                output=output_path,
                crf=crf,
                preset=preset,
                soft_subtitle=True,
                progress_callback=progress_callback,
            )
        else:
            # Hard subtitle: resolve style and render
            resolved = _resolve_style(config, verbose)
            mode, ass_style, rounded_style, font_file, _ = resolved
            if mode is None:
                if progress:
                    progress.fail("Style configuration error")
                return EXIT.USAGE_ERROR

            # 样式 id 的渲染器前缀是唯一真源：显式 --render-mode 与所选样式前缀冲突时
            # 会被忽略，提示用户改用对应前缀的样式，避免"传了 flag 却不生效"的困惑。
            if render_arg and render_arg != mode:
                style_name = get(config, "synthesize.style", "default")
                output.warn(
                    f"--render-mode {render_arg} 被忽略：样式 '{style_name}' 的前缀决定了"
                    f"渲染模式为 {mode}。如需 {render_arg} 渲染，请改用 {render_arg}/ 前缀的样式"
                    f"（运行 'videocaptioner style' 查看）。"
                )

            from videocaptioner.cli.validators import resolve_layout
            from videocaptioner.core.asr.asr_data import ASRData
            layout_str = get(config, "synthesize.layout", "target-above")
            layout = resolve_layout(layout_str)

            # 字幕文件的行序即布局；按文件行序原样烧录，不二次翻转已排版的双语文件。
            asr_data = ASRData.from_subtitle_file(str(subtitle_path))
            layout = asr_data.resolve_layout_from_file(layout)

            if mode == "rounded":
                from videocaptioner.core.subtitle.rounded_renderer import render_rounded_video
                render_rounded_video(
                    video_path=str(video_path),
                    asr_data=asr_data,
                    output_path=output_path,
                    rounded_style=rounded_style,
                    layout=layout,
                    crf=crf,
                    preset=preset,
                    progress_callback=progress_callback,
                )
            else:
                from videocaptioner.core.subtitle.ass_renderer import render_ass_video

                # Register custom font if provided
                if font_file:
                    _register_font(font_file)

                render_ass_video(
                    video_path=str(video_path),
                    asr_data=asr_data,
                    output_path=output_path,
                    style_str=ass_style,
                    layout=layout,
                    crf=crf,
                    preset=preset,
                    progress_callback=progress_callback,
                )

        if progress:
            progress.finish(f"Done -> {output_path}")
        if quiet:
            print(output_path)
        return EXIT.SUCCESS

    except Exception as e:
        msg = output.clean_error(str(e))
        if progress:
            progress.fail(msg)
        else:
            output.error(msg)
        if verbose:
            import traceback
            traceback.print_exc()
        return EXIT.RUNTIME_ERROR


def _register_font(font_file: str) -> None:
    """Copy custom font file to FONTS_PATH so FFmpeg can find it."""
    import shutil

    from videocaptioner.config import FONTS_PATH
    FONTS_PATH.mkdir(parents=True, exist_ok=True)
    dest = FONTS_PATH / Path(font_file).name
    if not dest.exists():
        shutil.copy(font_file, dest)
