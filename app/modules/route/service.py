"""route 模块 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.amap.route_client import AmapRouteClient
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.models.address import NavigationConstraintPoint, TransportNode
from app.modules.dictionary.service import CodeSequenceService
from app.modules.route.repository import ShippingRouteLineRepository, ShippingRoutePlanRepository, ShippingRouteRepository
from app.modules.route.schemas import (
    PageResponse,
    RouteDetailResponse,
    RouteLineResponse,
    RouteLineStructureResponse,
    RouteLineTrackGenerateResponse,
    RouteLineTrackResponse,
    RouteLineNodeResponse,
    RouteLineSegmentResponse,
    RoutePlanResponse,
    RouteResponse,
)
from app.modules.system.runtime_config import RuntimeConfigService

PLAN_TYPES = {"STANDARD", "SEASONAL", "EMERGENCY", "MANUAL"}
LINE_ROLES = {"MAIN", "ALTERNATE", "DETOUR", "EMERGENCY"}
NODE_TYPES = {"TRANSPORT_NODE", "CONSTRAINT_POINT", "MANUAL_POINT"}
TRANSPORT_MODES = {"WATER", "ROAD", "RAIL"}
TRACK_STATUSES = {"NOT_GENERATED", "READY", "PARTIAL", "FAILED"}
GEOMETRY_SOURCES = {"AMAP", "HIFLEET", "MANUAL", "FALLBACK"}


def _status_from_provider_status(value: str | None) -> str:
    return "READY" if str(value or "").lower() == "ready" else "FAILED"


def _geometry_source_from_provider(value: str | None) -> str | None:
    source = str(value or "").strip().upper()
    return source if source in GEOMETRY_SOURCES else None


def _line_string_points(geometry: dict | None) -> list[list[float]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") != "LineString":
        return []
    points: list[list[float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            lon = float(item[0])
            lat = float(item[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            if not points or points[-1] != [lon, lat]:
                points.append([lon, lat])
    return points


def _combine_line_strings(geometries: list[dict]) -> dict | None:
    combined: list[list[float]] = []
    for geometry in geometries:
        for point in _line_string_points(geometry):
            if not combined or combined[-1] != point:
                combined.append(point)
    if len(combined) < 2:
        return None
    return {"type": "LineString", "coordinates": combined}


def _track_status_from_success_count(success_count: int, total_count: int) -> str:
    if total_count <= 0:
        return "FAILED"
    if success_count == total_count:
        return "READY"
    if success_count > 0:
        return "PARTIAL"
    return "FAILED"


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_route_response(
    entity,
    *,
    plan_count: int = 0,
    line_count: int = 0,
    main_line_name: str | None = None,
    track_status: str = "NOT_GENERATED",
    track_error_message: str | None = None,
    track_generated_at: datetime | None = None,
) -> RouteResponse:
    return RouteResponse(
        id=entity.id,
        code=entity.code,
        name=entity.name,
        transport_org_type_code=entity.transport_org_type_code,
        multimodal_combination_code=entity.multimodal_combination_code,
        origin_region_id=entity.origin_region_id,
        destination_region_id=entity.destination_region_id,
        description=entity.description,
        audit_status=entity.audit_status,
        submitter_id=entity.submitter_id,
        auditor_id=entity.auditor_id,
        audited_at=entity.audited_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        plan_count=plan_count,
        line_count=line_count,
        main_line_name=main_line_name,
        track_status=track_status,
        track_error_message=track_error_message,
        track_generated_at=track_generated_at,
    )


def _to_plan_response(entity, *, line_count: int = 0, main_line_name: str | None = None) -> RoutePlanResponse:
    return RoutePlanResponse(
        id=entity.id,
        route_id=entity.route_id,
        plan_code=entity.plan_code,
        plan_name=entity.plan_name,
        plan_type_code=entity.plan_type_code,
        description=entity.description,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        line_count=line_count,
        main_line_name=main_line_name,
    )


def _to_line_response(entity, *, segment_count: int = 0) -> RouteLineResponse:
    return RouteLineResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        line_code=entity.line_code,
        line_name=entity.line_name,
        line_role_code=entity.line_role_code,
        priority=entity.priority,
        trigger_condition=entity.trigger_condition,
        description=entity.description,
        track_status=entity.track_status,
        track_generated_at=entity.track_generated_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        segment_count=segment_count,
    )


def _to_node_response(
    entity,
    *,
    transport_node: TransportNode | None = None,
    constraint_point: NavigationConstraintPoint | None = None,
) -> RouteLineNodeResponse:
    longitude = entity.longitude
    latitude = entity.latitude
    resolved_name = entity.display_name
    resolved_code = None
    resolved_node_type_code = entity.node_type_code
    resolved_address = entity.remark

    if transport_node is not None:
        longitude = transport_node.longitude
        latitude = transport_node.latitude
        resolved_name = transport_node.name
        resolved_code = transport_node.code
        resolved_node_type_code = transport_node.node_type_code
        resolved_address = transport_node.address
    elif constraint_point is not None:
        longitude = constraint_point.longitude
        latitude = constraint_point.latitude
        resolved_name = constraint_point.name
        resolved_code = constraint_point.code
        resolved_node_type_code = constraint_point.constraint_type_code
        resolved_address = constraint_point.description or entity.remark
    elif entity.node_type_code == "MANUAL_POINT":
        resolved_name = entity.manual_name or entity.display_name
        resolved_node_type_code = "MANUAL_POINT"

    return RouteLineNodeResponse(
        id=entity.id,
        line_id=entity.line_id,
        node_order=entity.node_order,
        node_type_code=entity.node_type_code,
        transport_node_id=entity.transport_node_id,
        constraint_point_id=entity.constraint_point_id,
        manual_name=entity.manual_name,
        longitude=longitude,
        latitude=latitude,
        display_name=entity.display_name,
        resolved_name=resolved_name,
        resolved_code=resolved_code,
        resolved_node_type_code=resolved_node_type_code,
        resolved_address=resolved_address,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_segment_response(entity) -> RouteLineSegmentResponse:
    return RouteLineSegmentResponse(
        id=entity.id,
        line_id=entity.line_id,
        segment_no=entity.segment_no,
        start_line_node_id=entity.start_line_node_id,
        end_line_node_id=entity.end_line_node_id,
        transport_mode_code=entity.transport_mode_code,
        distance_km=entity.distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        segment_track_status=entity.segment_track_status,
        geometry_source=entity.geometry_source,
        geometry_json=entity.geometry_json,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_track_response(entity) -> RouteLineTrackResponse:
    return RouteLineTrackResponse(
        id=entity.id,
        line_id=entity.line_id,
        track_status=entity.track_status,
        geometry_json=entity.geometry_json,
        distance_km=entity.distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        provider_summary_json=entity.provider_summary_json,
        error_message=entity.error_message,
        generated_at=entity.generated_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class ShippingRouteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.line_repo = ShippingRouteLineRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _route_stats(self, route_id: int) -> tuple[int, int, str | None, str]:
        plans = await self.plan_repo.list_all_plans(route_id)
        line_count = 0
        main_line_name = None
        status_rank = {"FAILED": 4, "PARTIAL": 3, "READY": 2, "NOT_GENERATED": 1}
        best_status = "NOT_GENERATED"
        for plan in plans:
            lines = await self.line_repo.list_lines(plan.id)
            line_count += len(lines)
            for line in lines:
                if line.line_role_code == "MAIN" and main_line_name is None:
                    main_line_name = line.line_name
                if status_rank.get(line.track_status, 0) > status_rank.get(best_status, 0):
                    best_status = line.track_status
        return len(plans), line_count, main_line_name, best_status

    async def list_routes(self, query) -> PageResponse[RouteResponse]:
        rows, total = await self.route_repo.list_routes_with_stats(
            keyword=query.keyword,
            origin_region_id=query.origin_region_id,
            destination_region_id=query.destination_region_id,
            transport_org_type_code=query.transport_org_type_code,
            plan_type_code=query.plan_type_code,
            has_plan=query.has_plan,
            has_main_line=query.has_main_line,
            track_status=query.track_status,
            page=query.page,
            page_size=query.page_size,
        )
        responses: list[RouteResponse] = []
        for row, plan_count, line_count, main_line_name, track_status, track_error_message, track_generated_at in rows:
            responses.append(
                _to_route_response(
                    row,
                    plan_count=plan_count,
                    line_count=line_count,
                    main_line_name=main_line_name,
                    track_status=track_status,
                    track_error_message=track_error_message,
                    track_generated_at=track_generated_at,
                )
            )
        return PageResponse[RouteResponse](total=total, page=query.page, page_size=query.page_size, items=responses)

    async def create_route(self, payload) -> RouteResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip() or await self.sequence_service.next_code("ROUTE_CODE")
        data["code"] = code
        if await self.route_repo.exists_route_code(code):
            raise ConflictError(f"route code already exists: {code}")
        row = await self.route_repo.create_route({**data, "name": payload.name.strip()})
        row.audit_status = "APPROVED"
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
        plan_count, line_count, main_line_name, track_status = await self._route_stats(row.id)
        return _to_route_response(row, plan_count=plan_count, line_count=line_count, main_line_name=main_line_name, track_status=track_status)

    async def get_route_detail(self, route_id: int) -> RouteDetailResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        plans = await self.plan_repo.list_all_plans(route_id)
        plan_count, line_count, main_line_name, track_status = await self._route_stats(route_id)
        plan_items = []
        for plan in plans:
            lines = await self.line_repo.list_lines(plan.id)
            main = next((line.line_name for line in lines if line.line_role_code == "MAIN"), None)
            plan_items.append(_to_plan_response(plan, line_count=len(lines), main_line_name=main))
        return RouteDetailResponse(
            route=_to_route_response(route, plan_count=plan_count, line_count=line_count, main_line_name=main_line_name, track_status=track_status),
            plans=plan_items,
        )

    async def delete_route(self, route_id: int) -> None:
        ok = await self.route_repo.soft_delete_route(route_id)
        if not ok:
            raise NotFoundError("ShippingRoute", route_id)
        await self.db.commit()


class ShippingRoutePlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.line_repo = ShippingRouteLineRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_plans(self, route_id: int, query) -> PageResponse[RoutePlanResponse]:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        rows, total = await self.plan_repo.list_plans(route_id, query.plan_type_code, query.page, query.page_size)
        items: list[RoutePlanResponse] = []
        for row in rows:
            lines = await self.line_repo.list_lines(row.id)
            main = next((line.line_name for line in lines if line.line_role_code == "MAIN"), None)
            items.append(_to_plan_response(row, line_count=len(lines), main_line_name=main))
        return PageResponse[RoutePlanResponse](total=total, page=query.page, page_size=query.page_size, items=items)

    async def create_plan(self, route_id: int, payload) -> RoutePlanResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        if payload.plan_type_code not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        data = payload.model_dump(exclude_none=True)
        plan_code = (payload.plan_code or "").strip() or await self.sequence_service.next_code("ROUTE_PLAN_CODE")
        data["plan_code"] = plan_code
        if await self.plan_repo.exists_plan_code(plan_code):
            raise ConflictError(f"plan code already exists: {plan_code}")
        row = await self.plan_repo.create_plan(route_id, data)
        await self.db.commit()
        return _to_plan_response(row)

    async def update_plan(self, plan_id: int, payload) -> RoutePlanResponse:
        updates = payload.model_dump(exclude_none=True)
        if "plan_type_code" in updates and updates["plan_type_code"] not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.plan_repo.update_plan(plan_id, updates)
        if row is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        await self.db.commit()
        lines = await self.line_repo.list_lines(row.id)
        main = next((line.line_name for line in lines if line.line_role_code == "MAIN"), None)
        return _to_plan_response(row, line_count=len(lines), main_line_name=main)

    async def delete_plan(self, plan_id: int) -> None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        for line in await self.line_repo.list_lines(plan_id):
            await self.line_repo.delete_line(line.id)
        await self.plan_repo.delete_plan(plan_id)
        await self.db.commit()


class ShippingRouteLineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.line_repo = ShippingRouteLineRepository(db)
        self.sequence_service = CodeSequenceService(db)
        self.runtime_config = RuntimeConfigService(db)

    async def _line_response(self, line) -> RouteLineResponse:
        segments = await self.line_repo.list_segments(line.id)
        return _to_line_response(line, segment_count=len(segments))

    async def _node_responses(self, nodes) -> list[RouteLineNodeResponse]:
        transport_ids = {
            node.transport_node_id
            for node in nodes
            if node.node_type_code == "TRANSPORT_NODE" and node.transport_node_id is not None
        }
        constraint_ids = {
            node.constraint_point_id
            for node in nodes
            if node.node_type_code == "CONSTRAINT_POINT" and node.constraint_point_id is not None
        }
        transport_by_id: dict[int, TransportNode] = {}
        constraint_by_id: dict[int, NavigationConstraintPoint] = {}

        if transport_ids:
            rows = (
                await self.db.execute(
                    select(TransportNode).where(
                        TransportNode.id.in_(transport_ids),
                        TransportNode.deleted_at.is_(None),
                    )
                )
            ).scalars()
            transport_by_id = {row.id: row for row in rows}

        if constraint_ids:
            rows = (
                await self.db.execute(
                    select(NavigationConstraintPoint).where(
                        NavigationConstraintPoint.id.in_(constraint_ids)
                    )
                )
            ).scalars()
            constraint_by_id = {row.id: row for row in rows}

        return [
            _to_node_response(
                node,
                transport_node=transport_by_id.get(node.transport_node_id),
                constraint_point=constraint_by_id.get(node.constraint_point_id),
            )
            for node in nodes
        ]

    async def list_lines(self, plan_id: int) -> list[RouteLineResponse]:
        if await self.plan_repo.get_plan_by_id(plan_id) is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        return [await self._line_response(item) for item in await self.line_repo.list_lines(plan_id)]

    async def create_line(self, plan_id: int, payload) -> RouteLineResponse:
        if await self.plan_repo.get_plan_by_id(plan_id) is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        if payload.line_role_code not in LINE_ROLES:
            raise ValidationError("invalid line_role_code")
        if payload.line_role_code == "MAIN" and await self.line_repo.main_line_exists(plan_id):
            raise ConflictError("main line already exists for this plan")
        data = payload.model_dump(exclude_none=True)
        line_code = (payload.line_code or "").strip() or await self.sequence_service.next_code("ROUTE_LINE_CODE")
        data["line_code"] = line_code
        data.setdefault("track_status", "NOT_GENERATED")
        if await self.line_repo.exists_line_code(plan_id, line_code):
            raise ConflictError(f"line code already exists: {line_code}")
        line = await self.line_repo.create_line(plan_id, data)
        await self.db.commit()
        return await self._line_response(line)

    async def update_line(self, line_id: int, payload) -> RouteLineResponse:
        line = await self.line_repo.get_line_by_id(line_id)
        if line is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        updates = payload.model_dump(exclude_none=True)
        if "line_role_code" in updates:
            if updates["line_role_code"] not in LINE_ROLES:
                raise ValidationError("invalid line_role_code")
            if updates["line_role_code"] == "MAIN" and await self.line_repo.main_line_exists(line.plan_id, exclude_line_id=line_id):
                raise ConflictError("main line already exists for this plan")
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.line_repo.update_line(line_id, updates)
        await self.db.commit()
        return await self._line_response(row)

    async def delete_line(self, line_id: int) -> None:
        ok = await self.line_repo.delete_line(line_id)
        if not ok:
            raise NotFoundError("ShippingRouteLine", line_id)
        await self.db.commit()

    async def get_structure(self, line_id: int) -> RouteLineStructureResponse:
        line = await self.line_repo.get_line_by_id(line_id)
        if line is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        nodes = await self.line_repo.list_nodes(line_id)
        segments = await self.line_repo.list_segments(line_id)
        track = await self.line_repo.get_track(line_id)
        return RouteLineStructureResponse(
            line=await self._line_response(line),
            nodes=await self._node_responses(nodes),
            segments=[_to_segment_response(item) for item in segments],
            track=_to_track_response(track) if track else None,
        )

    async def replace_structure(self, line_id: int, payload) -> RouteLineStructureResponse:
        line = await self.line_repo.get_line_by_id(line_id)
        if line is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        nodes = self._normalize_nodes(payload.nodes)
        segments = self._normalize_segments(payload.segments, len(nodes))
        await self._validate_node_refs(nodes)
        node_rows, segment_rows = await self.line_repo.replace_structure(line_id, nodes, segments)
        line.track_status = "NOT_GENERATED"
        line.track_generated_at = None
        await self.db.commit()
        return RouteLineStructureResponse(
            line=await self._line_response(line),
            nodes=await self._node_responses(node_rows),
            segments=[_to_segment_response(item) for item in segment_rows],
            track=None,
        )

    def _normalize_nodes(self, items) -> list[dict]:
        rows = []
        for idx, item in enumerate(items, start=1):
            data = item.model_dump(exclude_none=True)
            data["node_order"] = idx
            node_type = data.get("node_type_code")
            if node_type not in NODE_TYPES:
                raise ValidationError("invalid node_type_code")
            has_transport = data.get("transport_node_id") is not None
            has_constraint = data.get("constraint_point_id") is not None
            if node_type == "TRANSPORT_NODE":
                if not has_transport or has_constraint or data.get("manual_name") or data.get("longitude") is not None or data.get("latitude") is not None:
                    raise ValidationError("TRANSPORT_NODE must only reference transport_node_id")
            elif node_type == "CONSTRAINT_POINT":
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
            rows.append(data)
        return rows

    def _normalize_segments(self, items, node_count: int) -> list[dict]:
        rows = []
        expected_count = node_count - 1
        if len(items) != expected_count:
            raise ValidationError("segments must connect each adjacent line node")
        for idx, item in enumerate(items, start=1):
            data = item.model_dump(exclude_none=True)
            if data.get("segment_no") != idx:
                raise ValidationError("segment_no must be continuous from 1")
            if data.get("start_node_order") != idx or data.get("end_node_order") != idx + 1:
                raise ValidationError("segments must connect adjacent nodes")
            if data.get("transport_mode_code") not in TRANSPORT_MODES:
                raise ValidationError("invalid transport_mode_code")
            data["segment_track_status"] = data.get("segment_track_status") or "NOT_GENERATED"
            if data["segment_track_status"] not in {"NOT_GENERATED", "READY", "FAILED"}:
                raise ValidationError("invalid segment_track_status")
            if data.get("geometry_source") and data["geometry_source"] not in GEOMETRY_SOURCES:
                raise ValidationError("invalid geometry_source")
            rows.append(data)
        return rows

    async def _validate_node_refs(self, nodes: list[dict]) -> None:
        for item in nodes:
            if item["node_type_code"] == "TRANSPORT_NODE":
                exists = await self.db.scalar(select(TransportNode.id).where(TransportNode.id == item["transport_node_id"], TransportNode.deleted_at.is_(None)))
                if exists is None:
                    raise NotFoundError("TransportNode", item["transport_node_id"])
            elif item["node_type_code"] == "CONSTRAINT_POINT":
                exists = await self.db.scalar(select(NavigationConstraintPoint.id).where(NavigationConstraintPoint.id == item["constraint_point_id"]))
                if exists is None:
                    raise NotFoundError("NavigationConstraintPoint", item["constraint_point_id"])

    async def get_track(self, line_id: int) -> RouteLineTrackResponse | None:
        if await self.line_repo.get_line_by_id(line_id) is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        track = await self.line_repo.get_track(line_id)
        return _to_track_response(track) if track else None

    async def _resolve_node_point(self, node) -> tuple[float, float]:
        longitude = node.longitude
        latitude = node.latitude

        if node.node_type_code == "TRANSPORT_NODE":
            transport_node = await self.db.scalar(
                select(TransportNode).where(
                    TransportNode.id == node.transport_node_id,
                    TransportNode.deleted_at.is_(None),
                )
            )
            if transport_node is None:
                raise NotFoundError("TransportNode", node.transport_node_id)
            longitude = transport_node.longitude
            latitude = transport_node.latitude
        elif node.node_type_code == "CONSTRAINT_POINT":
            constraint_point = await self.db.scalar(
                select(NavigationConstraintPoint).where(
                    NavigationConstraintPoint.id == node.constraint_point_id
                )
            )
            if constraint_point is None:
                raise NotFoundError("NavigationConstraintPoint", node.constraint_point_id)
            longitude = constraint_point.longitude
            latitude = constraint_point.latitude

        if longitude is None or latitude is None:
            raise ValidationError(f"路线节点缺少经纬度: {node.display_name}")

        lon = float(longitude)
        lat = float(latitude)
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            raise ValidationError(f"路线节点经纬度非法: {node.display_name}")
        return lon, lat

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

    async def _generate_segment_geometry(
        self,
        *,
        segment,
        start_node,
        end_node,
        provider_code: str | None,
    ) -> RouteGeometryResult:
        origin_lon, origin_lat = await self._resolve_node_point(start_node)
        dest_lon, dest_lat = await self._resolve_node_point(end_node)
        client = self._geometry_client_for_segment(segment.transport_mode_code, provider_code)
        return await client.generate(
            RouteGeometryQuery(
                origin_lon=origin_lon,
                origin_lat=origin_lat,
                dest_lon=dest_lon,
                dest_lat=dest_lat,
                transport_mode=segment.transport_mode_code,
                segment_type="ROUTE_LINE_SEGMENT",
            )
        )

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        text = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
        return (text or "未知错误")[:180]

    async def generate_track(self, line_id: int, payload) -> RouteLineTrackGenerateResponse:
        line = await self.line_repo.get_line_by_id(line_id)
        if line is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        nodes = await self.line_repo.list_nodes(line_id)
        segments = await self.line_repo.list_segments(line_id)
        if not segments:
            raise ValidationError("请先保存至少一个路线段，再生成轨迹")

        now = datetime.utcnow()
        node_by_id = {node.id: node for node in nodes}
        successful_geometries: list[dict] = []
        segment_summaries: list[dict] = []
        error_messages: list[str] = []
        total_distance = Decimal("0")
        total_duration = Decimal("0")
        has_distance = False
        has_duration = False

        for segment in segments:
            start_node = node_by_id.get(segment.start_line_node_id)
            end_node = node_by_id.get(segment.end_line_node_id)
            if start_node is None or end_node is None:
                error_text = "路线段引用的起终点不存在"
                segment.segment_track_status = "FAILED"
                segment.geometry_source = None
                segment.geometry_json = None
                segment.distance_km = None
                segment.estimated_duration_hour = None
                error_messages.append(f"#{segment.segment_no} {error_text}")
                segment_summaries.append(
                    {
                        "segment_no": segment.segment_no,
                        "transport_mode_code": segment.transport_mode_code,
                        "status": "FAILED",
                        "error": error_text,
                    }
                )
                continue

            try:
                result = await self._generate_segment_geometry(
                    segment=segment,
                    start_node=start_node,
                    end_node=end_node,
                    provider_code=payload.provider_code,
                )
                status = _status_from_provider_status(result.status)
                source = _geometry_source_from_provider(result.source)
                if status != "READY" or not source:
                    raise ValidationError(f"provider 返回状态无效: {result.status}")

                segment.segment_track_status = "READY"
                segment.geometry_source = source
                segment.geometry_json = result.geometry
                segment.distance_km = _to_decimal(result.distance_km)
                segment.estimated_duration_hour = _to_decimal(result.estimated_duration_hour)
                successful_geometries.append(result.geometry)
                if result.distance_km is not None:
                    total_distance += Decimal(str(result.distance_km))
                    has_distance = True
                if result.estimated_duration_hour is not None:
                    total_duration += Decimal(str(result.estimated_duration_hour))
                    has_duration = True
                segment_summaries.append(
                    {
                        "segment_no": segment.segment_no,
                        "transport_mode_code": segment.transport_mode_code,
                        "status": "READY",
                        "provider": result.provider,
                        "geometry_source": source,
                        "provider_trace_id": result.provider_trace_id,
                        "point_count": len(_line_string_points(result.geometry)),
                        "distance_km": result.distance_km,
                        "estimated_duration_hour": result.estimated_duration_hour,
                        "raw_summary": result.raw_summary,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                error_text = self._safe_error_message(exc)
                segment.segment_track_status = "FAILED"
                segment.geometry_source = None
                segment.geometry_json = None
                segment.distance_km = None
                segment.estimated_duration_hour = None
                error_messages.append(f"#{segment.segment_no} {error_text}")
                segment_summaries.append(
                    {
                        "segment_no": segment.segment_no,
                        "transport_mode_code": segment.transport_mode_code,
                        "status": "FAILED",
                        "error": error_text,
                    }
                )

        success_count = len(successful_geometries)
        status = _track_status_from_success_count(success_count, len(segments))
        if status == "READY":
            message = "轨迹生成完成"
        elif status == "PARTIAL":
            message = f"轨迹部分生成：成功 {success_count}/{len(segments)} 段"
        else:
            message = "轨迹生成失败，未写入回退直线"

        line_geometry = _combine_line_strings(successful_geometries)
        line.track_status = status
        line.track_generated_at = now
        track = await self.line_repo.upsert_track(
            line_id,
            {
                "track_status": status,
                "geometry_json": line_geometry,
                "distance_km": total_distance if has_distance else None,
                "estimated_duration_hour": total_duration if has_duration else None,
                "provider_summary_json": {
                    "generated_by": "route_line_track_generate",
                    "success_count": success_count,
                    "failed_count": len(segments) - success_count,
                    "segments": segment_summaries,
                },
                "error_message": "; ".join(error_messages)[:512] if error_messages else None,
                "generated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        await self.db.commit()
        return RouteLineTrackGenerateResponse(
            line_id=line_id,
            status=status,
            message=message,
            track=_to_track_response(track),
        )
