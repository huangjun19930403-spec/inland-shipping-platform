from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    # 应用基础配置
    APP_NAME: str = "中国内河航运数据采集与分析平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./inland_shipping.db"

    # JWT配置
    SECRET_KEY: str = "inland-shipping-platform-secret-key-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时

    # AI配置（Anthropic Claude）
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY", "")
    AI_MODEL: str = "claude-sonnet-4-6"
    AI_CONFIDENCE_THRESHOLD: int = 60  # AI解析置信度阈值

    # 定时任务配置
    STATS_CRON_HOUR: int = 2  # 每日凌晨2点执行统计聚合
    STATS_CRON_MINUTE: int = 0

    # CORS配置
    ALLOWED_ORIGINS: list = ["http://localhost:3000", "http://127.0.0.1:3000", "*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
