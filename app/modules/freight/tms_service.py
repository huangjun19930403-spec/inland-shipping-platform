"""TMS inbound freight parsing service."""

from __future__ import annotations

from app.modules.freight.support import *

class FreightTmsInboundService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightTmsInboundRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightTmsInboundResponse]:
        rows, total = await self.repo.list_items(keyword=keyword, status_code=status_code, page=page, page_size=page_size)
        ctx = await _load_display_context(self.db, tms_inbounds=rows)
        return PageResponse[FreightTmsInboundResponse](total=total, page=page, page_size=page_size, items=[_to_tms_response(item, ctx) for item in rows])

    async def create(self, payload) -> FreightTmsInboundResponse:
        existing = await self.repo.get_by_idempotency_key(payload.idempotency_key.strip())
        if existing is not None:
            ctx = await _load_display_context(self.db, tms_inbounds=[existing])
            return _to_tms_response(existing, ctx)
        inbound_no = (payload.inbound_no or "").strip() or await self.sequence_service.next_code("FREIGHT_TMS_INBOUND_NO")
        raw_content = (payload.raw_content or "").strip() or json.dumps(payload.payload_json, ensure_ascii=False)
        row = await self.repo.create(
            {
                "inbound_no": inbound_no,
                "source_type_code": "TMS",
                "source_channel_code": payload.source_channel_code,
                "source_trace_id": payload.source_trace_id,
                "idempotency_key": payload.idempotency_key.strip(),
                "external_ref_no": payload.external_ref_no,
                "payload_json": payload.payload_json,
                "raw_content": raw_content,
                "status_code": "NEW",
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, tms_inbounds=[row])
        return _to_tms_response(row, ctx)

    async def get_detail(self, inbound_id: int) -> FreightTmsInboundDetailResponse:
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        clues = await self.clue_repo.list_by_tms_inbound(inbound_id)
        candidates = await self.candidate_repo.list_by_tms_inbound(inbound_id)
        ctx = await _load_display_context(self.db, tms_inbounds=[inbound], clues=clues, candidates=candidates)
        return FreightTmsInboundDetailResponse(
            inbound=_to_tms_response(inbound, ctx),
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
        )

    async def parse(self, inbound_id: int, requested_by: int | None = None) -> FreightTmsInboundDetailResponse:
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        if inbound.status_code == "PARSING":
            return await self.get_detail(inbound_id)
        await self.repo.update(inbound_id, {"status_code": "QUEUED", "error_message": None})
        task_run_service = AsyncTaskRunService(self.db)
        task_run = await task_run_service.create_queued(
            task_name="freight.parse_tms_inbound",
            task_title="TMS 入站货源解析",
            queue_name="freight_ai",
            business_type="FREIGHT_TMS_INBOUND",
            business_id=inbound_id,
            business_no=inbound.inbound_no,
            idempotency_key=f"freight.parse_tms_inbound:{inbound_id}",
            requested_by=requested_by,
            triggered_by="manual",
            max_retries=1,
            extra_json={"source_trace_id": inbound.source_trace_id, "external_ref_no": inbound.external_ref_no},
        )
        should_dispatch = not (
            task_run.celery_task_id
            and task_run.status_code in {"QUEUED", "STARTED", "RUNNING", "RETRYING"}
        )
        await self.db.commit()
        if not should_dispatch:
            return await self.get_detail(inbound_id)
        try:
            from app.tasks.freight_ai_tasks import parse_tms_inbound_task

            async_result = parse_tms_inbound_task.delay(inbound_id, requested_by, task_run.id)
            await task_run_service.bind_celery_task_id(task_run.id, str(async_result.id))
        except Exception as exc:  # noqa: BLE001
            await task_run_service.mark_failed(task_run.id, f"解析任务投递失败：{exc}")
            await self.repo.update(inbound_id, {"status_code": "FAILED", "processed_at": datetime.utcnow(), "error_message": f"解析任务投递失败：{exc}"})
            await self.db.commit()
            raise ValidationError(f"解析任务投递失败：{exc}") from exc
        return await self.get_detail(inbound_id)

    async def run_parse_now(self, inbound_id: int, requested_by: int | None = None) -> FreightTmsInboundDetailResponse:
        _ = requested_by
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        existing = await self.candidate_repo.list_by_tms_inbound(inbound_id)
        if inbound.status_code == "PARSED" and existing:
            return await self.get_detail(inbound_id)
        clue_ids = await self.candidate_repo.delete_unconfirmed_by_tms_inbound(inbound_id)
        await self.clue_repo.delete_by_ids(clue_ids)
        await self.repo.update(inbound_id, {"status_code": "PARSING", "error_message": None})
        await self.db.commit()
        client = DashScopeQwenFreightParserClient(runtime_config=RuntimeConfigService(self.db))
        try:
            parsed = await client.parse(inbound.raw_content, source_type_code="TMS")
            clue_count = 0
            candidate_count = 0
            failed_count = 0
            for index, segment in enumerate(parsed.segments, start=1):
                try:
                    clue = await self.clue_repo.create(
                        {
                            "clue_no": await self.sequence_service.next_code("FREIGHT_CLUE_NO"),
                            "source_type_code": "TMS",
                            "source_channel_code": inbound.source_channel_code,
                            "source_batch_id": None,
                            "source_tms_inbound_id": inbound_id,
                            "segment_index": index,
                            "semantic_role_code": _first(segment, "semantic_role_code", "role_code") or "ROUTE",
                            "raw_text": str(segment.get("raw_text") or inbound.raw_content),
                            "line_refs_json": segment.get("line_refs") or segment.get("line_refs_json"),
                            "context_summary": segment.get("context_summary"),
                            "extracted_fields_json": segment,
                            "quality_score": _to_decimal_or_none(segment.get("confidence_score")),
                            "status_code": "CANDIDATE_CREATED",
                        }
                    )
                    await self.candidate_repo.create(
                        await self._candidate_from_segment(
                            source_type_code="TMS",
                            source_channel_code=inbound.source_channel_code,
                            source_batch_id=None,
                            source_tms_inbound_id=inbound_id,
                            clue_id=clue.id,
                            segment=segment,
                        )
                    )
                    clue_count += 1
                    candidate_count += 1
                except Exception:  # noqa: BLE001
                    failed_count += 1
                    continue
            status = "PARSED" if candidate_count and failed_count == 0 else "PARTIAL_FAILED" if candidate_count else "FAILED"
            await self.repo.update(
                inbound_id,
                {
                    "status_code": status,
                    "clue_count": clue_count,
                    "candidate_count": candidate_count,
                    "processed_at": datetime.utcnow(),
                    "prompt_version": parsed.prompt_version,
                    "raw_response_json": {"parsed_payload": parsed.parsed_payload, "raw_response": parsed.raw_response},
                },
            )
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.db.rollback()
            await self.repo.update(inbound_id, {"status_code": "FAILED", "processed_at": datetime.utcnow(), "error_message": message})
            await self.db.commit()
            raise
        return await self.get_detail(inbound_id)


