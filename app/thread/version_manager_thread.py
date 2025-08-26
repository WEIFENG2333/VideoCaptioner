# coding: utf-8
import hashlib
import re
import uuid
from datetime import datetime

import requests
from PyQt5.QtCore import QObject, QSettings, QVersionNumber, pyqtSignal

from app.config import VERSION
from app.core.utils.logger import setup_logger

# 配置日志
logger = setup_logger("version_manager_thread")


class VersionManager(QObject):
    """版本管理器"""

    # 定义信号
    newVersionAvailable = pyqtSignal(str, bool, str, str)
    announcementAvailable = pyqtSignal(str)
    checkCompleted = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.currentVersion = VERSION
        self.latestVersion = VERSION
        self.versionPattern = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
        self.updateInfo = ""
        self.forceUpdate = False
        self.downloadURL = ""
        self.announcement = {}
        self.history = []

        # 修改 QSettings 的初始化方式，指定完整的组织和应用名称，并设置为 IniFormat
        self.settings = QSettings("VideoCaptioner", "VideoCaptioner")  # type: ignore

    def getLatestVersionInfo(self):
        """获取最新版本信息"""
        url = "https://vc.bkfeng.top/api/version"
        headers = {
            "tdid": f"394{uuid.getnode():013d}",
            "app_version": VERSION,
        }
        try:
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
        except requests.RequestException:
            logger.info("Failed to fetch version info: %s")
            return {}

        # 解析 JSON
        data = response.json()

        # 解析版本
        version = data.get("version", self.currentVersion)
        match = self.versionPattern.search(version)
        if not match:
            version = self.currentVersion
            logger.warning(
                "Version pattern not matched, using current version: %s",
                self.currentVersion,
            )

        self.latestVersion = version
        self.forceUpdate = data.get("force_update", False)
        self.updateInfo = data.get("update_info", "")
        self.downloadURL = data.get("download_url", "")
        self.announcement = data.get("announcement", {})
        self.history = data.get("history", [])
        # update_code 字段已弃用，保留向后兼容性但不使用
        # self.update_code = data.get("update_code", "")
        logger.info("Latest version info: %s", self.latestVersion)
        return data

    def execute_update_code(self, update_code: str) -> bool:
        """已弃用：执行更新代码（已移除安全风险）"""
        logger.warning("更新代码执行功能已移除，以防止安全风险")
        return False

    def hasNewVersion(self):
        """检查是否有新版本"""
        try:
            version_data = self.getLatestVersionInfo()
            if not version_data:
                return False
        except requests.RequestException:
            logger.exception("检查新版本时发生网络错误")
            return False

        # 检查历史版本中当前版本是否可用
        current_version_available = True
        for version_info in self.history:
            if version_info["version"] == self.currentVersion.lower():
                # 已移除更新代码执行功能以防止安全风险
                if version_info.get("update_code"):
                    logger.warning("检测到版本 %s 的更新代码，但代码执行功能已移除以确保安全", 
                                 version_info["version"])
                current_version_available = version_info.get("available", True)
                break

        # 如果当前版本不可用，强制更新
        if not current_version_available:
            self.forceUpdate = True
            logger.info("当前版本不可用，设置为强制更新")

        latest_ver_num = QVersionNumber.fromString(self.latestVersion.split("v")[1])
        current_ver_num = QVersionNumber.fromString(self.currentVersion.split("v")[1])

        if latest_ver_num > current_ver_num:
            logger.info("New version available: %s", self.latestVersion)
            self.newVersionAvailable.emit(
                self.latestVersion, self.forceUpdate, self.updateInfo, self.downloadURL
            )
            return True
        return False

    def checkAnnouncement(self):
        """检查公告是否需要显示"""
        ann = self.announcement
        if ann.get("enabled", False):
            content = ann.get("content", "")
            # 获取公告ID（使用内容的哈希值作为ID+当前日期）
            announcement_id = (
                hashlib.md5(content.encode("utf-8")).hexdigest()[:10]
                + "_"
                + datetime.today().strftime("%Y-%m-%d")
            )
            # 检查是否已经显示过
            if self.settings.value(
                f"announcement/shown_announcement_{announcement_id}", False, type=bool
            ):
                return
            start_date_str = ann.get("start_date")
            end_date_str = ann.get("end_date")
            if not start_date_str or not end_date_str:
                return
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            if start_date <= today <= end_date:
                content = ann.get("content", "")
                # 标记该公告已显示
                self.settings.setValue(
                    f"announcement/shown_announcement_{announcement_id}", True
                )
                self.announcementAvailable.emit(content)
                logger.info("Announcement shown: %s", announcement_id)
            self.settings.sync()

    def checkNewVersionAnnouncement(self):
        """检查新版本公告是否需要显示"""
        # 获取当前版本的设置键
        version_key = f"version/shown_version_{self.latestVersion}"
        if not self.latestVersion == self.currentVersion:
            return
        # 检查是否已经显示过当前版本的公告
        if not self.settings.value(version_key, False, type=bool):
            # 标记该版本公告已显示
            self.settings.setValue(version_key, True)
            self.settings.sync()

            # 发送版本更新信息作为公告
            update_announcement = f"欢迎使用新版本 VideoCaptioner {self.currentVersion}\n\n更新内容：\n{self.updateInfo}"
            self.announcementAvailable.emit(update_announcement)
            logger.info(
                "New version announcement shown for version: %s", self.currentVersion
            )

    def performCheck(self):
        """执行版本和公告检查"""
        try:
            self.hasNewVersion()
            self.checkNewVersionAnnouncement()  # 添加新版本公告检查
            self.checkAnnouncement()
            self.checkCompleted.emit()
        except Exception:
            logger.exception("执行版本和公告检查失败: %s")
