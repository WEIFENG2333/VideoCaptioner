"""AudioPlayerBar seek 时序契约：媒体未加载完时 setPosition 会被 AVFoundation 丢弃，
必须暂存目标位置并在 LoadedMedia 时补跳——否则进入详情后「第一次点句子不跳、之后才跳」。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOCAPTIONER_CONFIG_FILE", "/tmp/vc-test-lc-player.toml")

from PyQt5.QtMultimedia import QMediaPlayer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from videocaptioner.ui.components.live_caption.player import AudioPlayerBar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def player(app):
    bar = AudioPlayerBar()
    bar._starts = [0.0, 3.0, 7.5]
    bar._duration_ms = 12_000
    yield bar
    bar.deleteLater()


def test_seek_before_loaded_stashes_pending(player):
    # 未加载完（NoMedia）→ setPosition 被丢弃 → 暂存目标，等加载完成
    assert player._player.mediaStatus() != QMediaPlayer.LoadedMedia
    player.seek_sentence(1)
    assert player._pending_seek_ms == 3000  # 第 2 句起点暂存


def test_loaded_status_replays_pending(player):
    player.seek_sentence(2)
    assert player._pending_seek_ms == 7500
    # 模拟媒体加载完成 → 补跳并清空暂存
    player._on_media_status(QMediaPlayer.LoadedMedia)
    assert player._pending_seek_ms is None


def test_load_clears_stale_pending(player):
    player._pending_seek_ms = 5000
    player.load(None, [0.0, 2.0], 5.0)  # 换记录后旧的待跳必须清掉
    assert player._pending_seek_ms is None
