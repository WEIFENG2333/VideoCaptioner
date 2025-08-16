import logging
import logging.handlers
from pathlib import Path

from ...config import LOG_LEVEL, LOG_PATH


def setup_logger(
    name: str,
    level: int = LOG_LEVEL,
    info_fmt: str = "%(message)s",  # INFO级别使用简化格式
    default_fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # 其他级别使用详细格式
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    log_file: str = str(LOG_PATH / "app.log"),
    console_output: bool = True,
) -> logging.Logger:
    """
    创建并配置一个日志记录器，INFO级别使用简化格式。

    参数：
    - name: 日志记录器的名称
    - level: 日志级别
    - info_fmt: INFO级别的日志格式字符串
    - default_fmt: 其他级别的日志格式字符串
    - datefmt: 时间格式字符串
    - log_file: 日志文件路径
    """

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # 创建级别特定的格式化器
        class LevelSpecificFormatter(logging.Formatter):
            def format(self, record):
                if record.levelno == logging.INFO:
                    self._style._fmt = info_fmt
                else:
                    self._style._fmt = default_fmt
                return super().format(record)

        level_formatter = LevelSpecificFormatter(default_fmt, datefmt=datefmt)

        # 只在console_output为True时添加控制台处理器
        if console_output:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)
            console_handler.setFormatter(level_formatter)
            logger.addHandler(console_handler)

        # 文件处理器
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(level_formatter)
            logger.addHandler(file_handler)

    # 设置特定库的日志级别为ERROR以减少日志噪音
    error_loggers = [
        "urllib3",
        "requests",
        "openai",
        "httpx",
        "httpcore",
        "ssl",
        "certifi",
    ]
    for lib in error_loggers:
        logging.getLogger(lib).setLevel(logging.ERROR)

    return logger
