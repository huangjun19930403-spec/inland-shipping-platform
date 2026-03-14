"""
Celery应用配置
生产级异步任务执行引擎
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "inland_shipping",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.ai_tasks",
        "app.tasks.analysis_tasks",
        "app.tasks.dispatch_tasks",
    ],
)

celery_app.conf.update(
    # 序列化配置
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务超时与重试
    task_soft_time_limit=120,  # 2分钟软超时
    task_time_limit=180,       # 3分钟硬超时
    task_max_retries=3,
    task_default_retry_delay=30,  # 30秒后重试
    # 结果过期时间
    result_expires=86400,  # 24小时
    # 定时任务（Beat调度）
    beat_schedule={
        "daily-stats-aggregation": {
            "task": "app.tasks.analysis_tasks.compute_daily_stats",
            "schedule": settings.STATS_CRON_SCHEDULE,
            "options": {"queue": "analysis"},
        },
        "cleanup-stale-parsing": {
            "task": "app.tasks.ai_tasks.cleanup_stale_parsing",
            "schedule": 3600.0,  # 每小时
            "options": {"queue": "ai"},
        },
    },
    # 队列路由
    task_routes={
        "app.tasks.ai_tasks.*": {"queue": "ai"},
        "app.tasks.analysis_tasks.*": {"queue": "analysis"},
        "app.tasks.dispatch_tasks.*": {"queue": "dispatch"},
    },
)
