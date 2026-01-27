import os
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from app.core.asr.asr_data import ASRData
from app.core.entities import (
    SubtitleConfig,
    SubtitleLayoutEnum,
    SubtitleProcessData,
    SubtitleTask,
    TranslatorServiceEnum,
)
from app.core.llm.check_llm import check_llm_connection
from app.core.llm.context import clear_task_context, set_task_context, update_stage
from app.core.optimize.optimize import SubtitleOptimizer
from app.core.split.split import SubtitleSplitter
from app.core.translate import (
    BingTranslator,
    DeepLXTranslator,
    GoogleTranslator,
    LLMTranslator,
)
from app.core.utils.logger import setup_logger

# 配置日志
logger = setup_logger("subtitle_optimization_thread")


class SubtitleThread(QThread):
    finished = pyqtSignal(str, str)
    progress = pyqtSignal(int, str)
    update = pyqtSignal(dict)
    update_all = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task: SubtitleTask = task
        self.subtitle_length = 0
        self.finished_subtitle_length = 0
        self.custom_prompt_text = ""
        self.optimizer = None

    def set_custom_prompt_text(self, text: str):
        self.custom_prompt_text = text

    def _setup_llm_config(self) -> Optional[SubtitleConfig]:
        """设置API配置，返回SubtitleConfig"""
        if (
            self.task.subtitle_config.base_url
            and self.task.subtitle_config.api_key
            and self.task.subtitle_config.llm_model
        ):
            success, message = check_llm_connection(
                self.task.subtitle_config.base_url,
                self.task.subtitle_config.api_key,
                self.task.subtitle_config.llm_model,
            )
            if not success:
                raise Exception(f"{self.tr('LLM API 测试失败: ')}{message or ''}")
            # 设置环境变量
            if self.task.subtitle_config.base_url:
                os.environ["OPENAI_BASE_URL"] = self.task.subtitle_config.base_url
            if self.task.subtitle_config.api_key:
                os.environ["OPENAI_API_KEY"] = self.task.subtitle_config.api_key
            return self.task.subtitle_config
        else:
            raise Exception(self.tr("LLM API 未配置, 请检查LLM配置"))

    def run(self):
        # 设置任务上下文
        task_file = (
            Path(self.task.video_path) if self.task.video_path else Path(self.task.subtitle_path)
        )
        set_task_context(
            task_id=self.task.task_id,
            file_name=task_file.name,
            stage="subtitle",
        )

        try:
            logger.info(f"\n{self.task.subtitle_config.print_config()}")

            # 字幕文件路径检查、对断句字幕路径进行定义
            subtitle_path = self.task.subtitle_path
            assert subtitle_path is not None, self.tr("字幕文件路径为空")

            subtitle_config = self.task.subtitle_config
            assert subtitle_config is not None, self.tr("字幕配置为空")

            asr_data = ASRData.from_subtitle_file(subtitle_path)

            # 1. 分割成字词级时间戳（对于非断句字幕且开启分割选项）
            if subtitle_config.need_split and not asr_data.is_word_timestamp():
                asr_data.split_to_word_segments()
                self.update_all.emit(asr_data.to_json())

            # 验证 LLM 配置
            if self.need_llm(subtitle_config, asr_data):
                self.progress.emit(2, self.tr("开始验证 LLM 配置..."))
                subtitle_config = self._setup_llm_config()

            # 2. 重新断句（对于字词级字幕）
            if asr_data.is_word_timestamp():
                update_stage("split")
                self.progress.emit(5, self.tr("字幕断句..."))
                logger.info("正在字幕断句...")
                splitter = SubtitleSplitter(
                    thread_num=subtitle_config.thread_num,
                    model=subtitle_config.llm_model,
                    max_word_count_cjk=subtitle_config.max_word_count_cjk,
                    max_word_count_english=subtitle_config.max_word_count_english,
                )
                asr_data = splitter.split_subtitle(asr_data)
                self.update_all.emit(asr_data.to_json())

            # 3. 优化字幕
            context_info = f'The subtitles below are from a file named "{task_file}". Use this context to improve accuracy if needed.\n'
            custom_prompt = context_info + (subtitle_config.custom_prompt_text or "") + "\n"
            self.subtitle_length = len(asr_data.segments)

            if subtitle_config.need_optimize:
                update_stage("optimize")
                self.progress.emit(0, self.tr("优化字幕..."))
                logger.info("正在优化字幕...")
                self.finished_subtitle_length = 0
                if not subtitle_config.llm_model:
                    raise Exception(self.tr("LLM 模型未配置"))
                optimizer = SubtitleOptimizer(
                    thread_num=subtitle_config.thread_num,
                    batch_num=subtitle_config.batch_size,
                    model=subtitle_config.llm_model,
                    custom_prompt=custom_prompt or "",
                    update_callback=self.callback,
                )
                asr_data = optimizer.optimize_subtitle(asr_data)
                asr_data.remove_punctuation()
                self.update_all.emit(asr_data.to_json())

            # 4. 翻译字幕
            if subtitle_config.need_translate:
                update_stage("translate")
                self.progress.emit(0, self.tr("翻译字幕..."))
                logger.info("正在翻译字幕...")
                self.finished_subtitle_length = 0
                translator_service = subtitle_config.translator_service

                if not subtitle_config.target_language:
                    raise Exception(self.tr("目标语言未配置"))

                if translator_service == TranslatorServiceEnum.OPENAI:
                    if not subtitle_config.llm_model:
                        raise Exception(self.tr("LLM 模型未配置"))
                    translator = LLMTranslator(
                        thread_num=subtitle_config.thread_num,
                        batch_num=subtitle_config.batch_size,
                        target_language=subtitle_config.target_language,
                        model=subtitle_config.llm_model,
                        custom_prompt=custom_prompt or "",
                        is_reflect=subtitle_config.need_reflect,
                        update_callback=self.callback,
                    )
                elif translator_service == TranslatorServiceEnum.GOOGLE:
                    translator = GoogleTranslator(
                        thread_num=subtitle_config.thread_num,
                        batch_num=5,
                        target_language=subtitle_config.target_language,
                        timeout=20,
                        update_callback=self.callback,
                    )
                elif translator_service == TranslatorServiceEnum.BING:
                    translator = BingTranslator(
                        thread_num=subtitle_config.thread_num,
                        batch_num=10,
                        target_language=subtitle_config.target_language,
                        update_callback=self.callback,
                    )
                elif translator_service == TranslatorServiceEnum.DEEPLX:
                    os.environ["DEEPLX_ENDPOINT"] = subtitle_config.deeplx_endpoint or ""
                    translator = DeepLXTranslator(
                        thread_num=subtitle_config.thread_num,
                        batch_num=5,
                        target_language=subtitle_config.target_language,
                        timeout=20,
                        update_callback=self.callback,
                    )
                else:
                    raise Exception(self.tr(f"不支持的翻译服务: {translator_service}"))

                asr_data = translator.translate_subtitle(asr_data)

                # 移除末尾标点符号
                asr_data.remove_punctuation()
                self.update_all.emit(asr_data.to_json())

                # 保存翻译结果(单语、双语)
                if self.task.need_next_task and self.task.video_path:
                    for layout in SubtitleLayoutEnum:
                        save_path = str(
                            Path(self.task.subtitle_path).parent
                            / f"{Path(self.task.video_path).stem}-{layout.value}.srt"
                        )
                        asr_data.save(
                            save_path=save_path,
                            ass_style=subtitle_config.subtitle_style or "",
                            layout=layout,
                        )
                        logger.info(f"翻译字幕保存到：{save_path}")

            # 5. 保存字幕
            asr_data.save(
                save_path=self.task.output_path or "",
                ass_style=subtitle_config.subtitle_style or "",
                layout=subtitle_config.subtitle_layout or SubtitleLayoutEnum.ONLY_TRANSLATE,
            )
            logger.info(f"字幕保存到 {self.task.output_path}")

            # 6. 文件移动与清理
            if self.task.need_next_task and self.task.video_path:
                # 保存srt/ass文件到视频目录（对于全流程任务）
                save_srt_path = (
                    Path(self.task.video_path).parent / f"{Path(self.task.video_path).stem}.srt"
                )
                asr_data.to_srt(
                    save_path=str(save_srt_path),
                    layout=subtitle_config.subtitle_layout,
                )
                save_ass_path = (
                    Path(self.task.video_path).parent / f"{Path(self.task.video_path).stem}.ass"
                )
                asr_data.to_ass(
                    save_path=str(save_ass_path),
                    layout=subtitle_config.subtitle_layout,
                    style_str=subtitle_config.subtitle_style,
                )

            self.progress.emit(100, self.tr("优化完成"))
            logger.info("优化完成")
            self.finished.emit(self.task.video_path, self.task.output_path)

        except Exception as e:
            logger.exception(f"字幕处理失败: {str(e)}")
            self.error.emit(str(e))
            self.progress.emit(100, self.tr("字幕处理失败"))
        finally:
            clear_task_context()

    def need_llm(self, subtitle_config: SubtitleConfig, asr_data: ASRData):
        return (
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
        )

    def callback(self, result: List[SubtitleProcessData]):
        self.finished_subtitle_length += len(result)
        # 简单计算当前进度（0-100%）
        progress = min(int((self.finished_subtitle_length / self.subtitle_length) * 100), 100)
        self.progress.emit(progress, self.tr("{0}% 处理字幕").format(progress))
        # 转换为字典格式供UI使用
        result_dict = {
            str(data.index): data.translated_text or data.optimized_text or data.original_text
            for data in result
        }
        self.update.emit(result_dict)

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
