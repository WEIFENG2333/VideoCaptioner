"""批量处理页纯逻辑测试：文件收集、阶段链、任务数据、队列调度边界。"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal  # noqa: E402

import videocaptioner.ui.view.batch_process_interface as batch_module  # noqa: E402
from videocaptioner.ui.view.batch_process_interface import (  # noqa: E402
    BatchController,
    BatchJob,
    JobStatus,
    collect_files,
    mode_by_key,
    stages_for_mode,
)


class TestStagesForMode:
    def test_transcribe_only(self):
        assert stages_for_mode("transcribe", dubbing_enabled=True) == ["transcribe"]

    def test_subtitle_only(self):
        assert stages_for_mode("subtitle", dubbing_enabled=True) == ["subtitle"]

    def test_trans_sub(self):
        assert stages_for_mode("trans_sub", dubbing_enabled=True) == [
            "transcribe",
            "subtitle",
        ]

    def test_full_without_dubbing(self):
        assert stages_for_mode("full", dubbing_enabled=False) == [
            "transcribe",
            "subtitle",
            "synthesis",
        ]

    def test_full_with_dubbing(self):
        assert stages_for_mode("full", dubbing_enabled=True) == [
            "transcribe",
            "subtitle",
            "dubbing",
            "synthesis",
        ]


class TestModeByKey:
    def test_known_key(self):
        assert mode_by_key("subtitle").accepts_media is False

    def test_unknown_key_falls_back_to_full(self):
        assert mode_by_key("nope").key == "full"


class TestCollectFiles:
    @pytest.fixture
    def tree(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"\0")
        (tmp_path / "b.txt").write_text("x")
        deep = tmp_path / "l1" / "l2"
        deep.mkdir(parents=True)
        (deep / "c.mp3").write_bytes(b"\0")
        too_deep = deep / "l3" / "l4"
        too_deep.mkdir(parents=True)
        (too_deep / "d.mp4").write_bytes(b"\0")
        return tmp_path

    def test_expands_folder_and_filters(self, tree):
        valid, ignored = collect_files([str(tree)], {".mp4", ".mp3"})
        names = sorted(os.path.basename(path) for path in valid)
        assert names == ["a.mp4", "c.mp3"]  # 第 4 层不展开
        assert ignored == 1  # b.txt

    def test_single_files(self, tree):
        valid, ignored = collect_files(
            [str(tree / "a.mp4"), str(tree / "b.txt"), str(tree / "missing.mp4")],
            {".mp4"},
        )
        assert valid == [str(tree / "a.mp4")]
        assert ignored == 2

    def test_extension_case_insensitive(self, tmp_path):
        upper = tmp_path / "UP.MP4"
        upper.write_bytes(b"\0")
        valid, _ = collect_files([str(upper)], {".mp4"})
        assert valid == [str(upper)]


class FakeRunner(QObject):
    """替身 JobRunner：由测试手动触发完成/失败。"""

    progressChanged = pyqtSignal(int, str, str)
    completed = pyqtSignal(list)
    failed = pyqtSignal(str)
    instances: list["FakeRunner"] = []

    def __init__(self, file_path, stages, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.cancelled = False
        FakeRunner.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def release(self):
        pass


@pytest.fixture
def controller(monkeypatch):
    from PyQt5.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(batch_module, "JobRunner", FakeRunner)
    FakeRunner.instances.clear()
    ctrl = BatchController(concurrency=lambda: 2)
    finished = []
    ctrl.batchFinished.connect(lambda: finished.append(True))
    ctrl.finished_events = finished
    return ctrl


class TestControllerScheduling:
    def test_pause_drain_announces_finish(self, controller):
        """暂停后排空到底应宣布批次结束（历史 bug：永不收尾）。"""
        controller.add_paths(["/tmp/a.mp4", "/tmp/b.mp4"])
        controller.start(["transcribe"])
        assert len(FakeRunner.instances) == 2  # 并发 2 全部起跑
        controller.pause()
        for runner in list(FakeRunner.instances):
            runner.completed.emit(["/tmp/out.srt"])
        assert controller.finished_events == [True]
        assert not controller.is_active()

    def test_pause_with_waiting_jobs_does_not_finish(self, controller):
        controller.add_paths(["/tmp/a.mp4", "/tmp/b.mp4", "/tmp/c.mp4"])
        controller.start(["transcribe"])
        controller.pause()
        for runner in list(FakeRunner.instances):
            runner.completed.emit([])
        assert controller.finished_events == []  # 还有等待任务，是暂停不是结束
        assert controller.count(JobStatus.WAITING) == 1

    def test_add_files_while_running_gets_dispatched(self, controller):
        controller.add_paths(["/tmp/a.mp4"])
        controller.start(["transcribe"])
        controller.add_paths(["/tmp/b.mp4"])
        assert len(FakeRunner.instances) == 2  # 运行中加入的文件自动派发

    def test_remove_last_waiting_finishes_batch(self, controller):
        controller.add_paths(["/tmp/a.mp4", "/tmp/b.mp4", "/tmp/c.mp4"])
        controller.start(["transcribe"])
        waiting = next(j for j in controller.jobs if j.status == JobStatus.WAITING)
        controller.remove(waiting)
        for runner in list(FakeRunner.instances):
            if not runner.cancelled:
                runner.completed.emit([])
        assert controller.finished_events == [True]

    def test_finish_announced_only_once(self, controller):
        controller.add_paths(["/tmp/a.mp4"])
        controller.start(["transcribe"])
        FakeRunner.instances[0].completed.emit([])
        controller.remove(controller.jobs[0])  # 结束后再操作不应重复宣布
        assert controller.finished_events == [True]

    def test_retry_reopens_dispatch_and_finishes_again(self, controller):
        controller.add_paths(["/tmp/a.mp4"])
        controller.start(["transcribe"])
        FakeRunner.instances[0].failed.emit("boom")
        assert controller.finished_events == [True]
        job = controller.jobs[0]
        controller.retry(job, ["transcribe"])
        assert job.status == JobStatus.RUNNING  # 重试即跑
        assert len(FakeRunner.instances) == 2
        FakeRunner.instances[1].completed.emit([])
        assert controller.finished_events == [True, True]


class TestBatchJob:
    def test_defaults(self, tmp_path):
        job = BatchJob(path=str(tmp_path / "视频.mp4"))
        assert job.status == JobStatus.WAITING
        assert job.progress == 0
        assert job.name == "视频.mp4"
        assert job.outputs == []

    def test_folder_abbreviates_home(self):
        home = os.path.expanduser("~")
        job = BatchJob(path=os.path.join(home, "Movies", "a.mp4"))
        assert job.folder == os.path.join("~", "Movies")
