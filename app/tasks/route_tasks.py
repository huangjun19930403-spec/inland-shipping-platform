"""Celery route task entrypoints."""

from __future__ import annotations

from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.route.schemas import RouteTrackGenerateRequest
from app.modules.route.service import ShippingRoutePlanStructureService
from app.modules.tasks.service import AsyncTaskRunService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_coro_sync


async def _track_task_start(task_run_id: int | None, celery_task_id: str | None) -> None:
    if task_run_id is None:
        return
    async with AsyncSessionLocal() as db:
        service = AsyncTaskRunService(db)
        await service.bind_celery_task_id(task_run_id, celery_task_id)
        await service.mark_started(task_run_id, stage_name="轨迹生成中")


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


async def _generate_route_track_version(
    plan_id: int,
    payload: dict[str, Any] | None = None,
    task_run_id: int | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        if task_run_id is not None:
            await AsyncTaskRunService(db).heartbeat(
                task_run_id,
                stage_code="GENERATING",
                stage_name="轨迹生成中",
                stage_message="正在调用外部路径服务并生成方案轨迹版本",
                progress_percent=20,
            )
        response = await ShippingRoutePlanStructureService(db).generate_track_version(
            plan_id,
            RouteTrackGenerateRequest(**(payload or {})),
        )
        result = response.model_dump(mode="json")
        if task_run_id is not None:
            await AsyncTaskRunService(db).heartbeat(
                task_run_id,
                stage_code=response.status,
                stage_name="轨迹生成完成" if response.status != "FAILED" else "轨迹生成失败",
                stage_message=response.message,
                progress_percent=95,
                result_json=result,
            )
        return result


async def _run_tracked_async(celery_task_id: str | None, task_run_id: int | None, coro):
    await _track_task_start(task_run_id, celery_task_id)
    try:
        result = await coro
    except BaseException as exc:
        await _track_task_failure(task_run_id, exc)
        raise
    await _track_task_success(task_run_id, result)
    return result


def _run_tracked(celery_task_id: str | None, task_run_id: int | None, coro):
    return run_coro_sync(_run_tracked_async(celery_task_id, task_run_id, coro))


_ROUTE_TASK_OPTIONS = {
    "acks_late": True,
    "reject_on_worker_lost": True,
    "soft_time_limit": 900,
    "time_limit": 960,
}


@celery_app.task(name="route.generate_track_version", bind=True, **_ROUTE_TASK_OPTIONS)
def generate_route_track_version_task(
    self,
    plan_id: int,
    payload: dict[str, Any] | None = None,
    requested_by: int | None = None,
    task_run_id: int | None = None,
) -> dict[str, Any]:
    _ = requested_by
    celery_task_id = getattr(getattr(self, "request", None), "id", None)
    return _run_tracked(
        celery_task_id,
        task_run_id,
        _generate_route_track_version(plan_id, payload, task_run_id),
    )
