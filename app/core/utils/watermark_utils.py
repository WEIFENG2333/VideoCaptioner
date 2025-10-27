"""水印工具模块 - 处理视频水印相关功能"""
from pathlib import Path
from typing import Optional, Tuple

from ..entities import WatermarkConfig
from .logger import setup_logger

logger = setup_logger("watermark_utils")


def get_watermark_filter(
    watermark_config: WatermarkConfig,
    video_width: int = 1920,
    video_height: int = 1080,
) -> Optional[Tuple[str, bool]]:
    """
    根据水印配置生成FFmpeg过滤器字符串
    
    Args:
        watermark_config: 水印配置对象
        video_width: 视频宽度
        video_height: 视频高度
        
    Returns:
        元组 (FFmpeg过滤器字符串, 是否需要使用filter_complex)
        如果不需要水印则返回None
    """
    if not watermark_config or not watermark_config.enabled:
        return None

    # 如果同时有文字和图片，优先使用图片
    has_image = watermark_config.image_path and Path(watermark_config.image_path).is_file()
    has_text = watermark_config.text and watermark_config.text.strip()

    if not has_image and not has_text:
        logger.warning("水印已启用但未配置文字或图片")
        return None

    # 获取位置坐标
    position = _get_position_coordinates(
        watermark_config.position, video_width, video_height, watermark_config.size
    )

    # 处理透明度
    opacity = max(0.0, min(1.0, watermark_config.opacity))

    if has_image:
        return _create_image_watermark_filter(
            watermark_config.image_path, position, opacity, watermark_config.size
        )
    else:
        return _create_text_watermark_filter(
            watermark_config.text, position, opacity, watermark_config.size, watermark_config.font
        )


def _get_position_coordinates(position: str, video_width: int, video_height: int, size: int) -> dict:
    """
    根据位置名称返回坐标
    
    Args:
        position: 位置名称
        video_width: 视频宽度 (保留用于未来扩展，当前使用FFmpeg动态变量)
        video_height: 视频高度 (保留用于未来扩展，当前使用FFmpeg动态变量)
        size: 水印大小 (保留用于未来扩展)
    
    Returns:
        包含 x, y 坐标的字典
        
    Note:
        使用FFmpeg的动态变量 w, h (视频尺寸) 和 overlay_w, overlay_h (水印尺寸)
        这样可以适应任何视频尺寸，无需预先计算
    """
    # 预留边距
    margin = 10
    
    positions = {
        "右下角": {
            "x": f"w-overlay_w-{margin}",
            "y": f"h-overlay_h-{margin}",
        },
        "左下角": {
            "x": str(margin),
            "y": f"h-overlay_h-{margin}",
        },
        "右上角": {
            "x": f"w-overlay_w-{margin}",
            "y": str(margin),
        },
        "左上角": {
            "x": str(margin),
            "y": str(margin),
        },
        "居中": {
            "x": "(w-overlay_w)/2",
            "y": "(h-overlay_h)/2",
        },
    }
    
    return positions.get(position, positions["右下角"])


def _create_image_watermark_filter(
    image_path: str, position: dict, opacity: float, size: int
) -> Tuple[str, bool]:
    """
    创建图片水印过滤器
    
    Args:
        image_path: 图片路径
        position: 位置坐标字典
        opacity: 透明度 (0.0-1.0)
        size: 缩放百分比
        
    Returns:
        元组 (FFmpeg过滤器字符串, True表示需要使用filter_complex)
        
    Note:
        返回的过滤器字符串格式固定为:
        "movie='path',scale=...,format=...[wm];[0:v][wm]overlay=x:y"
        这个格式由video_utils.py解析，修改时需要同步更新解析逻辑
    """
    # 转换为POSIX路径并转义冒号
    image_path = Path(image_path).as_posix().replace(":", r"\:")
    
    # 构建过滤器 - 使用movie作为输入源，需要用复杂过滤器语法
    scale_factor = size / 100.0
    # 使用filter_complex语法，格式: "movie处理[标签];[输入][标签]overlay"
    filter_str = (
        f"movie='{image_path}',scale=iw*{scale_factor}:ih*{scale_factor},"
        f"format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay={position['x']}:{position['y']}"
    )
    
    logger.info(f"生成图片水印过滤器: {filter_str}")
    return (filter_str, True)


def _create_text_watermark_filter(
    text: str, position: dict, opacity: float, size: int, font: str = ""
) -> Tuple[str, bool]:
    """
    创建文字水印过滤器
    
    Args:
        text: 水印文字
        position: 位置坐标字典
        opacity: 透明度 (0.0-1.0)
        size: 字体大小
        font: 字体名称
        
    Returns:
        元组 (FFmpeg过滤器字符串, False表示可以使用-vf)
    """
    # 转义文字中的特殊字符
    # FFmpeg drawtext需要转义的字符: \ ' : % \n \r
    text = (
        text.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace("\n", r"\\n")
        .replace("\r", r"\\r")
    )
    
    # 计算透明度对应的颜色alpha值 (0-1 转换为 0-255)
    alpha = int(opacity * 255)
    
    # 构建drawtext过滤器参数
    params = [
        f"text='{text}'",
        f"fontsize={size}",
        f"fontcolor=white@0x{alpha:02X}",  # 白色文字，带透明度
        f"x={position['x']}",
        f"y={position['y']}",
        "box=1",  # 添加背景框
        f"boxcolor=black@0x{int(opacity * 0.5 * 255):02X}",  # 黑色半透明背景
        "boxborderw=5",
    ]
    
    # 如果指定了字体，添加字体参数
    if font and font.strip():
        # 检测是否为字体文件路径（包含路径分隔符或常见字体扩展名）
        font_extensions = ('.ttf', '.otf', '.ttc', '.woff', '.woff2')
        is_font_file = (
            font.lower().endswith(font_extensions) or 
            "/" in font or 
            "\\" in font
        )
        
        if is_font_file:
            # 字体文件路径，需要转义
            # FFmpeg在Windows上也接受正斜杠路径，统一使用正斜杠简化处理
            font_escaped = font.replace("\\", "/").replace(":", r"\:")
            params.append(f"fontfile='{font_escaped}'")
        else:
            # 字体名称（如 "Arial", "SimSun"）
            params.append(f"font='{font}'")
    
    filter_str = "drawtext=" + ":".join(params)
    
    logger.info(f"生成文字水印过滤器: {filter_str}")
    return (filter_str, False)
