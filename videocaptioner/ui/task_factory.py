from typing import Optional

from videocaptioner.core.application import TaskBuilder
from videocaptioner.core.entities import DubbingUIConfig
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.config_adapter import app_config_from_ui


class TaskFactory:
    """Build UI tasks from the shared application config.

    Task-construction logic lives in core.application.TaskBuilder. This class
    keeps UI call sites small and removes UI settings internals from the executable task layer.
    """

    @staticmethod
    def _builder() -> TaskBuilder:
        return TaskBuilder(app_config_from_ui(cfg))

    @staticmethod
    def create_subtitle_config():
        """当前设置下的字幕处理配置（预检/展示用，不创建任务）。"""
        return TaskFactory._builder().create_subtitle_config()

    @staticmethod
    def get_ass_style(style_name: str) -> str:
        return TaskFactory._builder().get_ass_style(style_name)

    @staticmethod
    def get_rounded_style() -> dict:
        return TaskFactory._builder().get_rounded_style()

    @staticmethod
    def new_task_dir(source: str, task_type: str) -> str:
        """流水线开始时创建一次任务目录，跨阶段复用，由流程所有者清理。

        task_type 按功能归类（output_paths.TASK_*：transcribe/synthesis/batch/dubbing），
        决定落到 ``{work_dir}/{task_type}/`` 下哪个子目录。
        """
        return TaskFactory._builder().new_task_dir(source, task_type)

    @staticmethod
    def create_transcribe_task(
        file_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ):
        return TaskFactory._builder().create_transcribe_task(
            file_path,
            need_next_task=need_next_task,
            task_id=task_id,
            task_dir=task_dir,
        )

    @staticmethod
    def create_subtitle_task(
        file_path: str,
        video_path: Optional[str] = None,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ):
        return TaskFactory._builder().create_subtitle_task(
            file_path,
            video_path=video_path,
            need_next_task=need_next_task,
            task_id=task_id,
            task_dir=task_dir,
        )

    @staticmethod
    def create_synthesis_task(
        video_path: str,
        subtitle_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
        dubbed: bool = False,
    ):
        return TaskFactory._builder().create_synthesis_task(
            video_path,
            subtitle_path,
            need_next_task=need_next_task,
            task_id=task_id,
            task_dir=task_dir,
            dubbed=dubbed,
        )

    @staticmethod
    def create_dubbing_task(
        video_path: str,
        subtitle_path: str,
        output_video_path: Optional[str] = None,
        output_audio_path: Optional[str] = None,
        task_id: Optional[str] = None,
        task_dir: Optional[str] = None,
    ):
        return TaskFactory._builder().create_dubbing_task(
            video_path,
            subtitle_path,
            output_video_path=output_video_path,
            output_audio_path=output_audio_path,
            task_id=task_id,
            task_dir=task_dir,
        )

    @staticmethod
    def create_dubbing_ui_config() -> DubbingUIConfig:
        return TaskFactory._builder().create_dubbing_ui_config()
