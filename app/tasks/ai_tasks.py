"""
AI异步任务
负责处理AI解析等计算密集型异步任务

注意：Celery任务使用asyncio.run()执行异步代码
开发模式下仍支持通过BackgroundTask直接调用
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


async def _run_cargo_parse(raw_message_id: int) -> dict:
    """执行货源解析工作流（异步实现）"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.cargo import CargoRawMessage
    from app.workflows.cargo_parse_workflow import CargoParseWorkflow

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
        )
        msg = result.scalar_one_or_none()

        if not msg:
            logger.error("[ai_tasks] raw_message %s not found", raw_message_id)
            return {"success": False, "error": "message not found"}

        workflow = CargoParseWorkflow(db)
        wf_result = await workflow.execute({
            "raw_message_id": raw_message_id,
            "raw_text": msg.raw_text,
        })

        return {
            "success": wf_result.success,
            "result": wf_result.result,
            "error": wf_result.error,
        }


def parse_cargo_message(raw_message_id: int) -> dict:
    """
    Celery任务：解析单条货运消息

    可通过以下方式触发：
    1. parse_cargo_message.delay(msg_id)  # Celery异步
    2. asyncio.run(_run_cargo_parse(msg_id))  # 直接同步调用（测试用）
    """
    logger.info("[ai_tasks] parse_cargo_message start id=%s", raw_message_id)
    try:
        result = asyncio.run(_run_cargo_parse(raw_message_id))
        logger.info("[ai_tasks] parse_cargo_message done id=%s success=%s", raw_message_id, result["success"])
        return result
    except Exception as e:
        logger.error("[ai_tasks] parse_cargo_message failed id=%s: %s", raw_message_id, e)
        return {"success": False, "error": str(e)}


# 注册为Celery任务（如果Celery可用）
try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.ai_tasks.parse_cargo_message", bind=True, max_retries=3)
    def parse_cargo_message_task(self, raw_message_id: int) -> dict:
        try:
            return parse_cargo_message(raw_message_id)
        except Exception as exc:
            raise self.retry(exc=exc, countdown=30)

except ImportError:
    pass


async def _cleanup_stale() -> int:
    """清理超时的PARSING状态消息"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.cargo import CargoRawMessage

    async with AsyncSessionLocal() as db:
        threshold = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await db.execute(
            select(CargoRawMessage).where(
                CargoRawMessage.status == "PARSING",
                CargoRawMessage.created_at < threshold,
            )
        )
        stale = result.scalars().all()
        count = 0
        for msg in stale:
            msg.status = "PENDING"
            count += 1
        await db.commit()
        return count


def cleanup_stale_parsing() -> dict:
    """Celery任务：清理超时解析任务"""
    count = asyncio.run(_cleanup_stale())
    logger.info("[ai_tasks] cleanup_stale_parsing reset %s messages", count)
    return {"reset_count": count}


try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.ai_tasks.cleanup_stale_parsing")
    def cleanup_stale_parsing_task() -> dict:
        return cleanup_stale_parsing()

except ImportError:
    pass


async def trigger_cargo_parse(raw_message_id: int) -> None:
    """
    从FastAPI BackgroundTask触发货源解析
    在没有Celery的开发环境中使用此函数
    """
    try:
        result = await _run_cargo_parse(raw_message_id)
        if not result["success"]:
            logger.warning(
                "[ai_tasks] parse workflow failed id=%s: %s",
                raw_message_id, result.get("error"),
            )
    except Exception as e:
        logger.error("[ai_tasks] trigger_cargo_parse exception id=%s: %s", raw_message_id, e)
