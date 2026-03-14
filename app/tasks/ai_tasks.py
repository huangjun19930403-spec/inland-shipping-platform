"""
AI异步任务
负责处理AI解析等计算密集型异步任务

注意：Celery任务使用asyncio.run()执行异步代码
开发模式下仍支持通过BackgroundTask直接调用
"""
import asyncio
import logging

from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


async def _run_cargo_parse(raw_message_id: int) -> dict:
    """执行货源解析工作流（异步实现）"""
    from app.core.database import AsyncSessionLocal
    from app.models.cargo import CargoRawMessage
    from app.workflows.cargo_parse_workflow import CargoParseWorkflow

    async with AsyncSessionLocal() as db:
        # 获取原始消息
        from sqlalchemy import select
        result = await db.execute(
            select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
        )
        msg = result.scalar_one_or_none()

        if not msg:
            logger.error(f"[ai_tasks] raw_message {raw_message_id} not found")
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
    logger.info(f"[ai_tasks] parse_cargo_message start id={raw_message_id}")
    try:
        result = asyncio.run(_run_cargo_parse(raw_message_id))
        logger.info(f"[ai_tasks] parse_cargo_message done id={raw_message_id} success={result['success']}")
        return result
    except Exception as e:
        logger.error(f"[ai_tasks] parse_cargo_message failed id={raw_message_id}: {e}")
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
    from datetime import datetime, timedelta
    from app.core.database import AsyncSessionLocal
    from app.models.cargo import CargoRawMessage
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as db:
        threshold = datetime.utcnow() - timedelta(hours=1)
        result = await db.execute(
            select(CargoRawMessage).where(
                CargoRawMessage.parse_status == "PARSING",
                CargoRawMessage.updated_at < threshold,
            )
        )
        stale = result.scalars().all()
        count = 0
        for msg in stale:
            msg.parse_status = "PENDING"
            count += 1
        await db.commit()
        return count


def cleanup_stale_parsing() -> dict:
    """Celery任务：清理超时解析任务"""
    count = asyncio.run(_cleanup_stale())
    logger.info(f"[ai_tasks] cleanup_stale_parsing reset {count} messages")
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
                f"[ai_tasks] parse workflow failed id={raw_message_id}: {result.get('error')}"
            )
    except Exception as e:
        logger.error(f"[ai_tasks] trigger_cargo_parse exception id={raw_message_id}: {e}")
