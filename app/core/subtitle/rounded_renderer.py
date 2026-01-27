"""Rounded background subtitle renderer"""

import os
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from PIL import Image, ImageDraw

from app.core.entities import SubtitleLayoutEnum
from app.core.utils.logger import setup_logger

from .font_utils import FontType, get_font
from .styles import RoundedBgStyle
from .text_utils import hex_to_rgba, wrap_text

if TYPE_CHECKING:
    from app.core.asr.asr_data import ASRData

logger = setup_logger("subtitle.rounded")


def _get_video_info(video_path: str) -> Tuple[int, int, float]:
    """获取视频分辨率和时长"""
    result = subprocess.run(
        ["ffmpeg", "-i", video_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )

    # 解析分辨率
    width, height = 0, 0
    if match := re.search(r"Stream.*Video:.* (\d{2,5})x(\d{2,5})", result.stderr):
        width, height = int(match.group(1)), int(match.group(2))
    else:
        raise ValueError(f"无法获取视频分辨率: {video_path}")

    # 解析时长
    duration = 0.0
    if match := re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr):
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    return width, height, duration


def render_text_block(
    draw: ImageDraw.ImageDraw,
    texts: List[str],
    font: FontType,
    center_x: int,
    top_y: float,
    style: RoundedBgStyle,
) -> float:
    """
    渲染多行文本块（共享圆角背景）

    Args:
        draw: PIL ImageDraw 对象
        texts: 文本行列表
        font: 字体对象
        center_x: 水平中心位置
        top_y: 顶部 y 坐标
        style: 样式配置

    Returns:
        背景框高度
    """
    if not texts:
        return 0

    bg_color = hex_to_rgba(style.bg_color)
    text_color = hex_to_rgba(style.text_color)

    # 计算所有行的尺寸和垂直偏移
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

    max_width = max(w for w, h in line_sizes)
    line_height = max(h for w, h in line_sizes)
    total_height = line_height * len(texts) + style.line_spacing * (len(texts) - 1)

    # 绘制共享背景
    bg_width = max_width + style.padding_h * 2
    bg_height = total_height + style.padding_v * 2
    bg_left = center_x - bg_width // 2
    bg_top = top_y

    draw.rounded_rectangle(
        [bg_left, bg_top, bg_left + bg_width, bg_top + bg_height],
        radius=style.corner_radius,
        fill=bg_color,
    )

    # 绘制文本（补偿字体垂直偏移）
    y = bg_top + style.padding_v
    for i, text in enumerate(texts):
        w, h = line_sizes[i]
        x = center_x - w // 2
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

    # 换行处理（额外留 40px 边距防止文字贴边）
    extra_margin = int(width * 0.1)
    primary_lines = (
        wrap_text(primary_text, font, width, style.padding_h, extra_margin=extra_margin)
        if primary_text
        else []
    )
    secondary_lines = (
        wrap_text(secondary_text, font, width, style.padding_h, extra_margin=extra_margin)
        if secondary_text
        else []
    )

    center_x = width // 2

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
        h = render_text_block(draw, primary_lines, font, center_x, current_y, style)
        current_y += h + gap
    if secondary_lines:
        render_text_block(draw, secondary_lines, font, center_x, current_y, style)

    return image


def render_preview(
    primary_text: str,
    secondary_text: str = "",
    width: Optional[int] = None,
    height: Optional[int] = None,
    style: Optional[RoundedBgStyle] = None,
    bg_image_path: Optional[str] = None,
    reference_height: int = 720,
) -> str:
    """
    渲染圆角背景字幕预览图

    Args:
        primary_text: 主字幕文本
        secondary_text: 副字幕文本
        width: 图片宽度（None=从bg_image_path自动获取）
        height: 图片高度（None=从bg_image_path自动获取）
        style: 圆角背景样式（包含reference_height，会根据height自动缩放）
        bg_image_path: 背景图片路径
        reference_height: 参考高度（固定720P）
    Returns:
        生成的预览图路径
    """
    if style is None:
        style = RoundedBgStyle()

    # 加载或创建背景
    if bg_image_path and Path(bg_image_path).exists():
        background = Image.open(bg_image_path).convert("RGB")
        # 如果未提供尺寸，从图片获取
        if width is None or height is None:
            width, height = background.size
    else:
        # 没有背景图片，使用默认尺寸或提供的尺寸
        if width is None:
            width = 1920
        if height is None:
            height = 1080
        background = Image.new("RGB", (width, height), (20, 20, 20))

    # 确保 width 和 height 不为 None（类型收窄）
    assert width is not None and height is not None

    # 从样式中获取参考高度，根据图片高度自动缩放样式
    scale_factor = height / reference_height

    if scale_factor != 1.0:
        style = replace(
            style,
            font_size=int(style.font_size * scale_factor),
            corner_radius=int(style.corner_radius * scale_factor),
            padding_h=int(style.padding_h * scale_factor),
            padding_v=int(style.padding_v * scale_factor),
            margin_bottom=int(style.margin_bottom * scale_factor),
            line_spacing=int(style.line_spacing * scale_factor),
            letter_spacing=int(style.letter_spacing * scale_factor),
        )

    # 渲染字幕并叠加
    subtitle_img = render_subtitle_image(primary_text, secondary_text, width, height, style)
    background.paste(subtitle_img, (0, 0), subtitle_img)

    # 保存到临时目录
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
        background.save(tmp_file, "PNG")
        return tmp_file.name


