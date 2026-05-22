"""Freight normalization governance service."""

from __future__ import annotations

from app.modules.freight.support import *

class FreightNormalizationSuggestionService(FreightNormalizationMixin):
    AUTO_LOCATION_THRESHOLD = Decimal("0.86")
    AUTO_COMMODITY_THRESHOLD = Decimal("0.82")

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightNormalizationSuggestionRepository(db)
        self.task_repo = FreightNormalizationTaskRepository(db)
        self.freight_repo = FreightRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_tasks(self, *, page: int, page_size: int) -> PageResponse[FreightNormalizationTaskResponse]:
        rows, total = await self.task_repo.list_items(page=page, page_size=page_size)
        task_ids = [int(item.id) for item in rows]
        status_counts = await self.repo.count_status_by_tasks(task_ids)
        type_counts = await self.repo.count_type_by_tasks(task_ids)
        ctx = await _load_display_context(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[
                _to_normalization_task_response(
                    item,
                    status_counts=status_counts.get(int(item.id), {}),
                    type_counts=type_counts.get(int(item.id), {}),
                    ctx=ctx,
                )
                for item in rows
            ],
        )

    async def get_task(self, task_id: int) -> FreightNormalizationTaskResponse:
        row = await self.task_repo.get_by_id(task_id)
        if row is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        ctx = await _load_display_context(self.db)
        return _to_normalization_task_response(
            row,
            status_counts=await self.repo.count_status_by_task(task_id),
            type_counts=await self.repo.count_type_by_task(task_id),
            ctx=ctx,
        )

    async def list_task_suggestions(
        self,
        task_id: int,
        *,
        keyword: str | None,
        status_code: str | None,
        suggestion_type_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightNormalizationSuggestionResponse]:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        rows, total = await self.repo.list_by_task(
            task_id=task_id,
            keyword=keyword,
            status_code=status_code,
            suggestion_type_code=suggestion_type_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, suggestions=rows)
        return PageResponse[FreightNormalizationSuggestionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_normalization_suggestion_response(item, ctx) for item in rows],
        )

    async def quality(self) -> FreightNormalizationQualityResponse:
        freight_count = int(
            await self.db.scalar(select(func.count(Freight.id)).where(Freight.deleted_at.is_(None)))
            or 0
        )
        raw_origin_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.origin_match_level_code == "RAW", Freight.origin_city_code.is_(None)),
                )
            )
            or 0
        )
        raw_destination_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.destination_match_level_code == "RAW", Freight.destination_city_code.is_(None)),
                )
            )
            or 0
        )
        raw_commodity_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.commodity_match_level_code == "RAW", Freight.commodity_standard_id.is_(None)),
                )
            )
            or 0
        )
        pending = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationSuggestion.id)).where(
                    FreightNormalizationSuggestion.status_code == "PENDING"
                )
            )
            or 0
        )
        auto_applied = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationSuggestion.id)).where(
                    FreightNormalizationSuggestion.status_code == "AUTO_APPLIED"
                )
            )
            or 0
        )
        running_tasks = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationTask.id)).where(
                    FreightNormalizationTask.status_code.in_(["QUEUED", "RUNNING"])
                )
            )
            or 0
        )
        failed_tasks = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationTask.id)).where(FreightNormalizationTask.status_code == "FAILED")
            )
            or 0
        )
        latest = await self.task_repo.latest()
        return FreightNormalizationQualityResponse(
            freight_count=freight_count,
            raw_origin_count=raw_origin_count,
            raw_destination_count=raw_destination_count,
            raw_commodity_count=raw_commodity_count,
            pending_suggestion_count=pending,
            auto_applied_suggestion_count=auto_applied,
            running_task_count=running_tasks,
            failed_task_count=failed_tasks,
            latest_task_id=latest.id if latest is not None else None,
            latest_task_no=latest.task_no if latest is not None else None,
            latest_task_status_code=latest.status_code if latest is not None else None,
            latest_task_stage_name=latest.stage_name if latest is not None else None,
            latest_task_finished_at=latest.finished_at if latest is not None else None,
        )

    async def clean(self, operator_id: int | None = None) -> FreightNormalizationCleanResponse:
        now = datetime.utcnow()
        task = await self.task_repo.create(
            {
                "task_no": await self.sequence_service.next_code("FREIGHT_NORMALIZATION_TASK_NO"),
                "celery_task_id": None,
                "status_code": "QUEUED",
                "review_status_code": "NOT_REQUIRED",
                "stage_code": "QUEUED",
                "stage_name": "排队中",
                "stage_message": "清洗任务已提交，等待 Celery worker 消费",
                "progress_percent": 5,
                "requested_by": operator_id,
                "heartbeat_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
        task_run_service = AsyncTaskRunService(self.db)
        task_run = await task_run_service.create_queued(
            task_name="freight.clean_normalization",
            task_title="货源主数据清洗治理",
            queue_name="freight_ai",
            business_type="FREIGHT_NORMALIZATION_TASK",
            business_id=task.id,
            business_no=task.task_no,
            idempotency_key=f"freight.clean_normalization:{task.id}",
            requested_by=operator_id,
            triggered_by="manual",
            max_retries=1,
        )
        await self.db.commit()
        celery_task_id: str | None = None
        try:
            from app.tasks.freight_ai_tasks import clean_freight_normalization_task

            async_result = clean_freight_normalization_task.delay(task.id, operator_id, task_run.id)
            celery_task_id = str(async_result.id)
            task = await self.task_repo.update(task.id, {"celery_task_id": celery_task_id}) or task
            await self.db.commit()
            await task_run_service.bind_celery_task_id(task_run.id, celery_task_id)
        except Exception as exc:  # noqa: BLE001
            await task_run_service.mark_failed(task_run.id, f"清洗任务投递失败：{exc}")
            task = await self.task_repo.update(
                task.id,
                {
                    "status_code": "FAILED",
                    "stage_code": "FAILED",
                    "stage_name": "投递失败",
                    "stage_message": f"清洗任务投递失败：{exc}",
                    "error_message": f"清洗任务投递失败：{exc}",
                    "progress_percent": 100,
                    "finished_at": datetime.utcnow(),
                    "heartbeat_at": datetime.utcnow(),
                },
            ) or task
            await self.db.commit()
            raise ValidationError(f"清洗任务投递失败：{exc}") from exc
        return self._clean_response_from_task(task, message="清洗任务已提交，正在后台执行")

    def _clean_response_from_task(self, task: FreightNormalizationTask, *, message: str | None = None) -> FreightNormalizationCleanResponse:
        result_json = task.result_json or {}
        affected_from = result_json.get("affected_date_from")
        affected_to = result_json.get("affected_date_to")
        if isinstance(affected_from, str):
            affected_from = datetime.fromisoformat(affected_from) if affected_from else None
        if isinstance(affected_to, str):
            affected_to = datetime.fromisoformat(affected_to) if affected_to else None
        return FreightNormalizationCleanResponse(
            task_id=task.id,
            task_no=task.task_no,
            celery_task_id=task.celery_task_id,
            status_code=task.status_code,
            review_status_code=getattr(task, "review_status_code", None) or "NOT_REQUIRED",
            stage_name=task.stage_name,
            message=message or task.stage_message,
            scanned_count=task.scanned_count,
            suggestion_count=task.suggestion_count,
            auto_applied_count=task.auto_applied_count,
            pending_count=task.pending_count,
            affected_date_from=affected_from,
            affected_date_to=affected_to,
        )

    async def _update_clean_task(
        self,
        task_id: int,
        *,
        status_code: str | None = None,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        progress_percent: int,
        **extra: Any,
    ) -> None:
        updates: dict[str, Any] = {
            "stage_code": stage_code,
            "stage_name": stage_name,
            "stage_message": stage_message,
            "progress_percent": max(0, min(int(progress_percent), 100)),
            "heartbeat_at": datetime.utcnow(),
            **extra,
        }
        if status_code is not None:
            updates["status_code"] = status_code
        await self.task_repo.update(task_id, updates)
        await self.db.commit()

    async def run_clean_now(self, task_id: int, operator_id: int | None = None) -> FreightNormalizationCleanResponse:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        started = datetime.utcnow()
        await self._update_clean_task(
            task_id,
            status_code="RUNNING",
            stage_code="SCANNING",
            stage_name="扫描正式货源",
            stage_message="正在扫描原文级、缺城市、缺节点和缺标准货品的正式货源",
            progress_percent=12,
            started_at=started,
            error_message=None,
        )
        rows = (
            await self.db.execute(
                select(Freight)
                .where(
                    Freight.deleted_at.is_(None),
                    or_(
                        Freight.origin_match_level_code == "RAW",
                        Freight.origin_city_code.is_(None),
                        Freight.destination_match_level_code == "RAW",
                        Freight.destination_city_code.is_(None),
                        Freight.commodity_match_level_code == "RAW",
                        Freight.commodity_standard_id.is_(None),
                    ),
                )
                .order_by(Freight.id.asc())
            )
        ).scalars().all()
        await self._update_clean_task(
            task_id,
            status_code="RUNNING",
            stage_code="MATCHING",
            stage_name="AI 清洗匹配",
            stage_message=f"已扫描 {len(rows)} 条正式货源，正在生成标准化建议",
            progress_percent=30,
            scanned_count=len(rows),
        )
        suggestion_count = 0
        auto_applied_count = 0
        pending_count = 0
        failed_count = 0
        affected_dates: list[datetime] = []
        total = max(len(rows), 1)
        for index, freight in enumerate(rows, start=1):
            for suggestion_type in ("ORIGIN", "DESTINATION", "COMMODITY"):
                try:
                    suggestion = await self._suggest_for_freight(freight, suggestion_type, clean_task_id=task_id)
                    if suggestion is None:
                        continue
                    suggestion_count += 1
                    if suggestion.auto_apply_flag:
                        await self._apply_suggestion(suggestion, operator_id=operator_id, auto=True)
                        auto_applied_count += 1
                        affected_date = freight.published_at or freight.confirmed_at or freight.created_at
                        if affected_date is not None:
                            affected_dates.append(affected_date)
                    else:
                        pending_count += 1
                except Exception:  # noqa: BLE001
                    failed_count += 1
                    continue
            if index == len(rows) or index % 10 == 0:
                await self._update_clean_task(
                    task_id,
                    status_code="RUNNING",
                    stage_code="MATCHING",
                    stage_name="AI 清洗匹配",
                    stage_message=f"正在清洗正式货源 {index}/{len(rows)}",
                    progress_percent=30 + int(index / total * 45),
                    scanned_count=len(rows),
                    suggestion_count=suggestion_count,
                    auto_applied_count=auto_applied_count,
                    pending_count=pending_count,
                    failed_count=failed_count,
                )
        await self.db.commit()
        if affected_dates:
            await self._update_clean_task(
                task_id,
                status_code="RUNNING",
                stage_code="REBUILD_ANALYSIS",
                stage_name="重算分析事实",
                stage_message="自动提升已回填，正在重算受影响的货源态势事实",
                progress_percent=86,
            )
            await self._rebuild_affected_analysis(min(affected_dates), max(affected_dates))
        finished = datetime.utcnow()
        review_status_code = "PENDING_REVIEW" if pending_count > 0 else "NOT_REQUIRED"
        status_counts = await self.repo.count_status_by_task(task_id)
        type_counts = await self.repo.count_type_by_task(task_id)
        task = await self.task_repo.update(
            task_id,
            {
                "status_code": "SUCCESS" if failed_count == 0 else "PARTIAL_SUCCESS",
                "review_status_code": review_status_code,
                "review_completed_at": finished if review_status_code == "NOT_REQUIRED" else None,
                "stage_code": "DONE",
                "stage_name": "清洗完成",
                "stage_message": "正式货源清洗任务已完成" if pending_count == 0 else f"清洗执行完成，仍有 {pending_count} 条建议待确认",
                "progress_percent": 100,
                "scanned_count": len(rows),
                "suggestion_count": suggestion_count,
                "auto_applied_count": auto_applied_count,
                "pending_count": pending_count,
                "failed_count": failed_count,
                "finished_at": finished,
                "heartbeat_at": finished,
                "result_json": {
                    "affected_date_from": min(affected_dates).isoformat() if affected_dates else None,
                    "affected_date_to": max(affected_dates).isoformat() if affected_dates else None,
                    "suggestion_status_counts": status_counts,
                    "suggestion_type_counts": type_counts,
                },
            },
        ) or task
        await self.db.commit()
        return self._clean_response_from_task(
            task,
            message=f"已扫描 {len(rows)} 条，自动提升 {auto_applied_count} 条，待确认 {pending_count} 条",
        )

    async def _get_task_suggestion(self, task_id: int, suggestion_id: int) -> FreightNormalizationSuggestion:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        row = await self.repo.get_by_task_and_id(task_id, suggestion_id)
        if row is None:
            raise NotFoundError("FreightNormalizationSuggestion", suggestion_id)
        return row

    async def _refresh_task_review_state(self, task_id: int) -> FreightNormalizationTask:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        status_counts = await self.repo.count_status_by_task(task_id)
        type_counts = await self.repo.count_type_by_task(task_id)
        pending_count = status_counts.get("PENDING", 0)
        applied_count = status_counts.get("APPLIED", 0)
        auto_applied_count = status_counts.get("AUTO_APPLIED", 0)
        rejected_count = status_counts.get("REJECTED", 0)
        suggestion_count = sum(status_counts.values())
        if pending_count > 0:
            review_status_code = "PENDING_REVIEW"
            review_completed_at = None
        elif task.status_code in {"SUCCESS", "PARTIAL_SUCCESS"} and (
            applied_count > 0 or rejected_count > 0 or getattr(task, "review_status_code", None) == "PENDING_REVIEW"
        ):
            review_status_code = "COMPLETED"
            review_completed_at = datetime.utcnow()
        else:
            review_status_code = "NOT_REQUIRED"
            review_completed_at = getattr(task, "finished_at", None)

        result_json = dict(task.result_json or {})
        result_json["suggestion_status_counts"] = status_counts
        result_json["suggestion_type_counts"] = type_counts
        return await self.task_repo.update(
            task_id,
            {
                "suggestion_count": suggestion_count,
                "auto_applied_count": auto_applied_count,
                "pending_count": pending_count,
                "review_status_code": review_status_code,
                "review_completed_at": review_completed_at,
                "result_json": result_json,
                "updated_at": datetime.utcnow(),
            },
        ) or task

    async def apply(self, task_id: int, suggestion_id: int, operator_id: int | None = None) -> FreightNormalizationSuggestionResponse:
        row = await self._get_task_suggestion(task_id, suggestion_id)
        if row.status_code != "PENDING":
            raise ValidationError("只有待确认清洗建议可以应用")
        freight = await self.freight_repo.get_freight_by_id(row.freight_id)
        affected_date = (freight.published_at or freight.confirmed_at or freight.created_at) if freight is not None else None
        await self._apply_suggestion(row, operator_id=operator_id, auto=False)
        await self._refresh_task_review_state(task_id)
        await self.db.commit()
        if affected_date is not None:
            await self._rebuild_affected_analysis(affected_date, affected_date)
        ctx = await _load_display_context(self.db, suggestions=[row])
        return _to_normalization_suggestion_response(row, ctx)

    async def reject(self, task_id: int, suggestion_id: int, operator_id: int | None = None) -> FreightNormalizationSuggestionResponse:
        row = await self._get_task_suggestion(task_id, suggestion_id)
        if row.status_code != "PENDING":
            raise ValidationError("只有待确认清洗建议可以拒绝")
        row = await self.repo.update(
            suggestion_id,
            {"status_code": "REJECTED", "rejected_at": datetime.utcnow(), "rejected_by": operator_id},
        ) or row
        await self._refresh_task_review_state(task_id)
        await self.db.commit()
        ctx = await _load_display_context(self.db, suggestions=[row])
        return _to_normalization_suggestion_response(row, ctx)

    async def bulk_apply(self, task_id: int, payload, operator_id: int | None = None) -> FreightNormalizationBulkActionResponse:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        suggestion_ids = [int(item) for item in (payload.suggestion_ids or []) if int(item) > 0]
        if not payload.apply_all_filtered and not suggestion_ids:
            raise ValidationError("请选择要批量应用的清洗建议")
        rows = await self.repo.list_pending_for_task_bulk(
            task_id=task_id,
            suggestion_ids=None if payload.apply_all_filtered else suggestion_ids,
            keyword=(payload.keyword or "").strip() or None,
            suggestion_type_code=(payload.suggestion_type_code or "").strip() or None,
        )
        applied_count = 0
        skipped: list[dict[str, Any]] = []
        affected_dates: list[datetime] = []
        for row in rows:
            try:
                freight = await self.freight_repo.get_freight_by_id(row.freight_id)
                await self._apply_suggestion(row, operator_id=operator_id, auto=False)
                applied_count += 1
                if freight is not None:
                    affected_date = freight.published_at or freight.confirmed_at or freight.created_at
                    if affected_date is not None:
                        affected_dates.append(affected_date)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"suggestion_id": row.id, "reason": str(exc)})
        await self._refresh_task_review_state(task_id)
        await self.db.commit()
        if affected_dates:
            await self._rebuild_affected_analysis(min(affected_dates), max(affected_dates))
        return FreightNormalizationBulkActionResponse(
            processed_count=applied_count,
            skipped_count=len(skipped),
            skipped=skipped,
        )

    async def bulk_reject(self, task_id: int, payload, operator_id: int | None = None) -> FreightNormalizationBulkActionResponse:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        suggestion_ids = [int(item) for item in (payload.suggestion_ids or []) if int(item) > 0]
        if not payload.apply_all_filtered and not suggestion_ids:
            raise ValidationError("请选择要批量拒绝的清洗建议")
        rows = await self.repo.list_pending_for_task_bulk(
            task_id=task_id,
            suggestion_ids=None if payload.apply_all_filtered else suggestion_ids,
            keyword=(payload.keyword or "").strip() or None,
            suggestion_type_code=(payload.suggestion_type_code or "").strip() or None,
        )
        rejected_count = 0
        skipped: list[dict[str, Any]] = []
        for row in rows:
            try:
                await self.repo.update(
                    int(row.id),
                    {"status_code": "REJECTED", "rejected_at": datetime.utcnow(), "rejected_by": operator_id},
                )
                rejected_count += 1
            except Exception as exc:  # noqa: BLE001
                skipped.append({"suggestion_id": row.id, "reason": str(exc)})
        await self._refresh_task_review_state(task_id)
        await self.db.commit()
        return FreightNormalizationBulkActionResponse(
            processed_count=rejected_count,
            skipped_count=len(skipped),
            skipped=skipped,
        )

    async def _suggest_for_freight(
        self, freight: Freight, suggestion_type: str, *, clean_task_id: int | None = None
    ) -> FreightNormalizationSuggestion | None:
        current = await self.repo.find_open(freight.id, suggestion_type)
        if current is not None:
            return None
        if suggestion_type == "ORIGIN":
            if freight.origin_match_level_code != "RAW" and freight.origin_city_code:
                return None
            raw_text = freight.raw_origin_text
            normalized, options, basis = await self._match_location(raw_text or "")
            return await self._create_location_suggestion(freight, suggestion_type, raw_text, freight.origin_match_level_code, normalized, options, basis, clean_task_id=clean_task_id)
        if suggestion_type == "DESTINATION":
            if freight.destination_match_level_code != "RAW" and freight.destination_city_code:
                return None
            raw_text = freight.raw_destination_text
            normalized, options, basis = await self._match_location(raw_text or "")
            return await self._create_location_suggestion(freight, suggestion_type, raw_text, freight.destination_match_level_code, normalized, options, basis, clean_task_id=clean_task_id)
        if freight.commodity_match_level_code != "RAW" and freight.commodity_standard_id is not None:
            return None
        raw_text = freight.raw_commodity_name or freight.cargo_title
        commodity_id, score, level, options, basis = await self._match_commodity(raw_text or "")
        if commodity_id is None or level == "RAW":
            return None
        return await self._create_suggestion(
            freight=freight,
            clean_task_id=clean_task_id,
            suggestion_type_code="COMMODITY",
            raw_text=raw_text,
            current_level_code=freight.commodity_match_level_code,
            suggested_level_code="STANDARD",
            confidence_score=score,
            auto_apply_flag=score is not None and score >= self.AUTO_COMMODITY_THRESHOLD,
            match_basis_json={"commodity": basis, "options": options},
            suggested_commodity_standard_id=commodity_id,
        )

    async def _create_location_suggestion(
        self,
        freight: Freight,
        suggestion_type: str,
        raw_text: str | None,
        current_level: str | None,
        normalized: dict[str, Any],
        options: list[dict[str, Any]],
        basis: dict[str, Any],
        clean_task_id: int | None = None,
    ) -> FreightNormalizationSuggestion | None:
        level = normalized.get("match_level_code")
        if level not in {"NODE", "CITY"}:
            return None
        score = _to_decimal_or_none(normalized.get("match_score")) or Decimal("0")
        return await self._create_suggestion(
            freight=freight,
            clean_task_id=clean_task_id,
            suggestion_type_code=suggestion_type,
            raw_text=raw_text,
            current_level_code=current_level,
            suggested_level_code=level,
            suggested_node_id=normalized.get("node_id"),
            suggested_province_code=normalized.get("province_code"),
            suggested_city_code=normalized.get("city_code"),
            suggested_district_code=normalized.get("district_code"),
            suggested_region_id=normalized.get("region_id"),
            confidence_score=score,
            auto_apply_flag=score >= self.AUTO_LOCATION_THRESHOLD,
            match_basis_json={"location": basis, "options": options},
        )

    async def _create_suggestion(self, **data: Any) -> FreightNormalizationSuggestion:
        now = datetime.utcnow()
        freight = data.pop("freight")
        auto_apply = bool(data.get("auto_apply_flag"))
        return await self.repo.create(
            {
                "freight_id": freight.id,
                "status_code": "PENDING",
                "before_json": _entity_snapshot(freight, self._freight_snapshot_fields()),
                "created_at": now,
                "updated_at": now,
                **data,
                "auto_apply_flag": auto_apply,
            }
        )

    async def _apply_suggestion(self, row: FreightNormalizationSuggestion, *, operator_id: int | None, auto: bool) -> None:
        freight = await self.freight_repo.get_freight_by_id(row.freight_id)
        if freight is None:
            raise NotFoundError("Freight", row.freight_id)
        updates = self._updates_from_suggestion(row)
        after_preview = dict(_entity_snapshot(freight, self._freight_snapshot_fields()))
        after_preview.update(_compact_json_value(updates))
        await self.freight_repo.update_freight(freight.id, updates)
        await self.repo.update(
            row.id,
            {
                "status_code": "AUTO_APPLIED" if auto else "APPLIED",
                "after_json": after_preview,
                "applied_at": datetime.utcnow(),
                "applied_by": operator_id,
            },
        )

    def _updates_from_suggestion(self, row: FreightNormalizationSuggestion) -> dict[str, Any]:
        if row.suggestion_type_code == "COMMODITY":
            return {
                "commodity_standard_id": row.suggested_commodity_standard_id,
                "commodity_match_level_code": row.suggested_level_code,
            }
        prefix = "origin" if row.suggestion_type_code == "ORIGIN" else "destination"
        return {
            f"{prefix}_node_id": row.suggested_node_id,
            f"{prefix}_province_code": row.suggested_province_code,
            f"{prefix}_city_code": row.suggested_city_code,
            f"{prefix}_district_code": row.suggested_district_code,
            f"{prefix}_region_id_cache": row.suggested_region_id,
            f"{prefix}_match_level_code": row.suggested_level_code,
        }

    async def _rebuild_affected_analysis(self, start_at: datetime, end_at: datetime) -> None:
        from app.modules.analysis.statistics import AnalysisStatisticsService

        service = AnalysisStatisticsService(self.db)
        start = start_at.date()
        end = end_at.date()
        await service.run_freight_flow_daily(start, end)
        await service.run_freight_commodity_daily(start, end)
        await service.run_freight_city_daily(start, end)
        await service.run_freight_node_daily(start, end)
        await self.db.commit()

    @staticmethod
    def _freight_snapshot_fields() -> list[str]:
        return [
            "freight_no",
            "cargo_title",
            "raw_commodity_name",
            "commodity_standard_id",
            "commodity_match_level_code",
            "raw_origin_text",
            "origin_node_id",
            "origin_city_code",
            "origin_match_level_code",
            "raw_destination_text",
            "destination_node_id",
            "destination_city_code",
            "destination_match_level_code",
        ]


