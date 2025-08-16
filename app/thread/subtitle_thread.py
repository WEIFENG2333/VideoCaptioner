import datetime
import os
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from app.config import CACHE_PATH
from app.core.bk_asr.asr_data import ASRData
from app.core.entities import SubtitleConfig, SubtitleTask, TranslatorServiceEnum
from app.core.storage.cache_manager import ServiceUsageManager
from app.core.storage.database import DatabaseManager
from app.core.subtitle_processor.optimize import SubtitleOptimizer
from app.core.subtitle_processor.split import SubtitleSplitter
from app.core.subtitle_processor.translate import TranslatorFactory, TranslatorType
from app.core.utils.logger import setup_logger
from app.core.utils.test_opanai import test_openai

# 配置日志
logger = setup_logger("subtitle_optimization_thread")


class SubtitleThread(QThread):
    finished = pyqtSignal(str, str)
    progress = pyqtSignal(int, str)
    update = pyqtSignal(dict)
    update_all = pyqtSignal(dict)
    error = pyqtSignal(str)
    MAX_DAILY_LLM_CALLS = 30

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task: SubtitleTask = task
        self.subtitle_length = 0
        self.finished_subtitle_length = 0
        self.custom_prompt_text = ""
        self.optimizer = None  # Initialize optimizer attribute
        # 初始化数据库和服务使用管理器
        self.db_manager = DatabaseManager(str(CACHE_PATH))
        self.service_manager = ServiceUsageManager(self.db_manager)

    def set_custom_prompt_text(self, text: str):
        self.custom_prompt_text = text

    def _setup_api_config(self) -> Optional[SubtitleConfig]:
        """设置API配置，返回SubtitleConfig"""
        public_base_url = "https://ddg.bkfeng.top/v1"
        if self.task.subtitle_config.base_url == public_base_url:
            # 检查是否可以使用服务

            if not self.service_manager.check_service_available(
                "llm", self.MAX_DAILY_LLM_CALLS
            ):
                raise Exception(
                    self.tr(
                        f"公益LLM服务已达到每日使用限制 {self.MAX_DAILY_LLM_CALLS} 次，建议使用自己的API"
                    )
                )
            self.task.subtitle_config.thread_num = 5
            self.task.subtitle_config.batch_size = 10
            return self.task.subtitle_config

        if self.task.subtitle_config.base_url and self.task.subtitle_config.api_key:
            # Check if model is None and provide a default
            model = self.task.subtitle_config.llm_model or "gpt-3.5-turbo"
            if not test_openai(
                self.task.subtitle_config.base_url,
                self.task.subtitle_config.api_key,
                model,
            )[0]:
                raise Exception(
                    self.tr(
                        "（字幕断句或字幕修正需要大模型）\nOpenAI API 测试失败, 请检查LLM配置"
                    )
                )
            # 增加服务使用次数
            if self.task.subtitle_config.base_url == public_base_url:
                self.service_manager.increment_usage("llm", self.MAX_DAILY_LLM_CALLS)
            return self.task.subtitle_config
        else:
            raise Exception(
                self.tr(
                    "（字幕断句或字幕修正需要大模型）\nOpenAI API 未配置, 请检查LLM配置"
                )
            )

        return None

    def run(self):
        try:
            logger.info("\n===========字幕处理任务开始===========")
            logger.info(f"时间：{datetime.datetime.now()}")

            # 字幕文件路径检查、对断句字幕路径进行定义
            subtitle_path = self.task.subtitle_path
            output_name = (
                Path(subtitle_path)
                .stem.replace("【原始字幕】", "")
                .replace("【下载字幕】", "")
            )
            split_path = str(
                Path(subtitle_path).parent / f"【断句字幕】{output_name}.srt"
            )
            assert subtitle_path is not None, self.tr("字幕文件路径为空")

            subtitle_config = self.task.subtitle_config

            asr_data = ASRData.from_subtitle_file(subtitle_path)

            # 1. 分割成字词级时间戳（对于非断句字幕且开启分割选项）
            if subtitle_config.need_split and not asr_data.is_word_timestamp():
                asr_data.split_to_word_segments()

            # 获取API配置，会先检查可用性（优先使用设置的API，其次使用自带的公益API）
            if (
                subtitle_config.need_optimize
                or asr_data.is_word_timestamp()
                or (
                    subtitle_config.need_translate
                    and subtitle_config.translator_service
                    not in [
                        TranslatorServiceEnum.DEEPLX,
                        TranslatorServiceEnum.BING,
                        TranslatorServiceEnum.GOOGLE,
                    ]
                )
            ):
                self.progress.emit(2, self.tr("开始验证API配置..."))
                subtitle_config = self._setup_api_config()
                if subtitle_config.base_url:
                    os.environ["OPENAI_BASE_URL"] = subtitle_config.base_url
                if subtitle_config.api_key:
                    os.environ["OPENAI_API_KEY"] = subtitle_config.api_key

            # 2. 重新断句（对于字词级字幕）
            if asr_data.is_word_timestamp():
                self.progress.emit(5, self.tr("字幕断句..."))
                logger.info("正在字幕断句...")
                if not subtitle_config.llm_model:
                    raise Exception(self.tr("字幕断句需要配置LLM模型"))
                splitter = SubtitleSplitter(
                    thread_num=subtitle_config.thread_num,
                    model=subtitle_config.llm_model,
                    temperature=0.3,
                    timeout=60,
                    retry_times=1,
                    split_type=(
                        str(subtitle_config.split_type)
                        if subtitle_config.split_type
                        else "SEMANTIC"
                    ),
                    max_word_count_cjk=subtitle_config.max_word_count_cjk,
                    max_word_count_english=subtitle_config.max_word_count_english,
                )
                asr_data = splitter.split_subtitle(asr_data)
                asr_data.save(save_path=split_path)
                self.update_all.emit(asr_data.to_json())

            # 3. 优化字幕
            custom_prompt = subtitle_config.custom_prompt_text
            self.subtitle_length = len(asr_data.segments)

            if subtitle_config.need_optimize:
                self.progress.emit(0, self.tr("优化字幕..."))
                logger.info("正在优化字幕...")
                self.finished_subtitle_length = 0  # 重置计数器
                if not subtitle_config.llm_model:
                    raise Exception(self.tr("字幕优化需要配置LLM模型"))
                self.optimizer = SubtitleOptimizer(
                    custom_prompt=custom_prompt or "",
                    model=subtitle_config.llm_model,
                    batch_num=subtitle_config.batch_size,
                    thread_num=subtitle_config.thread_num,
                    update_callback=self.callback,
                )
                asr_data = self.optimizer.optimize_subtitle(asr_data)
                self.update_all.emit(asr_data.to_json())

            # 4. 翻译字幕
            translator_map = {
                TranslatorServiceEnum.OPENAI: TranslatorType.OPENAI,
                TranslatorServiceEnum.DEEPLX: TranslatorType.DEEPLX,
                TranslatorServiceEnum.BING: TranslatorType.BING,
                TranslatorServiceEnum.GOOGLE: TranslatorType.GOOGLE,
            }
            if subtitle_config.need_translate:
                self.progress.emit(0, self.tr("翻译字幕..."))
                logger.info("正在翻译字幕...")
                self.finished_subtitle_length = 0  # 重置计数器
                if subtitle_config.deeplx_endpoint:
                    os.environ["DEEPLX_ENDPOINT"] = subtitle_config.deeplx_endpoint
                if subtitle_config.translator_service:
                    # 只有使用 OpenAI 翻译服务时才需要检查 llm_model
                    if (
                        subtitle_config.translator_service
                        == TranslatorServiceEnum.OPENAI
                    ):
                        if not subtitle_config.llm_model:
                            raise Exception(self.tr("使用OpenAI翻译需要配置LLM模型"))
                    translator = TranslatorFactory.create_translator(
                        translator_type=translator_map[
                            subtitle_config.translator_service
                        ],
                        thread_num=subtitle_config.thread_num,
                        batch_num=subtitle_config.batch_size,
                        target_language=(
                            str(subtitle_config.target_language)
                            if subtitle_config.target_language
                            else "zh-CN"
                        ),
                        model=subtitle_config.llm_model
                        or "",  # 非 OpenAI 服务不需要 model
                        custom_prompt=custom_prompt or "",
                        is_reflect=subtitle_config.need_reflect,
                        update_callback=self.callback,
                    )
                else:
                    raise Exception(self.tr("翻译服务未配置"))
                asr_data = translator.translate_subtitle(asr_data)
                # 移除末尾标点符号
                if subtitle_config.need_remove_punctuation:
                    asr_data.remove_punctuation()
                self.update_all.emit(asr_data.to_json())
                # 保存翻译结果(单语、双语)
                if self.task.need_next_task and self.task.video_path:
                    for subtitle_layout in ["原文在上", "译文在上", "仅原文", "仅译文"]:
                        save_path = str(
                            Path(self.task.subtitle_path).parent
                            / f"{Path(self.task.video_path).stem}-{subtitle_layout}.srt"
                        )
                        asr_data.save(
                            save_path=save_path,
                            ass_style=subtitle_config.subtitle_style or "",
                            layout=subtitle_layout,
                        )
                        logger.info(f"字幕保存到 {save_path}")

            # 5. 保存字幕
            asr_data.save(
                save_path=self.task.output_path or "",
                ass_style=subtitle_config.subtitle_style or "",
                layout=subtitle_config.subtitle_layout or "仅译文",
            )
            logger.info(f"字幕保存到 {self.task.output_path}")

            # 6. 文件移动与清理
            if self.task.need_next_task and self.task.video_path:
                # 保存srt/ass文件到视频目录（对于全流程任务）
                save_srt_path = (
                    Path(self.task.video_path).parent
                    / f"{Path(self.task.video_path).stem}.srt"
                )
                asr_data.to_srt(
                    save_path=str(save_srt_path),
                    layout=subtitle_config.subtitle_layout or "仅译文",
                )
                # save_ass_path = (
                #     Path(self.task.video_path).parent
                #     / f"{Path(self.task.video_path).stem}.ass"
                # )
                # asr_data.to_ass(
                #     save_path=str(save_ass_path),
                #     layout=subtitle_config.subtitle_layout,
                #     style_str=subtitle_config.subtitle_style,
                # )
            else:
                # 删除断句文件（对于仅字幕任务）
                split_path = str(
                    Path(self.task.subtitle_path).parent
                    / f"【智能断句】{Path(self.task.subtitle_path).stem}.srt"
                )
                if os.path.exists(split_path):
                    os.remove(split_path)

            self.progress.emit(100, self.tr("优化完成"))
            logger.info("优化完成")
            self.finished.emit(self.task.video_path, self.task.output_path)
        except Exception as e:
            logger.exception(f"优化失败: {str(e)}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("优化失败"))

    def callback(self, result: Dict):
        self.finished_subtitle_length += len(result)
        # 简单计算当前进度（0-100%）
        progress = min(
            int((self.finished_subtitle_length / self.subtitle_length) * 100), 100
        )
        self.progress.emit(progress, self.tr("{0}% 处理字幕").format(progress))
        self.update.emit(result)

    def stop(self):
        """停止所有处理"""
        try:
            # 先停止优化器
            if hasattr(self, "optimizer") and self.optimizer:
                try:
                    self.optimizer.stop()  # type: ignore
                except Exception as e:
                    logger.error(f"停止优化器时出错：{str(e)}")

            # 终止线程
            self.terminate()
            # 等待最多3秒
            if not self.wait(3000):
                logger.warning("线程未能在3秒内正常停止")

            # 发送进度信号
            self.progress.emit(100, self.tr("已终止"))

        except Exception as e:
            logger.error(f"停止线程时出错：{str(e)}")
            self.progress.emit(100, self.tr("终止时发生错误"))
