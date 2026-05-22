"""Wechat freight batch parsing and review handoff service."""

from __future__ import annotations

from app.modules.freight.support import *

class FreightBatchTaskService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightBatchTaskRepository(db)
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
    ) -> PageResponse[FreightBatchResponse]:
        rows, total = await self.repo.list_items(keyword=keyword, status_code=status_code, page=page, page_size=page_size)
        ctx = await _load_display_context(self.db, batches=rows)
        ctx["batch_candidate_summary"] = await self._batch_candidate_summary([int(item.id) for item in rows])
        ctx["stale_heartbeat_seconds"] = await self._stale_heartbeat_seconds()
        return PageResponse[FreightBatchResponse](total=total, page=page, page_size=page_size, items=[_to_batch_response(item, ctx) for item in rows])

    async def _batch_candidate_summary(self, batch_ids: list[int]) -> dict[int, dict[str, Any]]:
        rows = await self.candidate_repo.list_by_batch_ids(batch_ids)
        summary: dict[int, dict[str, Any]] = {}
        for item in rows:
            if item.source_batch_id is None:
                continue
            data = summary.setdefault(
                int(item.source_batch_id),
                {
                    "candidate_count": 0,
                    "pending_count": 0,
                    "confirmed_count": 0,
                    "rejected_count": 0,
                    "ready_count": 0,
                    "review_count": 0,
                    "routes": [],
                    "contacts": set(),
                },
            )
            data["candidate_count"] += 1
            if item.status_code == "PENDING":
                data["pending_count"] += 1
            if item.status_code == "CONFIRMED":
                data["confirmed_count"] += 1
            if item.status_code == "REJECTED":
                data["rejected_count"] += 1
            if item.status_code == "PENDING" and item.availability_status_code == "READY" and _candidate_ai_review_pass(item):
                data["ready_count"] += 1
            elif item.status_code == "PENDING":
                data["review_count"] += 1
            origin = item.raw_origin_text or item.origin_city_code or "-"
            dest = item.raw_destination_text or item.destination_city_code or "-"
            commodity = item.raw_commodity_name or item.commodity_match_name or ""
            data["routes"].append(f"{origin}->{dest}{f' {commodity}' if commodity else ''}")
            if item.contact_phone:
                data["contacts"].add(f"{item.contact_name or ''}{item.contact_phone}".strip())
        for data in summary.values():
            routes = data.pop("routes")
            contacts = sorted(data.pop("contacts"))
            data["route_summary"] = "；".join(routes[:3]) + ("..." if len(routes) > 3 else "") if routes else None
            data["contact_summary"] = "、".join(contacts[:3]) if contacts else None
        return summary

    async def _stale_heartbeat_seconds(self) -> int:
        value = await RuntimeConfigService(self.db).get_int(
            FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
            settings.FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return max(30, value)

    async def _update_parse_progress(
        self,
        batch_id: int,
        *,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        percent: int,
        started_at: datetime | None,
        status_code: str | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        now = datetime.utcnow()
        updates: dict[str, Any] = {
            "parse_stage_code": stage_code,
            "parse_stage_name": stage_name,
            "parse_stage_message": stage_message,
            "parse_progress_percent": max(0, min(int(percent), 100)),
            "parse_heartbeat_at": now,
            "ai_elapsed_seconds": int((now - started_at).total_seconds()) if started_at else 0,
        }
        if status_code is not None:
            updates["status_code"] = status_code
        if error_message is not None:
            updates["error_message"] = error_message
        if finished_at is not None:
            updates["finished_at"] = finished_at
        await self.repo.update(batch_id, updates)
        await self.db.commit()

    async def _progress_callback(self, batch_id: int, started_at: datetime):
        last_update = {"at": 0.0, "stage": ""}

        async def callback(stage_code: str, stage_name: str, stage_message: str, percent: int) -> None:
            import time

            now = time.monotonic()
            if last_update["stage"] == stage_code and now - float(last_update["at"]) < 3:
                return
            last_update["stage"] = stage_code
            last_update["at"] = now
            await self._update_parse_progress(
                batch_id,
                stage_code=stage_code,
                stage_name=stage_name,
                stage_message=stage_message,
                percent=percent,
                started_at=started_at,
                status_code="PARSING",
            )

        return callback

    async def create_wechat_batch(self, payload, creator_id: int | None) -> FreightBatchResponse:
        batch_no = (payload.batch_no or "").strip() or await self.sequence_service.next_code("FREIGHT_BATCH_NO")
        row = await self.repo.create(
            {
                "batch_no": batch_no,
                "source_type_code": "WECHAT",
                "source_channel_code": "WECHAT_TEXT",
                "raw_text": payload.raw_text.strip(),
                "status_code": "NEW",
                "review_flow_status_code": "REVIEWING",
                "parse_stage_code": "NEW",
                "parse_stage_name": "待解析",
                "parse_stage_message": "批次已保存，尚未提交 AI 解析",
                "parse_progress_percent": 0,
                "ai_elapsed_seconds": 0,
                "ai_pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
                "creator_id": creator_id,
                "remark": payload.remark,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, batches=[row])
        return _to_batch_response(row, ctx)

    async def get_detail(self, batch_id: int) -> FreightBatchDetailResponse:
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        clues = await self.clue_repo.list_by_batch(batch_id)
        candidates = await self.candidate_repo.list_by_batch(batch_id)
        ctx = await _load_display_context(self.db, batches=[batch], clues=clues, candidates=candidates)
        ctx["batch_candidate_summary"] = await self._batch_candidate_summary([batch_id])
        ctx["stale_heartbeat_seconds"] = await self._stale_heartbeat_seconds()
        return FreightBatchDetailResponse(
            batch=_to_batch_response(batch, ctx),
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
        )

    async def parse(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        existing = await self.candidate_repo.list_by_batch(batch_id)
        if any(item.status_code == "CONFIRMED" or item.confirmed_freight_id is not None for item in existing):
            raise ValidationError("该解析批次已有确认入库货源，不能重新解析")
        if str(getattr(batch, "review_flow_status_code", "") or "").upper() == "QUEUED_FOR_REVIEW":
            raise ValidationError("该解析批次已移交待确认候选证据池，不能重新解析")
        if batch.status_code == "PARSING":
            stale_seconds = await self._stale_heartbeat_seconds()
            heartbeat = batch.parse_heartbeat_at or batch.updated_at or batch.started_at
            if heartbeat and datetime.utcnow() - heartbeat < timedelta(seconds=stale_seconds):
                return await self.get_detail(batch_id)
        now = datetime.utcnow()
        await self.repo.update(
            batch_id,
            {
                "status_code": "QUEUED",
                "review_flow_status_code": "REVIEWING",
                "error_message": None,
                "finished_at": None,
                "parse_stage_code": "QUEUED",
                "parse_stage_name": "排队中",
                "parse_stage_message": "解析任务已提交，等待 Celery worker 消费",
                "parse_progress_percent": 5,
                "parse_heartbeat_at": now,
                "ai_elapsed_seconds": 0,
            },
        )
        task_run_service = AsyncTaskRunService(self.db)
        task_run = await task_run_service.create_queued(
            task_name="freight.parse_wechat_batch",
            task_title="微信货源语义解析",
            queue_name="freight_ai",
            business_type="FREIGHT_BATCH",
            business_id=batch_id,
            business_no=batch.batch_no,
            idempotency_key=f"freight.parse_wechat_batch:{batch_id}",
            requested_by=requested_by,
            triggered_by="manual",
            max_retries=1,
            extra_json={"source_type_code": batch.source_type_code, "source_channel_code": batch.source_channel_code},
        )
        should_dispatch = not (
            task_run.celery_task_id
            and task_run.status_code in {"QUEUED", "STARTED", "RUNNING", "RETRYING"}
        )
        await self.db.commit()
        if not should_dispatch:
            return await self.get_detail(batch_id)
        try:
            from app.tasks.freight_ai_tasks import parse_wechat_batch_task

            async_result = parse_wechat_batch_task.delay(batch_id, requested_by, task_run.id)
            await task_run_service.bind_celery_task_id(task_run.id, str(async_result.id))
        except Exception as exc:  # noqa: BLE001
            await task_run_service.mark_failed(task_run.id, f"解析任务投递失败：{exc}")
            await self.repo.update(
                batch_id,
                {
                    "status_code": "FAILED",
                    "finished_at": datetime.utcnow(),
                    "error_message": f"解析任务投递失败：{exc}",
                    "parse_stage_code": "FAILED",
                    "parse_stage_name": "投递失败",
                    "parse_stage_message": f"解析任务投递失败：{exc}",
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": datetime.utcnow(),
                },
            )
            await self.db.commit()
            raise ValidationError(f"解析任务投递失败：{exc}") from exc
        return await self.get_detail(batch_id)

    async def run_parse_now(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        _ = requested_by
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        existing = await self.candidate_repo.list_by_batch(batch_id)
        if any(item.status_code == "CONFIRMED" or item.confirmed_freight_id is not None for item in existing):
            raise ValidationError("该解析批次已有确认入库货源，不能重新解析")
        if str(getattr(batch, "review_flow_status_code", "") or "").upper() == "QUEUED_FOR_REVIEW":
            raise ValidationError("该解析批次已移交待确认候选证据池，不能重新解析")
        if batch.status_code == "PARSED" and existing:
            return await self.get_detail(batch_id)
        started = datetime.utcnow()
        timings: dict[str, Any] = {}
        timer_started = time.monotonic()

        def mark_timing(stage_code: str) -> None:
            timings[stage_code] = int((time.monotonic() - timer_started) * 1000)

        await self.repo.update(
            batch_id,
            {
                "status_code": "PARSING",
                "review_flow_status_code": "REVIEWING",
                "started_at": started,
                "finished_at": None,
                "error_message": None,
                "parse_stage_code": "PREPARE",
                "parse_stage_name": "准备解析",
                "parse_stage_message": "系统正在准备原文行号索引和解析上下文",
                "parse_progress_percent": 8,
                "parse_heartbeat_at": started,
                "ai_elapsed_seconds": 0,
            },
        )
        await self.db.commit()
        client = DashScopeQwenFreightParserClient(runtime_config=RuntimeConfigService(self.db))
        try:
            callback = await self._progress_callback(batch_id, started)
            repair_records: list[dict[str, Any]] = []
            if hasattr(client, "parse_semantic_map") and hasattr(client, "complete_candidate_fields"):
                runtime = await client._runtime()  # noqa: SLF001 - staged orchestration uses the parser runtime contract.
                runtime.setdefault("budget", FreightParseBudget())
                indexed_text = FreightTextIndexer().index(batch.raw_text)
                skeleton = FreightStructuralSkeletonBuilder().build(indexed_text)
                mark_timing("SKELETON_BUILD")
                try:
                    semantic_map, semantic_raw = await client.parse_semantic_map(
                        indexed_text,
                        runtime=runtime,
                        progress_callback=callback,
                    )
                except Exception as exc:  # noqa: BLE001
                    semantic_raw = {"error": str(exc), "fallback": "LOCAL_SKELETON"}
                    semantic_map = {
                        "route_clues": [],
                        "context_blocks": [],
                        "context_notes": [],
                        "warnings": [f"AI_SEMANTIC_MAP_FAILED:{exc}"],
                    }
                semantic_map = apply_skeleton_to_semantic_map(semantic_map, skeleton)
                semantic_map["performance_budget"] = runtime["budget"].as_dict() if runtime.get("budget") else {}
                validator = FreightSemanticValidator(indexed_text)
                semantic_warnings = validator.validate_semantic_map(semantic_map)
                semantic_gate = validate_semantic_map_contract(indexed_text, semantic_map)
                patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
                if (
                    should_call_ai_repair(semantic_gate)
                    and hasattr(client, "repair_semantic_output")
                    and len(semantic_map.get("route_clues") or []) <= 8
                ):
                    try:
                        repaired_map, _, repair_raw = await client.repair_semantic_output(
                            indexed_text,
                            semantic_map,
                            [],
                            semantic_gate.issues,
                            runtime=runtime,
                            progress_callback=callback,
                            stage_code="AI_SEMANTIC_REPAIR",
                            progress_percent=36,
                        )
                        repair_records.append({"stage": "semantic", **repair_raw})
                        semantic_map = repaired_map
                        validator = FreightSemanticValidator(indexed_text)
                        semantic_warnings.extend(validator.validate_semantic_map(semantic_map))
                        semantic_gate = validate_semantic_map_contract(indexed_text, semantic_map)
                        patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
                    except Exception as exc:  # noqa: BLE001
                        semantic_map.setdefault("warnings", []).append(f"AI_SEMANTIC_REPAIR_FAILED: {exc}")
                        patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
                elif should_call_ai_repair(semantic_gate):
                    semantic_map.setdefault("warnings", []).append("AI_SEMANTIC_REPAIR_SKIPPED_BUDGET: 本地骨架已兜底，跳过整批强模型修复")
                mark_timing("AI_SEMANTIC_MAP")

                segments, detail_raws, detail_warnings, detail_metrics = await client.complete_candidate_fields(
                    indexed_text,
                    semantic_map,
                    runtime=runtime,
                    progress_callback=callback,
                )
                segments, skeleton_fallback_warnings = ensure_segments_for_route_clues(semantic_map, segments)
                detail_warnings.extend(skeleton_fallback_warnings)
                if hasattr(client, "assign_segment_uids"):
                    client.assign_segment_uids(segments, preserve_existing=True)
                timings["AI_DETAIL_REQUEST_COUNT"] = len(detail_metrics)
                timings["AI_DETAIL_EVIDENCE_LINE_COUNTS"] = [int(item.get("evidence_line_count") or 0) for item in detail_metrics]
                timings["AI_DETAIL_BATCH_METRICS"] = detail_metrics
                semantic_warnings.extend(validator.validate_segments(semantic_map, segments))
                detail_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
                patch_semantic_map_with_gate_result(semantic_map, detail_gate)
                if (
                    should_call_ai_repair(detail_gate)
                    and hasattr(client, "repair_semantic_output")
                    and len(segments) <= 8
                    and len(detail_gate.issues) <= 16
                ):
                    try:
                        repaired_map, repaired_segments, repair_raw = await client.repair_semantic_output(
                            indexed_text,
                            semantic_map,
                            segments,
                            detail_gate.issues,
                            runtime=runtime,
                            progress_callback=callback,
                            stage_code="AI_DETAIL_REPAIR",
                            progress_percent=69,
                        )
                        repair_records.append({"stage": "detail", **repair_raw})
                        semantic_map = repaired_map
                        segments = repaired_segments
                        if hasattr(client, "assign_segment_uids"):
                            client.assign_segment_uids(segments, preserve_existing=True)
                        validator = FreightSemanticValidator(indexed_text)
                        semantic_warnings.extend(validator.validate_semantic_map(semantic_map))
                        semantic_warnings.extend(validator.validate_segments(semantic_map, segments))
                        detail_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
                        patch_semantic_map_with_gate_result(semantic_map, detail_gate)
                    except Exception as exc:  # noqa: BLE001
                        semantic_map.setdefault("warnings", []).append(f"AI_DETAIL_REPAIR_FAILED: {exc}")
                        for item in segments:
                            item["availability_status_code"] = "UNKNOWN"
                            item["needs_strong_review"] = True
                            item["manual_review_reason"] = _append_reason(
                                item.get("manual_review_reason") or item.get("ai_review_reason"),
                                f"AI 证据修复失败，需人工判断：{exc}",
                            )
                elif should_call_ai_repair(detail_gate):
                    semantic_map.setdefault("warnings", []).append("AI_DETAIL_REPAIR_SKIPPED_BUDGET: 候选较多或问题较多，跳过整批强模型修复并进入分块复核")
                mark_timing("AI_DETAIL")

                await self._update_parse_progress(
                    batch_id,
                    stage_code="MATCHING",
                    stage_name="标准化匹配",
                    stage_message="系统正在批量匹配运输节点、城市和标准货品",
                    percent=68,
                    started_at=started,
                    status_code="PARSING",
                )
                matcher = FreightMasterDataBatchMatcher(self.db)

                review_results, review_raw, review_failed_count, review_metrics = await client.review_risky_segments(
                    indexed_text,
                    semantic_map,
                    segments,
                    runtime=runtime,
                    progress_callback=callback,
                )
                timings["AI_REVIEW_REQUEST_COUNT"] = len(review_metrics)
                timings["AI_REVIEW_EVIDENCE_LINE_COUNTS"] = [int(item.get("evidence_line_count") or 0) for item in review_metrics]
                timings["AI_REVIEW_BATCH_METRICS"] = review_metrics
                if review_results:
                    segments = client.merge_review_results(segments, review_results)
                    semantic_warnings.extend(validator.validate_segments(semantic_map, segments))
                    final_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
                    patch_semantic_map_with_gate_result(semantic_map, final_gate)
                mark_timing("AI_REVIEW")

                if hasattr(client, "assign_segment_uids"):
                    client.assign_segment_uids(segments, preserve_existing=True)
                accepted_segments, ignored_segments, quality_warnings = _prepare_segments(batch.raw_text, segments)
                final_match_results = await matcher.match_segments(accepted_segments)
                mark_timing("MATCHING")
                warnings = list(
                    dict.fromkeys(
                        [
                            *(semantic_map.get("warnings") or []),
                            *semantic_warnings,
                            *detail_warnings,
                            *quality_warnings,
                        ]
                    )
                )
                parsed = type(
                    "StagedFreightParseResult",
                    (),
                    {
                        "segments": accepted_segments,
                        "ignored_segments": ignored_segments,
                        "prompt_version": client.wechat_prompt_version,
                        "model": " -> ".join(
                            dict.fromkeys(
                                [
                                    runtime["semantic_model"],
                                    *[str(item.get("detail_model") or runtime["detail_model"]) for item in detail_metrics],
                                    *([runtime["review_model"]] if review_raw is not None else []),
                                    *([runtime["review_model"]] if repair_records else []),
                                ]
                            )
                        ),
                        "parsed_payload": {
                            "segments": accepted_segments,
                            "ignored_segments": ignored_segments,
                            "context_blocks": semantic_map.get("context_blocks") or [],
                            "context_notes": semantic_map.get("context_notes") or [],
                            "warnings": warnings,
                        },
                        "raw_response": {
                            "provider": runtime["provider"],
                            "pipeline": "freight_ai_semantic_pipeline_v2",
                            "semantic_map": semantic_raw,
                            "detail": detail_raws,
                            "review": review_raw,
                            "repair": repair_records,
                        },
                        "review_failed_count": review_failed_count,
                        "semantic_map": semantic_map,
                        "review_results": review_results,
                        "match_results": final_match_results,
                    },
                )()
            else:
                parsed = await client.parse(
                    batch.raw_text,
                    source_type_code="WECHAT",
                    progress_callback=callback,
                )
                await self._update_parse_progress(
                    batch_id,
                    stage_code="MATCHING",
                    stage_name="标准化匹配",
                    stage_message="系统正在批量匹配运输节点、城市和标准货品",
                    percent=68,
                    started_at=started,
                    status_code="PARSING",
                )
                matcher = FreightMasterDataBatchMatcher(self.db)
                parsed.match_results = await matcher.match_segments(list(getattr(parsed, "segments", []) or []))
                mark_timing("MATCHING")
                mark_timing("AI_REVIEW")

            await self._update_parse_progress(
                batch_id,
                stage_code="SAVING",
                stage_name="保存候选",
                stage_message="系统正在批量生成编码并保存候选货源",
                percent=88,
                started_at=started,
                status_code="PARSING",
            )
            mark_timing("SAVING_START")
            ignored_segments = list(getattr(parsed, "ignored_segments", []) or [])
            work_items = [("ignored", item) for item in ignored_segments] + [("candidate", item) for item in parsed.segments]
            candidate_segments = [segment for item_type, segment in work_items if item_type == "candidate" and not _segment_ignore_reason(segment)]
            if not candidate_segments:
                raise ValidationError("AI 未生成可入库候选")
            clue_nos = await self.sequence_service.next_codes("FREIGHT_CLUE_NO", len(work_items))
            candidate_nos = await self.sequence_service.next_codes("FREIGHT_CANDIDATE_NO", len(candidate_segments))
            match_results = list(getattr(parsed, "match_results", []) or [])

            clue_rows: list[dict[str, Any]] = []
            normalized_work_items: list[tuple[str, dict[str, Any], str | None]] = []
            for index, (item_type, segment) in enumerate(work_items, start=1):
                ignore_reason = str(segment.get("drop_reason") or "") if item_type == "ignored" else _segment_ignore_reason(segment)
                if ignore_reason:
                    segment = {**segment, "drop_reason": ignore_reason, "is_freight_candidate": False}
                normalized_work_items.append((item_type, segment, ignore_reason))
                clue_rows.append(
                    {
                        "clue_no": clue_nos[index - 1],
                        "source_type_code": "WECHAT",
                        "source_channel_code": "WECHAT_TEXT",
                        "source_batch_id": batch_id,
                        "source_tms_inbound_id": None,
                        "segment_index": int(segment.get("segment_index") or index),
                        "semantic_role_code": _first(segment, "semantic_role_code", "role_code") or ("IGNORED" if ignore_reason else "ROUTE"),
                        "raw_text": str(segment.get("raw_text") or batch.raw_text),
                        "line_refs_json": segment.get("line_refs") or segment.get("line_refs_json"),
                        "context_summary": segment.get("context_summary") or ignore_reason or segment.get("manual_review_reason"),
                        "extracted_fields_json": segment,
                        "quality_score": _to_decimal_or_none(segment.get("confidence_score")),
                        "status_code": "IGNORED" if ignore_reason else "CANDIDATE_CREATED",
                    }
                )

            clue_ids = await self.candidate_repo.delete_unconfirmed_by_batch(batch_id)
            await self.clue_repo.delete_by_ids(clue_ids)
            clues = await self.clue_repo.bulk_create(clue_rows)
            candidate_rows: list[dict[str, Any]] = []
            candidate_index = 0
            for item_index, (item_type, segment, ignore_reason) in enumerate(normalized_work_items):
                if item_type != "candidate" or ignore_reason:
                    continue
                candidate_rows.append(
                    await self._candidate_from_segment(
                        source_type_code="WECHAT",
                        source_channel_code="WECHAT_TEXT",
                        source_batch_id=batch_id,
                        source_tms_inbound_id=None,
                        clue_id=clues[item_index].id,
                        segment=segment,
                        candidate_no=candidate_nos[candidate_index],
                        match_result=match_results[candidate_index] if candidate_index < len(match_results) else None,
                    )
                )
                candidate_index += 1
            await self.candidate_repo.bulk_create(candidate_rows)
            clue_count = len(clue_rows)
            candidate_count = len(candidate_rows)
            failed_count = int(getattr(parsed, "review_failed_count", 0) or 0)
            mark_timing("SAVING")
            status = "PARSED" if candidate_count and failed_count == 0 else "PARTIAL_FAILED" if candidate_count else "FAILED"
            finished = datetime.utcnow()
            semantic_map_json = getattr(parsed, "semantic_map", None) or {
                "context_blocks": (getattr(parsed, "parsed_payload", {}) or {}).get("context_blocks") or [],
                "context_notes": (getattr(parsed, "parsed_payload", {}) or {}).get("context_notes") or [],
                "ignored_segments": (getattr(parsed, "parsed_payload", {}) or {}).get("ignored_segments") or [],
                "warnings": (getattr(parsed, "parsed_payload", {}) or {}).get("warnings") or [],
            }
            semantic_map_json = {
                "pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
                "prompt_version": parsed.prompt_version,
                **semantic_map_json,
            }
            raw_response_json = {
                "semantic_map": semantic_map_json,
                "segments": (getattr(parsed, "parsed_payload", {}) or {}).get("segments") or [],
                "review_results": getattr(parsed, "review_results", []) or [],
                "warnings": (getattr(parsed, "parsed_payload", {}) or {}).get("warnings") or [],
                "timings": timings,
                "raw_response": getattr(parsed, "raw_response", {}),
            }
            await self.repo.update(
                batch_id,
                {
                    "status_code": status,
                    "review_flow_status_code": "REVIEWING" if status != "FAILED" else "REVIEWING",
                    "clue_count": clue_count,
                    "candidate_count": candidate_count,
                    "success_count": candidate_count,
                    "failed_count": failed_count if candidate_count else 1,
                    "prompt_version": parsed.prompt_version,
                    "ai_pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
                    "ai_semantic_map_json": semantic_map_json,
                    "finished_at": finished,
                    "parse_stage_code": "DONE" if status != "FAILED" else "FAILED",
                    "parse_stage_name": "解析完成" if status != "FAILED" else "解析失败",
                    "parse_stage_message": "候选货源已生成，可进入确认入库" if status != "FAILED" else "AI 未生成可入库候选",
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": finished,
                    "ai_elapsed_seconds": int((finished - started).total_seconds()),
                    "raw_response_json": raw_response_json,
                },
            )
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.db.rollback()
            finished = datetime.utcnow()
            await self.repo.update(
                batch_id,
                {
                    "status_code": "FAILED",
                    "finished_at": finished,
                    "error_message": message,
                    "parse_stage_code": "FAILED",
                    "parse_stage_name": "解析失败",
                    "parse_stage_message": message,
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": finished,
                    "ai_elapsed_seconds": int((finished - started).total_seconds()),
                },
            )
            await self.db.commit()
            raise
        return await self.get_detail(batch_id)

    async def handoff_review(self, batch_id: int, operator_id: int | None = None) -> FreightBatchHandoffResponse:
        _ = operator_id
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        if batch.status_code not in {"PARSED", "PARTIAL_FAILED"}:
            raise ValidationError("只有解析完成的批次可以移交候选证据池")
        candidates = await self.candidate_repo.list_by_batch(batch_id)
        pending_count = sum(1 for item in candidates if item.status_code == "PENDING")
        if pending_count <= 0:
            raise ValidationError("该批次没有待确认候选货源")
        await self.repo.update(batch_id, {"review_flow_status_code": "QUEUED_FOR_REVIEW"})
        await self.db.commit()
        return FreightBatchHandoffResponse(
            batch_id=batch_id,
            handoff_count=pending_count,
            review_flow_status_code="QUEUED_FOR_REVIEW",
            message=f"已移交 {pending_count} 条候选货源到候选证据池",
        )


