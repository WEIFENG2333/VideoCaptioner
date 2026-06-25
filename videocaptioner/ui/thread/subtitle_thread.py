# -*- coding: utf-8 -*-
"""字幕处理线程：断句 -> 校正 -> 翻译 -> 导出。

SubtitleThread 跑完整流水线，RetranslateThread 只翻译选中的行。
两者都基于 WorkerThread：协作取消（stop() 会停掉正在执行的
splitter / optimizer / translator），取消的运行静默退出。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import pyqtSignal

from videocaptioner.core.application import output_paths
from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.entities import (
    SubtitleConfig,
    SubtitleLayoutEnum,
    SubtitleProcessData,
    SubtitleTask,
    TranslatorServiceEnum,
)
from videocaptioner.core.llm.check_llm import check_llm_connection
from videocaptioner.core.llm.context import (
    clear_task_context,
    generate_task_id,
    set_task_context,
    update_stage,
)
from videocaptioner.core.optimize.optimize import SubtitleOptimizer
from videocaptioner.core.split.split import SubtitleSplitter
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.types import TranslatorType
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.worker import WorkerThread

logger = setup_logger("subtitle_thread")

_SERVICE_TO_TYPE = {
    TranslatorServiceEnum.OPENAI: TranslatorType.OPENAI,
    TranslatorServiceEnum.GOOGLE: TranslatorType.GOOGLE,
    TranslatorServiceEnum.BING: TranslatorType.BING,
    TranslatorServiceEnum.DEEPLX: TranslatorType.DEEPLX,
    TranslatorServiceEnum.IMMERSIVE: TranslatorType.IMMERSIVE,
}

# 不依赖 LLM 的翻译服务（沉浸式免费模型自带令牌，也无需用户配 LLM key）
_NON_LLM_TRANSLATORS = (
    TranslatorServiceEnum.DEEPLX,
    TranslatorServiceEnum.BING,
    TranslatorServiceEnum.GOOGLE,
    TranslatorServiceEnum.IMMERSIVE,
)


def create_translator_from_config(
    config: SubtitleConfig,
    custom_prompt: str = "",
    callback=None,
):
    """根据 SubtitleConfig 创建翻译器。"""
    service = config.translator_service
    if service not in _SERVICE_TO_TYPE:
        raise ValueError(tr("t_subtitle.error.unsupported_service", service=service))
    if service == TranslatorServiceEnum.DEEPLX:
        os.environ["DEEPLX_ENDPOINT"] = config.deeplx_endpoint or ""
    return TranslatorFactory.create_translator(
        translator_type=_SERVICE_TO_TYPE[service],
        thread_num=config.thread_num,
        batch_num=config.batch_size,
        target_language=config.target_language,
        model=config.llm_model or "",
        custom_prompt=custom_prompt,
        is_reflect=config.need_reflect,
        update_callback=callback,
    )


def _setup_llm_environment(config: SubtitleConfig) -> None:
    """验证 LLM 连通性并写入环境变量；失败抛异常。"""
    if not (config.base_url and config.api_key and config.llm_model):
        raise Exception(tr("t_subtitle.error.llm_not_configured"))
    success, message = check_llm_connection(
        config.base_url, config.api_key, config.llm_model
    )
    if not success:
        raise Exception(tr("t_subtitle.error.llm_test_failed", message=message or ""))
    os.environ["OPENAI_BASE_URL"] = config.base_url
    os.environ["OPENAI_API_KEY"] = config.api_key


class SubtitleThread(WorkerThread):
    """字幕处理流水线线程。

    信号：
        finished(video_path, output_path)  处理成功
        update(dict)                       增量结果（{行号: 文本}）
        update_all(dict)                   全量刷新（断句等结构性变化后）
    """

    finished = pyqtSignal(str, str)
    update = pyqtSignal(dict)
    update_all = pyqtSignal(dict)

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task = task
        self.custom_prompt_text = ""
        self._total_segments = 0
        self._done_segments = 0
        # 当前正在执行的 core 执行器（splitter/optimizer/translator），
        # 取消时调用它的 stop()。
        self._active_worker = None

    def set_custom_prompt_text(self, text: str):
        self.custom_prompt_text = text

    # ----- WorkerThread 接口 -----

    def _on_cancel(self):
        worker = self._active_worker
        if worker is not None and hasattr(worker, "stop"):
            worker.stop()

    def _work(self):
        task_file = Path(self.task.video_path or self.task.subtitle_path)
        set_task_context(
            task_id=self.task.task_id, file_name=task_file.name, stage="subtitle"
        )
        try:
            config = self.task.subtitle_config
            if self.task.subtitle_path is None:
                raise Exception(tr("t_subtitle.error.no_subtitle_path"))
            if config is None:
                raise Exception(tr("t_subtitle.error.no_config"))
            logger.info("\n%s", config.print_config())

            asr_data = ASRData.from_subtitle_file(self.task.subtitle_path)

            # 1. 需要断句时先拆成字词级时间戳
            if config.need_split and not asr_data.is_word_timestamp():
                asr_data.split_to_word_segments()
                self.update_all.emit(asr_data.to_json())
            self.checkpoint()

            # 2. 验证 LLM（断句/校正/LLM 翻译任一需要）
            if self._need_llm(config, asr_data):
                self.progress.emit(2, tr("t_subtitle.status.verifying_llm"))
                _setup_llm_environment(config)
            self.checkpoint()

            # 3. 字词级字幕重新断句
            if asr_data.is_word_timestamp():
                asr_data = self._split_stage(asr_data, config)
            self.checkpoint()

            context_prompt = (
                f'The subtitles below are from a file named "{task_file}". '
                "Use this context to improve accuracy if needed.\n"
                f"{config.custom_prompt_text or ''}\n"
            )
            self._total_segments = len(asr_data.segments)

            # 4. 校正
            if config.need_optimize:
                asr_data = self._optimize_stage(asr_data, config, context_prompt)
            self.checkpoint()

            # 5. 翻译
            if config.need_translate:
                asr_data = self._translate_stage(asr_data, config, context_prompt)
            self.checkpoint()

            # 6. 导出
            self._export_stage(asr_data, config)
            self.progress.emit(100, tr("t_subtitle.status.done"))
            logger.info("字幕处理完成")
            self.finished.emit(
                self.task.video_path or "", self.task.output_path or ""
            )
        finally:
            clear_task_context()

    # ----- 流水线阶段 -----

    def _split_stage(self, asr_data: ASRData, config: SubtitleConfig) -> ASRData:
        update_stage("split")
        self.progress.emit(5, tr("t_subtitle.status.splitting"))
        logger.info("正在字幕断句...")
        splitter = SubtitleSplitter(
            thread_num=config.thread_num,
            model=config.llm_model,
            max_word_count_cjk=config.max_word_count_cjk,
            max_word_count_english=config.max_word_count_english,
        )
        self._active_worker = splitter
        try:
            asr_data = splitter.split_subtitle(asr_data)
        finally:
            self._active_worker = None
        self.update_all.emit(asr_data.to_json())
        return asr_data

    def _optimize_stage(
        self, asr_data: ASRData, config: SubtitleConfig, prompt: str
    ) -> ASRData:
        update_stage("optimize")
        self.progress.emit(0, tr("t_subtitle.status.optimizing"))
        logger.info("正在优化字幕...")
        if not config.llm_model:
            raise Exception(tr("t_subtitle.error.llm_model_not_configured"))
        self._done_segments = 0
        optimizer = SubtitleOptimizer(
            thread_num=config.thread_num,
            batch_num=config.batch_size,
            model=config.llm_model,
            custom_prompt=prompt,
            update_callback=self._batch_callback,
        )
        self._active_worker = optimizer
        try:
            asr_data = optimizer.optimize_subtitle(asr_data)
        finally:
            self._active_worker = None
        asr_data.remove_punctuation()
        self.update_all.emit(asr_data.to_json())
        return asr_data

    def _translate_stage(
        self, asr_data: ASRData, config: SubtitleConfig, prompt: str
    ) -> ASRData:
        update_stage("translate")
        self.progress.emit(0, tr("t_subtitle.status.translating"))
        logger.info("正在翻译字幕...")
        if not config.target_language:
            raise Exception(tr("t_subtitle.error.no_target_language"))
        self._done_segments = 0
        translator = create_translator_from_config(config, prompt, self._batch_callback)
        self._active_worker = translator
        try:
            asr_data = translator.translate_subtitle(asr_data)
        finally:
            self._active_worker = None
        asr_data.remove_punctuation()
        self.update_all.emit(asr_data.to_json())

        # 全流程任务把其余布局副本留在任务目录（保留中间文件时可取用）
        if self.task.need_next_task and self.task.task_dir:
            for layout in SubtitleLayoutEnum:
                save_path = str(
                    Path(self.task.task_dir) / output_paths.layout_copy_name(layout)
                )
                asr_data.save(
                    save_path=save_path,
                    ass_style=config.subtitle_style or "",
                    layout=layout,
                )
                logger.info("布局副本保存到：%s", save_path)
        return asr_data

    def _export_stage(self, asr_data: ASRData, config: SubtitleConfig) -> None:
        asr_data.save(
            save_path=self.task.output_path or "",
            ass_style=config.subtitle_style or "",
            layout=config.subtitle_layout or SubtitleLayoutEnum.ONLY_TRANSLATE,
        )
        logger.info("字幕保存到 %s", self.task.output_path)

        # 全流程任务的主输出在任务目录（subtitle.ass，供合成消费）；
        # 字幕成品本身也交付到视频旁，遵循播放器 sidecar 约定。
        if self.task.need_next_task and self.task.video_path:
            tag = (
                output_paths.language_tag(config.target_language)
                if config.need_translate
                else output_paths.TAG_OPTIMIZED
            )
            sidecar = output_paths.unique_path(
                output_paths.product_path(self.task.video_path, tag, ext=".srt")
            )
            asr_data.to_srt(save_path=str(sidecar), layout=config.subtitle_layout)
            logger.info("字幕成品保存到 %s", sidecar)

    # ----- 工具 -----

    @staticmethod
    def _need_llm(config: SubtitleConfig, asr_data: ASRData) -> bool:
        return (
            config.need_optimize
            or asr_data.is_word_timestamp()
            or (
                config.need_translate
                and config.translator_service not in _NON_LLM_TRANSLATORS
            )
        )

    def _batch_callback(self, result: List[SubtitleProcessData]):
        """core 执行器的批量回调：上报进度 + 推送增量结果。"""
        self.checkpoint()
        self._done_segments += len(result)
        percent = min(
            int(self._done_segments / max(self._total_segments, 1) * 100), 100
        )
        self.progress.emit(percent, tr("t_subtitle.status.processing_percent", percent=percent))
        self.update.emit(
            {
                str(data.index): data.translated_text
                or data.optimized_text
                or data.original_text
                for data in result
            }
        )


class RetranslateThread(WorkerThread):
    """重新翻译选中行的轻量线程。finished(dict) -> {行号: 译文}。"""

    finished = pyqtSignal(dict)

    def __init__(
        self,
        selected_data: dict,
        subtitle_config: SubtitleConfig,
        file_name: str = "",
    ):
        super().__init__()
        self.selected_data = selected_data
        self.config = subtitle_config
        self.file_name = file_name
        self._done = 0
        self._translator: Optional[object] = None

    def _on_cancel(self):
        translator = self._translator
        if translator is not None and hasattr(translator, "stop"):
            translator.stop()

    def _callback(self, result: List[SubtitleProcessData]):
        self.checkpoint()
        self._done += len(result)
        percent = min(int(self._done / max(len(self.selected_data), 1) * 100), 100)
        self.progress.emit(percent, tr("t_subtitle.status.translating_percent", percent=percent))

    def _work(self):
        set_task_context(
            task_id=generate_task_id(), file_name=self.file_name, stage="translate"
        )
        try:
            if not self.config.target_language:
                raise Exception(tr("t_subtitle.error.no_target_language"))
            if self.config.translator_service == TranslatorServiceEnum.OPENAI:
                _setup_llm_environment(self.config)

            asr_data = ASRData.from_json(self.selected_data)
            translator = create_translator_from_config(
                self.config, callback=self._callback
            )
            self._translator = translator
            try:
                asr_data = translator.translate_subtitle(asr_data)
            finally:
                self._translator = None
            self.checkpoint()

            keys = list(self.selected_data.keys())
            self.finished.emit(
                {
                    keys[index]: segment.translated_text
                    for index, segment in enumerate(asr_data.segments)
                }
            )
        finally:
            clear_task_context()
