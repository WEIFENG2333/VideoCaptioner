import atexit
import os
import shutil
from pathlib import Path

import psutil
from PyQt5.QtCore import QSize, QUrl
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

from videocaptioner.config import ASSETS_PATH, CACHE_PATH, GITHUB_REPO_URL
from videocaptioner.core.constant import INFOBAR_DURATION_FOREVER
from videocaptioner.core.update import apply_update, can_self_update
from videocaptioner.core.utils.cache import get_version_state_cache
from videocaptioner.ui.common.app_icons import AppFluentIcon, AppIcon
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.theme_tokens import BG_DARK, BG_LIGHT
from videocaptioner.ui.components.app_dialog import ConfirmDialog
from videocaptioner.ui.components.donate_dialog import DonateDialog
from videocaptioner.ui.components.update_banner import UpdateBanner
from videocaptioner.ui.i18n import tr
from videocaptioner.ui.thread.update_thread import UpdateCheckThread
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

        # 设置页「检查更新」按钮 → 主动走同一套更新流程
        self.settingInterface.checkUpdateRequested.connect(self._on_manual_update_check)

        # 启动时后台检查更新；有新版时弹出更新提示条（下载 + 重启安装一键完成）
        self.updateBanner = None
        self.updateCheckThread = None
        self._check_updates()

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

    def _check_updates(self, *, manual=False):
        """启动后台检查更新。manual=True 时（设置页按钮触发）额外提示「已是最新/检查失败」。"""
        if self.updateCheckThread is not None and self.updateCheckThread.isRunning():
            return
        self.updateCheckThread = UpdateCheckThread(self)
        self.updateCheckThread.updateAvailable.connect(self._on_update_available)
        self.updateCheckThread.announcementAvailable.connect(self._on_announcement)
        if manual:
            self.updateCheckThread.upToDate.connect(self._on_up_to_date)
            self.updateCheckThread.checkFailed.connect(self._on_check_failed)
        self.updateCheckThread.start()

    def _on_announcement(self, ann):
        """展示线上公告（按 id 去重，只弹一次）。公告与是否有新版无关。"""
        cache = get_version_state_cache()
        key = f"announcement_shown_{ann.id}"
        if cache.get(key, default=False):
            return
        cache.set(key, True)
        ConfirmDialog(
            ann.title or tr("app.announcement.title"),
            ann.content,
            self,
            confirm_text=tr("app.announcement.got_it"),
            cancel_text=None,
            icon=AppIcon.DOCUMENT,
        ).exec()

    def _on_manual_update_check(self):
        if self.updateBanner is not None:  # 已有提示条在展示，直接复用
            return
        if self.updateCheckThread is not None and self.updateCheckThread.isRunning():
            # 启动检查还没跑完就点了「检查更新」：给反馈，别让按钮像没反应（死点击）
            InfoBar.info(
                title=tr("app.update.checking"),
                content="",
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return
        self._check_updates(manual=True)

    def _on_update_available(self, info):
        """有新版：展示更新提示条（可用→下载中→重启安装）。强制更新时禁用主流程页。"""
        if self.updateBanner is not None:  # 防重复（手动检查叠加自动检查）
            return
        self.updateBanner = UpdateBanner(self, info, CACHE_PATH / "update", self._install_update)
        self.updateBanner.show()
        # 仅当能在应用内自更新时才禁用主流程页逼用户更新；不能自更新（开发态/安装目录不可写）
        # 时禁用会把用户卡死在只能「前往下载」的死胡同，故保持页面可用、提示条可关。
        if info.mandatory and can_self_update():
            self.homeInterface.setEnabled(False)
            self.batchProcessInterface.setEnabled(False)

    def _on_up_to_date(self):
        InfoBar.success(
            title=tr("app.update.up_to_date"),
            content="",
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _on_check_failed(self, message):
        InfoBar.warning(
            title=tr("app.update.check_failed"),
            content=message,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self,
        )

    def _install_update(self, zip_path):
        """下载完成、用户点「重启并安装」：启动 helper 替换并退出本进程。"""
        try:
            apply_update(Path(zip_path))
        except Exception as exc:  # noqa: BLE001 — 安装失败提示用户手动更新
            InfoBar.error(
                title=tr("app.update.install_failed"),
                content=str(exc),
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self,
            )
            return
        QApplication.quit()

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

        # 停掉更新检查/下载线程，避免退出时销毁运行中的 QThread 触发 abort
        if self.updateBanner is not None:
            self.updateBanner.stop()
        if self.updateCheckThread is not None and self.updateCheckThread.isRunning():
            self.updateCheckThread.wait(2000)

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
