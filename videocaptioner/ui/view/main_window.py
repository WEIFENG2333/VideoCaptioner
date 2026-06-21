import atexit
import os
import shutil

import psutil
from PyQt5.QtCore import QSize, QThread, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QIcon
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    SplashScreen,
)

from videocaptioner.config import ASSETS_PATH, GITHUB_REPO_URL
from videocaptioner.core.constant import INFOBAR_DURATION_FOREVER
from videocaptioner.ui.common.app_icons import AppFluentIcon, AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import BG_DARK, BG_LIGHT
from videocaptioner.ui.components.app_dialog import ConfirmDialog
from videocaptioner.ui.components.donate_dialog import DonateDialog
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.version_checker_thread import VersionChecker
from videocaptioner.ui.view.batch_process_interface import BatchProcessInterface
from videocaptioner.ui.view.doctor_interface import DoctorInterface
from videocaptioner.ui.view.dubbing_interface import DubbingInterface
from videocaptioner.ui.view.hardsub_interface import HardsubInterface
from videocaptioner.ui.view.home_interface import HomeInterface
from videocaptioner.ui.view.live_caption_interface import LiveCaptionInterface
from videocaptioner.ui.view.llm_logs_interface import LLMLogsInterface
from videocaptioner.ui.view.setting_interface import SettingsDialog
from videocaptioner.ui.view.subtitle_style_interface import SubtitleStyleInterface

