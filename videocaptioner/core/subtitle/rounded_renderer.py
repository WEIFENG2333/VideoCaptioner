"""Rounded background subtitle renderer"""

import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from PIL import Image, ImageDraw

from videocaptioner.core.entities import SubtitleLayoutEnum
from videocaptioner.core.subtitle.preview_cache import preview_path
from videocaptioner.core.subtitle.preview_cache import prune as prune_preview_cache
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.media_info import probe_media

from .font_utils import FontType, get_font
from .styles import RoundedBgStyle
from .text_utils import hex_to_rgba, wrap_text

if TYPE_CHECKING:
    from videocaptioner.core.asr.asr_data import ASRData

logger = setup_logger("subtitle.rounded")


def _get_video_info(video_path: str) -> Tuple[int, int, float]:
    """获取视频分辨率和时长；无视频流时抛 ValueError（圆角渲染必须知道画布尺寸）。"""
    info = probe_media(video_path)
    if info is None or not info.has_video:
        raise ValueError(f"Cannot get video resolution: {video_path}")
    return info.width, info.height, info.duration_seconds


def _scaled_style(style: RoundedBgStyle, width: int, height: int) -> RoundedBgStyle:
    """样式以 720p 为基准编写，按目标分辨率的短边等比缩放全部尺寸字段。"""
    factor = min(width, height) / 720
    if factor == 1.0:
        return style
    return replace(
        style,
        font_size=int(style.font_size * factor),
        corner_radius=int(style.corner_radius * factor),
        padding_h=int(style.padding_h * factor),
        padding_v=int(style.padding_v * factor),
        margin_bottom=int(style.margin_bottom * factor),
        line_spacing=int(style.line_spacing * factor),
        letter_spacing=int(style.letter_spacing * factor),
    )


def render_text_block(
    draw: ImageDraw.ImageDraw,
    texts: List[str],
    font: FontType,
    usable_left: int,
    usable_right: int,
    top_y: float,
    style: RoundedBgStyle,
) -> float:
    """
    渲染多行文本块（共享圆角背景）

    Args:
        draw: PIL ImageDraw 对象
        texts: 文本行列表
        font: 字体对象
        usable_left: 可用区域左边界（受最大宽度约束）
        usable_right: 可用区域右边界
        top_y: 顶部 y 坐标
        style: 样式配置

    Returns:
        背景框高度
    """
    if not texts:
        return 0

    bg_color = hex_to_rgba(style.bg_color)
    text_color = hex_to_rgba(style.text_color)

    # 计算All行的尺寸和垂直偏移
    line_sizes = []
    line_offsets = []
    for text in texts:
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        # 如果有字符间距，需要加上额外的宽度
        if style.letter_spacing > 0 and len(text) > 1:
            text_width += style.letter_spacing * (len(text) - 1)
        line_sizes.append((text_width, bbox[3] - bbox[1]))
        line_offsets.append(bbox[1])  # 记录垂直偏移，用于居中对齐

    block_width = max(w for w, h in line_sizes)
    # 行高用固定模板串，与 render_subtitle_image 的块高估算取同一值——
    # 按各行自身 bbox 取高会随内容（有无下伸部）抖动，背景框和文字错位
    template_bbox = font.getbbox("测试Ag")
    line_height = template_bbox[3] - template_bbox[1]
    total_height = line_height * len(texts) + style.line_spacing * (len(texts) - 1)

    # 绘制共享背景：按对齐方式把气泡贴到可用区域的左/中/右
    bg_width = block_width + style.padding_h * 2
    bg_height = total_height + style.padding_v * 2
    if style.align == "left":
        bg_left = usable_left
    elif style.align == "right":
        bg_left = usable_right - bg_width
    else:
        bg_left = (usable_left + usable_right) // 2 - bg_width // 2
    bg_top = top_y

    draw.rounded_rectangle(
        [bg_left, bg_top, bg_left + bg_width, bg_top + bg_height],
        radius=style.corner_radius,
        fill=bg_color,
    )

    # 绘制文本（文字在气泡内水平居中，补偿字体垂直偏移）
    text_center = bg_left + bg_width // 2
    y = bg_top + style.padding_v
    for i, text in enumerate(texts):
        w, h = line_sizes[i]
        x = text_center - w // 2
        y_offset = line_offsets[i]
        text_y = y - y_offset  # 补偿垂直偏移，使文本视觉居中

        # 如果有字符间距，逐字符绘制
        if style.letter_spacing > 0 and len(text) > 1:
            current_x = x
            for char in text:
                draw.text((current_x, text_y), char, font=font, fill=text_color)
                char_width = font.getbbox(char)[2] - font.getbbox(char)[0]
                current_x += char_width + style.letter_spacing
        else:
            # 无字符间距，一次性绘制（性能更好）
            draw.text((x, text_y), text, font=font, fill=text_color)

        y += line_height + style.line_spacing

    return bg_height


