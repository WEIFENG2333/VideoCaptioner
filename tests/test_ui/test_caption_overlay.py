"""CaptionOverlay 交互契约：按 seg_id upsert、工具条按钮切换形态/显示/暂停。

锁住"点击各按钮后状态正确翻转"的行为，防止以后改 toolbar 接线时退化。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-overlay.toml")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from videocaptioner.core.realtime.events import CaptionEntry  # noqa: E402
from videocaptioner.ui.components import caption_overlay as co  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def overlay(app):
    ov = co.CaptionOverlay()
    yield ov
    ov.close()
    ov.deleteLater()


def _entry(seg_id="s#0", seq=0, source="hello world", stable=5, target="", final=False):
    return CaptionEntry(
        seg_id=seg_id, seq=seq, source_text=source, source_stable_len=stable,
        target_text=target, is_final=final, started_at=1_700_000_000.0,
    )


class TestUpsert:
    def test_renders_source_and_target(self, overlay):
        # 标准/转录态当前段落都落到 _cur_item 卡片（标准 bare），不再用独立 _src/_tgt 标签
        overlay.upsert_caption(_entry(source="今天天气", stable=2, target="weather", final=True))
        row = overlay._current_row()
        assert row.source_text == "今天天气"
        assert row.target_text == "weather"
        item = overlay._cur_item
        assert "span" in item._src.text()  # 原文双色 span
        # 当前段原文/译文都逐字打字（_tgt.text() 是动画中的可见串，会从空打起）；
        # 译文是否落地看 _content_tgt（整段，set_content 即登记，供定高）。
        assert item._content_tgt == "weather"

    def test_same_seg_id_updates_in_place(self, overlay):
        overlay.upsert_caption(_entry(seg_id="s#0", source="我相信", target=""))
        overlay.upsert_caption(_entry(seg_id="s#0", source="我相信美国", target="i believe"))
        assert len(overlay._rows) == 1
        assert overlay._current_row().source_text == "我相信美国"
        assert overlay._current_row().target_text == "i believe"

    def test_current_is_highest_seq(self, overlay):
        overlay.upsert_caption(_entry(seg_id="s#0", seq=0, source="first", final=True))
        overlay.upsert_caption(_entry(seg_id="s#1", seq=1, source="second"))
        assert overlay._current_row().seg_id == "s#1"

    def test_current_target_row_is_content_tight_no_reserve(self, overlay):
        """当前段落不预留空译文行（预留会留一大块空白＝用户反馈的「巨大空卡片」）：无译文
        时 tgt 隐藏、卡片贴合内容；译文到达才显示。固定窗高 + 保留上次译文 → 不闪不缩窗。"""
        overlay.upsert_caption(_entry(seg_id="s", source="你好世界", stable=4, target=""))
        item = overlay._cur_item
        assert item._tgt.isHidden() is True   # 无译文 → 不占空行（内容紧凑）
        assert item._src.isHidden() is False
        # 译文到达 → 显示（_content_tgt 是去标签纯文本，双色 span 不影响断言）
        overlay.upsert_caption(_entry(seg_id="s", source="你好世界", stable=4, target="hello"))
        assert item._tgt.isHidden() is False and item._content_tgt == "hello"
        # 后端改写帧 target 空：upsert 保留上次译文 → tgt 仍显示，不在「有↔无」之间闪
        overlay.upsert_caption(_entry(seg_id="s", source="你好世界啊", stable=4, target=""))
        assert item._tgt.isHidden() is False and item._content_tgt == "hello"

    def test_empty_target_keeps_previous_translation(self, overlay):
        """防闪：新一帧还没翻译（target 空）就保留上次译文，不在空↔有之间闪。"""
        overlay.upsert_caption(_entry(seg_id="s#0", source="你好世界", target="hello"))
        overlay.upsert_caption(_entry(seg_id="s#0", source="你好世界啊", target=""))
        assert overlay._current_row().target_text == "hello"
        # 新译文到达才覆盖
        overlay.upsert_caption(_entry(seg_id="s#0", source="你好世界啊", target="hello world"))
        assert overlay._current_row().target_text == "hello world"


class TestHistoryFollow:
    def test_follow_flag_tracks_bottom(self, overlay):
        """历史跟随：贴底=跟随，上翻=停跟。"""
        sb = overlay._history.verticalScrollBar()
        sb.setRange(0, 100)
        overlay._on_history_scroll(100)  # 在底
        assert overlay._history_follow is True
        overlay._on_history_scroll(40)  # 上翻
        assert overlay._history_follow is False
        overlay._on_history_scroll(100)  # 回底
        assert overlay._history_follow is True

    def test_range_grow_scrolls_to_bottom_when_following(self, overlay):
        sb = overlay._history.verticalScrollBar()
        overlay._history_follow = True
        sb.setRange(0, 200)
        overlay._on_history_range(0, 200)
        assert sb.value() == 200  # 跟随时自动贴底
        overlay._history_follow = False
        sb.setValue(50)
        overlay._on_history_range(0, 300)
        assert sb.value() == 50  # 停跟时不被拽走

    def test_transcript_bottom_anchored(self, overlay):
        """底对齐时间线：stretch 顶在最上，历史段落卡片 + 常驻的当前段落卡片在其后。"""
        overlay.set_mode(co.MODE_TALL)
        for i in range(3):
            overlay.upsert_caption(_entry(seg_id=f"h{i}", seq=i, source=f"line {i}",
                                          target=f"行 {i}", final=True))
        overlay.upsert_caption(_entry(seg_id="cur", seq=9, source="current", target="当前"))
        overlay._flush_layout()  # 同步触发转录重建（绕开 33ms 合批定时器）
        layout = overlay._history_layout
        assert layout.itemAt(0).widget() is None  # 顶端 stretch
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())
                   if layout.itemAt(i).widget() is not None]
        assert len(widgets) == 4  # 3 历史段落 + 1 当前段落卡片
        assert widgets[-1] is overlay._cur_item  # 当前段落常驻在最底


class TestShellBehaviors:
    def test_show_is_offscreen_safe_and_installs_edge_filter(self, overlay):
        # showEvent 关原生阴影 + 装边缘过滤器；离屏平台必须不崩（曾因 winId objc 段错误）
        overlay.show()
        app = overlay.window()
        assert app is not None
        assert overlay._edge_filter_installed is True

    def test_no_autofade_no_resize_grip(self, overlay):
        # 自动淡隐与右下角缩放角标都已移除（用户嫌打扰/多余）；缩放靠拖边缘
        assert not hasattr(overlay, "_autofade")
        assert not hasattr(overlay, "_rz")

    def test_edge_press_over_child_resizes(self, overlay):
        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QMouseEvent

        overlay.set_mode(co.MODE_TALL)
        overlay.show()
        calls = []
        overlay._begin_drag_or_resize = lambda pos: calls.append(pos)  # 不触发真 resize
        vp = overlay._history.viewport()
        # 历史滚动区左边缘按下 → 过滤器吃掉并触发缩放
        edge = QPoint(1, max(2, vp.height() // 2))
        ev = QMouseEvent(
            QEvent.MouseButtonPress, QPoint(edge),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        consumed = overlay.eventFilter(vp, ev)
        assert consumed is True and len(calls) == 1

    def test_body_press_over_child_moves_window(self, overlay):
        # 本体（非边缘）按下也转交浮窗 → 拖动整窗。转录文字铺满浮窗，不转交就「按在
        # 文字上拖不动、缩放不了」（用户反馈浮窗大小调不了的根因）。
        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QMouseEvent

        overlay.set_mode(co.MODE_TALL)
        overlay.show()
        calls = []
        overlay._begin_drag_or_resize = lambda pos: calls.append(pos)
        vp = overlay._history.viewport()
        center = QPoint(max(40, vp.width() // 2), max(40, vp.height() // 2))  # 远离边缘
        ev = QMouseEvent(
            QEvent.MouseButtonPress, QPoint(center),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        consumed = overlay.eventFilter(vp, ev)
        assert consumed is True and len(calls) == 1


class TestCursor:
    def test_body_grab_edges_resize(self, overlay):
        from PyQt5.QtCore import Qt

        card = overlay._card.geometry()
        # 本体 → 抓手（表明可拖）；四角/边 → 缩放
        assert overlay._cursor_for(overlay._edge_at(card.center())) == Qt.OpenHandCursor
        assert overlay._cursor_for(overlay._edge_at(card.topLeft())) == Qt.SizeFDiagCursor
        # 卡片默认就是抓手（悬浮即提示可拖，不必等 hover 事件）
        assert overlay._card.cursor().shape() == Qt.OpenHandCursor


class TestToolbarButtons:
    def test_pause_button_toggles_state_and_signal(self, overlay):
        seen = []
        overlay.pauseToggled.connect(seen.append)
        overlay._btn_pause.click()
        assert overlay._paused is True and seen == [True]
        overlay._btn_pause.click()
        assert overlay._paused is False and seen == [True, False]

    def test_pause_swaps_play_pause_icon(self, overlay):
        # 暂停态用"播放"图标（点击=恢复），而不是只给一个高亮——符合正常认知
        assert overlay._btn_pause._key == "pause"
        overlay.set_paused(True)
        assert overlay._btn_pause._key == "play"
        overlay.set_paused(False)
        assert overlay._btn_pause._key == "pause"

    def test_history_button_toggles_tall(self, overlay):
        overlay._btn_hist.click()
        assert overlay.mode == co.MODE_TALL
        overlay._btn_hist.click()
        assert overlay.mode == co.MODE_STANDARD

    def test_display_mode_set_via_api(self, overlay):
        # 双语/仅译文/仅原文改由设置弹层（API），工具条不再放双语按钮
        assert not hasattr(overlay, "_btn_bi")
        overlay.set_display_mode(co.DISPLAY_TARGET)
        assert overlay._display == co.DISPLAY_TARGET

    def test_pin_via_control_page_api(self, overlay):
        # 鼠标穿透由控制页开关驱动（set_pinned），浮窗工具条不再放钉住按钮
        from PyQt5.QtCore import Qt

        assert not hasattr(overlay, "_btn_pin")
        overlay.set_pinned(True)
        assert overlay._pinned is True
        assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)

    def test_removed_toolbar_extras_absent(self, overlay):
        # 语言胶囊、复制/收藏、收起(胶囊态已删)都已去掉
        for attr in ("_lang_pill", "_btn_copy", "_btn_star", "_line_acts", "_btn_min"):
            assert not hasattr(overlay, attr), attr

    def test_compact_mode_removed(self, overlay):
        # COMPACT 胶囊态已彻底删除：常量/方法/波形都不应存在
        assert not hasattr(co, "MODE_COMPACT")
        assert not hasattr(co, "_Waveform")
        assert not hasattr(overlay, "_render_compact")
        assert not hasattr(overlay, "_wave")


class TestScrollbarPolicy:
    def test_standard_never_shows_scrollbar(self, overlay):
        """标准态紧凑单段视图，滚动条永远关（杜绝右侧诡异滚动条）；转录态按需。"""
        from PyQt5.QtCore import Qt

        overlay.set_mode(co.MODE_STANDARD)
        assert overlay._history.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        overlay.set_mode(co.MODE_TALL)
        assert overlay._history.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


class TestModeWidths:
    @pytest.mark.parametrize(
        "mode,width",
        [
            (co.MODE_STANDARD, 540),
            (co.MODE_TALL, 540),  # 两态同宽 → 切历史只变高不左右抖
        ],
    )
    def test_card_width_per_mode(self, overlay, mode, width):
        overlay.set_mode(mode)
        assert overlay._card.width() == width


class TestStatePreservation:
    def test_user_size_kept_across_mode_toggle(self, overlay):
        """用户在标准态拖大后，切到展开再切回，标准态尺寸应保持（不再每次切形态清空）。"""
        overlay.set_mode(co.MODE_STANDARD)
        overlay._user_sizes[co.MODE_STANDARD] = (640, 200)
        overlay._relayout()
        assert overlay._card.width() == 640
        overlay.set_mode(co.MODE_TALL)
        overlay.set_mode(co.MODE_STANDARD)
        assert overlay._card.width() == 640  # 切换往返后仍是用户尺寸

    def test_tall_height_is_fixed_not_content_driven(self, overlay):
        """根治高度抖动：转录态默认高度固定（_TALL_H），不随历史内容增减——内容多了在
        转录区内部滚动到底，窗口高度只由用户拖边决定。"""
        overlay.set_mode(co.MODE_TALL)
        _, h0 = overlay._card_size()
        assert h0 == co._TALL_H
        for i in range(6):
            overlay.upsert_caption(
                _entry(seg_id=f"h#{i}", seq=i, source=f"line {i}", target=f"行{i}", final=True)
            )
        _, h1 = overlay._card_size()
        assert h1 == co._TALL_H  # 加一堆历史后高度仍固定，不被内容撑动

    def test_standard_height_adapts_to_content_no_clip(self, overlay):
        """标准态卡高随当前段落行数自适应（根治多行时首行顶部被裁半字）：单行=_STANDARD_H，
        多行长内容在上限内长高；不再固定 140 裁字。短内容仍回基准高、不留大空白。"""
        overlay.set_mode(co.MODE_STANDARD)
        _, h0 = overlay._card_size()
        assert h0 == co._STANDARD_H  # 空态/占位 = 基准高
        overlay.upsert_caption(_entry(seg_id="s", source="hi", stable=2, target=""))
        _, h1 = overlay._card_size()
        assert h1 == co._STANDARD_H  # 一句短话仍是基准高
        overlay.upsert_caption(
            _entry(
                seg_id="s",
                source="这是一段相当长的当前句用来测试自动换行会不会被裁切掉首行的顶部" * 2,
                stable=4,
                target="A fairly long current paragraph used to verify the card grows to fit " * 2,
            )
        )
        _, h2 = overlay._card_size()
        assert h2 > co._STANDARD_H          # 多行长内容 → 长高（不再固定裁字）
        assert h2 <= co._STANDARD_MAX_H     # 但不超上限（再长则内部滚动）

    def test_manual_resize_changes_geometry_and_clamps(self, overlay):
        """macOS startSystemResize 返回 False → 手动缩放兜底：拖右下角改窗几何，夹住最小尺寸。"""
        from PyQt5.QtCore import QPoint, QRect

        overlay.set_mode(co.MODE_TALL)
        before = overlay.geometry()
        overlay._drag_mode = "resize"
        overlay._resize_edge = co._RIGHT | co._BOTTOM
        overlay._drag_geo = QRect(overlay.geometry())
        overlay._apply_manual_resize(QPoint(70, 50))
        after = overlay.geometry()
        assert after.width() - before.width() == 70
        assert after.height() - before.height() == 50
        overlay._drag_geo = QRect(after)  # 缩到极小 → 被夹住
        overlay._apply_manual_resize(QPoint(-9999, -9999))
        assert overlay.width() >= 260 + 2 * co.MARGIN
        assert overlay.height() >= 56 + 2 * co.MARGIN

    def test_standard_centers_when_dragged_taller(self, overlay):
        """标准态拖大后当前单句垂直居中（不再被顶 stretch 推到底沿留大块空白）：底部
        stretch 因子=1 与顶部对称；转录态有内容时=0 保持底对齐时间线。"""
        # 有内容，避开空态占位（空态两态都居中，是 #97 行为）
        overlay.upsert_caption(_entry(seg_id="s", source="hi", target="你好", final=True))
        overlay.set_mode(co.MODE_STANDARD)
        last = overlay._history_layout.count() - 1
        assert overlay._history_layout.itemAt(last).widget() is None  # 末尾是 stretch
        assert overlay._history_layout.stretch(last) == 1  # 标准态底 stretch=1 → 居中
        overlay.set_mode(co.MODE_TALL)
        last = overlay._history_layout.count() - 1
        assert overlay._history_layout.stretch(last) == 0  # 转录态底 stretch=0 → 底对齐

    def test_empty_placeholder_centers_in_both_modes(self, overlay):
        """空态「监听中…」两态都垂直居中（#97）：底部 stretch=1 与顶部对称。"""
        for mode in (co.MODE_STANDARD, co.MODE_TALL):
            overlay.set_mode(mode)
            last = overlay._history_layout.count() - 1
            assert overlay._history_layout.stretch(last) == 1

    def test_set_mode_emits_mode_changed(self, overlay):
        seen = []
        overlay.modeChanged.connect(seen.append)
        overlay.set_mode(co.MODE_TALL)
        assert seen == [co.MODE_TALL]
        overlay.set_mode(co.MODE_TALL)  # 同形态不重复发
        assert seen == [co.MODE_TALL]

    def test_restore_size_seeds_user_size(self, overlay):
        overlay.set_mode(co.MODE_TALL)
        overlay.restore_size(co.MODE_TALL, 700, 520)
        assert overlay._user_sizes[co.MODE_TALL] == (700, 520)
        assert overlay._card.width() == 700
