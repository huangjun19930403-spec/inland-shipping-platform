"""结构化日志配置。"""
import logging
import sys
from typing import Any

from app.core.config import settings


class StructuredFormatter(logging.Formatter):
    """结构化日志格式器"""

    GREY = "\x1b[38;21m"
    BLUE = "\x1b[34m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: BLUE,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        record.name = f"\x1b[36m{record.name}\x1b[0m"
        return super().format(record)


def setup_logging() -> None:
    """初始化全局日志配置"""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 移除已有handlers避免重复
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    if settings.DEBUG:
        handler.setFormatter(StructuredFormatter(fmt=fmt, datefmt=date_fmt))
    else:
        handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=date_fmt))

    root_logger.addHandler(handler)

    # 抑制第三方库冗余日志
    for noisy in ("aiosqlite", "httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """获取模块级Logger"""
    return logging.getLogger(name)


def log_operation(logger: logging.Logger, operation: str, **kwargs: Any) -> None:
    """统一操作日志格式"""
    details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"[{operation}] {details}")
