"""route 模块 service。"""

from __future__ import annotations

import math
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.amap import AmapRouteClient
from app.integrations.hifleet import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.modules.dictionary.service import CodeSequenceService
from app.modules.route.repository import (
    RouteNodeLookupRepository,
    ShippingRoutePlanRepository,
    ShippingRoutePlanSegmentPointRepository,
    ShippingRoutePlanSegmentRepository,
    ShippingRouteRepository,
)
from app.modules.route.schemas import (
    PageResponse,
    RouteDetailResponse,
    RouteGeometryRefreshResponse,
    RoutePlanDetailResponse,
    RoutePlanResponse,
    RoutePlanSummaryResponse,
    RouteResponse,
    RouteSegmentPointResponse,
    RouteSegmentResponse,
)


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_route_response(entity) -> RouteResponse:
    return RouteResponse(
        id=entity.id,
        code=entity.code,
        name=entity.name,
        transport_org_type_code=entity.transport_org_type_code,
        multimodal_combination_code=entity.multimodal_combination_code,
        origin_region_id=entity.origin_region_id,
        destination_region_id=entity.destination_region_id,
        description=entity.description,
        status=entity.status,
        sort_order=entity.sort_order,
        audit_status=entity.audit_status,
        submitter_id=entity.submitter_id,
        auditor_id=entity.auditor_id,
        audited_at=entity.audited_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_plan_response(entity) -> RoutePlanResponse:
    return RoutePlanResponse(
        id=entity.id,
        route_id=entity.route_id,
        plan_code=entity.plan_code,
        plan_name=entity.plan_name,
        version_no=entity.version_no,
        plan_type_code=entity.plan_type_code,
        total_distance_km=entity.total_distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        effective_from=entity.effective_from,
        effective_to=entity.effective_to,
        status=entity.status,
        is_default=entity.is_default,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_plan_summary(entity) -> RoutePlanSummaryResponse:
    return RoutePlanSummaryResponse(**_to_plan_response(entity).model_dump())


def _to_segment_response(entity) -> RouteSegmentResponse:
    return RouteSegmentResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        segment_no=entity.segment_no,
        segment_type_code=entity.segment_type_code,
        start_node_id=entity.start_node_id,
        end_node_id=entity.end_node_id,
        start_constraint_point_id=entity.start_constraint_point_id,
        end_constraint_point_id=entity.end_constraint_point_id,
        distance_km=entity.distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        geometry_json=entity.geometry_json,
        sort_order=entity.sort_order,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_point_response(entity) -> RouteSegmentPointResponse:
    return RouteSegmentPointResponse(
        id=entity.id,
        segment_id=entity.segment_id,
        point_no=entity.point_no,
        point_type_code=entity.point_type_code,
        related_node_id=entity.related_node_id,
        related_constraint_point_id=entity.related_constraint_point_id,
        longitude=entity.longitude,
        latitude=entity.latitude,
        stay_minutes=entity.stay_minutes,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _haversine_km(p1: list[float], p2: list[float]) -> float:
    lon1, lat1 = math.radians(float(p1[0])), math.radians(float(p1[1]))
    lon2, lat2 = math.radians(float(p2[0])), math.radians(float(p2[1]))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return 6371.0 * c


def _polyline_distance_km(coordinates: list[list[float]]) -> float:
    if len(coordinates) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(coordinates)):
        total += _haversine_km(coordinates[idx - 1], coordinates[idx])
    return total


class ShippingRouteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_routes(
        self,
        keyword: str | None,
        status_code: int | None,
        origin_region_id: int | None,
        destination_region_id: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[RouteResponse]:
        rows, total = await self.route_repo.list_routes(
            keyword=keyword,
            status_code=status_code,
            origin_region_id=origin_region_id,
            destination_region_id=destination_region_id,
            page=page,
            page_size=page_size,
        )
        return PageResponse[RouteResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_route_response(item) for item in rows],
        )

    async def create_route(self, payload) -> RouteResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("ROUTE_CODE")
        data["code"] = code
        if await self.route_repo.exists_route_code(code):
            raise ConflictError(f"route code already exists: {code}")
        row = await self.route_repo.create_route(
            {
                **data,
                "name": payload.name.strip(),
            }
        )
        await self.db.commit()
        return _to_route_response(row)

    async def update_route(self, route_id: int, payload) -> RouteResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.route_repo.update_route(route_id, updates)
        if row is None:
            raise NotFoundError("ShippingRoute", route_id)
        await self.db.commit()
        return _to_route_response(row)

    async def get_route_detail(self, route_id: int) -> RouteDetailResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        current_plan = await self.plan_repo.get_current_plan(route_id)
        plans = await self.plan_repo.list_all_plans(route_id)
        return RouteDetailResponse(
            route=_to_route_response(route),
            current_plan=_to_plan_summary(current_plan) if current_plan else None,
            plans=[_to_plan_summary(item) for item in plans],
        )

    async def change_route_status(self, route_id: int, status_code: int) -> None:
        ok = await self.route_repo.update_route_status(route_id, status_code)
        if not ok:
            raise NotFoundError("ShippingRoute", route_id)
        await self.db.commit()


class ShippingRoutePlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.segment_repo = ShippingRoutePlanSegmentRepository(db)
        self.point_repo = ShippingRoutePlanSegmentPointRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_plans(
        self,
        route_id: int,
        status_code: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[RoutePlanResponse]:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        rows, total = await self.plan_repo.list_plans(route_id, status_code, page, page_size)
        return PageResponse[RoutePlanResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_plan_response(item) for item in rows],
        )

    async def create_plan(self, route_id: int, payload) -> RoutePlanResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        data = payload.model_dump(exclude_none=True)
        plan_code = (payload.plan_code or "").strip()
        if not plan_code:
            plan_code = await self.sequence_service.next_code("ROUTE_PLAN_CODE")
        data["plan_code"] = plan_code
        if await self.plan_repo.exists_plan_code(plan_code):
            raise ConflictError(f"plan code already exists: {plan_code}")
        row = await self.plan_repo.create_plan(
            route_id,
            {
                **data,
                "plan_name": payload.plan_name.strip(),
            },
        )
        if row.is_default:
            await self.plan_repo.activate_plan(route_id, row.id)
        await self.db.commit()
        return _to_plan_response(row)

    async def update_plan(self, plan_id: int, payload) -> RoutePlanResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.plan_repo.update_plan(plan_id, updates)
        if row is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        if updates.get("is_default") is True:
            await self.plan_repo.activate_plan(row.route_id, row.id)
        await self.db.commit()
        return _to_plan_response(row)

    async def get_plan_detail(self, plan_id: int) -> RoutePlanDetailResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        segments = await self.segment_repo.list_segments(plan_id)
        points_by_segment: dict[int, list[RouteSegmentPointResponse]] = {}
        for seg in segments:
            points = await self.point_repo.list_points(seg.id)
            points_by_segment[seg.id] = [_to_point_response(item) for item in points]
        return RoutePlanDetailResponse(
            plan=_to_plan_response(plan),
            segments=[_to_segment_response(item) for item in segments],
            points_by_segment=points_by_segment,
        )

    async def change_plan_status(self, plan_id: int, status_code: int) -> None:
        ok = await self.plan_repo.update_plan_status(plan_id, status_code)
        if not ok:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        await self.db.commit()

    async def activate_plan(self, route_id: int, plan_id: int) -> None:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        ok = await self.plan_repo.activate_plan(route_id, plan_id)
        if not ok:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        await self.db.commit()


class ShippingRouteSegmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.segment_repo = ShippingRoutePlanSegmentRepository(db)

    async def list_segments(self, plan_id: int) -> list[RouteSegmentResponse]:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        rows = await self.segment_repo.list_segments(plan_id)
        return [_to_segment_response(item) for item in rows]

    async def create_segment(self, plan_id: int, payload) -> RouteSegmentResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        row = await self.segment_repo.create_segment(plan_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_segment_response(row)

    async def update_segment(self, segment_id: int, payload) -> RouteSegmentResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.segment_repo.update_segment(segment_id, updates)
        if row is None:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)
        await self.db.commit()
        return _to_segment_response(row)

    async def delete_segment(self, segment_id: int) -> None:
        ok = await self.segment_repo.delete_segment(segment_id)
        if not ok:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)
        await self.db.commit()

    async def reorder_segments(self, plan_id: int, ordered_ids: list[int]) -> int:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        sorted_count = await self.segment_repo.reorder_segments(plan_id, ordered_ids)
        await self.db.commit()
        return sorted_count


class ShippingRoutePointService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.segment_repo = ShippingRoutePlanSegmentRepository(db)
        self.point_repo = ShippingRoutePlanSegmentPointRepository(db)

    async def list_points(self, segment_id: int) -> list[RouteSegmentPointResponse]:
        segment = await self.segment_repo.get_segment(segment_id)
        if segment is None:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)
        rows = await self.point_repo.list_points(segment_id)
        return [_to_point_response(item) for item in rows]

    async def create_point(self, segment_id: int, payload) -> RouteSegmentPointResponse:
        segment = await self.segment_repo.get_segment(segment_id)
        if segment is None:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)
        row = await self.point_repo.create_point(segment_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_point_response(row)

    async def update_point(self, point_id: int, payload) -> RouteSegmentPointResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.point_repo.update_point(point_id, updates)
        if row is None:
            raise NotFoundError("ShippingRoutePlanSegmentPoint", point_id)
        await self.db.commit()
        return _to_point_response(row)

    async def delete_point(self, point_id: int) -> None:
        ok = await self.point_repo.delete_point(point_id)
        if not ok:
            raise NotFoundError("ShippingRoutePlanSegmentPoint", point_id)
        await self.db.commit()

    async def reorder_points(self, segment_id: int, ordered_ids: list[int]) -> int:
        segment = await self.segment_repo.get_segment(segment_id)
        if segment is None:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)
        sorted_count = await self.point_repo.reorder_points(segment_id, ordered_ids)
        await self.db.commit()
        return sorted_count


class RouteGeometryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.segment_repo = ShippingRoutePlanSegmentRepository(db)
        self.point_repo = ShippingRoutePlanSegmentPointRepository(db)
        self.node_repo = RouteNodeLookupRepository(db)

    async def _build_segment_query(self, segment) -> RouteGeometryQuery:
        start: tuple[float, float] | None = None
        end: tuple[float, float] | None = None

        if segment.start_node_id:
            node = await self.node_repo.get_node(segment.start_node_id)
            if node and node.longitude is not None and node.latitude is not None:
                start = (float(node.longitude), float(node.latitude))
        if segment.end_node_id:
            node = await self.node_repo.get_node(segment.end_node_id)
            if node and node.longitude is not None and node.latitude is not None:
                end = (float(node.longitude), float(node.latitude))

        if start is None or end is None:
            points = await self.point_repo.list_points(segment.id)
            if points:
                first = points[0]
                last = points[-1]
                if start is None:
                    if first.longitude is not None and first.latitude is not None:
                        start = (float(first.longitude), float(first.latitude))
                    elif first.related_node_id:
                        node = await self.node_repo.get_node(first.related_node_id)
                        if node and node.longitude is not None and node.latitude is not None:
                            start = (float(node.longitude), float(node.latitude))
                if end is None:
                    if last.longitude is not None and last.latitude is not None:
                        end = (float(last.longitude), float(last.latitude))
                    elif last.related_node_id:
                        node = await self.node_repo.get_node(last.related_node_id)
                        if node and node.longitude is not None and node.latitude is not None:
                            end = (float(node.longitude), float(node.latitude))

        if start is None or end is None:
            raise ValidationError("segment 缺少可用起终点坐标，无法刷新几何")

        return RouteGeometryQuery(
            origin_lon=start[0],
            origin_lat=start[1],
            dest_lon=end[0],
            dest_lat=end[1],
            transport_mode="WATERWAY",
            segment_type=segment.segment_type_code,
        )

    async def _call_provider(self, provider_code: str, query: RouteGeometryQuery) -> RouteGeometryResult:
        code = provider_code.strip().lower()
        if code == "amap":
            return await AmapRouteClient().generate(query)
        if code == "hifleet":
            return await HifleetRouteClient().generate(query)
        raise ValidationError(f"unsupported provider_code: {provider_code}")

    async def _refresh_segment_geometry(
        self,
        segment_id: int,
        provider_code: str,
        force_refresh: bool,
    ) -> tuple[int, Decimal | None]:
        segment = await self.segment_repo.get_segment(segment_id)
        if segment is None:
            raise NotFoundError("ShippingRoutePlanSegment", segment_id)

        if not force_refresh and segment.geometry_json:
            return segment.plan_id, _to_decimal(segment.distance_km)

        query = await self._build_segment_query(segment)
        result = await self._call_provider(provider_code, query)

        coords = (result.geometry or {}).get("coordinates") or []
        if len(coords) < 2:
            raise ValidationError("provider 返回轨迹点不足")
        distance_km = _to_decimal(round(_polyline_distance_km(coords), 3))
        await self.segment_repo.update_segment(
            segment_id,
            {
                "geometry_json": result.geometry,
                "distance_km": distance_km,
            },
        )
        return segment.plan_id, distance_km

    async def _refresh_plan_totals(self, plan_id: int) -> None:
        segments = await self.segment_repo.list_segments(plan_id)
        distance_values = [item.distance_km for item in segments if item.distance_km is not None]
        duration_values = [item.estimated_duration_hour for item in segments if item.estimated_duration_hour is not None]
        await self.plan_repo.update_plan(
            plan_id,
            {
                "total_distance_km": sum(distance_values) if distance_values else None,
                "estimated_duration_hour": sum(duration_values) if duration_values else None,
            },
        )

    async def refresh_plan_geometry(
        self,
        plan_id: int,
        provider_code: str,
        force_refresh: bool = False,
    ) -> RouteGeometryRefreshResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        segments = await self.segment_repo.list_segments(plan_id)
        if not segments:
            raise ValidationError("plan 下无 segment，无法刷新几何")

        refreshed_count = 0
        for item in segments:
            old_geometry = item.geometry_json
            await self._refresh_segment_geometry(item.id, provider_code, force_refresh)
            if force_refresh or old_geometry is None:
                refreshed_count += 1

        await self._refresh_plan_totals(plan_id)
        await self.db.commit()
        return RouteGeometryRefreshResponse(
            target_type="plan",
            target_id=plan_id,
            provider_code=provider_code,
            status="READY",
            message=f"plan geometry refresh finished, refreshed_segments={refreshed_count}",
            updated_plan_id=plan_id,
            updated_segment_id=None,
        )

    async def refresh_segment_geometry(
        self,
        segment_id: int,
        provider_code: str,
        force_refresh: bool = False,
    ) -> RouteGeometryRefreshResponse:
        plan_id, _ = await self._refresh_segment_geometry(segment_id, provider_code, force_refresh)
        await self._refresh_plan_totals(plan_id)
        await self.db.commit()
        return RouteGeometryRefreshResponse(
            target_type="segment",
            target_id=segment_id,
            provider_code=provider_code,
            status="READY",
            message="segment geometry refresh finished",
            updated_plan_id=plan_id,
            updated_segment_id=segment_id,
        )
