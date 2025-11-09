# coding: utf-8
import hashlib
from datetime import datetime

import requests
from PyQt5.QtCore import QObject, QVersionNumber, pyqtSignal

from app.config import VERSION
from app.core.utils.cache import get_version_state_cache
from app.core.utils.logger import setup_logger

logger = setup_logger("version_checker")


class VersionChecker(QObject):
    """Version checker"""

    newVersionAvailable = pyqtSignal(str, bool, str, str)
    announcementAvailable = pyqtSignal(str)
    checkCompleted = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_version = VERSION
        self.latest_version = VERSION
        self.update_info = ""
        self.update_required = False
        self.download_url = ""
        self.announcement = {}

        self.cache = get_version_state_cache()

    def get_latest_version_info(self) -> dict:
        """Get latest version information"""
        url = "https://vc.bkfeng.top/api/version"
        headers = {"app_version": VERSION}

        try:
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()
            data = response.json()
            # data = {
            #     "latest_version": "v1.4.0",
            #     "update_required": True,
            #     "update_info": "更新内容",
            #     "download_url": "https://github.com/WEIFENG2333/VideoCaptioner/releases/latest",
            #     "announcement": {
            #         "enabled": True,
            #         "content": "公告内容211",
            #         "start_date": "2025-01-01",
            #         "end_date": "2025-12-30",
            #     },
            # }

            self.latest_version = data.get("latest_version", self.current_version)
            self.update_required = data.get("update_required", False)
            self.update_info = data.get("update_info", "")
            self.download_url = data.get("download_url", "")
            self.announcement = data.get("announcement", {})

            logger.info("Successfully fetched version info: %s", self.latest_version)
            return data

        except requests.RequestException:
            return {}

    def has_new_version(self) -> bool:
        """Check if new version is available"""
        try:
            latest_ver = self.latest_version.lstrip("v")
            current_ver = self.current_version.lstrip("v")

            latest_ver_num = QVersionNumber.fromString(latest_ver)
            current_ver_num = QVersionNumber.fromString(current_ver)

            if latest_ver_num > current_ver_num:
                logger.info(
                    "New version found: %s (current: %s)",
                    self.latest_version,
                    self.current_version,
                )
                self.newVersionAvailable.emit(
                    self.latest_version,
                    self.update_required,
                    self.update_info,
                    self.download_url,
                )
                return True

        except Exception as e:
            logger.error("Version comparison failed: %s", str(e))

        return False

    def check_announcement(self) -> None:
        """Check and show announcement"""
        ann = self.announcement
        if not ann.get("enabled", False):
            return

        content = ann.get("content", "")
        if not content:
            return

        announcement_id = (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            + "_"
            + datetime.today().strftime("%Y-%m-%d")
        )

        settings_key = f"announcement/shown_{announcement_id}"
        if self.cache.get(settings_key, default=False):
            return

        start_date_str = ann.get("start_date")
        end_date_str = ann.get("end_date")
        if not start_date_str or not end_date_str:
            return

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            today = datetime.today().date()

            if start_date <= today <= end_date:
                self.cache.set(settings_key, True, expire=30 * 60 * 24)
                self.announcementAvailable.emit(content)

        except ValueError as e:
            logger.error("Announcement date format error: %s", str(e))

    def check_new_version_announcement(self) -> None:
        """Check new version announcement"""
        if self.latest_version != self.current_version:
            return

        version_key = f"version/shown_{self.latest_version}"

        if not self.cache.get(version_key, default=False):
            self.cache.set(version_key, True)

            update_announcement = (
                f"Welcome to VideoCaptioner {self.current_version}\n\n"
                f"What's new:\n{self.update_info}"
            )
            self.announcementAvailable.emit(update_announcement)

    def perform_check(self) -> None:
        """Perform version and announcement check"""
        try:
            version_data = self.get_latest_version_info()
            if not version_data:
                return
            self.has_new_version()
            self.check_new_version_announcement()
            self.check_announcement()
            self.checkCompleted.emit()
        except Exception:
            logger.exception("Version and announcement check failed")
