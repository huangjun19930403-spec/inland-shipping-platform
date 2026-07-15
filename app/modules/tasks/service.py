"""统一后台任务运行账本服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.analysis import AnalysisJobRun
from app.models.task import AsyncTaskRun
from app.modules.tasks.repository import ACTIVE_STATUSES, AnalysisJobRunAdapterRepository, AsyncTaskRunRepository
from app.modules.tasks.schemas import AsyncTaskRunResponse, PageResponse, TaskRecoverStaleResponse


TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "STALE", "CANCELED"}
RETRYABLE_STATUSES = {"FAILED", "STALE"}
DEFAULT_TASK_STALE_SECONDS = 1800


def _status_name(status_code: str | None) -> str:
    return {
        "NEW": "新建",
        "QUEUED": "排队中",
        "STARTED": "已启动",
        "RUNNING": "运行中",
        "RETRYING": "重试中",
        "SUCCESS": "成功",
        "PARTIAL_SUCCESS": "部分成功",
        "FAILED": "失败",
        "STALE": "心跳过期",
        "CANCELED": "已取消",
    }.get(status_code or "", status_code or "")


def _task_heartbeat_at(row: AsyncTaskRun) -> datetime | None:
    return row.heartbeat_at or row.updated_at or row.queued_at or row.created_at


class AsyncTaskRunService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AsyncTaskRunRepository(db)
        self.analysis_repo = AnalysisJobRunAdapterRepository(db)

    async def create_queued(
        self,
        *,
        task_name: str,
        task_title: str,
        queue_name: str,
        business_type: str,
        business_id: int | None = None,
        business_no: str | None = None,
        idempotency_key: str | None = None,
        requested_by: int | None = None,
        triggered_by: str | None = "manual",
        max_retries: int = 1,
        extra_json: dict | None = None,
        stale_seconds: int = DEFAULT_TASK_STALE_SECONDS,
    ) -> AsyncTaskRun:
        now = datetime.utcnow()
        if idempotency_key:
            active = await self.repo.get_active_by_idempotency_key(idempotency_key)
            if active is not None:
                if await self.mark_failed_if_celery_failed(active):
                    active = None
                elif await self.mark_stale_if_expired(active, stale_seconds=stale_seconds):
                    active = None
                else:
                    return active
        return await self.repo.create(
            {
                "task_name": task_name,
                "task_title": task_title,
                "queue_name": queue_name,
                "business_type": business_type,
                "business_id": business_id,
                "business_no": business_no,
                "idempotency_key": idempotency_key,
                "status_code": "QUEUED",
                "stage_code": "QUEUED",
                "stage_name": "排队中",
                "stage_message": "任务已提交，等待 worker 消费",
                "progress_percent": 5,
                "attempt": 0,
                "max_retries": max(0, int(max_retries)),
                "requested_by": requested_by,
                "triggered_by": triggered_by,
                "queued_at": now,
                "heartbeat_at": now,
                "extra_json": extra_json,
            }
        )

    async def mark_stale_if_expired(self, row: AsyncTaskRun, *, stale_seconds: int = DEFAULT_TASK_STALE_SECONDS) -> bool:
        if row.status_code not in ACTIVE_STATUSES:
            return False
        heartbeat_at = _task_heartbeat_at(row)
        if heartbeat_at is None:
            return False
        stale_seconds = max(30, stale_seconds)
        cutoff = datetime.utcnow() - timedelta(seconds=stale_seconds)
        if heartbeat_at >= cutoff:
            return False
        await self.repo.update(
            row.id,
            {
                "status_code": "STALE",
                "stage_code": "STALE",
                "stage_name": "心跳过期",
                "stage_message": f"任务超过 {stale_seconds} 秒未更新心跳，已标记为可重新提交",
                "finished_at": datetime.utcnow(),
                "error_message": f"任务超过 {stale_seconds} 秒未更新心跳",
                "progress_percent": 100,
            },
        )
        await self.db.commit()
        return True

    async def mark_failed_if_celery_failed(self, row: AsyncTaskRun) -> bool:
        if row.status_code not in ACTIVE_STATUSES or not row.celery_task_id:
            return False
        try:
            from celery.result import AsyncResult

            from app.tasks.celery_app import celery_app

            result = AsyncResult(row.celery_task_id, app=celery_app)
            if result.state != "FAILURE":
                return False
            message = str(result.info)[:4000]
        except Exception:
            return False
        now = datetime.utcnow()
        await self.repo.update(
            row.id,
            {
                "status_code": "FAILED",
                "stage_code": "FAILED",
                "stage_name": "处理失败",
                "stage_message": message,
                "finished_at": now,
                "heartbeat_at": now,
                "error_message": message,
                "progress_percent": 100,
            },
        )
        await self.db.commit()
        return True

    async def get_latest_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        stale_seconds: int = DEFAULT_TASK_STALE_SECONDS,
        recover_stale: bool = True,
    ) -> AsyncTaskRunResponse | None:
        row = await self.repo.get_latest_by_idempotency_key(idempotency_key)
        if row is None:
            return None
        if recover_stale and await self.mark_stale_if_expired(row, stale_seconds=stale_seconds):
            fresh = await self.repo.get_by_id(row.id)
            row = fresh or row
        return self._from_async_task(row)

    async def get_latest_by_idempotency_key_prefix(
        self,
        idempotency_key_prefix: str,
        *,
        status_codes: set[str] | None = None,
        stale_seconds: int = DEFAULT_TASK_STALE_SECONDS,
        recover_stale: bool = True,
    ) -> AsyncTaskRunResponse | None:
        row = await self.repo.get_latest_by_idempotency_key_prefix(
            idempotency_key_prefix,
            status_codes=status_codes,
        )
        if row is None:
            return None
        if recover_stale and await self.mark_stale_if_expired(row, stale_seconds=stale_seconds):
            fresh = await self.repo.get_by_id(row.id)
            row = fresh or row
        return self._from_async_task(row)

    async def bind_celery_task_id(self, task_run_id: int | None, celery_task_id: str | None) -> None:
        if task_run_id is None or not celery_task_id:
            return
        await self.repo.update(task_run_id, {"celery_task_id": celery_task_id, "heartbeat_at": datetime.utcnow()})
        await self.db.commit()

    async def mark_started(self, task_run_id: int | None, *, stage_name: str = "运行中") -> None:
        if task_run_id is None:
            return
        now = datetime.utcnow()
        row = await self.repo.get_by_id(task_run_id)
        if row is None:
            return
        await self.repo.update(
            task_run_id,
            {
                "status_code": "RUNNING",
                "stage_code": "RUNNING",
                "stage_name": stage_name,
                "stage_message": "worker 已开始处理任务",
                "progress_percent": max(int(row.progress_percent or 0), 10),
                "started_at": row.started_at or now,
                "heartbeat_at": now,
                "attempt": int(row.attempt or 0) + 1,
                "error_message": None,
            },
        )
        await self.db.commit()

    async def heartbeat(
        self,
        task_run_id: int | None,
        *,
        stage_code: str | None = None,
        stage_name: str | None = None,
        stage_message: str | None = None,
        progress_percent: int | None = None,
        result_json: dict | None = None,
    ) -> None:
        if task_run_id is None:
            return
        updates: dict[str, Any] = {"heartbeat_at": datetime.utcnow()}
        if stage_code is not None:
            updates["stage_code"] = stage_code
        if stage_name is not None:
            updates["stage_name"] = stage_name
        if stage_message is not None:
            updates["stage_message"] = stage_message
        if progress_percent is not None:
            updates["progress_percent"] = max(0, min(int(progress_percent), 100))
        if result_json is not None:
            updates["result_json"] = result_json
        await self.repo.update(task_run_id, updates)
        await self.db.commit()

    async def mark_success(self, task_run_id: int | None, result_json: dict | None = None) -> None:
        if task_run_id is None:
            return
        now = datetime.utcnow()
        await self.repo.update(
            task_run_id,
            {
                "status_code": "SUCCESS",
                "stage_code": "SUCCESS",
                "stage_name": "处理完成",
                "stage_message": "任务已完成",
                "progress_percent": 100,
                "finished_at": now,
                "heartbeat_at": now,
                "error_message": None,
                "result_json": result_json,
            },
        )
        await self.db.commit()

    async def mark_failed(self, task_run_id: int | None, error: BaseException | str) -> None:
        if task_run_id is None:
            return
        now = datetime.utcnow()
        message = str(error)[:4000]
        await self.repo.update(
            task_run_id,
            {
                "status_code": "FAILED",
                "stage_code": "FAILED",
                "stage_name": "处理失败",
                "stage_message": message,
                "progress_percent": 100,
                "finished_at": now,
                "heartbeat_at": now,
                "error_message": message,
            },
        )
        await self.db.commit()

    async def list_runs(
        self,
        *,
        keyword: str | None,
        task_name: str | None,
        queue_name: str | None,
        business_type: str | None,
        status_code: str | None,
        include_analysis_runs: bool,
        page: int,
        page_size: int,
    ) -> PageResponse[AsyncTaskRunResponse]:
        fetch_limit = max(page * page_size, page_size)
        celery_rows = await self.repo.list_items(
            keyword=keyword,
            task_name=task_name,
            queue_name=queue_name,
            business_type=business_type,
            status_code=status_code,
            limit=fetch_limit,
        )
        total = await self.repo.count_items(
            keyword=keyword,
            task_name=task_name,
            queue_name=queue_name,
            business_type=business_type,
            status_code=status_code,
        )
        items = [self._from_async_task(row) for row in celery_rows]
        if include_analysis_runs and not task_name and (not queue_name or queue_name == "analysis") and (not business_type or business_type == "ANALYSIS_JOB"):
            analysis_rows = await self.analysis_repo.list_items(keyword=keyword, status_code=status_code, limit=fetch_limit)
            total += await self.analysis_repo.count_items(keyword=keyword, status_code=status_code)
            items.extend(self._from_analysis_run(row) for row in analysis_rows)
        items.sort(key=lambda item: item.created_at, reverse=True)
        start = (page - 1) * page_size
        end = start + page_size
        return PageResponse[AsyncTaskRunResponse](total=total, page=page, page_size=page_size, items=items[start:end])

    async def get_run(self, task_run_id: int) -> AsyncTaskRunResponse:
        row = await self.repo.get_by_id(task_run_id)
        if row is None:
            raise NotFoundError("AsyncTaskRun", task_run_id)
        return self._from_async_task(row)

    async def retry(self, task_run_id: int, *, reason: str | None = None) -> AsyncTaskRunResponse:
        row = await self.repo.get_by_id(task_run_id)
        if row is None:
            raise NotFoundError("AsyncTaskRun", task_run_id)
        if row.status_code not in RETRYABLE_STATUSES:
            raise ValidationError("只有失败或心跳过期的后台任务可以重试")
        if row.business_id is None:
            raise ValidationError("该任务缺少业务对象，不能自动重试")
        await self.repo.update(
            row.id,
            {
                "status_code": "QUEUED",
                "stage_code": "QUEUED",
                "stage_name": "重试排队中",
                "stage_message": reason or "任务已重新提交，等待 worker 消费",
                "progress_percent": 5,
                "queued_at": datetime.utcnow(),
                "finished_at": None,
                "heartbeat_at": datetime.utcnow(),
                "error_message": None,
            },
        )
        await self.db.commit()
        celery_task_id = self._dispatch_known_task(row)
        await self.bind_celery_task_id(row.id, celery_task_id)
        fresh = await self.repo.get_by_id(row.id)
        return self._from_async_task(fresh or row)

    async def recover_stale(self, *, stale_seconds: int = 1800) -> TaskRecoverStaleResponse:
        rows = await self.repo.list_stale(stale_seconds=stale_seconds)
        now = datetime.utcnow()
        for row in rows:
            await self.repo.update(
                row.id,
                {
                    "status_code": "STALE",
                    "stage_code": "STALE",
                    "stage_name": "心跳过期",
                    "stage_message": f"任务超过 {stale_seconds} 秒未更新心跳，已标记为可重试",
                    "finished_at": now,
                    "error_message": f"任务超过 {stale_seconds} 秒未更新心跳",
                },
            )
        await self.db.commit()
        return TaskRecoverStaleResponse(recovered_count=len(rows), stale_seconds=stale_seconds)

    def _dispatch_known_task(self, row: AsyncTaskRun) -> str:
        if row.task_name == "freight.parse_wechat_batch":
            from app.tasks.freight_ai_tasks import parse_wechat_batch_task

            result = parse_wechat_batch_task.delay(row.business_id, row.requested_by, row.id)
            return str(result.id)
        if row.task_name == "freight.parse_tms_inbound":
            from app.tasks.freight_ai_tasks import parse_tms_inbound_task

            result = parse_tms_inbound_task.delay(row.business_id, row.requested_by, row.id)
            return str(result.id)
        if row.task_name == "freight.clean_normalization":
            from app.tasks.freight_ai_tasks import clean_freight_normalization_task

            result = clean_freight_normalization_task.delay(row.business_id, row.requested_by, row.id)
            return str(result.id)
        if row.task_name == "route.generate_track_version":
            from app.tasks.route_tasks import generate_route_track_version_task

            extra = row.extra_json or {}
            result = generate_route_track_version_task.delay(
                row.business_id,
                {"provider_code": extra.get("provider_code")},
                row.requested_by,
                row.id,
            )
            return str(result.id)
        raise ValidationError(f"暂不支持自动重试任务：{row.task_name}")

    def _from_async_task(self, row: AsyncTaskRun) -> AsyncTaskRunResponse:
        return AsyncTaskRunResponse(
            id=int(row.id),
            source_type_code="CELERY",
            task_name=row.task_name,
            task_title=row.task_title,
            celery_task_id=row.celery_task_id,
            queue_name=row.queue_name,
            business_type=row.business_type,
            business_id=int(row.business_id) if row.business_id is not None else None,
            business_no=row.business_no,
            idempotency_key=row.idempotency_key,
            status_code=row.status_code,
            status_name=_status_name(row.status_code),
            stage_code=row.stage_code,
            stage_name=row.stage_name,
            stage_message=row.stage_message,
            progress_percent=int(row.progress_percent or 0),
            attempt=int(row.attempt or 0),
            max_retries=int(row.max_retries or 0),
            requested_by=int(row.requested_by) if row.requested_by is not None else None,
            triggered_by=row.triggered_by,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            heartbeat_at=row.heartbeat_at,
            error_message=row.error_message,
            result_json=row.result_json,
            extra_json=row.extra_json,
            retryable=row.status_code in RETRYABLE_STATUSES and row.task_name in {
                "freight.parse_wechat_batch",
                "freight.parse_tms_inbound",
                "freight.clean_normalization",
                "route.generate_track_version",
            },
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _from_analysis_run(self, row: AnalysisJobRun) -> AsyncTaskRunResponse:
        status_code = row.status_code or "UNKNOWN"
        heartbeat = row.finished_at or row.started_at or row.queued_at or row.created_at
        return AsyncTaskRunResponse(
            id=int(row.id),
            source_type_code="ANALYSIS_JOB",
            task_name="analysis.run_job",
            task_title=row.job_name,
            celery_task_id=row.celery_task_id,
            queue_name="analysis",
            business_type="ANALYSIS_JOB",
            business_id=int(row.id),
            business_no=row.job_code,
            idempotency_key=None,
            status_code=status_code,
            status_name=row.status_name or _status_name(status_code),
            stage_code=status_code,
            stage_name=row.status_name or _status_name(status_code),
            stage_message=None,
            progress_percent=100 if status_code in TERMINAL_STATUSES else 50,
            attempt=1 if row.started_at else 0,
            max_retries=0,
            requested_by=None,
            triggered_by=row.triggered_by,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            heartbeat_at=heartbeat,
            error_message=row.error_message,
            result_json=row.result_summary_json,
            extra_json={
                "module_code": row.module_code,
                "module_name": row.module_name,
                "stat_date_from": row.stat_date_from.isoformat() if row.stat_date_from else None,
                "stat_date_to": row.stat_date_to.isoformat() if row.stat_date_to else None,
                "input_rows": row.input_rows,
                "output_rows": row.output_rows,
                "affected_rows": row.affected_rows,
            },
            retryable=False,
            created_at=row.created_at,
            updated_at=None,
        )
