"""Celery freight AI parsing task entrypoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.freight.batch_service import FreightBatchTaskService
from app.modules.freight.normalization_service import FreightNormalizationSuggestionService
from app.modules.freight.tms_service import FreightTmsInboundService
from app.modules.tasks.service import AsyncTaskRunService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_coro_sync


async def _track_task_start(task_run_id: int | None, celery_task_id: str | None, stage_name: str) -> None:
    if task_run_id is None:
        return
    async with AsyncSessionLocal() as db:
        service = AsyncTaskRunService(db)
        await service.bind_celery_task_id(task_run_id, celery_task_id)
        await service.mark_started(task_run_id, stage_name=stage_name)


async def _track_task_success(task_run_id: int | None, result: dict[str, Any]) -> None:
    if task_run_id is None:
        return
    async with AsyncSessionLocal() as db:
        await AsyncTaskRunService(db).mark_success(task_run_id, result)


async def _track_task_failure(task_run_id: int | None, exc: BaseException) -> None:
    if task_run_id is None:
        return
    async with AsyncSessionLocal() as db:
        await AsyncTaskRunService(db).mark_failed(task_run_id, exc)


async def _parse_wechat_batch(batch_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        if task_run_id is not None:
            await AsyncTaskRunService(db).heartbeat(
                task_run_id,
                stage_code="PARSING",
                stage_name="货源解析中",
                stage_message="正在执行微信原文语义解析",
                progress_percent=10,
            )
        detail = await FreightBatchTaskService(db).run_parse_now(batch_id, requested_by=requested_by)
        return {
            "batch_id": batch_id,
            "status_code": detail.batch.status_code,
            "candidate_count": detail.batch.candidate_count,
            "failed_count": detail.batch.failed_count,
        }


async def _parse_tms_inbound(inbound_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        if task_run_id is not None:
            await AsyncTaskRunService(db).heartbeat(
                task_run_id,
                stage_code="PARSING",
                stage_name="TMS 入站解析中",
                stage_message="正在将 TMS 结构化入站转换为候选货源",
                progress_percent=10,
            )
        detail = await FreightTmsInboundService(db).run_parse_now(inbound_id, requested_by=requested_by)
        return {
            "inbound_id": inbound_id,
            "status_code": detail.inbound.status_code,
            "candidate_count": detail.inbound.candidate_count,
        }


async def _clean_freight_normalization(task_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        try:
            if task_run_id is not None:
                await AsyncTaskRunService(db).heartbeat(
                    task_run_id,
                    stage_code="CLEANING",
                    stage_name="货源清洗中",
                    stage_message="正在扫描正式货源并生成主数据治理建议",
                    progress_percent=10,
                )
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


async def _run_tracked_async(celery_task_id: str | None, task_run_id: int | None, stage_name: str, coro):
    await _track_task_start(task_run_id, celery_task_id, stage_name)
    try:
        result = await coro
    except BaseException as exc:
        await _track_task_failure(task_run_id, exc)
        raise
    await _track_task_success(task_run_id, result)
    return result


def _run_tracked(celery_task_id: str | None, task_run_id: int | None, stage_name: str, coro):
    return run_coro_sync(_run_tracked_async(celery_task_id, task_run_id, stage_name, coro))


_FREIGHT_TASK_OPTIONS = {
    "acks_late": True,
    "reject_on_worker_lost": True,
    "autoretry_for": (ConnectionError, TimeoutError),
    "retry_backoff": True,
    "retry_kwargs": {"max_retries": 1},
    "soft_time_limit": 900,
    "time_limit": 960,
}


@celery_app.task(name="freight.parse_wechat_batch", bind=True, **_FREIGHT_TASK_OPTIONS)
def parse_wechat_batch_task(self, batch_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    celery_task_id = getattr(getattr(self, "request", None), "id", None)
    return _run_tracked(celery_task_id, task_run_id, "微信货源解析中", _parse_wechat_batch(batch_id, requested_by, task_run_id))


@celery_app.task(name="freight.parse_tms_inbound", bind=True, **_FREIGHT_TASK_OPTIONS)
def parse_tms_inbound_task(self, inbound_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    celery_task_id = getattr(getattr(self, "request", None), "id", None)
    return _run_tracked(celery_task_id, task_run_id, "TMS 入站解析中", _parse_tms_inbound(inbound_id, requested_by, task_run_id))


@celery_app.task(name="freight.clean_normalization", bind=True, **_FREIGHT_TASK_OPTIONS)
def clean_freight_normalization_task(self, task_id: int, requested_by: int | None = None, task_run_id: int | None = None) -> dict[str, Any]:
    celery_task_id = getattr(getattr(self, "request", None), "id", None)
    return _run_tracked(celery_task_id, task_run_id, "货源清洗中", _clean_freight_normalization(task_id, requested_by, task_run_id))