def render_subtitle_image(
    primary_text: str,
    secondary_text: str,
    width: int,
    height: int,
    style: RoundedBgStyle,
) -> Image.Image:
    """
    渲染单帧字幕图像（透明背景）

    Args:
        primary_text: 主字幕文本
        secondary_text: 副字幕文本
        width: 图像宽度
        height: 图像高度
        style: 样式配置

    Returns:
        PIL Image 对象（RGBA 格式）
    """
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = get_font(style.font_size, style.font_name)

    # 可用区域受最大宽度百分比约束；文字可用宽再扣去气泡左右内边距。
    # 断行测量必须带 letter_spacing——绘制端逐字加间距，测量不带会超出气泡。
    max_pct = style.max_width if 0 < style.max_width <= 100 else 90
    usable_w = max(1, int(width * max_pct / 100))
    usable_left = (width - usable_w) // 2
    usable_right = usable_left + usable_w
    text_max_w = max(1, usable_w - style.padding_h * 2)
    primary_lines = (
        wrap_text(primary_text, font, text_max_w, spacing=style.letter_spacing)
        if primary_text
        else []
    )
    secondary_lines = (
        wrap_text(secondary_text, font, text_max_w, spacing=style.letter_spacing)
        if secondary_text
        else []
    )

    # 计算总高度
    def calc_block_height(lines: List[str]) -> float:
        if not lines:
            return 0
        bbox = font.getbbox("测试Ag")
        line_h = bbox[3] - bbox[1]
        return line_h * len(lines) + style.line_spacing * (len(lines) - 1) + style.padding_v * 2

    primary_height = calc_block_height(primary_lines)
    secondary_height = calc_block_height(secondary_lines)
    gap = style.line_spacing if primary_lines and secondary_lines else 0
    total_height = primary_height + gap + secondary_height

    # 从底部计算起始位置
    bottom_y = height - style.margin_bottom
    start_y = bottom_y - total_height

    # 渲染文本块
    current_y = start_y
    if primary_lines:
        h = render_text_block(
            draw, primary_lines, font, usable_left, usable_right, current_y, style
        )
        current_y += h + gap
    if secondary_lines:
        render_text_block(draw, secondary_lines, font, usable_left, usable_right, current_y, style)

    return image


def render_preview(
    primary_text: str,
    secondary_text: str = "",
    width: Optional[int] = None,
    height: Optional[int] = None,
    style: Optional[RoundedBgStyle] = None,
    bg_image_path: Optional[str] = None,
) -> str:
    """
    渲染圆角背景字幕预览图

    Args:
        primary_text: 主字幕文本
        secondary_text: 副字幕文本
        width: 图片宽度（None=从bg_image_path自动获取）
        height: 图片高度（None=从bg_image_path自动获取）
        style: 圆角背景样式（按分辨率短边自动缩放）
        bg_image_path: 背景图片路径
    Returns:
        生成的预览图路径
    """
    if style is None:
        style = RoundedBgStyle()

    # 先解析尺寸（懒探测，不解码像素）以构建缓存签名
    has_bg = bool(bg_image_path) and Path(bg_image_path).exists()
    if width is None or height is None:
        if has_bg:
            with Image.open(bg_image_path) as probe:
                bw, bh = probe.size
            width = width or bw
            height = height or bh
        else:
            width = width or 1920
            height = height or 1080
    assert width is not None and height is not None

    # 内容寻址缓存：同样的样式 + 文字 + 背景 + 尺寸只渲染一次，命中即直接返回
    output_path = preview_path(
        f"rounded|{primary_text}|{secondary_text}|{width}x{height}|{bg_image_path}|{style!r}"
    )
    if output_path.exists():
        return str(output_path)

    # 加载或创建背景
    if has_bg:
        background = Image.open(bg_image_path).convert("RGB")
    else:
        background = Image.new("RGB", (width, height), (20, 20, 20))

    style = _scaled_style(style, width, height)

    # 渲染字幕并叠加
    subtitle_img = render_subtitle_image(primary_text, secondary_text, width, height, style)
    background.paste(subtitle_img, (0, 0), subtitle_img)

    background.save(output_path, "PNG")
    prune_preview_cache()
    return str(output_path)