def render_rounded_video(
    video_path: str,
    asr_data: "ASRData",
    output_path: str,
    rounded_style: Optional[dict] = None,
    layout: SubtitleLayoutEnum = SubtitleLayoutEnum.ONLY_ORIGINAL,
    crf: int = 23,
    preset: str = "medium",
    progress_callback: Optional[Callable] = None,
    reference_height: int = 720,
) -> None:
    """
    渲染圆角背景字幕到视频（分批overlay方案）

    核心流程：直接分批overlay字幕PNG到原视频
    每批50个字幕，避免FFmpeg文件数量限制

    Args:
        video_path: 输入视频路径
        asr_data: 字幕数据
        output_path: 输出视频路径
        rounded_style: 圆角背景样式配置字典
        layout: 字幕布局
        crf: 视频质量参数
        preset: FFmpeg编码预设
        progress_callback: 进度回调 (progress: int, message: str)
        reference_height: 参考高度（固定720P）
    """
    # 检查字幕数据
    if not asr_data or not asr_data.segments:
        raise ValueError("字幕数据为空，无法渲染视频")

    # 检查布局合理性
    if layout == SubtitleLayoutEnum.ONLY_TRANSLATE:
        has_translation = any(
            seg.translated_text and seg.translated_text.strip() for seg in asr_data.segments
        )
        if not has_translation:
            layout = SubtitleLayoutEnum.ONLY_ORIGINAL
    elif (
        layout == SubtitleLayoutEnum.TRANSLATE_ON_TOP
        or layout == SubtitleLayoutEnum.ORIGINAL_ON_TOP
    ):
        has_translation = any(
            seg.translated_text and seg.translated_text.strip() for seg in asr_data.segments
        )
        if not has_translation:
            layout = SubtitleLayoutEnum.ONLY_ORIGINAL

    # 获取视频信息
    width, height, video_duration = _get_video_info(video_path)

    # 构建并缩放样式
    style_config = rounded_style or {}
    style_config["layout"] = layout
    style = RoundedBgStyle(**style_config)

    scale_factor = height / reference_height
    if scale_factor != 1.0:
        style = replace(
            style,
            font_size=int(style.font_size * scale_factor),
            corner_radius=int(style.corner_radius * scale_factor),
            padding_h=int(style.padding_h * scale_factor),
            padding_v=int(style.padding_v * scale_factor),
            margin_bottom=int(style.margin_bottom * scale_factor),
            line_spacing=int(style.line_spacing * scale_factor),
            letter_spacing=int(style.letter_spacing * scale_factor),
        )

    with tempfile.TemporaryDirectory(prefix="rounded_subtitle_") as temp_dir:
        temp_path = Path(temp_dir)

        # 步骤1: 生成所有字幕PNG (0-30%)
        logger.info(f"生成字幕PNG图片（共{len(asr_data.segments)}个，布局：{layout.value}）")
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
            raise ValueError("没有生成任何有效的字幕图片")

        # 步骤2: 分批overlay到视频 (30-100%)
        logger.info("分批叠加字幕到视频")
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

            logger.info(f"处理批次 {batch_idx + 1}/{total_batches}（{len(batch_frames)}个字幕）")
            # 构建 ffmpeg 命令
            # -t 参数强制保持原视频时长，防止因 overlay 结束而截断视频
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
                logger.info(f"执行命令: {cmd_str}")

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
                raise RuntimeError(f"字幕处理失败（批次 {batch_idx + 1}）")

            # 更新进度 (30-100%)
            if progress_callback:
                progress = 30 + int((batch_idx + 1) / total_batches * 70)
                progress_callback(progress, f"合成视频 {batch_idx + 1}/{total_batches}")

            # 更新当前视频
            current_video = str(batch_output)

        logger.info("视频合成完成")
