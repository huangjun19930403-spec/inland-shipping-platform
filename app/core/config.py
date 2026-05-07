"""应用基础配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # 应用基础配置
    APP_NAME: str = "Inland Shipping Platform"
    APP_VERSION: str = "3.0.0"
    DEBUG: bool = True

    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./inland_shipping.db"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/1"
    ANALYSIS_CELERY_EAGER: bool = False
    ANALYSIS_DEFAULT_DAILY_CRON: str = "20 2 * * *"

    # 认证
    SECRET_KEY: str = "inland-shipping-platform-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # CORS
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ]

    # Elasticsearch
    ES_TIMEOUT_SECONDS: float = 10.0
    ES_HISTORY_TIMEOUT_SECONDS: float = 30.0
    ES_R_SCHEME: str = "http"
    ES_R_HOST: str = ""
    ES_R_PORT: int = 80
    ES_R_USER: str = "elastic"
    ES_R_PASSWORD: str = ""
    ES_R_INDEX: str = "ship_positions"
    ES_SCHEME: str = "http"
    ES_HOST: str = ""
    ES_PORT: int = 80
    ES_USER: str = "elastic"
    ES_PASSWORD: str = ""
    ES_HISTORY_INDEX_PREFIX: str = "ship_locations_"

    # 高德
    ROUTE_GEOMETRY_MODE: str = "real"  # real / mock / fallback
    ROUTE_GEOMETRY_TIMEOUT_SECONDS: float = 8.0
    ROUTE_AMAP_WEB_API_KEY: str = ""
    AMAP_JS_API_KEY: str = ""
    AMAP_SECURITY_JS_CODE: str = ""

    # HiFleet
    HIFLEET_ENABLED: bool = False
    HIFLEET_BASE_URL: str = "https://www.hifleet.com"
    HIFLEET_LOGIN_URL: str = "/hifleetapi/generalUserLoginAction.do"
    HIFLEET_ROUTE_URL: str = "/hifleetrouteapi/getNewRoute"
    HIFLEET_CHECK_LOGIN_URL: str = "/hifleetapi/queryAlertRsCount.do"
    HIFLEET_USERNAME: str = ""
    HIFLEET_PASSWORD: str = ""
    HIFLEET_TIMEOUT_SECONDS: float = 8.0
    HIFLEET_RELOGIN_CHECK_ENABLED: bool = True

    # 通义千问 / 阿里云百炼 DashScope
    AI_PROVIDER: str = "DASHSCOPE_QWEN"
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_TIMEOUT_SECONDS: float = 60.0
    DASHSCOPE_STREAM_TIMEOUT_SECONDS: float = 120.0
    FREIGHT_AI_SEMANTIC_MODEL: str = "qwen-plus"
    FREIGHT_AI_DETAIL_MODEL: str = "qwen-turbo"
    FREIGHT_AI_REVIEW_MODEL: str = "qwen-plus"
    FREIGHT_AI_DETAIL_BATCH_SIZE: int = 8
    FREIGHT_AI_DETAIL_CONCURRENCY: int = 2
    FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD: float = 0.80
    FREIGHT_AI_WARN_RAW_CHARS: int = 20000
    FREIGHT_AI_STALE_HEARTBEAT_SECONDS: int = 180

    # 腾讯云 COS / 对象存储
    COS_ENABLED: bool = False
    COS_BUCKET_NAME: str = ""
    COS_REGION: str = "ap-nanjing"
    COS_ENDPOINT: str = "cos.ap-nanjing.myqcloud.com"
    COS_ACCESS_KEY: str = ""
    COS_SECRET_KEY: str = ""
    COS_PATH_STYLE_ACCESS: bool = False
    COS_IMAGE_MAX_SIZE_MB: int = 10


settings = Settings()
