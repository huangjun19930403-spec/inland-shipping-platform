"""Route CRUD service."""

from __future__ import annotations

from app.modules.route.services.common import *  # noqa: F403

class ShippingRouteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _route_stats(self, route_id: int) -> dict[str, Any]:
        plans = await self.plan_repo.list_all_plans(route_id)
        plan_count = len(plans)
        point_count = 0
        segment_count = 0
        selected_result_count = 0
        failed_count = 0
        track_version_count = 0
        current_track_version_id = None
        current_track_version_no = None
        current_track_source_type_code = None
        default_plan_id = None
        default_plan_name = None
        track_generated_at = None
        track_error_message = None
        active_track_generation_task = None
        for plan in plans:
            if plan.is_default and default_plan_id is None:
                default_plan_id = plan.id
                default_plan_name = plan.plan_name
                current_track_version_id = plan.current_track_version_id
            active_task = await _active_track_generation_task(self.db, plan)
            if active_task is not None and (active_track_generation_task is None or plan.is_default):
                active_track_generation_task = active_task
            points = await self.structure_repo.list_points(plan.id, plan.structure_revision)
            segments = await self.structure_repo.list_segments(plan.id, plan.structure_revision)
            versions = await self.structure_repo.list_track_versions(plan.id)
            track_version_count += len(versions)
            current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
            current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
            point_count += len(points)
            segment_count += len(segments)
            selected_result_count += len(current_version_segments)
            failed_count += 1 if current_version and current_version.version_status_code == "FAILED" else 0
            if current_version:
                if plan.is_default and current_track_version_no is None:
                    current_track_version_no = current_version.version_no
                    current_track_source_type_code = current_version.source_type_code
                if current_version.generated_at and (track_generated_at is None or current_version.generated_at > track_generated_at):
                    track_generated_at = current_version.generated_at
                if current_version.error_message:
                    track_error_message = current_version.error_message
        return {
            "plan_count": plan_count,
            "point_count": point_count,
            "segment_count": segment_count,
            "selected_result_count": selected_result_count,
            "current_track_version_id": current_track_version_id,
            "current_track_version_no": current_track_version_no,
            "current_track_source_type_code": current_track_source_type_code,
            "track_version_count": track_version_count,
            "default_plan_id": default_plan_id,
            "default_plan_name": default_plan_name,
            "track_status": _track_status_from_current_version(segment_count, selected_result_count, failed_count),
            "track_error_message": track_error_message,
            "track_generated_at": track_generated_at,
            "active_track_generation_task": active_track_generation_task,
        }

    async def _plan_response(self, plan) -> RoutePlanResponse:
        points = await self.structure_repo.list_points(plan.id, plan.structure_revision)
        segments = await self.structure_repo.list_segments(plan.id, plan.structure_revision)
        versions = await self.structure_repo.list_track_versions(plan.id)
        current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
        current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
        selected_count = len(current_version_segments)
        failed_count = 1 if current_version and current_version.version_status_code == "FAILED" else 0
        active_track_generation_task = await _active_track_generation_task(self.db, plan)
        return _to_plan_response(
            plan,
            point_count=len(points),
            segment_count=len(segments),
            selected_result_count=selected_count,
            failed_count=failed_count,
            current_track_version=current_version,
            track_version_count=len(versions),
            active_track_generation_task=active_track_generation_task,
        )

    async def list_routes(self, query) -> PageResponse[RouteResponse]:
        rows, total = await self.route_repo.list_routes_with_stats(
            keyword=query.keyword,
            origin_endpoint_type_code=query.origin_endpoint_type_code,
            origin_region_id=query.origin_region_id,
            origin_city_code=query.origin_city_code,
            origin_node_id=query.origin_node_id,
            destination_endpoint_type_code=query.destination_endpoint_type_code,
            destination_region_id=query.destination_region_id,
            destination_city_code=query.destination_city_code,
            destination_node_id=query.destination_node_id,
            transport_org_type_code=query.transport_org_type_code,
            plan_type_code=query.plan_type_code,
            has_plan=query.has_plan,
            has_default_plan=query.has_default_plan,
            track_status=query.track_status,
            page=query.page,
            page_size=query.page_size,
        )
        responses: list[RouteResponse] = []
        for (
            row,
            plan_count,
            point_count,
            segment_count,
            selected_count,
            current_version_id,
            current_version_no,
            current_source,
            track_version_count,
            default_id,
            default_name,
            status,
            error,
            generated_at,
        ) in rows:
            active_track_generation_task = None
            plans = await self.plan_repo.list_all_plans(row.id)
            for plan in sorted(plans, key=lambda item: (not item.is_default, item.display_order, item.id)):
                active_track_generation_task = await _active_track_generation_task(self.db, plan)
                if active_track_generation_task is not None:
                    break
            responses.append(
                _to_route_response(
                    row,
                    plan_count=plan_count,
                    point_count=point_count,
                    segment_count=segment_count,
                    selected_result_count=selected_count,
                    current_track_version_id=current_version_id,
                    current_track_version_no=current_version_no,
                    current_track_source_type_code=current_source,
                    track_version_count=track_version_count,
                    default_plan_id=default_id,
                    default_plan_name=default_name,
                    track_status=status,
                    track_error_message=error,
                    track_generated_at=generated_at,
                    active_track_generation_task=active_track_generation_task,
                )
            )
        return PageResponse[RouteResponse](total=total, page=query.page, page_size=query.page_size, items=responses)

    async def create_route(self, payload) -> RouteResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip() or await self.sequence_service.next_code("ROUTE_CODE")
        data["code"] = code
        data["name"] = payload.name.strip()
        data = await self._normalize_route_endpoint_data(data)
        if await self.route_repo.exists_route_code(code):
            raise ConflictError(f"route code already exists: {code}")
        row = await self.route_repo.create_route(data)
        await self.db.commit()
        return _to_route_response(row)

    async def update_route(self, route_id: int, payload) -> RouteResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        merged = {
            "origin_endpoint_type_code": route.origin_endpoint_type_code,
            "origin_region_id": route.origin_region_id,
            "origin_city_code": route.origin_city_code,
            "origin_node_id": route.origin_node_id,
            "destination_endpoint_type_code": route.destination_endpoint_type_code,
            "destination_region_id": route.destination_region_id,
            "destination_city_code": route.destination_city_code,
            "destination_node_id": route.destination_node_id,
        }
        merged.update({key: value for key, value in updates.items() if key in merged})
        normalized_endpoint = await self._normalize_route_endpoint_data(merged)
        updates.update(normalized_endpoint)
        if "name" in updates and updates["name"] is not None:
            updates["name"] = updates["name"].strip()
        row = await self.route_repo.update_route(route_id, updates)
        await self.db.commit()
        stats = await self._route_stats(row.id)
        return _to_route_response(row, **stats)

    async def get_route_detail(self, route_id: int) -> RouteDetailResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        plans = await self.plan_repo.list_all_plans(route_id)
        return RouteDetailResponse(
            route=_to_route_response(route, **await self._route_stats(route_id)),
            plans=[await self._plan_response(plan) for plan in plans],
        )

    async def delete_route(self, route_id: int) -> None:
        ok = await self.route_repo.hard_delete_route(route_id)
        if not ok:
            raise NotFoundError("ShippingRoute", route_id)
        await self.db.commit()

    async def _normalize_route_endpoint_data(self, data: dict[str, Any]) -> dict[str, Any]:
        for side in ("origin", "destination"):
            type_key = f"{side}_endpoint_type_code"
            endpoint_type = str(data.get(type_key) or "REGION").upper()
            if endpoint_type not in ENDPOINT_TYPES:
                raise ValidationError(f"invalid {type_key}")
            data[type_key] = endpoint_type
            region_key = f"{side}_region_id"
            city_key = f"{side}_city_code"
            node_key = f"{side}_node_id"
            if endpoint_type == "REGION":
                if data.get(region_key) is None:
                    raise ValidationError(f"{region_key} is required")
                exists = await self.db.scalar(select(Region.id).where(Region.id == data[region_key], Region.deleted_at.is_(None)))
                if exists is None:
                    raise NotFoundError("Region", data[region_key])
                data[city_key] = None
                data[node_key] = None
            elif endpoint_type == "CITY":
                if not data.get(city_key):
                    raise ValidationError(f"{city_key} is required")
                data[region_key] = None
                data[node_key] = None
            else:
                if data.get(node_key) is None:
                    raise ValidationError(f"{node_key} is required")
                exists = await self.db.scalar(select(TransportNode.id).where(TransportNode.id == data[node_key], TransportNode.deleted_at.is_(None)))
                if exists is None:
                    raise NotFoundError("TransportNode", data[node_key])
                data[region_key] = None
                data[city_key] = None
        return data


