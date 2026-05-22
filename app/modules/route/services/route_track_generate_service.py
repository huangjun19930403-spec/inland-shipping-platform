"""Route track generation service mixin."""

from __future__ import annotations

from app.modules.route.services.common import *  # noqa: F403

class RouteTrackGenerateServiceMixin:
    async def enqueue_generate_track_version(
        self,
        plan_id: int,
        payload,
        *,
        requested_by: int | None = None,
    ) -> AsyncTaskRunResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        provider_code = _normalize_provider_code(payload.provider_code)
        task_run_service = AsyncTaskRunService(self.db)
        task_run = await task_run_service.create_queued(
            task_name=ROUTE_TRACK_GENERATION_TASK_NAME,
            task_title=f"航线轨迹生成：{plan.plan_name}",
            queue_name="analysis",
            business_type=ROUTE_TRACK_GENERATION_BUSINESS_TYPE,
            business_id=plan.id,
            business_no=plan.plan_code,
            idempotency_key=_track_generation_idempotency_key(plan, provider_code),
            requested_by=requested_by,
            triggered_by="manual",
            max_retries=0,
            extra_json={
                "plan_id": plan.id,
                "plan_code": plan.plan_code,
                "structure_revision": int(plan.structure_revision or 1),
                "provider_code": provider_code,
            },
            stale_seconds=ROUTE_TRACK_GENERATION_STALE_SECONDS,
        )
        should_dispatch = not (
            task_run.celery_task_id
            and task_run.status_code in {"QUEUED", "STARTED", "RUNNING", "RETRYING"}
        )
        await self.db.commit()
        if should_dispatch:
            try:
                from app.tasks.route_tasks import generate_route_track_version_task

                async_result = generate_route_track_version_task.delay(
                    plan.id,
                    payload.model_dump(mode="json"),
                    requested_by,
                    task_run.id,
                )
                await task_run_service.bind_celery_task_id(task_run.id, str(async_result.id))
            except Exception as exc:  # noqa: BLE001
                await task_run_service.mark_failed(task_run.id, f"轨迹生成任务投递失败：{exc}")
                raise ValidationError(f"轨迹生成任务投递失败：{exc}") from exc
        return await task_run_service.get_run(task_run.id)

    async def get_latest_track_generation_task(
        self,
        plan_id: int,
        *,
        provider_code: str | None = None,
    ) -> AsyncTaskRunResponse | None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        return await _latest_track_generation_task(self.db, plan, provider_code=provider_code)

    async def generate_track_version(self, plan_id: int, payload) -> RouteTrackVersionGenerateResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = await self.structure_repo.list_points(plan_id, plan.structure_revision)
        segments = await self.structure_repo.list_segments(plan_id, plan.structure_revision)
        if not segments:
            raise ValidationError("请先维护至少两个点位，系统才能生成逻辑段")
        point_by_id = {point.id: point for point in points}
        now = datetime.utcnow()
        version_segments: list[dict[str, Any]] = []
        errors: list[str] = []
        fallback_notes: list[str] = []
        provider_codes: set[str] = set()
        source_codes: set[str] = set()
        total_distance = Decimal("0")
        total_duration = Decimal("0")
        total_points = 0
        for segment in segments:
            start = point_by_id.get(segment.start_plan_point_id)
            end = point_by_id.get(segment.end_plan_point_id)
            if start is None or end is None:
                errors.append(f"航段 {segment.segment_no} 缺少起终点")
                continue
            try:
                result = await self._call_geometry_provider(
                    segment=segment,
                    start_point=start,
                    end_point=end,
                    provider_code=payload.provider_code,
                )
                status = _status_from_provider_status(result.status)
                source = _geometry_source_from_provider(result.source)
                if status != "READY" or not source:
                    raise ValidationError(f"provider 返回状态无效: {result.status}")
                raw_point_count = _line_point_count(result.geometry)
                if raw_point_count < 3:
                    raise ValidationError("provider 返回轨迹仅包含起终点，未形成可编辑轨迹")
                start_anchor = await self._resolve_point(start)
                end_anchor = await self._resolve_point(end)
                geometry = _snap_line_string_to_anchors(result.geometry, start_anchor, end_anchor)
                point_count = _line_point_count(geometry)
                if point_count < 3:
                    raise ValidationError("provider 返回轨迹仅包含起终点，未形成可编辑轨迹")
                distance = _to_decimal(result.distance_km) or _line_distance_km(geometry)
                duration = _to_decimal(result.estimated_duration_hour)
                total_distance += distance or Decimal("0")
                total_duration += duration or Decimal("0")
                total_points += point_count
                provider_codes.add(result.provider or source)
                source_codes.add(source)
                if source == "FALLBACK":
                    raw_summary = result.raw_summary or {}
                    fallback_reason = raw_summary.get("fallback_reason") if isinstance(raw_summary, dict) else None
                    fallback_notes.append(f"航段 {segment.segment_no}: {fallback_reason or '外部轨迹服务不可用，已生成可编辑降级轨迹'}")
                version_segments.append(
                    {
                        "segment_id": segment.id,
                        "segment_no": segment.segment_no,
                        "geometry_json": geometry,
                        "distance_km": distance,
                        "estimated_duration_hour": duration,
                        "point_count": point_count,
                        "edit_status_code": "ORIGINAL",
                    }
                )
                segment.generation_status_code = "READY"
                segment.error_message = None
                segment.generated_at = now
            except Exception as exc:  # noqa: BLE001
                error_text = _safe_error_message(exc)
                errors.append(f"航段 {segment.segment_no}: {error_text}")
                segment.generation_status_code = "FAILED"
                segment.error_message = error_text
                segment.generated_at = now
        status = _track_status(len(segments), len(version_segments), len(errors))
        source_type = str(payload.provider_code or "").strip().upper()
        if source_codes and source_codes == {"FALLBACK"}:
            source_type = "FALLBACK"
        elif source_type not in TRACK_VERSION_SOURCES:
            source_type = next(iter(provider_codes), None) or "HIFLEET"
        provider_type = ",".join(sorted(provider_codes)) if provider_codes else source_type
        version_no = await self.structure_repo.next_track_version_no(plan_id)
        version = await self.structure_repo.create_track_version(
            plan_id,
            {
                "version_name": f"{_track_source_display(source_type)}生成 V{version_no}",
                "structure_revision": plan.structure_revision,
                "source_type_code": source_type,
                "provider_type_code": provider_type,
                "parent_version_id": None,
                "is_current": False,
                "version_status_code": status if status in TRACK_VERSION_STATUSES else "FAILED",
                "distance_km": total_distance if version_segments else None,
                "estimated_duration_hour": total_duration if total_duration > 0 else None,
                "point_count": total_points,
                "segment_count": len(version_segments),
                "summary_json": {
                    "provider_codes": sorted(provider_codes),
                    "success_count": len(version_segments),
                    "segment_count": len(segments),
                    "errors": errors[:5],
                    "fallback_notes": fallback_notes[:5],
                },
                "error_message": "；".join(errors)[:512] if errors else None,
                "generated_at": now,
            },
            version_segments,
        )
        await self.db.commit()
        response = await self.get_track_version(plan_id, version.id)
        if status == "READY":
            message = "轨迹版本生成完成，可进入全屏编辑后保存为当前轨迹"
        elif status == "PARTIAL":
            message = f"轨迹版本部分生成：成功 {len(version_segments)}/{len(segments)} 段"
        else:
            message = "轨迹版本生成失败"
        return RouteTrackVersionGenerateResponse(plan_id=plan_id, status=status, message=message, version=response)

    def _geometry_client_for_segment(self, transport_mode_code: str, provider_code: str | None):
        provider_override = str(provider_code or "").strip().upper()
        if provider_override in {"AMAP", "HIFLEET"}:
            provider = provider_override
        elif provider_override and provider_override != "AUTO":
            raise ValidationError(f"不支持的轨迹 provider_code: {provider_override}")
        elif transport_mode_code == "WATER":
            provider = "HIFLEET"
        elif transport_mode_code == "ROAD":
            provider = "AMAP"
        elif transport_mode_code == "RAIL":
            raise ValidationError("铁路段暂不支持真实轨迹生成")
        else:
            raise ValidationError(f"不支持的运输方式: {transport_mode_code}")
        if provider == "HIFLEET":
            return HifleetRouteClient(runtime_config=self.runtime_config)
        return AmapRouteClient(runtime_config=self.runtime_config)

    async def _call_geometry_provider(
        self,
        *,
        segment: ShippingRoutePlanSegment,
        start_point: ShippingRoutePlanPoint,
        end_point: ShippingRoutePlanPoint,
        provider_code: str | None,
    ) -> RouteGeometryResult:
        origin_lon, origin_lat = await self._resolve_point(start_point)
        dest_lon, dest_lat = await self._resolve_point(end_point)
        if _haversine_km((origin_lon, origin_lat), (dest_lon, dest_lat)) < 0.05:
            raise ValidationError("航段起终点坐标相同或过近，AMMS 无法规划真实航线；请调整点位后再生成轨迹")
        client = self._geometry_client_for_segment(segment.transport_mode_code, provider_code)
        query = RouteGeometryQuery(
            origin_lon=origin_lon,
            origin_lat=origin_lat,
            dest_lon=dest_lon,
            dest_lat=dest_lat,
            transport_mode=segment.transport_mode_code,
            segment_type="ROUTE_PLAN_SEGMENT",
        )
        try:
            return await client.generate(query)
        except Exception as exc:  # noqa: BLE001
            provider = getattr(client, "provider_name", None) or str(provider_code or "UNKNOWN").upper()
            message = _safe_error_message(exc)
            if _should_use_fallback_track(exc):
                geometry = _fallback_geometry((origin_lon, origin_lat), (dest_lon, dest_lat))
                distance = _line_distance_km(geometry)
                return RouteGeometryResult(
                    geometry=geometry,
                    source="fallback",
                    provider=provider,
                    provider_trace_id="local-fallback",
                    status="ready",
                    distance_km=float(distance) if distance is not None else None,
                    estimated_duration_hour=None,
                    raw_summary={
                        "fallback_reason": message,
                        "requested_provider": provider,
                    },
                )
            raise
