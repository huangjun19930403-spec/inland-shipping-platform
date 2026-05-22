"""Route plan structure service."""

from __future__ import annotations

from app.modules.route.services.common import *  # noqa: F403

from app.modules.route.services.route_track_generate_service import RouteTrackGenerateServiceMixin
from app.modules.route.services.route_track_version_service import RouteTrackVersionServiceMixin


class ShippingRoutePlanStructureService(RouteTrackGenerateServiceMixin, RouteTrackVersionServiceMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.runtime_config = RuntimeConfigService(db)

    async def get_structure(self, plan_id: int) -> RoutePlanStructureResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        return await self._structure_response(plan)

    async def replace_structure(self, plan_id: int, payload) -> RoutePlanStructureResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = self._normalize_points(payload.points)
        await self._validate_point_refs(points)
        existing_points = await self.structure_repo.list_points(plan_id, plan.structure_revision)
        if [_point_compare_signature(point) for point in existing_points] == [_point_compare_signature(point) for point in points]:
            return await self._structure_response(plan)
        await self.structure_repo.replace_structure(plan, points)
        await self.db.commit()
        await self.db.refresh(plan)
        return await self._structure_response(plan)

    async def _structure_response(self, plan) -> RoutePlanStructureResponse:
        points = await self.structure_repo.list_points(plan.id, plan.structure_revision)
        segments = await self.structure_repo.list_segments(plan.id, plan.structure_revision)
        point_responses = await self._point_responses(points)
        versions = await self.structure_repo.list_track_versions(plan.id)
        current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
        current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
        selected_count = len(current_version_segments)
        failed_count = 1 if current_version and current_version.version_status_code == "FAILED" else 0
        active_track_generation_task = await _active_track_generation_task(self.db, plan)
        return RoutePlanStructureResponse(
            plan=_to_plan_response(
                plan,
                point_count=len(points),
                segment_count=len(segments),
                selected_result_count=selected_count,
                failed_count=failed_count,
                current_track_version=current_version,
                track_version_count=len(versions),
                active_track_generation_task=active_track_generation_task,
            ),
            points=point_responses,
            segments=[
                _to_segment_response(
                    segment,
                    point_by_id={point.id: point for point in points},
                )
                for segment in segments
            ],
        )

    async def _point_responses(self, points: list[ShippingRoutePlanPoint]) -> list[RoutePlanPointResponse]:
        transport_ids = {
            point.transport_node_id
            for point in points
            if point.point_type_code == "TRANSPORT_NODE" and point.transport_node_id is not None
        }
        constraint_ids = {
            point.constraint_point_id
            for point in points
            if point.point_type_code == "CONSTRAINT_POINT" and point.constraint_point_id is not None
        }
        transport_by_id: dict[int, TransportNode] = {}
        constraint_by_id: dict[int, NavigationConstraintPoint] = {}
        if transport_ids:
            rows = (
                await self.db.execute(
                    select(TransportNode).where(TransportNode.id.in_(transport_ids), TransportNode.deleted_at.is_(None))
                )
            ).scalars()
            transport_by_id = {row.id: row for row in rows}
        if constraint_ids:
            rows = (
                await self.db.execute(select(NavigationConstraintPoint).where(NavigationConstraintPoint.id.in_(constraint_ids)))
            ).scalars()
            constraint_by_id = {row.id: row for row in rows}
        return [
            _to_point_response(
                point,
                transport_node=transport_by_id.get(point.transport_node_id),
                constraint_point=constraint_by_id.get(point.constraint_point_id),
            )
            for point in points
        ]

    def _normalize_points(self, items) -> list[dict[str, Any]]:
        rows = []
        total = len(items)
        for idx, item in enumerate(items, start=1):
            data = item.model_dump(exclude_none=True)
            data["point_order"] = idx
            point_type = data.get("point_type_code")
            if point_type not in POINT_TYPES:
                raise ValidationError("invalid point_type_code")
            has_transport = data.get("transport_node_id") is not None
            has_constraint = data.get("constraint_point_id") is not None
            if point_type == "TRANSPORT_NODE":
                if not has_transport or has_constraint or data.get("manual_name") or data.get("longitude") is not None or data.get("latitude") is not None:
                    raise ValidationError("TRANSPORT_NODE must only reference transport_node_id")
            elif point_type == "CONSTRAINT_POINT":
                if not has_constraint or has_transport or data.get("manual_name") or data.get("longitude") is not None or data.get("latitude") is not None:
                    raise ValidationError("CONSTRAINT_POINT must only reference constraint_point_id")
            else:
                if has_transport or has_constraint:
                    raise ValidationError("MANUAL_POINT must not reference existing nodes")
                if not data.get("manual_name") or data.get("longitude") is None or data.get("latitude") is None:
                    raise ValidationError("MANUAL_POINT requires name and lng/lat")
                lng = Decimal(str(data["longitude"]))
                lat = Decimal(str(data["latitude"]))
                if lng < Decimal("-180") or lng > Decimal("180") or lat < Decimal("-90") or lat > Decimal("90"):
                    raise ValidationError("invalid manual point coordinates")
            if idx < total:
                mode = data.get("transport_mode_after_code")
                if mode not in TRANSPORT_MODES:
                    raise ValidationError("transport_mode_after_code is required before the next point")
            else:
                data["transport_mode_after_code"] = None
            rows.append(data)
        return rows

    async def _validate_point_refs(self, points: list[dict[str, Any]]) -> None:
        for item in points:
            if item["point_type_code"] == "TRANSPORT_NODE":
                exists = await self.db.scalar(
                    select(TransportNode.id).where(TransportNode.id == item["transport_node_id"], TransportNode.deleted_at.is_(None))
                )
                if exists is None:
                    raise NotFoundError("TransportNode", item["transport_node_id"])
            elif item["point_type_code"] == "CONSTRAINT_POINT":
                exists = await self.db.scalar(
                    select(NavigationConstraintPoint.id).where(NavigationConstraintPoint.id == item["constraint_point_id"])
                )
                if exists is None:
                    raise NotFoundError("NavigationConstraintPoint", item["constraint_point_id"])

    async def _resolve_point(self, point: ShippingRoutePlanPoint) -> tuple[float, float]:
        longitude = point.longitude
        latitude = point.latitude
        if point.point_type_code == "TRANSPORT_NODE":
            transport_node = await self.db.scalar(
                select(TransportNode).where(TransportNode.id == point.transport_node_id, TransportNode.deleted_at.is_(None))
            )
            if transport_node is None:
                raise NotFoundError("TransportNode", point.transport_node_id)
            longitude = transport_node.longitude
            latitude = transport_node.latitude
        elif point.point_type_code == "CONSTRAINT_POINT":
            constraint_point = await self.db.scalar(
                select(NavigationConstraintPoint).where(NavigationConstraintPoint.id == point.constraint_point_id)
            )
            if constraint_point is None:
                raise NotFoundError("NavigationConstraintPoint", point.constraint_point_id)
            longitude = constraint_point.longitude
            latitude = constraint_point.latitude
        if longitude is None or latitude is None:
            raise ValidationError(f"点位缺少经纬度: {point.display_name}")
        lon = float(longitude)
        lat = float(latitude)
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            raise ValidationError(f"点位经纬度非法: {point.display_name}")
        return lon, lat

