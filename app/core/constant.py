"""
常量配置模块

定义应用程序中使用的常量，包括 InfoBar 显示时长等
"""

# InfoBar 显示时长配置（单位：毫秒）
INFOBAR_DURATION_FOREVER = 24 * 60 * 60 * 1000  # 永久提示：1天
INFOBAR_DURATION_ERROR = 10000  # 错误提示：10秒
INFOBAR_DURATION_WARNING = 5000  # 警告提示：5秒
INFOBAR_DURATION_INFO = 3000  # 信息提示：3秒
INFOBAR_DURATION_SUCCESS = 2000  # 成功提示：2秒