def render_rounded_video(
    video_path: str,
    asr_data: "ASRData",
    output_path: str,
    rounded_style: Optional[dict] = None,
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ONLY_ORIGINAL,
    crf: int = 23,
    preset: str = "medium",
    progress_callback: Optional[Callable] = None,
) -> None:
    """把字幕以圆角气泡样式烧录进视频。

    每帧字幕先渲染成透明 PNG，再分批 overlay 到视频上（每批 50 个，
    避开 FFmpeg 的输入数量限制）。progress_callback(percent, message)。
    """
    if not asr_data or not asr_data.segments:
        raise ValueError("Empty subtitle data, cannot render video")

    # 无译文时双语/仅译文布局都退回仅原文
    needs_translation = layout in (
        SubtitleLayoutEnum.ONLY_TRANSLATE,
        SubtitleLayoutEnum.TRANSLATE_ON_TOP,
        SubtitleLayoutEnum.ORIGINAL_ON_TOP,
    )
    if needs_translation and not any(
        seg.translated_text and seg.translated_text.strip() for seg in asr_data.segments
    ):
        layout = SubtitleLayoutEnum.ONLY_ORIGINAL

    width, height, video_duration = _get_video_info(video_path)

    style_config = rounded_style or {}
    style_config["layout"] = layout
    style = _scaled_style(RoundedBgStyle(**style_config), width, height)

    with tempfile.TemporaryDirectory(prefix="rounded_subtitle_") as temp_dir:
        temp_path = Path(temp_dir)

        # 步骤1: 生成全部字幕 PNG（进度 0-30%）
        logger.debug(
            "Generating %d subtitle PNGs (layout: %s)", len(asr_data.segments), layout.value
        )
        subtitle_frames = []

        for i, seg in enumerate(asr_data.segments):
            # 根据布局确定主副文本
            if layout == SubtitleLayoutEnum.ONLY_ORIGINAL:
                primary, secondary = seg.text, ""
            elif layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
                primary, secondary = seg.translated_text or "", ""
            elif layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP:
                primary, secondary = seg.text, seg.translated_text or ""
            else:  # TRANSLATE_ON_TOP
                primary, secondary = seg.translated_text or "", seg.text

            # 渲染字幕图片
            img = render_subtitle_image(primary, secondary, width, height, style)
            png_path = temp_path / f"subtitle_{i:06d}.png"
            img.save(png_path, "PNG")

            # 记录时间戳
            start_time = seg.start_time / 1000.0
            end_time = seg.end_time / 1000.0
            subtitle_frames.append((start_time, end_time, png_path))

            # 进度回调
            if progress_callback:
                progress = int((i + 1) / len(asr_data.segments) * 30)
                progress_callback(progress, f"生成字幕图片 {i + 1}/{len(asr_data.segments)}")

        if not subtitle_frames:
            raise ValueError("No valid subtitle images generated")

        # 步骤2: 分批overlay到视频 (30-100%)
        logger.debug("Overlaying subtitle batches onto video")
        BATCH_SIZE = 50
        current_video = video_path
        total_batches = (len(subtitle_frames) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(total_batches):
            start_idx = batch_idx * BATCH_SIZE
            end_idx = min((batch_idx + 1) * BATCH_SIZE, len(subtitle_frames))
            batch_frames = subtitle_frames[start_idx:end_idx]

            # 构建overlay滤镜链
            input_args = ["-i", current_video]
            filter_parts = []

            for local_idx, (start, end, png_path) in enumerate(batch_frames):
                input_args.extend(["-i", str(png_path)])
                prev = f"[v{local_idx}]" if local_idx > 0 else "[0:v]"
                curr = f"[{local_idx + 1}:v]"
                out = f"[v{local_idx + 1}]"
                filter_parts.append(
                    f"{prev}{curr}overlay=0:0:enable='between(t,{start},{end})'{out}"
                )

            filter_complex = ";".join(filter_parts)
            final_output = f"[v{len(batch_frames)}]"

            # 判断是否是最后一批
            is_last_batch = batch_idx == total_batches - 1
            batch_output = (
                output_path if is_last_batch else temp_path / f"batch_{batch_idx:03d}.mp4"
            )

            logger.debug(
                f"Processing batch {batch_idx + 1}/{total_batches}（{len(batch_frames)}个字幕）"
            )
            # 构建 ffmpeg Command
            # -t 参数强制保持原视频时长，防止因 overlay ended而截断视频
            cmd = [
                "ffmpeg",
                "-y",
                *input_args,
                "-filter_complex",
                filter_complex,
                "-map",
                final_output,
                "-map",
                "0:a?",
                "-t",
                str(video_duration),  # 强制保持原视频时长
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast" if not is_last_batch else preset,
                "-crf",
                "0" if not is_last_batch else str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(batch_output),
            ]

            if batch_idx == 0 or is_last_batch:
                cmd_str = subprocess.list2cmdline(cmd)
                logger.debug(f"FFmpeg cmd: {cmd_str}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                ),
            )

            if result.returncode != 0:
                logger.error(f"批次 {batch_idx + 1} 失败: {result.stderr}")
                raise RuntimeError(f"Subtitle processing failed（批次 {batch_idx + 1}）")

            # 更新进度 (30-100%)
            if progress_callback:
                progress = 30 + int((batch_idx + 1) / total_batches * 70)
                progress_callback(progress, f"合成视频 {batch_idx + 1}/{total_batches}")

            # 更新当前视频
            current_video = str(batch_output)

        logger.debug("Video synthesis complete")
