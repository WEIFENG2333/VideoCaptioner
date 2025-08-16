# coding:utf-8
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import vlc  # type: ignore
from PyQt5.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

# from qfluentwidgets.multimedia.media_player import MediaPlayer, MediaPlayerBase
from qfluentwidgets.common.icon import FluentIcon
from qfluentwidgets.common.style_sheet import FluentStyleSheet
from qfluentwidgets.components.widgets.label import CaptionLabel
from qfluentwidgets.multimedia.media_play_bar import (
    MediaPlayBarBase,
    MediaPlayBarButton,
)

from app.common.signal_bus import signalBus
from app.config import RESOURCE_PATH


class MediaStatus(Enum):
    NoMedia = 0
    LoadingMedia = 1
    LoadedMedia = 2
    BufferingMedia = 3
    BufferedMedia = 4
    EndOfMedia = 5
    InvalidMedia = 6
    UnknownMediaStatus = 7


class PlaybackState(Enum):
    StoppedState = 0
    PlayingState = 1
    PausedState = 2


class MediaPlayerBase(QObject):
    """Media player base class"""

    mediaStatusChanged = pyqtSignal(MediaStatus)
    playbackRateChanged = pyqtSignal(float)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    sourceChanged = pyqtSignal(QUrl)
    volumeChanged = pyqtSignal(int)
    mutedChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent=parent)

    def isPlaying(self):
        """Whether the media is playing"""
        raise NotImplementedError

    def mediaStatus(self) -> MediaStatus:
        """Return the status of the current media stream"""
        raise NotImplementedError

    def playbackState(self) -> PlaybackState:
        """Return the playback status of the current media stream"""
        raise NotImplementedError

    def duration(self):
        """Returns the duration of the current media in ms"""
        raise NotImplementedError

    def position(self):
        """Returns the current position inside the media being played back in ms"""
        raise NotImplementedError

    def volume(self):
        """Return the volume of player"""
        raise NotImplementedError

    def source(self) -> QUrl:
        """Return the active media source being used"""
        raise NotImplementedError

    def pause(self):
        """Pause playing the current source"""
        raise NotImplementedError

    def play(self):
        """Start or resume playing the current source"""
        raise NotImplementedError

    def stop(self):
        """Stop playing, and reset the play position to the beginning"""
        raise NotImplementedError

    def playbackRate(self) -> float:
        """Return the playback rate of the current media"""
        raise NotImplementedError

    def setPosition(self, position: int):
        """Sets the position of media in ms"""
        raise NotImplementedError

    def setSource(self, media: QUrl):
        """Sets the current source"""
        raise NotImplementedError

    def setPlaybackRate(self, rate: float):
        """Sets the playback rate of player"""
        raise NotImplementedError

    def setVolume(self, volume: int):
        """Sets the volume of player"""
        raise NotImplementedError

    def setMuted(self, isMuted: bool):
        raise NotImplementedError

    def videoOutput(self) -> QObject:
        """Return the video output to be used by the media player"""
        raise NotImplementedError

    def setVideoOutput(self, output: QObject) -> None:
        """Sets the video output to be used by the media player"""
        raise NotImplementedError


