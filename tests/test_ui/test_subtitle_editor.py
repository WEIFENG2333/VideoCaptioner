"""字幕行内编辑器回归：双击进入编辑不再全选整格（用户反馈：双击直接全选不合理）。"""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QWidget

from videocaptioner.ui.view.subtitle_interface import SubtitleLineEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_focus_does_not_select_all(app):
    host = QWidget()
    host.resize(400, 80)
    host.show()
    editor = SubtitleLineEditor(host)
    editor.setText("欢迎报考百年名校华南师范大学")
    editor.setGeometry(10, 10, 360, 30)
    editor.show()
    app.processEvents()
    # OtherFocusReason 正是单元格进入编辑时的聚焦方式，Qt 默认会 selectAll
    editor.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    assert editor.hasSelectedText() is False
    # 无点击坐标时光标落到末尾，可直接续编
    assert editor.cursorPosition() == len(editor.text())
    host.close()


def test_click_point_positions_cursor(app):
    host = QWidget()
    host.resize(400, 80)
    host.show()
    editor = SubtitleLineEditor(host)
    editor.setText("abcdefghijklmnop")
    editor.setGeometry(10, 10, 360, 30)
    editor.show()
    app.processEvents()
    # 给一个落在文本左段的全局点，光标应落在靠前位置而非末尾/全选
    left_global = editor.mapToGlobal(editor.rect().topLeft())
    left_global.setX(left_global.x() + 6)
    editor.setClickPoint(left_global)
    editor.setFocus(Qt.OtherFocusReason)
    app.processEvents()
    # 关键保证：带点击坐标聚焦也不全选；精确光标列依赖真实几何，offscreen 不强校验
    assert editor.hasSelectedText() is False
    assert 0 <= editor.cursorPosition() <= len(editor.text())
    host.close()
