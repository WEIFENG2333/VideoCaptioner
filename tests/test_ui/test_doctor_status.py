"""诊断页状态映射契约：warn 与 error 必须区分（琥珀 vs 红）。

锁住「可选项缺失 = 琥珀 WARNING，不是红 ERROR」这条——live_caption 缺 voxgate、
dubbing 缺 Key 都属此类，不应像硬错误一样吓人，也不计入「未通过」。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-doctor-status.toml")

from videocaptioner.cli.commands.doctor import Check  # noqa: E402
from videocaptioner.ui.view import doctor_interface as di  # noqa: E402


def test_combined_status_distinguishes_warn_from_error():
    assert di._combined_status([Check("a", "ok", "")]) == di.ItemStatus.OK
    assert di._combined_status([Check("a", "warn", "")]) == di.ItemStatus.WARNING
    assert di._combined_status([Check("a", "error", "")]) == di.ItemStatus.ERROR
    # error 优先于 warn：同时存在按最严重算
    assert di._combined_status(
        [Check("a", "warn", ""), Check("b", "error", "")]
    ) == di.ItemStatus.ERROR
    assert di._combined_status([]) == di.ItemStatus.OK


def test_status_level_and_text_have_warning():
    assert di._status_level(di.ItemStatus.WARNING) == "warning"
    assert di._status_text(di.ItemStatus.WARNING)  # 有文案


def test_live_caption_missing_voxgate_is_amber_warning():
    # voxgate 缺失 → warn → 卡片 WARNING（琥珀），描述强调「可选」，而非红色「不可用」
    checks = [Check("live_caption.voxgate", "warn", "未找到 voxgate 转录程序")]
    items = di._items_from_checks(checks, lambda s: s)
    card = next(i for i in items if i.key == "live_caption")
    assert card.status == di.ItemStatus.WARNING
    assert "可选" in card.description


def test_live_caption_ready_is_ok():
    checks = [Check("live_caption.voxgate", "ok", "voxgate 已就绪：/usr/bin/voxgate")]
    items = di._items_from_checks(checks, lambda s: s)
    card = next(i for i in items if i.key == "live_caption")
    assert card.status == di.ItemStatus.OK