class MediaPlayer(MediaPlayerBase):
    def __init__(self, parent=None):
        # 确保在主线程中初始化
        if parent:
            super().__init__(parent)
        else:
            super().__init__()

        # 修改 VLC 参数以减少警告
        vlc_args = [
            "--no-xlib",
            "--quiet",
        ]

        # 在主线程中创建 VLC 实例
        self.moveToThread(QApplication.instance().thread())
        self.instance = vlc.Instance(vlc_args)
        self._player = self.instance.media_player_new()
        self._media = None
        self._source = None
        self._playback_rate = 1.0

        # 创建定时器用于更新状态
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(100)  # 100ms更新一次
        self._update_timer.timeout.connect(self._on_timer_update)
        self._update_timer.start()

        # 保存上一次的状态，用于检测变化
        self._last_position = 0
        self._last_duration = 0
        self._last_volume = 100

    def _on_timer_update(self):
        """定时更新状态并发送信号"""
        if self._player:
            # 更新位置
            position = self._player.get_time()
            if position != self._last_position:
                self._last_position = position
                self.positionChanged.emit(position)

            # 更新时长
            duration = self._player.get_length()
            if duration != self._last_duration:
                self._last_duration = duration
                self.durationChanged.emit(duration)

            # 更新音量
            volume = self._player.audio_get_volume()
            if volume != self._last_volume:
                self._last_volume = volume
                self.volumeChanged.emit(volume)

    def isPlaying(self):
        return bool(self._player and self._player.is_playing())

    def mediaStatus(self) -> MediaStatus:
        if not self._player:
            return MediaStatus.NoMedia

        state = self._player.get_state()
        if state == vlc.State.NothingSpecial:
            return MediaStatus.NoMedia
        elif state == vlc.State.Opening:
            return MediaStatus.LoadingMedia
        elif state == vlc.State.Playing:
            return MediaStatus.BufferedMedia
        elif state == vlc.State.Paused:
            return MediaStatus.BufferedMedia
        elif state == vlc.State.Stopped:
            return MediaStatus.LoadedMedia
        elif state == vlc.State.Ended:
            return MediaStatus.EndOfMedia
        elif state == vlc.State.Error:
            return MediaStatus.InvalidMedia
        return MediaStatus.UnknownMediaStatus

    def playbackState(self) -> PlaybackState:
        if not self._player:
            return PlaybackState.StoppedState

        if self._player.is_playing():
            return PlaybackState.PlayingState
        elif self._player.get_state() == vlc.State.Paused:
            return PlaybackState.PausedState
        return PlaybackState.StoppedState

    def duration(self):
        return self._player.get_length() if self._player else 0

    def position(self):
        return self._player.get_time() if self._player else 0

    def volume(self):
        return self._player.audio_get_volume() if self._player else 0

    def source(self) -> QUrl:
        return self._source

    def get_subtitle(self):
        """获取当前使用的字幕文件路径

        Returns:
            str: 当前字幕文件路径，如果没有字幕则返回 None
        """
        if not self._player:
            return None

        try:
            # 获取当前字幕轨道ID
            current_spu = self._player.video_get_spu()
            if current_spu <= 0:  # 0 表示禁用字幕，-1 表示错误
                return None

            # 获取字幕轨道描述信息
            spu_description = self._player.video_get_spu_description()
            if not spu_description:
                return None

            # 遍历查找当前使用的字幕轨道
            for spu in spu_description:
                if spu[0] == current_spu:
                    # 返回字幕文件路径
                    return spu[1].decode("utf-8")

            return None
        except Exception:
            return None

    def pause(self):
        self._player.pause()

    def play(self):
        self._player.play()

    def stop(self):
        self._player.stop()

    def playbackRate(self) -> float:
        return self._playback_rate

    def setPosition(self, position: int):
        if self._player:
            self._player.set_time(position)
            self.positionChanged.emit(position)

    def setSource(self, media: QUrl):
        """设置媒体源时重置状态"""
        path = media.toLocalFile() or media.toString()
        self._media = self.instance.media_new(path)
        self._player.set_media(self._media)
        self._source = media
        self.sourceChanged.emit(media)
        self.mediaStatusChanged.emit(self.mediaStatus())

    def setPlaybackRate(self, rate: float):
        if self._player:
            self._player.set_rate(rate)
            self._playback_rate = rate
            self.playbackRateChanged.emit(rate)

    def setVolume(self, volume: int):
        if self._player:
            self._player.audio_set_volume(volume)
            self.volumeChanged.emit(volume)

    def setMuted(self, isMuted: bool):
        if self._player:
            self._player.audio_set_mute(isMuted)
            self.mutedChanged.emit(isMuted)

    def videoOutput(self) -> Optional[QObject]:
        return None  # VLC不需要这个

    def setVideoOutput(self, output: QObject) -> None:
        if isinstance(output, QWidget) and hasattr(output, "winId"):  # type: ignore
            self._player.set_hwnd(output.winId())

    def hasMedia(self):
        """检查是否有媒体文件加载"""
        return bool(self._media and self._player)

    def playSegment(self, start_time: int, end_time: int):
        """播放指定时间段的视频片段

        Args:
            start_time: 开始时间（毫秒）
            end_time: 结束时间（毫秒）
        """
        if not self._player or not self.hasMedia():
            return

        # 确保时间范围有效
        if start_time < 0 or end_time > self.duration() or start_time >= end_time:
            return

        # 创建事件管理器
        event_manager = self._player.event_manager()

        def on_time_changed(event):
            # 当播放位置到达结束时间时停止播放
            if self.position() >= end_time:
                self.pause()
                # 移除事件监听器
                event_manager.event_detach(vlc.EventType.MediaPlayerTimeChanged)

        # 注册时间变化事件
        event_manager.event_attach(
            vlc.EventType.MediaPlayerTimeChanged, on_time_changed
        )

        # 设置开始位置并播放
        self.setPosition(start_time)
        self.play()

    def add_subtitle(self, subtitle_file: str) -> bool:
        """添加字幕文件

        Args:
            subtitle_file: 字幕文件的路径

        Returns:
            bool: 是否成功添加字幕
        """
        if not self._player or not self.hasMedia():
            return False

        try:
            # 将路径转换为 URI 格式

            subtitle_uri = Path(subtitle_file).as_uri()

            # 添加字幕轨道
            result = self._player.add_slave(
                vlc.MediaSlaveType.subtitle, subtitle_uri, True
            )

            # 获取字幕轨道信息 (unused but potentially useful for debugging)
            # spu_description = self._player.video_get_spu_description()

            return result == 0
        except Exception:
            return False

    def get_subtitle_tracks(self) -> list:
        """获取所有可用的字幕轨道"""
        if not self._player:
            return []

        tracks = []
        spu_count = self._player.video_get_spu_count()
        for i in range(spu_count):
            track_info = self._player.video_get_spu_description()[i]
            tracks.append(track_info)
        return tracks

    def set_subtitle_track(self, track_id: int):
        """设置当前使用的字幕轨道

        Args:
            track_id: 字幕轨道ID，-1 表示禁用字幕
        """
        if self._player:
            self._player.video_set_spu(track_id)


