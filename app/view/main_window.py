import atexit
import os
import shutil
import sys

import psutil
from PyQt5.QtCore import QSize, QThread, QUrl, QRect, Qt
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import QApplication, QLabel, QHBoxLayout
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    FluentWindow,
    FluentStyleSheet,
    FluentTitleBar,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    NavigationItemPosition,
    SplashScreen,
)

from app.common.config import cfg
from app.components.DonateDialog import DonateDialog
from app.config import ASSETS_PATH, GITHUB_REPO_URL
from app.core.constant import INFOBAR_DURATION_FOREVER
from app.thread.version_checker_thread import VersionChecker
from app.view.batch_process_interface import BatchProcessInterface
from app.view.home_interface import HomeInterface
from app.view.llm_logs_interface import LLMLogsInterface
from app.view.setting_interface import SettingInterface
from app.view.subtitle_style_interface import SubtitleStyleInterface

LOGO_PATH = ASSETS_PATH / "logo.png"

MAC_SYSTEM_BUTTON_WIDTH = 85
MAC_TITLE_LEFT_MARGIN = 45

class MacTitleBar(FluentTitleBar):
    """macOS style title bar with buttons on the left"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(48)

        self.hBoxLayout.removeWidget(self.minBtn)
        self.hBoxLayout.removeWidget(self.maxBtn)
        self.hBoxLayout.removeWidget(self.closeBtn)

        self.hBoxLayout.setContentsMargins(MAC_TITLE_LEFT_MARGIN, 0, 0, 0)

        self.vBoxLayout = QHBoxLayout()
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self.vBoxLayout.addWidget(self.minBtn)
        self.vBoxLayout.addWidget(self.maxBtn)
        self.vBoxLayout.addWidget(self.closeBtn)

        FluentStyleSheet.FLUENT_WINDOW.apply(self)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()

        if sys.platform == "darwin":
            self.setTitleBar(MacTitleBar(self))

        self.initWindow()

        # 创建子界面
        self.homeInterface = HomeInterface(self)
        self.settingInterface = SettingInterface(self)
        self.subtitleStyleInterface = SubtitleStyleInterface(self)
        self.batchProcessInterface = BatchProcessInterface(self)
        self.llmLogsInterface = LLMLogsInterface(self)

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
        # 添加导航项
        self.addSubInterface(self.homeInterface, FIF.HOME, self.tr("主页"))
        self.addSubInterface(self.batchProcessInterface, FIF.VIDEO, self.tr("批量处理"))
        self.addSubInterface(self.subtitleStyleInterface, FIF.FONT, self.tr("字幕样式"))
        self.addSubInterface(self.llmLogsInterface, FIF.HISTORY, self.tr("请求日志"))

        self.navigationInterface.addSeparator()

        # 在底部添加自定义小部件
        self.navigationInterface.addItem(
            routeKey="avatar",
            text="GitHub",
            icon=FIF.GITHUB,
            onClick=self.onGithubDialog,
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settingInterface,
            FIF.SETTING,
            self.tr("Settings"),
            NavigationItemPosition.BOTTOM,
        )

        if sys.platform == "darwin":
            # 隐藏返回按钮并避开三色灯
            self.navigationInterface.setReturnButtonVisible(False)
            self.navigationInterface.panel.topLayout.setContentsMargins(4, 40, 4, 0)

        # 设置默认界面
        self.switchTo(self.homeInterface)

    def switchTo(self, interface):
        if interface.windowTitle():
            self.setWindowTitle(interface.windowTitle())
        else:
            self.setWindowTitle(self.tr("卡卡字幕助手 -- VideoCaptioner"))
        self.stackedWidget.setCurrentWidget(interface, popOut=False)

    def initWindow(self):
        """初始化窗口"""
        self.resize(1050, 800)
        self.setMinimumWidth(700)
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setWindowTitle(self.tr("卡卡字幕助手 -- VideoCaptioner"))

        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        # 创建启动画面
        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(106, 106))
        self.splashScreen.raise_()

        # 设置窗口位置, 居中
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

        self.show()
        QApplication.processEvents()

    def onGithubDialog(self):
        """打开GitHub"""
        w = MessageBox(
            self.tr("GitHub信息"),
            self.tr(
                "VideoCaptioner 由本人在课余时间独立开发完成，目前托管在GitHub上，欢迎Star和Fork。项目诚然还有很多地方需要完善，遇到软件的问题或者BUG欢迎提交Issue。\n\n https://github.com/WEIFENG2333/VideoCaptioner"
            ),
            self,
        )
        w.yesButton.setText(self.tr("打开 GitHub"))
        w.cancelButton.setText(self.tr("支持作者"))
        if w.exec():
            QDesktopServices.openUrl(QUrl(GITHUB_REPO_URL))
        else:
            # 点击"支持作者"按钮时打开捐赠对话框
            donate_dialog = DonateDialog(self)
            donate_dialog.exec_()

    def onNewVersion(self, version, update_required, update_info, download_url):
        """新版本提示"""
        if update_required:
            title = "发现新版本, 需要更新"
            content = f"发现新版本 {version}\n\n" f"更新内容：\n{update_info}"
        else:
            title = "发现新版本"
            content = f"发现新版本 {version}\n\n{update_info}"

        w = MessageBox(title, content, self)
        w.yesButton.setText("立即更新")
        w.cancelButton.setText("稍后再说")

        if w.exec() or update_required:
            QDesktopServices.openUrl(QUrl(download_url))

        if update_required:
            self.homeInterface.setEnabled(False)
            self.batchProcessInterface.setEnabled(False)
            InfoBar.error(
                title="需要更新",
                content=self.tr("当前版本部分功能已被禁用。请尽快更新。"),
                isClosable=False,
                position=InfoBarPosition.BOTTOM,
                duration=-1,
                parent=self,
            )

    def onAnnouncement(self, content):
        """显示公告"""
        w = MessageBox("公告", content, self)
        w.yesButton.setText("我知道了")
        w.cancelButton.hide()
        w.exec()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "splashScreen"):
            self.splashScreen.resize(self.size())

    def systemTitleBarRect(self, size: QSize) -> QRect:
        """Returns the system title bar rect for macOS"""
        if sys.platform == "darwin":
            return QRect(0, 0 if self.isFullScreen() else 9, MAC_SYSTEM_BUTTON_WIDTH, size.height())
        return super().systemTitleBarRect(size)

    def closeEvent(self, event):
        # 关闭所有子界面
        # self.homeInterface.close()
        # self.batchProcessInterface.close()
        # self.subtitleStyleInterface.close()
        # self.settingInterface.close()
        super().closeEvent(event)

        # 强制退出应用程序
        QApplication.quit()

        # 确保所有线程和进程都被终止 要是一些错误退出就不会处理了。
        # import os
        # os._exit(0)

    def stop(self):
        # 找到 FFmpeg 进程并关闭
        process = psutil.Process(os.getpid())
        for child in process.children(recursive=True):
            child.kill()

    def _check_ffmpeg(self):
        """检查 FFmpeg 是否已安装"""
        if shutil.which("ffmpeg") is None:
            InfoBar.warning(
                self.tr("FFmpeg 未安装"),
                self.tr("软件处理音视频文件时需要 FFmpeg，请先安装"),
                duration=INFOBAR_DURATION_FOREVER,
                position=InfoBarPosition.BOTTOM,
                parent=self,
            )
