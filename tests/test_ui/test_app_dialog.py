"""AppDialog 壳契约：居中提升 + 确认/取消返回值。

历史 bug：弹窗 parent 传子页面（tab interface）时，qfluent MessageBoxBase
基于该子页面遮罩与居中，弹窗偏到窗口一角。AppDialog 构造时强制提升到
parent.window()，这里锁住该契约，防止以后新弹窗再退化。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-app-dialog.toml")

from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture()
def host(app):
    """主窗口 + 偏左子面板（模拟 tab interface）。"""
    window = QWidget()
    window.resize(1000, 700)
    row = QHBoxLayout(window)
    row.setContentsMargins(0, 0, 0, 0)
    tab = QFrame(window)
    tab.setFixedWidth(300)
    row.addWidget(tab)
    row.addStretch(1)
    window.show()
    app.processEvents()
    yield window, tab
    window.close()


class TestAppDialogShell:
    def test_parent_promoted_to_window(self, host):
        from videocaptioner.ui.components.app_dialog import AppDialog

        window, tab = host
        dialog = AppDialog("测试", parent=tab)
        assert dialog.parent() is window
        dialog.deleteLater()

    def test_card_centered_on_window_not_tab(self, app, host):
        from videocaptioner.ui.components.app_dialog import ConfirmDialog

        window, tab = host
        dialog = ConfirmDialog("标题", "正文", tab)
        dialog.show()
        app.processEvents()
        card_center = dialog.widget.mapTo(dialog, dialog.widget.rect().center())
        assert abs(card_center.x() - dialog.rect().center().x()) <= 2
        assert abs(card_center.y() - dialog.rect().center().y()) <= 2
        dialog.done(0)
        dialog.deleteLater()


class TestConfirmDialogResult:
    def test_confirm_returns_1(self, app, host):
        from videocaptioner.ui.components.app_dialog import ConfirmDialog

        _, tab = host
        dialog = ConfirmDialog("标题", "正文", tab)
        results = []
        dialog.finished.connect(results.append)
        dialog.show()
        app.processEvents()
        dialog.confirmButton.clicked.emit()
        QTest.qWait(500)  # MaskDialogBase.done 经淡出动画后才发 finished
        assert results == [1]
        dialog.deleteLater()

    def test_cancel_returns_0(self, app, host):
        from videocaptioner.ui.components.app_dialog import ConfirmDialog

        _, tab = host
        dialog = ConfirmDialog("标题", "正文", tab)
        results = []
        dialog.finished.connect(results.append)
        dialog.show()
        app.processEvents()
        assert dialog.cancelButton is not None
        dialog.cancelButton.clicked.emit()
        QTest.qWait(500)  # MaskDialogBase.done 经淡出动画后才发 finished
        assert results == [0]
        dialog.deleteLater()

    def test_notice_mode_has_no_cancel(self, host):
        from videocaptioner.ui.components.app_dialog import ConfirmDialog

        _, tab = host
        dialog = ConfirmDialog("公告", "正文", tab, cancel_text=None)
        assert dialog.cancelButton is None
        dialog.deleteLater()


class TestStyleNameDialog:
    def test_confirm_disabled_until_text(self, app, host):
        from videocaptioner.ui.view.subtitle_style_interface import StyleNameDialog

        _, tab = host
        dialog = StyleNameDialog(parent=tab)
        assert not dialog.confirmButton.isEnabled()
        dialog.nameLineEdit.setText("  ")
        app.processEvents()
        assert not dialog.confirmButton.isEnabled()
        dialog.nameLineEdit.setText("我的样式")
        app.processEvents()
        assert dialog.confirmButton.isEnabled()
        dialog.deleteLater()
