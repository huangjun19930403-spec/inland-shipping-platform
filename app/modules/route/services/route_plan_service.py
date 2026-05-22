"""Route plan service."""

from __future__ import annotations

from app.modules.route.services.common import *  # noqa: F403

class ShippingRoutePlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.sequence_service = CodeSequenceService(db)

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

    async def list_plans(self, route_id: int, query) -> PageResponse[RoutePlanResponse]:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        rows, total = await self.plan_repo.list_plans(route_id, query.plan_type_code, query.status_code, query.page, query.page_size)
        items = [await self._plan_response(row) for row in rows]
        return PageResponse[RoutePlanResponse](total=total, page=query.page, page_size=query.page_size, items=items)

    async def create_plan(self, route_id: int, payload) -> RoutePlanResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        if payload.plan_type_code not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        if payload.status_code not in PLAN_STATUSES:
            raise ValidationError("invalid status_code")
        field_set = getattr(payload, "model_fields_set", set())
        data = payload.model_dump(exclude_none=True)
        data["plan_code"] = (payload.plan_code or "").strip() or await self.sequence_service.next_code("ROUTE_PLAN_CODE")
        if "display_order" not in field_set:
            data["display_order"] = await self.plan_repo.next_display_order(route_id)
        existing = await self.plan_repo.list_all_plans(route_id)
        if not existing:
            data["is_default"] = True
        if data.get("is_default"):
            await self.plan_repo.clear_default_for_route(route_id)
        if await self.plan_repo.exists_plan_code(data["plan_code"]):
            raise ConflictError(f"plan code already exists: {data['plan_code']}")
        row = await self.plan_repo.create_plan(route_id, data)
        await self.db.commit()
        return await self._plan_response(row)

    async def update_plan(self, plan_id: int, payload) -> RoutePlanResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        updates = payload.model_dump(exclude_unset=True)
        if "plan_type_code" in updates and updates["plan_type_code"] not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        if "status_code" in updates and updates["status_code"] not in PLAN_STATUSES:
            raise ValidationError("invalid status_code")
        if not updates:
            raise ValidationError("no update fields provided")
        if updates.get("is_default"):
            await self.plan_repo.clear_default_for_route(plan.route_id, exclude_plan_id=plan_id)
        row = await self.plan_repo.update_plan(plan_id, updates)
        await self.db.commit()
        return await self._plan_response(row)

    async def delete_plan(self, plan_id: int) -> None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        route_id = plan.route_id
        was_default = plan.is_default
        await self.structure_repo.delete_plan_structure(plan_id)
        await self.plan_repo.delete_plan(plan_id)
        if was_default:
            remaining = await self.plan_repo.list_all_plans(route_id)
            if remaining:
                remaining[0].is_default = True
                await self.db.flush()
        await self.db.commit()


