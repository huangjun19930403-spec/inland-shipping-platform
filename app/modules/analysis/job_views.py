from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from celery.result import AsyncResult
from sqlalchemy import func, select

from app.core.exceptions import NotFoundError, ValidationError
from app.models.analysis import AnalysisJobDefinition, AnalysisJobRun
from app.modules.analysis.job_catalog import MODULE_NAMES
from app.modules.analysis.schemas import (
    AnalysisJobRunDetailResponse,
    AnalysisJobRunResponse,
    AnalysisTaskDetailResponse,
    AnalysisTaskResponse,
    AnalysisTaskTriggerRequest,
    PageResponse,
)
from app.tasks.celery_app import celery_app


def _job_to_response(entity: AnalysisJobRun) -> AnalysisJobRunResponse:
    module_name = MODULE_NAMES.get(entity.module_code, entity.module_name)
    return AnalysisJobRunResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=module_name,
        stat_date_from=entity.stat_date_from,
        stat_date_to=entity.stat_date_to,
        status_code=entity.status_code,
        status_name=entity.status_name,
        celery_task_id=entity.celery_task_id,
        queued_at=entity.queued_at,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        duration_ms=entity.duration_ms,
        input_rows=entity.input_rows,
        output_rows=entity.output_rows,
        affected_rows=entity.affected_rows,
        error_message=entity.error_message,
        triggered_by=entity.triggered_by,
        created_at=entity.created_at,
    )


def _task_to_response(entity: AnalysisJobDefinition) -> AnalysisTaskResponse:
    module_name = MODULE_NAMES.get(entity.module_code, entity.module_name)
    return AnalysisTaskResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=module_name,
        description=entity.description,
        source_tables_json=entity.source_tables_json,
        target_tables_json=entity.target_tables_json,
        default_parameters_json=entity.default_parameters_json,
        schedule_cron=entity.schedule_cron,
        schedule_enabled=entity.schedule_enabled,
        enabled=entity.enabled,
        last_run_id=entity.last_run_id,
        last_status_code=entity.last_status_code,
        last_finished_at=entity.last_finished_at,
        last_result_summary_json=entity.last_result_summary_json,
        sort_order=entity.sort_order,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _status_name(status_code: str) -> str:
    return {"QUEUED": "排队中", "RUNNING": "运行中", "SUCCESS": "成功", "PARTIAL_SUCCESS": "部分成功", "FAILED": "失败"}.get(
        status_code,
        status_code,
    )


