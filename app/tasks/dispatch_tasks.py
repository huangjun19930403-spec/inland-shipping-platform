"""
调度异步任务
货源与船舶的智能匹配、调度任务
预留扩展槽位，V2版本实现
"""
import logging

logger = logging.getLogger(__name__)


def match_cargo_vessel(cargo_opportunity_id: int) -> dict:
    """
    Celery任务：尝试为货源匹配合适船舶
    V2版本实现，当前为占位符
    """
    logger.info(f"[dispatch_tasks] match_cargo_vessel id={cargo_opportunity_id} (not implemented)")
    return {"matched": False, "reason": "dispatch matching not implemented in V1"}


try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.dispatch_tasks.match_cargo_vessel")
    def match_cargo_vessel_task(cargo_opportunity_id: int) -> dict:
        return match_cargo_vessel(cargo_opportunity_id)

except ImportError:
    pass
