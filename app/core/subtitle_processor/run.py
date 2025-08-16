from typing import Callable, Dict, Optional

from app.core.bk_asr.asr_data import ASRData, from_subtitle_file
from app.core.entities import SubtitleConfig
from app.core.subtitle_processor.optimization import SubtitleOptimizer
from app.core.subtitle_processor.splitting import merge_segments
from app.core.utils.logger import setup_logger

logger = setup_logger("subtitle_processor")


def run(
    subtitle_path: str,
    config: SubtitleConfig,
    callback: Optional[Callable[[Dict], None]] = None,
) -> ASRData:
    """
    运行字幕处理流程

    Args:
        subtitle_path: 字幕文件路径
        config: 字幕处理配置
        callback: 回调函数，用于更新进度

    Returns:
        ASRData: 处理后的字幕数据
    """
    logger.info(f"\n===========字幕处理任务开始===========")

    # 1. 加载字幕文件
    asr_data = from_subtitle_file(subtitle_path)

    # 2. 如果需要分割字幕
    # 检查是否需要合并重新断句
    if config.need_split:
        asr_data.split_to_word_segments()

    if asr_data.is_word_timestamp():
        logger.info("正在进行字幕断句...")
        asr_data = merge_segments(
            asr_data,
            model=config.llm_model,
            num_threads=config.thread_num,
            max_word_count_cjk=config.max_word_count_cjk,
            max_word_count_english=config.max_word_count_english,
        )

    # 3. 如果需要优化或翻译
    if config.need_optimize or config.need_translate:
        logger.info("正在进行字幕优化/翻译...")
        # 设置环境变量
        import os

        os.environ["OPENAI_BASE_URL"] = config.base_url
        os.environ["OPENAI_API_KEY"] = config.api_key

        # 创建优化器
        optimizer = SubtitleOptimizer(
            model=config.llm_model,
            target_language=config.target_language,
            batch_num=config.batch_size,
            thread_num=config.thread_num,
        )

        # 制作成请求llm接口的格式
        subtitle_json = {
            str(k): v["original_subtitle"] for k, v in asr_data.to_json().items()
        }

        # 进行优化/翻译
        optimizer_result = optimizer.optimizer_multi_thread(
            subtitle_json, translate=config.need_translate, callback=callback
        )

        # 更新字幕内容
        for i, subtitle_text in optimizer_result.items():
            seg = asr_data.segments[int(i) - 1]
            seg.text = subtitle_text

    return asr_data
