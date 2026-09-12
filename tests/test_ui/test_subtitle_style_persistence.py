"""字幕样式页：编辑内置样式不应每次新建一个，避免样式越积越多。

历史 bug：关闭/打开程序后字幕样式列表里突然多出一堆 `默认描边 · 自定义`、
`…-custom-2`、`…-custom-3`…… 用户并没有手动建这么多。

根因（两处耦合）：
1. `subtitle_style_name` 只存一份，却被 ASS / 圆角两种渲染模式共用。切到另一
   模式再切回时，`_refresh_style_list` 解析不到本模式的选择，回退到内置默认
   并把它写回配置——本模式的选择被悄悄重置成内置。
2. `_auto_save` 编辑内置时用递增 id（`-custom-N`）fork，每次重置回内置后再
   编辑就又新建一个。

修复：每个模式各记一份最近选择（切模式往返可还原）；编辑内置时 fork 到该内置
「唯一」的确定性 id（已存在就复用更新）。本测试锁死“无论怎么编辑/切模式/重启，
同一个内置至多派生一个用户样式”。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import videocaptioner.config as vc_config  # noqa: E402
import videocaptioner.core.application.config_store as config_store  # noqa: E402
from videocaptioner.ui.common.config import cfg  # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def isolated_styles(tmp_path, monkeypatch):
    """把用户样式目录与配置文件都指到临时路径，互不污染真实环境。"""
    styles_dir = tmp_path / "subtitle_styles"
    styles_dir.mkdir()
    monkeypatch.setattr(vc_config, "USER_SUBTITLE_STYLE_PATH", styles_dir)
    monkeypatch.setattr(config_store, "CONFIG_FILE", tmp_path / "config.toml")
    return styles_dir


def _user_style_files(styles_dir):
    return sorted(p.relative_to(styles_dir).as_posix() for p in styles_dir.rglob("*.json"))


def _make_page(monkeypatch):
    from videocaptioner.ui.view.subtitle_style_interface import SubtitleStyleInterface

    # 预览会起 QThread，本测试只关心 fork 逻辑，置空避免线程残留。
    monkeypatch.setattr(SubtitleStyleInterface, "update_preview", lambda self: None)
    page = SubtitleStyleInterface()
    page._on_mode_changed("ass")
    return page


def test_editing_builtin_forks_only_once(qapp, isolated_styles, monkeypatch):
    # 起始：当前是内置 ASS 默认样式
    cfg.set(cfg.subtitle_style_name, "ass/default", save=False)

    page = _make_page(monkeypatch)
    assert _user_style_files(isolated_styles) == []

    # 1) 编辑内置 → 派生唯一 fork
    page._ass["size"].setValue(41)
    page._on_edit()
    assert _user_style_files(isolated_styles) == ["ass/default-custom.json"]
    assert cfg.subtitle_style_name.value == "ass/default-custom"

    # 2) 切到圆角再切回 ASS（往返）——选择必须被记住、还原，而非重置回内置
    page._on_mode_changed("rounded")
    page._on_mode_changed("ass")
    assert cfg.subtitle_style_name.value == "ass/default-custom"

    # 3) 往返后再次编辑 → 更新同一个 fork，绝不新建
    page._ass["size"].setValue(46)
    page._on_edit()
    assert _user_style_files(isolated_styles) == ["ass/default-custom.json"]


def test_no_accumulation_across_restarts(qapp, isolated_styles, monkeypatch):
    cfg.set(cfg.subtitle_style_name, "ass/default", save=False)

    # 连续三次“启动→编辑内置→关闭”，模拟用户多日使用
    for size in (40, 44, 50):
        page = _make_page(monkeypatch)
        page._ass["size"].setValue(size)
        page._on_edit()
        page.deleteLater()

    # 三轮下来仍只有一个用户样式，而不是 3 个 -custom-N
    assert _user_style_files(isolated_styles) == ["ass/default-custom.json"]


def test_rebuilding_inspector_never_promotes_old_groups_to_windows(
    qapp, isolated_styles, monkeypatch
):
    cfg.set(cfg.subtitle_style_name, "ass/default", save=False)
    page = _make_page(monkeypatch)
    page.show()
    qapp.processEvents()

    old_groups = [
        page.inspectorLayout.itemAt(i).widget()
        for i in range(page.inspectorLayout.count() - 1)
    ]
    page._on_mode_changed("rounded")

    assert old_groups
    assert all(not group.isWindow() for group in old_groups)
    assert all(not group.isVisible() for group in old_groups)
    page.close()
