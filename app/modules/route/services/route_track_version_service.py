"""Route track version service mixin."""

from __future__ import annotations

from app.modules.route.services.common import *  # noqa: F403

class RouteTrackVersionServiceMixin:
    async def list_track_versions(self, plan_id: int) -> list[RoutePlanTrackVersionResponse]:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        versions = await self.structure_repo.list_track_versions(plan_id)
        return [_to_track_version_response(item, current_structure_revision=plan.structure_revision) for item in versions]

    async def get_track_version(self, plan_id: int, version_id: int) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        segments = await self.structure_repo.list_track_version_segments([version.id])
        return _to_track_version_response(version, segments=segments, current_structure_revision=plan.structure_revision)

    async def save_track_version(self, plan_id: int, payload) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = await self.structure_repo.list_points(plan_id, plan.structure_revision)
        segments = await self.structure_repo.list_segments(plan_id, plan.structure_revision)
        if not segments:
            raise ValidationError("请先维护至少两个点位，系统才能保存轨迹")
        if len(payload.segments) != len(segments):
            raise ValidationError("保存轨迹前必须补齐所有逻辑段")
        if payload.parent_version_id is not None:
            parent = await self.structure_repo.get_track_version_by_id(payload.parent_version_id)
            if parent is None or parent.plan_id != plan_id:
                raise NotFoundError("ShippingRoutePlanTrackVersion", payload.parent_version_id)
            if int(parent.structure_revision or 1) != int(plan.structure_revision or 1):
                raise ValidationError("历史结构轨迹不能作为当前结构的修线来源")
        segment_by_id = {segment.id: segment for segment in segments}
        point_by_id = {point.id: point for point in points}
        seen_segment_ids: set[int] = set()
        version_segments: list[dict[str, Any]] = []
        total_distance = Decimal("0")
        total_duration = Decimal("0")
        total_points = 0
        for item in payload.segments:
            segment = segment_by_id.get(item.segment_id)
            if segment is None or item.segment_id in seen_segment_ids:
                raise ValidationError("保存轨迹包含非法或重复的逻辑段")
            seen_segment_ids.add(item.segment_id)
            start = point_by_id.get(segment.start_plan_point_id)
            end = point_by_id.get(segment.end_plan_point_id)
            if start is None or end is None:
                raise ValidationError(f"航段 {segment.segment_no} 缺少起终点")
            start_anchor = await self._resolve_point(start)
            end_anchor = await self._resolve_point(end)
            geometry = _snap_line_string_to_anchors(item.geometry_json, start_anchor, end_anchor)
            point_count = _line_point_count(geometry)
            if point_count < 2:
                raise ValidationError(f"航段 {segment.segment_no} 轨迹点不足")
            distance = item.distance_km or _line_distance_km(geometry)
            duration = item.estimated_duration_hour
            total_distance += distance or Decimal("0")
            total_duration += duration or Decimal("0")
            total_points += point_count
            edit_status = str(item.edit_status_code or "EDITED").upper()
            if edit_status not in TRACK_EDIT_STATUSES:
                edit_status = "EDITED"
            version_segments.append(
                {
                    "segment_id": segment.id,
                    "segment_no": segment.segment_no,
                    "geometry_json": geometry,
                    "distance_km": distance,
                    "estimated_duration_hour": duration,
                    "point_count": point_count,
                    "edit_status_code": edit_status,
                }
            )
        version = await self.structure_repo.create_track_version(
            plan_id,
            {
                "version_name": (payload.version_name or "").strip() or f"人工修线 V{await self.structure_repo.next_track_version_no(plan_id)}",
                "structure_revision": plan.structure_revision,
                "source_type_code": "MANUAL",
                "provider_type_code": None,
                "parent_version_id": payload.parent_version_id,
                "is_current": False,
                "version_status_code": "READY",
                "distance_km": total_distance,
                "estimated_duration_hour": total_duration if total_duration > 0 else None,
                "point_count": total_points,
                "segment_count": len(version_segments),
                "summary_json": payload.summary_json or {"save_mode": "MANUAL_EDIT"},
                "error_message": None,
                "generated_at": datetime.utcnow(),
            },
            version_segments,
        )
        await self.structure_repo.set_current_track_version(plan, version)
        await self.db.commit()
        return await self.get_track_version(plan_id, version.id)

    async def set_current_track_version(self, plan_id: int, version_id: int) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        if version.version_status_code != "READY":
            raise ValidationError("只能把 READY 状态的轨迹版本设为当前")
        if int(version.structure_revision or 1) != int(plan.structure_revision or 1):
            raise ValidationError("历史结构轨迹不能设为当前，请先基于当前结构重新生成轨迹")
        current_segments = await self.structure_repo.list_segments(plan_id, plan.structure_revision)
        expected_segment_ids = {int(item.id) for item in current_segments}
        version_segments = await self.structure_repo.list_track_version_segments([version.id])
        version_segment_ids = {int(item.segment_id) for item in version_segments}
        if not expected_segment_ids or version_segment_ids != expected_segment_ids:
            raise ValidationError("该轨迹版本没有覆盖全部逻辑段，不能设为当前")
        await self.structure_repo.set_current_track_version(plan, version)
        await self.db.commit()
        return await self.get_track_version(plan_id, version.id)

    async def delete_track_version(self, plan_id: int, version_id: int) -> None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        await self.structure_repo.delete_track_version(plan, version)
        await self.db.commit()

