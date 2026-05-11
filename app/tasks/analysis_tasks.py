"""Celery analysis task entrypoints."""

from __future__ import annotations

import asyncio
import logging
from threading import Thread
from datetime import date, datetime, timedelta
from typing import Any

from celery.signals import worker_ready
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.analysis import AnalysisJobDefinition, AnalysisJobRun
from app.modules.analysis.job_catalog import ANALYSIS_JOB_SPEC_BY_CODE
from app.modules.analysis.service import AnalysisDashboardService
from app.modules.analysis.statistics import AnalysisStatisticsService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _parse_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value))
    return date.today() - timedelta(days=1)


def _status_name(status_code: str) -> str:
    return {
        "QUEUED": "排队中",
        "RUNNING": "运行中",
        "SUCCESS": "成功",
        "PARTIAL_SUCCESS": "部分成功",
        "FAILED": "失败",
    }.get(status_code, status_code)


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] | None = None
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


async def _run_analysis_job(
    job_code: str,
    date_from: str | None,
    date_to: str | None,
    force_rebuild: bool,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    options = options or {}
    job_run_id = options.get("job_run_id")
    async with AsyncSessionLocal() as db:
        run = await db.scalar(select(AnalysisJobRun).where(AnalysisJobRun.id == job_run_id)) if job_run_id else None
        now = datetime.utcnow()
        if run is None:
            spec = ANALYSIS_JOB_SPEC_BY_CODE[job_code]
            run = AnalysisJobRun(
                job_code=spec.job_code,
                job_name=spec.job_name,
                module_code=spec.module_code,
                module_name=spec.module_name,
                stat_date_from=start,
                stat_date_to=end,
                status_code="RUNNING",
                status_name=_status_name("RUNNING"),
                queued_at=now,
                started_at=now,
                parameters_json={"force_rebuild": force_rebuild, **options},
                triggered_by=str(options.get("triggered_by") or "celery"),
                created_at=now,
            )
            db.add(run)
            await db.flush()
        else:
            run.status_code = "RUNNING"
            run.status_name = _status_name("RUNNING")
            run.started_at = now
            run.error_message = None
        await db.commit()

        try:
            service = AnalysisStatisticsService(db)
            result = await service.run(job_code, start, end, force_rebuild=force_rebuild, job_run_id=run.id)
            finished = datetime.utcnow()
            run.status_code = "SUCCESS"
            run.status_name = _status_name("SUCCESS")
            run.finished_at = finished
            run.duration_ms = int((finished - (run.started_at or finished)).total_seconds() * 1000)
            run.input_rows = result.input_rows
            run.output_rows = result.output_rows
            run.affected_rows = result.affected_rows
            run.result_summary_json = result.as_summary()
            run.error_message = None
            definition = await db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
            if definition is not None:
                definition.last_run_id = run.id
                definition.last_status_code = run.status_code
                definition.last_finished_at = run.finished_at
                definition.last_result_summary_json = run.result_summary_json
                definition.updated_at = finished
            await db.commit()
            return result.as_summary()
        except Exception as exc:
            await db.rollback()
            failed = await db.scalar(select(AnalysisJobRun).where(AnalysisJobRun.id == run.id))
            finished = datetime.utcnow()
            if failed is not None:
                failed.status_code = "FAILED"
                failed.status_name = _status_name("FAILED")
                failed.finished_at = finished
                failed.duration_ms = int((finished - (failed.started_at or finished)).total_seconds() * 1000)
                failed.error_message = str(exc)[:4000]
                definition = await db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
                if definition is not None:
                    definition.last_run_id = failed.id
                    definition.last_status_code = failed.status_code
                    definition.last_finished_at = failed.finished_at
                    definition.last_result_summary_json = {"error": failed.error_message}
                    definition.updated_at = finished
                await db.commit()
            raise


@celery_app.task(name="analysis.run_job")
def run_analysis_job(
    job_code: str,
    date_from: str | None = None,
    date_to: str | None = None,
    force_rebuild: bool = True,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _run_coro_sync(_run_analysis_job(job_code, date_from, date_to, force_rebuild, options))


async def _precompute_flow_route_cache(
    date_from: str | None,
    date_to: str | None,
    flow_types: list[str] | None,
    limit: int | None,
    force_refresh: bool,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        service = AnalysisDashboardService(db)
        response = await service.precompute_flow_route_cache(
            date.fromisoformat(date_from) if date_from else None,
            date.fromisoformat(date_to) if date_to else None,
            flow_types=flow_types,
            limit=limit or settings.ANALYSIS_FLOW_ROUTE_PRECOMPUTE_LIMIT,
            force_refresh=force_refresh,
        )
        return response.model_dump(mode="json")


@celery_app.task(name="analysis.precompute_flow_route_cache")
def precompute_flow_route_cache_task(
    date_from: str | None = None,
    date_to: str | None = None,
    flow_types: list[str] | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    return _run_coro_sync(_precompute_flow_route_cache(date_from, date_to, flow_types, limit, force_refresh))


@worker_ready.connect
def precompute_flow_routes_on_worker_ready(sender=None, **_kwargs) -> None:
    if not bool(settings.ANALYSIS_FLOW_ROUTE_PRECOMPUTE_ON_WORKER_START):
        return
    try:
        precompute_flow_route_cache_task.apply_async(
            args=(None, None, ["freight", "ship"], settings.ANALYSIS_FLOW_ROUTE_PRECOMPUTE_LIMIT, False),
            queue="analysis",
        )
        logger.info("queued analysis flow route cache precompute task on celery worker ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to queue analysis flow route cache precompute task on worker ready: %s", exc)
