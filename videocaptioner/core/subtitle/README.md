# 字幕渲染模块

提供两种字幕渲染方式：
- **ASS 样式**：FFmpeg + libass 渲染（支持 CUDA 加速）
- **圆角背景**：PIL 绘制现代风格字幕（带圆角矩形背景）

## 模块结构

```
app/core/subtitle/
├── __init__.py           # 统一导出接口
├── ass_renderer.py       # ASS 渲染器（视频合成、预览）
├── ass_utils.py          # ASS 解析和处理（dataclass 化）
├── rounded_renderer.py   # 圆角背景渲染器
├── styles.py             # 样式配置（RoundedBgStyle）
├── font_utils.py         # 字体管理（内置/系统字体，LRU 缓存）
└── text_utils.py         # 文本处理（平衡换行算法）
```

## 快速使用

### 1. ASS 解析

```python
from app.core.subtitle import parse_ass_info, auto_wrap_ass_file

# 解析 ASS 文件（返回类型安全的 dataclass）
ass_info = parse_ass_info(ass_content)
print(f"分辨率: {ass_info.video_width}x{ass_info.video_height}")
for style in ass_info.styles.values():
    print(f"{style.name}: {style.font_name} {style.font_size}px")

# 智能换行（基于实际字体渲染宽度）
auto_wrap_ass_file("input.ass", video_width=1920)
```

### 2. 圆角背景渲染

```python
from app.core.subtitle import render_rounded_video, RoundedBgStyle

style = RoundedBgStyle(
    font_name="Noto Sans SC",
    font_size=52,
    bg_color="#191919C8",      # 半透明深灰
    text_color="#FFFFFF",
    corner_radius=12,
    letter_spacing=2,          # 字符间距
)

render_rounded_video(
    video_path="input.mp4",
    asr_data=asr_data,
    output_path="output.mp4",
    style=style,
)
```

### 3. 字体和文本工具

```python
from app.core.subtitle import get_font, get_ass_to_pil_ratio, wrap_text

# 获取字体（内置字体优先，系统字体后备）
font = get_font(52, "Noto Sans SC")

# ASS 到 PIL 字体大小转换
ratio = get_ass_to_pil_ratio("Noto Sans SC")  # ≈ 1.448
pil_size = int(74 / ratio)  # ASS 74px → PIL 51px

# 平衡文本换行（每行长度更均衡）
lines = wrap_text(text, font, max_width=1216)
```

## 核心特性

### 精确换行
- **实际渲染宽度**：使用 PIL 真实字体渲染，而非估算字符宽度
- **平衡算法**：先计算最小行数，再平均分配字符，避免最后一行过短
- **语言自适应**：CJK 按字符拆分，英文按单词拆分

### 字体管理
- **内置字体优先**：`resource/fonts/` 目录的字体优先加载
- **系统字体后备**：自动检测 macOS/Windows/Linux 系统字体
- **跨平台解析**：使用 `fontTools` 提取字体家族名
- **LRU 缓存**：`@lru_cache` 装饰器优化性能

### ASS 字体大小转换
- **问题**：ASS 使用 Windows 行高（usWinAscent + usWinDescent），PIL 使用 em 方块（unitsPerEm）
- **解决**：`get_ass_to_pil_ratio()` 自动读取字体度量，计算转换比例（通常 1.4-1.5）
- **效果**：ASS 74px ≈ PIL 51px（Noto Sans SC），换行准确率显著提升

## 技术难点与解决方案

### 1. ASS 文本提前换行问题
**现象**：直接用 ASS 字号加载 PIL 字体测量宽度，导致换行过早  
**原因**：ASS 和 PIL 对 font size 的解释不同（单位不同）  
**方案**：
- 从字体文件读取 `unitsPerEm` 和 Windows 行高
- 计算转换比例：`ratio = (usWinAscent + usWinDescent) / unitsPerEm`
- 使用转换后的字号：`pil_size = ass_size / ratio`

### 2. 字幕行长度不均衡
**现象**：贪心换行导致"第1行很长，第2行很短"  
**原因**：每行尽可能多地放字符，未考虑整体平衡  
**方案**：
- 先用贪心算法计算最小行数
- 计算目标宽度：`target = total_width / num_lines`
- 当前行达到 90% 目标宽度且下一个字符会超 110% 时提前换行
- 平衡度从 50% 提升到 96%

### 3. 类型安全与代码简洁
**问题**：字典 + 元组 + 手动缓存导致代码复杂  
**方案**：
- 使用 `@dataclass` 替代字典和元组（`AssInfo`, `AssStyle`）
- 使用 `@lru_cache` 替代手动缓存管理
- 返回值类型明确（`AssInfo` 而非 `tuple[int, Dict[...]]`）

## 注意事项

1. **字体文件路径**：内置字体放在 `resource/fonts/`，优先级高于系统字体
2. **ASS 样式换行**：使用 `\q2` 禁用 libass 自动换行，完全由我们控制换行位置
3. **文本宽度计算**：默认使用 95% 视频宽度（`video_width * 0.95`）作为最大文本宽度
4. **字体度量缓存**：`get_ass_to_pil_ratio()` 结果已缓存，重复调用无性能损失
5. **圆角背景字间距**：`letter_spacing > 0` 时逐字符绘制，`= 0` 时整体绘制（性能更好）