class AnalysisJobViewMixin:
    async def _mark_failed_if_celery_failed(self, row: AnalysisJobRun) -> bool:
        if row.status_code not in {"QUEUED", "RUNNING"} or not row.celery_task_id:
            return False
        try:
            result = AsyncResult(row.celery_task_id, app=celery_app)
            if result.state != "FAILURE":
                return False
            message = str(result.info)[:4000]
        except Exception:
            return False

        now = datetime.utcnow()
        row.status_code = "FAILED"
        row.status_name = _status_name("FAILED")
        row.finished_at = now
        baseline = row.started_at or row.queued_at or row.created_at
        row.duration_ms = int((now - baseline).total_seconds() * 1000) if baseline else None
        row.error_message = message

        definition = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == row.job_code))
        if definition is not None:
            definition.last_run_id = row.id
            definition.last_status_code = row.status_code
            definition.last_finished_at = now
            definition.last_result_summary_json = {"error": message}
            definition.updated_at = now
        await self.db.commit()
        await self.db.refresh(row)
        return True

    async def _page(self, stmt: Any, *, page: int, page_size: int, order_by: tuple[Any, ...], item_mapper: Callable[[Any], Any]) -> PageResponse:
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (await self.db.execute(stmt.order_by(*order_by).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return PageResponse(total=total, page=page, page_size=page_size, items=[item_mapper(row) for row in rows])

    async def list_jobs(
        self,
        module_code: str | None,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun)
        if module_code:
            stmt = stmt.where(AnalysisJobRun.module_code == module_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        for row in rows:
            await self._mark_failed_if_celery_failed(row)
        return PageResponse(total=total, page=page, page_size=page_size, items=[_job_to_response(row) for row in rows])

    async def get_job_detail(self, job_run_id: int) -> AnalysisJobRunDetailResponse:
        row = await self.db.scalar(select(AnalysisJobRun).where(AnalysisJobRun.id == job_run_id))
        if row is None:
            raise NotFoundError("AnalysisJobRun", job_run_id)
        await self._mark_failed_if_celery_failed(row)
        return AnalysisJobRunDetailResponse(
            **_job_to_response(row).model_dump(),
            parameters_json=row.parameters_json,
            result_summary_json=row.result_summary_json,
        )

    async def list_tasks(
        self,
        module_code: str | None,
        enabled: bool | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisTaskResponse]:
        stmt = select(AnalysisJobDefinition)
        if module_code:
            stmt = stmt.where(AnalysisJobDefinition.module_code == module_code)
        if enabled is not None:
            stmt = stmt.where(AnalysisJobDefinition.enabled == enabled)
        return await self._page(
            stmt,
            page=page,
            page_size=page_size,
            order_by=(AnalysisJobDefinition.sort_order.asc(), AnalysisJobDefinition.id.asc()),
            item_mapper=_task_to_response,
        )

    async def get_task_detail(self, job_code: str) -> AnalysisTaskDetailResponse:
        row = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if row is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        runs = (
            await self.db.execute(
                select(AnalysisJobRun)
                .where(AnalysisJobRun.job_code == job_code)
                .order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .limit(20)
            )
        ).scalars().all()
        for item in runs:
            await self._mark_failed_if_celery_failed(item)
        return AnalysisTaskDetailResponse(**_task_to_response(row).model_dump(), recent_runs=[_job_to_response(item) for item in runs])

    async def list_task_runs(
        self,
        job_code: str,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun).where(AnalysisJobRun.job_code == job_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        for row in rows:
            await self._mark_failed_if_celery_failed(row)
        return PageResponse(total=total, page=page, page_size=page_size, items=[_job_to_response(row) for row in rows])

    async def trigger_task(self, job_code: str, payload: AnalysisTaskTriggerRequest, triggered_by: str | None) -> AnalysisJobRunResponse:
        definition = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if definition is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        if not definition.enabled:
            raise ValidationError("分析任务已停用，不能手动触发", {"job_code": job_code})
        now = datetime.utcnow()
        run = AnalysisJobRun(
            job_code=definition.job_code,
            job_name=definition.job_name,
            module_code=definition.module_code,
            module_name=definition.module_name,
            stat_date_from=payload.date_from,
            stat_date_to=payload.date_to,
            status_code="QUEUED",
            status_name=_status_name("QUEUED"),
            queued_at=now,
            parameters_json={**(definition.default_parameters_json or {}), **(payload.parameters_json or {}), "force_rebuild": payload.force_rebuild},
            triggered_by=triggered_by,
            created_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(run)
        try:
            from app.tasks.analysis_tasks import run_analysis_job

            async_result = run_analysis_job.apply_async(
                args=[
                    definition.job_code,
                    payload.date_from.isoformat(),
                    payload.date_to.isoformat(),
                    payload.force_rebuild,
                    {"job_run_id": run.id, "triggered_by": triggered_by, **(payload.parameters_json or {})},
                ],
                queue="analysis",
            )
            run.celery_task_id = async_result.id
        except Exception as exc:
            run.status_code = "FAILED"
            run.status_name = _status_name("FAILED")
            run.finished_at = datetime.utcnow()
            run.error_message = f"Celery 任务投递失败：{exc}"
            await self.db.commit()
            raise ValidationError("Celery 任务投递失败，请确认 Redis 和 analysis-worker 已启动", {"error": str(exc)}) from exc
        await self.db.commit()
        await self.db.refresh(run)
        return _job_to_response(run)