LOGO_PATH = ASSETS_PATH / "logo.png"
NAV_EXPAND_WIDTH = 132
NAV_MINIMUM_EXPAND_WIDTH = 760
# 字幕样式页是三栏布局，最窄需约 950px；窗口最小宽要容纳它 + 导航栏，否则右栏被切。
WINDOW_MINIMUM_WIDTH = 1020
TITLEBAR_LEFT_INSET = 46  # 给左侧导航栏让位，标题栏不贴死左上角


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.initWindow()
        # 窗口底色与调色板对齐：否则 qfluent 默认窗口底与页面自绘的
        # palette.bg 形成两层颜色，页面区域看起来像浮在窗口上的色块。
        self.setCustomBackgroundColor(QColor(BG_LIGHT), QColor(BG_DARK))

        # 创建子界面
        self.homeInterface = HomeInterface(self)
        # 设置不再是导航 tab，而是定制大弹窗；SettingInterface 内嵌在弹窗里（长生命周期单例）
        self.settingsDialog = SettingsDialog(self)
        self.settingInterface = self.settingsDialog.settingInterface
        self.subtitleStyleInterface = SubtitleStyleInterface(self)
        self.hardsubInterface = HardsubInterface(self)
        self.dubbingInterface = DubbingInterface(self)
        self.liveCaptionInterface = LiveCaptionInterface(self)
        self.doctorInterface = DoctorInterface(self)
        self.batchProcessInterface = BatchProcessInterface(self)
        self.llmLogsInterface = LLMLogsInterface(self)

        # 硬字幕提取「送入字幕优化」：切到主页字幕优化 tab 并载入提取出的字幕
        self.hardsubInterface.sendToOptimize.connect(self._on_hardsub_to_optimize)

        # 初始化版本检查器
        self.versionChecker = VersionChecker()
        self.versionChecker.newVersionAvailable.connect(self.onNewVersion)
        self.versionChecker.announcementAvailable.connect(self.onAnnouncement)

        self.versionThread = QThread()
        self.versionChecker.moveToThread(self.versionThread)
        self.versionThread.started.connect(self.versionChecker.perform_check)
        self.versionThread.start()

        # 初始化导航界面
        self.initNavigation()
        self.splashScreen.finish()

        # 检查系统依赖
        self._check_ffmpeg()

        # 注册退出处理， 清理进程
        atexit.register(self.stop)

    def initNavigation(self):
        """初始化导航栏"""
        self.navigationInterface.setExpandWidth(NAV_EXPAND_WIDTH)
        self.navigationInterface.setMinimumExpandWidth(NAV_MINIMUM_EXPAND_WIDTH)

        # 添加导航项
        self.addSubInterface(self.homeInterface, FIF.HOME, tr("app.nav.home"))
        self.addSubInterface(self.batchProcessInterface, FIF.VIDEO, tr("app.nav.batch"))
        self.addSubInterface(
            self.subtitleStyleInterface, AppFluentIcon(AppIcon.SUBTITLE), tr("app.nav.subtitle_style")
        )
        self.addSubInterface(self.dubbingInterface, FIF.VOLUME, tr("app.nav.dubbing"))
        self.addSubInterface(
            self.liveCaptionInterface, AppFluentIcon(AppIcon.MICROPHONE), tr("app.nav.live_caption")
        )
        self.addSubInterface(
            self.hardsubInterface, AppFluentIcon(AppIcon.HARDSUB), tr("app.nav.hardsub")
        )
        self.addSubInterface(
            self.llmLogsInterface, AppFluentIcon(AppIcon.HISTORY), tr("app.nav.request_logs")
        )
        self.addSubInterface(
            self.doctorInterface, AppFluentIcon(AppIcon.DIAGNOSTIC), tr("app.nav.doctor")
        )

        self.navigationInterface.addSeparator()

        # 在底部添加自定义小部件
        self.navigationInterface.addItem(
            routeKey="avatar",
            text="GitHub",
            icon=FIF.GITHUB,
            onClick=self.onGithubDialog,
            position=NavigationItemPosition.BOTTOM,
        )
        # 设置：底部导航动作项（点击弹出设置 modal，不作为可选中的 tab）
        self.navigationInterface.addItem(
            routeKey="settings",
            text=tr("app.nav.settings"),
            icon=FIF.SETTING,
            onClick=lambda: self.openSettingsPage("transcribe"),
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )

        # 设置默认界面
        self.switchTo(self.homeInterface)

    def _on_hardsub_to_optimize(self, subtitle_path: str, video_path: str) -> None:
        """硬字幕提取 → 主页字幕优化页（载入提取出的字幕，等用户配置优化/翻译）。"""
        self.switchTo(self.homeInterface)
        self.homeInterface.load_subtitle_for_optimize(subtitle_path, video_path)

    def switchTo(self, interface):
        if interface.windowTitle():
            self.setWindowTitle(interface.windowTitle())
        else:
            self.setWindowTitle(tr("app.window_title"))
        self.stackedWidget.setCurrentWidget(interface, popOut=False)

    def openSettingsPage(self, page_key: str) -> bool:  # noqa: N802
        """弹出设置 modal 并切到指定分类；分类无效返回 False。"""
        return self.settingsDialog.open_at(page_key)

    def initWindow(self):
        """初始化窗口"""
        # 初始尺寸自适应屏幕：默认 1050x760，但绝不超过可用屏幕（留出菜单栏/Dock/标题栏余量）。
        # 否则在小屏笔记本上窗口会被「撑」到比屏幕还高，底部内容（如播放条/按钮）看不全。
        avail = QApplication.desktop().availableGeometry()
        win_w = max(WINDOW_MINIMUM_WIDTH, min(1050, avail.width() - 80))
        win_h = max(560, min(760, avail.height() - 100))
        self.resize(win_w, win_h)
        self.setMinimumWidth(WINDOW_MINIMUM_WIDTH)
        # 防御：任何页面的最小高度都不能把窗口顶出屏幕（否则底部播放条/按钮看不到）。
        self.setMaximumHeight(avail.height() - 40)
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setWindowTitle(tr("app.window_title"))

        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        # 创建启动画面
        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(106, 106))
        self.splashScreen.raise_()

        # 设置窗口位置, 居中（用可用区原点偏移，避开菜单栏/任务栏，多屏也正确）
        self.move(
            avail.x() + (avail.width() - self.width()) // 2,
            avail.y() + (avail.height() - self.height()) // 2,
        )

        self.show()
        QApplication.processEvents()

    def onGithubDialog(self):
        """打开GitHub"""
        w = ConfirmDialog(
            tr("app.github.title"),
            tr("app.github.body"),
            self,
            confirm_text=tr("app.github.open"),
            cancel_text=tr("app.github.support_author"),
            icon=AppIcon.GITHUB,
        )
        # 「支持作者」是动作而非放弃：点它打开捐赠弹窗，Esc/关闭则什么都不做
        open_donate = []
        assert w.cancelButton is not None
        w.cancelButton.clicked.connect(lambda: open_donate.append(True))
        if w.exec():
            QDesktopServices.openUrl(QUrl(GITHUB_REPO_URL))
        elif open_donate:
            DonateDialog(self).exec_()

    def onNewVersion(self, version, update_required, update_info, download_url):
        """新版本提示"""
        if update_required:
            title = tr("app.update.title_required")
            content = tr("app.update.body_required", version=version, update_info=update_info)
        else:
            title = tr("app.update.title")
            content = tr("app.update.body", version=version, update_info=update_info)

        w = ConfirmDialog(
            title,
            content,
            self,
            confirm_text=tr("app.update.now"),
            cancel_text=tr("app.update.later"),
            icon=AppIcon.DOWNLOAD,
        )
        if w.exec() or update_required:
            QDesktopServices.openUrl(QUrl(download_url))

        if update_required:
            self.homeInterface.setEnabled(False)
            self.batchProcessInterface.setEnabled(False)
            InfoBar.error(
                title=tr("app.update.disabled_title"),
                content=tr("app.update.disabled_body"),
                isClosable=False,
                position=InfoBarPosition.BOTTOM,
                duration=-1,
                parent=self,
            )

    def onAnnouncement(self, content):
        """显示公告"""
        w = ConfirmDialog(
            tr("app.announcement.title"),
            content,
            self,
            confirm_text=tr("app.announcement.got_it"),
            cancel_text=None,
            icon=AppIcon.DOCUMENT,
        )
        w.exec()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.titleBar.move(TITLEBAR_LEFT_INSET, 0)
        self.titleBar.resize(self.width() - TITLEBAR_LEFT_INSET, self.titleBar.height())
        if hasattr(self, "splashScreen"):
            self.splashScreen.resize(self.size())

    def closeEvent(self, event):
        # 退出前关停所有子界面：各页 closeEvent/shutdown 会取消正在跑的
        # QThread。Qt 只给顶层窗口派发 closeEvent，子 widget 必须显式
        # close()，否则解释器 teardown 销毁 running QThread 会触发
        # "QThread: Destroyed while thread is still running" abort。
        for interface in (
            self.homeInterface,
            self.batchProcessInterface,
            self.hardsubInterface,
            self.subtitleStyleInterface,
            self.dubbingInterface,
            self.liveCaptionInterface,
            self.doctorInterface,
            self.settingInterface,
        ):
            interface.close()

        # 版本检查线程是事件循环线程，需显式退出再等待
        if self.versionThread.isRunning():
            self.versionThread.quit()
            self.versionThread.wait(2000)

        super().closeEvent(event)
        QApplication.quit()

    def stop(self):
        # 找到 FFmpeg 进程并关闭
        process = psutil.Process(os.getpid())
        for child in process.children(recursive=True):
            child.kill()

    def _check_ffmpeg(self):
        """检查 FFmpeg 是否已安装"""
        if shutil.which("ffmpeg") is None:
            InfoBar.warning(
                tr("app.ffmpeg.missing_title"),
                tr("app.ffmpeg.missing_body"),
                duration=INFOBAR_DURATION_FOREVER,
                position=InfoBarPosition.BOTTOM,
                parent=self,
            )
