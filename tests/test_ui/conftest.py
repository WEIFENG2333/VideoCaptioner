# -*- coding: utf-8 -*-
"""test_ui 共享 Qt 夹具。

qfluentwidgets 的全局 ``qconfig`` 单例在进程内只创建一次；若某个测试模块结束时
其 ``QApplication`` 的最后一个 Python 引用被回收，sip 会把 C++ 对象连同 qconfig
一起删掉，导致后续模块构造 qfluent 控件时报 "QConfig has been deleted"。

这里用 session 作用域、autouse 的夹具长期持有同一个 QApplication，杜绝跨模块的
单例被提前销毁。各模块自带的 ``app`` 夹具仍可用（拿到的是同一个实例）。
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from videocaptioner.config import I18N_PATH  # noqa: E402
from videocaptioner.ui.i18n import init as _init_i18n  # noqa: E402

# 与 ui/main.py 一致装载 UI 翻译；缺了页面会显示 tr key 而非中文，断言会失败。
_init_i18n(I18N_PATH, "zh_CN")

_HELD_APP = None  # 进程级强引用：阻止 QApplication 被 GC


@pytest.fixture(scope="session", autouse=True)
def _shared_qapp():
    global _HELD_APP
    _HELD_APP = QApplication.instance() or QApplication(sys.argv)
    yield _HELD_APP
    # 不主动销毁：留给进程退出，避免触发 qfluent 单例的提前删除


@pytest.fixture()
def app():
    """共享 QApplication 的具名别名（模块未自带 app 夹具时取用）。"""
    return QApplication.instance() or QApplication(sys.argv)
