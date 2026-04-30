"""route 模块 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.address import NavigationConstraintPoint, Region, TransportNode
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

PLAN_TYPES = {"STANDARD", "SEASONAL", "EMERGENCY", "MANUAL"}
LINE_ROLES = {"MAIN", "ALTERNATE", "DETOUR", "EMERGENCY"}
NODE_TYPES = {"TRANSPORT_NODE", "CONSTRAINT_POINT", "MANUAL_POINT"}
TRANSPORT_MODES = {"WATER", "ROAD", "RAIL"}
TRACK_STATUSES = {"NOT_GENERATED", "READY", "PARTIAL", "FAILED"}
GEOMETRY_SOURCES = {"AMAP", "HIFLEET", "MANUAL", "FALLBACK"}


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_route_response(entity, *, plan_count: int = 0, line_count: int = 0, main_line_name: str | None = None, track_status: str = "NOT_GENERATED") -> RouteResponse:
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


def _to_node_response(entity) -> RouteLineNodeResponse:
    return RouteLineNodeResponse(
        id=entity.id,
        line_id=entity.line_id,
        node_order=entity.node_order,
        node_type_code=entity.node_type_code,
        transport_node_id=entity.transport_node_id,
        constraint_point_id=entity.constraint_point_id,
        manual_name=entity.manual_name,
        longitude=entity.longitude,
        latitude=entity.latitude,
        display_name=entity.display_name,
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
        rows, total = await self.route_repo.list_routes(
            keyword=query.keyword,
            origin_region_id=query.origin_region_id,
            destination_region_id=query.destination_region_id,
            transport_org_type_code=query.transport_org_type_code,
            page=query.page,
            page_size=query.page_size,
        )
        responses: list[RouteResponse] = []
        for row in rows:
            plan_count, line_count, main_line_name, track_status = await self._route_stats(row.id)
            if query.has_plan is not None and (plan_count > 0) != query.has_plan:
                continue
            if query.has_main_line is not None and bool(main_line_name) != query.has_main_line:
                continue
            if query.track_status and track_status != query.track_status:
                continue
            if query.plan_type_code:
                plans = await self.plan_repo.list_all_plans(row.id)
                if not any(plan.plan_type_code == query.plan_type_code for plan in plans):
                    continue
            responses.append(
                _to_route_response(
                    row,
                    plan_count=plan_count,
                    line_count=line_count,
                    main_line_name=main_line_name,
                    track_status=track_status,
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

    async def _line_response(self, line) -> RouteLineResponse:
        segments = await self.line_repo.list_segments(line.id)
        return _to_line_response(line, segment_count=len(segments))

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
            nodes=[_to_node_response(item) for item in nodes],
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
            nodes=[_to_node_response(item) for item in node_rows],
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

    async def generate_track(self, line_id: int, payload) -> RouteLineTrackGenerateResponse:
        if await self.line_repo.get_line_by_id(line_id) is None:
            raise NotFoundError("ShippingRouteLine", line_id)
        return RouteLineTrackGenerateResponse(
            line_id=line_id,
            status="FAILED",
            message="provider not configured in Stage 4G; no track was generated",
            track=None,
        )
