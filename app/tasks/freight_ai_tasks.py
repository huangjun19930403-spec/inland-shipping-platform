"""Celery freight AI parsing task entrypoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from threading import Thread
from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.freight.service import FreightBatchTaskService, FreightNormalizationSuggestionService, FreightTmsInboundService
from app.tasks.celery_app import celery_app


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Any = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge for eager mode
            error = exc

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


async def _parse_wechat_batch(batch_id: int, requested_by: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        detail = await FreightBatchTaskService(db).run_parse_now(batch_id, requested_by=requested_by)
        return {
            "batch_id": batch_id,
            "status_code": detail.batch.status_code,
            "candidate_count": detail.batch.candidate_count,
            "failed_count": detail.batch.failed_count,
        }


async def _parse_tms_inbound(inbound_id: int, requested_by: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        detail = await FreightTmsInboundService(db).run_parse_now(inbound_id, requested_by=requested_by)
        return {
            "inbound_id": inbound_id,
            "status_code": detail.inbound.status_code,
            "candidate_count": detail.inbound.candidate_count,
        }


async def _clean_freight_normalization(task_id: int, requested_by: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        try:
            result = await FreightNormalizationSuggestionService(db).run_clean_now(task_id, operator_id=requested_by)
            return {
                "task_id": task_id,
                "status_code": result.status_code,
                "review_status_code": result.review_status_code,
                "scanned_count": result.scanned_count,
                "suggestion_count": result.suggestion_count,
                "auto_applied_count": result.auto_applied_count,
                "pending_count": result.pending_count,
            }
        except Exception as exc:
            service = FreightNormalizationSuggestionService(db)
            finished = datetime.utcnow()
            await service.task_repo.update(
                task_id,
                {
                    "status_code": "FAILED",
                    "stage_code": "FAILED",
                    "stage_name": "清洗失败",
                    "stage_message": str(exc),
                    "error_message": str(exc),
                    "progress_percent": 100,
                    "finished_at": finished,
                    "heartbeat_at": finished,
                },
            )
            await db.commit()
            raise


@celery_app.task(name="freight.parse_wechat_batch")
def parse_wechat_batch_task(batch_id: int, requested_by: int | None = None) -> dict[str, Any]:
    return _run_coro_sync(_parse_wechat_batch(batch_id, requested_by))


@celery_app.task(name="freight.parse_tms_inbound")
def parse_tms_inbound_task(inbound_id: int, requested_by: int | None = None) -> dict[str, Any]:
    return _run_coro_sync(_parse_tms_inbound(inbound_id, requested_by))


@celery_app.task(name="freight.clean_normalization")
def clean_freight_normalization_task(task_id: int, requested_by: int | None = None) -> dict[str, Any]:
    return _run_coro_sync(_clean_freight_normalization(task_id, requested_by))
