"""依赖下载弹窗的行为契约。

锁住：已安装→绿胶囊无按钮；缺失→可下载；不支持平台→不可用禁用；一键安装仅在有缺失时
可点；下载流程经替身线程：progress 刷行、completed 发 depsChanged。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-depdlg.toml")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QWidget  # noqa: E402

from videocaptioner.ui.components import dependency_download_dialog as ddl  # noqa: E402


@pytest.fixture()
def host(app):
    # AppDialog 需要一个有 window() 的父控件（遮罩盖整个程序窗口）。
    # resize 即可满足 MaskDialogBase 取 parent.width/height，无需真的 show()。
    # 与 test_app_dialog 一致：弹窗各自 deleteLater，host 只 close（不删、不 flush），
    # 避免 MaskDialogBase 在离屏下被提前删触发段错误。
    w = QWidget()
    w.resize(900, 640)
    yield w
    w.close()


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *a):
        for s in list(self._slots):
            s(*a)


class _FakeThread:
    def __init__(self):
        self.started = False
        self.stopped = False
        for name in ("progress", "completed", "error", "finished"):
            setattr(self, name, _Signal())

    def start(self):
        self.started = True

    def stop(self, *a, **k):
        self.stopped = True

    def deleteLater(self):
        pass


@pytest.fixture()
def installed_map(monkeypatch):
    """可变的「已安装」表：测试按 key 控制每个依赖装没装。"""
    state = {"ffmpeg": True, "voxgate": False}
    monkeypatch.setattr(ddl, "is_installed", lambda spec: state.get(spec.key, False))
    return state


def test_rows_reflect_install_state(host, installed_map):
    dlg = ddl.DependencyDownloadDialog(parent=host)
    rows = {r.spec.key: r for r in dlg._rows}
    assert set(rows) == {"ffmpeg", "voxgate"}
    # ffmpeg 已装：绿胶囊、操作按钮隐藏
    assert rows["ffmpeg"].status.text() == "已安装"
    assert rows["ffmpeg"].status.isHidden() is False
    assert rows["ffmpeg"].actionButton.isHidden() is True
    # voxgate 缺失：右侧单槽只放下载按钮，状态胶囊隐藏（不再叠一个「待安装」胶囊）
    assert rows["voxgate"].actionButton.isHidden() is False
    assert rows["voxgate"].status.isHidden() is True
    assert dlg.installAllButton.isEnabled() is True
    dlg.done(0)
    dlg.deleteLater()


def test_install_all_disabled_when_all_installed(host, monkeypatch):
    monkeypatch.setattr(ddl, "is_installed", lambda spec: True)
    dlg = ddl.DependencyDownloadDialog(parent=host)
    assert dlg.installAllButton.isEnabled() is False
    dlg.done(0)
    dlg.deleteLater()


def test_unsupported_platform_disables_action(host, installed_map, monkeypatch):
    monkeypatch.setattr(ddl, "asset_for", lambda spec: None)  # 平台无件
    dlg = ddl.DependencyDownloadDialog(parent=host)
    vox = next(r for r in dlg._rows if r.spec.key == "voxgate")
    # 不支持的平台只显示「暂不支持」胶囊，不再放一个禁用按钮（右侧单槽只放一件事）
    assert vox.status.text() == "暂不支持"
    assert vox.status.isHidden() is False
    assert vox.actionButton.isHidden() is True
    dlg.done(0)
    dlg.deleteLater()


def test_download_flow_emits_deps_changed(host, installed_map, monkeypatch):
    fake = _FakeThread()
    monkeypatch.setattr(ddl, "dependency_download_thread", lambda spec, parent=None: fake)
    dlg = ddl.DependencyDownloadDialog(parent=host)
    changed = []
    dlg.depsChanged.connect(lambda: changed.append(True))

    vox = next(r for r in dlg._rows if r.spec.key == "voxgate")
    vox.actionButton.clicked.emit()
    assert fake.started is True
    assert dlg._busy is True

    fake.progress.emit(42, "voxgate · 4.2 MB / 10 MB")
    assert "42%" in vox.percentLabel.text()

    # 安装完成 → 标记已装 → 完成回调发 depsChanged，结束后回到非忙
    installed_map["voxgate"] = True
    fake.completed.emit("/x/voxgate")
    fake.finished.emit()
    assert changed == [True]
    assert dlg._busy is False
    dlg.done(0)
    dlg.deleteLater()


def test_close_cancels_active_download(host, installed_map, monkeypatch):
    fake = _FakeThread()
    monkeypatch.setattr(ddl, "dependency_download_thread", lambda spec, parent=None: fake)
    dlg = ddl.DependencyDownloadDialog(parent=host)
    next(r for r in dlg._rows if r.spec.key == "voxgate").actionButton.clicked.emit()
    dlg.done(0)  # 关闭即取消
    dlg.deleteLater()
    assert fake.stopped is True
