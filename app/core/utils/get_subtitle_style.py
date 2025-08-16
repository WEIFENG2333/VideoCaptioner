from typing import Optional
from app.config import SUBTITLE_STYLE_PATH


def get_subtitle_style(style_name: str) -> Optional[str]:
    """获取字幕样式内容

    Args:
        style_name: 样式名称

    Returns:
        str: 样式内容字符串，如果样式文件不存在则返回None
    """
    style_path = SUBTITLE_STYLE_PATH / f"{style_name}.txt"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return None