class StandardMediaPlayBar(MediaPlayBarBase):
    """Standard media play bar"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.timeLayout = QHBoxLayout()
        self.buttonLayout = QHBoxLayout()
        self.leftButtonContainer = QWidget()
        self.centerButtonContainer = QWidget()
        self.rightButtonContainer = QWidget()
        self.leftButtonLayout = QHBoxLayout(self.leftButtonContainer)
        self.centerButtonLayout = QHBoxLayout(self.centerButtonContainer)
        self.rightButtonLayout = QHBoxLayout(self.rightButtonContainer)

        self.skipBackButton = MediaPlayBarButton(FluentIcon.SKIP_BACK, self)
        self.skipForwardButton = MediaPlayBarButton(FluentIcon.SKIP_FORWARD, self)

        self.currentTimeLabel = CaptionLabel("0:00:00", self)
        self.remainTimeLabel = CaptionLabel("0:00:00", self)

        self.__initWidgets()

    def __initWidgets(self):
        self.setFixedHeight(102)
        self.vBoxLayout.setSpacing(6)
        self.vBoxLayout.setContentsMargins(5, 9, 5, 9)
        self.vBoxLayout.addWidget(self.progressSlider, 1, Qt.AlignTop)  # type: ignore

        self.vBoxLayout.addLayout(self.timeLayout)
        self.timeLayout.setContentsMargins(10, 0, 10, 0)
        self.timeLayout.addWidget(self.currentTimeLabel, 0, Qt.AlignLeft)  # type: ignore
        self.timeLayout.addWidget(self.remainTimeLabel, 0, Qt.AlignRight)  # type: ignore

        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.buttonLayout, 1)
        self.buttonLayout.setContentsMargins(0, 0, 0, 0)
        self.leftButtonLayout.setContentsMargins(4, 0, 0, 0)
        self.centerButtonLayout.setContentsMargins(0, 0, 0, 0)
        self.rightButtonLayout.setContentsMargins(0, 0, 4, 0)

        self.leftButtonLayout.addWidget(self.volumeButton, 0, Qt.AlignLeft)  # type: ignore
        self.centerButtonLayout.addWidget(self.skipBackButton)
        self.centerButtonLayout.addWidget(self.playButton)
        self.centerButtonLayout.addWidget(self.skipForwardButton)

        self.buttonLayout.addWidget(self.leftButtonContainer, 0, Qt.AlignLeft)  # type: ignore
        self.buttonLayout.addWidget(self.centerButtonContainer, 0, Qt.AlignHCenter)  # type: ignore
        self.buttonLayout.addWidget(self.rightButtonContainer, 0, Qt.AlignRight)  # type: ignore

        self.skipBackButton.clicked.connect(lambda: self.skipBack(5000))
        self.skipForwardButton.clicked.connect(lambda: self.skipForward(5000))

    def skipBack(self, ms: int):
        """Back up for specified milliseconds"""
        self.player.setPosition(self.player.position() - ms)

    def skipForward(self, ms: int):
        """Fast forward specified milliseconds"""
        self.player.setPosition(self.player.position() + ms)

    def _onPositionChanged(self, position: int):
        super()._onPositionChanged(position)
        self.currentTimeLabel.setText(self._formatTime(position))
        self.remainTimeLabel.setText(
            self._formatTime(self.player.duration() - position)
        )

    def _formatTime(self, time: int):
        time = int(time / 1000)
        s = time % 60
        m = int(time / 60)
        h = int(time / 3600)
        return f"{h}:{m:02}:{s:02}"

    def closeEvent(self, event):
        self.release()
        super().closeEvent(event)


class MyVideoWidget(QWidget):
    """Video widget"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置初始窗口大小
        self.resize(800, 600)
        self.setWindowTitle("VideoCaptioner")
        self.setWindowIcon(QIcon(str(RESOURCE_PATH / "assets" / "logo.png")))

        # 创建一个专门用于视频输出的 widget
        self.videoWidget = QWidget(self)
        self.videoWidget.setStyleSheet("background-color: rgb(24, 24, 24);")

        # 添加提示标签
        self.tipLabel = CaptionLabel("请拖入视频文件", self.videoWidget)
        self.tipLabel.setStyleSheet(
            """
            color: rgba(255, 255, 255, 0.5);
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
        """
        )

        # 创建布局使标签居中
        tipLayout = QVBoxLayout(self.videoWidget)
        tipLayout.addWidget(self.tipLabel, 0, Qt.AlignCenter)  # type: ignore

        # 创建播放控制栏
        self.playBar = StandardMediaPlayBar(self)
        self.playBar.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore

        # 设置字幕文件
        self.subtitle_file = None

        # 创建垂直布局
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.videoWidget, 1)
        self.vBoxLayout.addWidget(self.playBar, 0)

        # 创建播放器并传入优化参数
        self.vlc_player = MediaPlayer(self)

        # 设置新的播放器
        self.playBar.setMediaPlayer(self.vlc_player)  # type: ignore
        self.playBar.setVolume(80)
        self.vlc_player.setVideoOutput(self.videoWidget)
        FluentStyleSheet.MEDIA_PLAYER.apply(self)

        # 设置焦点和事件过滤
        self.setFocusPolicy(Qt.StrongFocus)  # type: ignore
        self.videoWidget.setFocusPolicy(Qt.StrongFocus)  # type: ignore

        # 安装事件过滤器
        self.videoWidget.installEventFilter(self)
        self.playBar.installEventFilter(self)

        FluentStyleSheet.MEDIA_PLAYER.apply(self)
        self.setAcceptDrops(True)

        # 连接 SignalBus 信号
        self._connectSignals()

    def _connectSignals(self):
        """连接 SignalBus 的信号"""
        # 视频控制信号
        signalBus.video_play.connect(self.play)
        signalBus.video_pause.connect(self.pause)
        signalBus.video_stop.connect(self.stop)
        signalBus.video_source_changed.connect(self.setVideo)
        signalBus.video_segment_play.connect(self.playSegment)
        signalBus.video_subtitle_added.connect(self.addSubtitle)

    def addSubtitle(self, subtitle_file: str):
        """添加字幕文件的内部方法"""
        self.subtitle_file = subtitle_file
        self.vlc_player.add_subtitle(subtitle_file)

    def setVideo(self, url: QUrl):
        """设置视频源

        Args:
            url: 视频文件的 QUrl
        """
        self.setWindowTitle(url.fileName())
        self.vlc_player.setSource(url)
        if self.subtitle_file:
            self.vlc_player.add_subtitle(self.subtitle_file)
        # 隐藏提示标签
        self.tipLabel.hide()

    def play(self):
        """播放视频"""
        self.playBar.play()

    def pause(self):
        """暂停视频"""
        self.playBar.pause()

    def stop(self):
        """停止视频"""
        self.playBar.stop()

    def playSegment(self, start_time: int, end_time: int):
        """播放指定时间段的视频

        Args:
            start_time: 开始时间(毫秒)
            end_time: 结束时间(毫秒)
        """
        self.vlc_player.playSegment(start_time, end_time)

    def hideEvent(self, e):
        self.stop()
        e.accept()

    def wheelEvent(self, e):
        return

    def togglePlayState(self):
        """toggle play state"""
        if self.vlc_player.isPlaying():
            self.pause()
        else:
            self.play()

    @property
    def player(self):
        return self.playBar.player

    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key_Space:  # type: ignore
            self.playBar.togglePlayState()
        elif event.key() == Qt.Key_Left:  # type: ignore
            self.playBar.skipBack(3000)
        elif event.key() == Qt.Key_Right:  # type: ignore
            self.playBar.skipForward(3000)
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        """处理拖入事件"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            # 检查是否为视频文件或字幕文件
            if any(
                url.toLocalFile()
                .lower()
                .endswith(
                    (".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".srt", ".ass")
                )
                for url in urls
            ):
                event.acceptProposedAction()

    def dropEvent(self, event):
        """处理放下事件"""
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile().lower()
            if file_path.endswith((".srt", ".ass")):
                # 处理字幕文件
                self.vlc_player.add_subtitle(url.toLocalFile())
            elif file_path.endswith((".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv")):
                # 处理视频文件
                self.setVideo(url)
                self.play()
                break  # 只处理第一个视频文件

    def eventFilter(self, obj, event):
        """事件过滤器，用于捕获所有子部件的按键事件"""
        if event.type() == event.KeyPress:
            if event.key() in (Qt.Key_Left, Qt.Key_Right):  # type: ignore
                self.keyPressEvent(event)
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """窗口显示时设置焦点"""
        super().showEvent(event)
        self.setFocus()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MyVideoWidget()
    # 设置视频源
    video_path = r"C:\Users\weifeng\Videos\【卡卡】N进制演示器.mp4"
    window.setVideo(QUrl.fromLocalFile(video_path))

    # 确保窗口显示在屏幕中央
    window.show()
    window.activateWindow()
    window.raise_()

    # 开始播放视频
    # window.play()
    sys.exit(app.exec_())
