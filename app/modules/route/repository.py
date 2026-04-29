"""route 模块 repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import NavigationConstraintPoint, Region, TransportNode
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanNode,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentPoint,
)


class ShippingRouteRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_route_by_id(self, route_id: int) -> ShippingRoute | None:
        return await self.db.scalar(
            select(ShippingRoute).where(ShippingRoute.id == route_id, ShippingRoute.deleted_at.is_(None))
        )

    async def list_routes(
        self,
        keyword: str | None,
        status_code: int | None,
        origin_region_id: int | None,
        destination_region_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShippingRoute], int]:
        stmt = select(ShippingRoute).where(ShippingRoute.deleted_at.is_(None))
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    ShippingRoute.code.ilike(like_value),
                    ShippingRoute.name.ilike(like_value),
                    ShippingRoute.description.ilike(like_value),
                )
            )
        if status_code is not None:
            stmt = stmt.where(ShippingRoute.status == status_code)
        if origin_region_id is not None:
            stmt = stmt.where(ShippingRoute.origin_region_id == origin_region_id)
        if destination_region_id is not None:
            stmt = stmt.where(ShippingRoute.destination_region_id == destination_region_id)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoute.sort_order.asc(), ShippingRoute.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_route(self, data: dict[str, Any]) -> ShippingRoute:
        row = ShippingRoute(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_route(self, route_id: int, data: dict[str, Any]) -> ShippingRoute | None:
        row = await self.get_route_by_id(route_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_route_status(self, route_id: int, status_code: int) -> bool:
        row = await self.get_route_by_id(route_id)
        if row is None:
            return False
        row.status = status_code
        await self.db.flush()
        return True

    async def exists_route_code(self, code: str, exclude_route_id: int | None = None) -> bool:
        stmt = select(ShippingRoute).where(
            ShippingRoute.code == code,
            ShippingRoute.deleted_at.is_(None),
        )
        if exclude_route_id is not None:
            stmt = stmt.where(ShippingRoute.id != exclude_route_id)
        return await self.db.scalar(stmt) is not None


class ShippingRoutePlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_plan_by_id(self, plan_id: int) -> ShippingRoutePlan | None:
        return await self.db.scalar(select(ShippingRoutePlan).where(ShippingRoutePlan.id == plan_id))

    async def list_plans(
        self,
        route_id: int,
        status_code: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShippingRoutePlan], int]:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id)
        if status_code is not None:
            stmt = stmt.where(ShippingRoutePlan.status == status_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoutePlan.is_default.desc(), ShippingRoutePlan.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_all_plans(self, route_id: int) -> list[ShippingRoutePlan]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlan)
                .where(ShippingRoutePlan.route_id == route_id)
                .order_by(ShippingRoutePlan.is_default.desc(), ShippingRoutePlan.id.desc())
            )
        ).scalars().all()
        return list(rows)

    async def create_plan(self, route_id: int, data: dict[str, Any]) -> ShippingRoutePlan:
        row = ShippingRoutePlan(route_id=route_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_plan(self, plan_id: int, data: dict[str, Any]) -> ShippingRoutePlan | None:
        row = await self.get_plan_by_id(plan_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_plan_status(self, plan_id: int, status_code: int) -> bool:
        row = await self.get_plan_by_id(plan_id)
        if row is None:
            return False
        row.status = status_code
        await self.db.flush()
        return True

    async def activate_plan(self, route_id: int, plan_id: int) -> bool:
        plan = await self.get_plan_by_id(plan_id)
        if plan is None or plan.route_id != route_id:
            return False
        rows = await self.list_all_plans(route_id)
        for item in rows:
            item.is_default = item.id == plan_id
        await self.db.flush()
        return True

    async def get_current_plan(self, route_id: int) -> ShippingRoutePlan | None:
        return await self.db.scalar(
            select(ShippingRoutePlan)
            .where(ShippingRoutePlan.route_id == route_id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.id.desc())
        )

    async def exists_plan_code(self, plan_code: str, exclude_plan_id: int | None = None) -> bool:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == plan_code)
        if exclude_plan_id is not None:
            stmt = stmt.where(ShippingRoutePlan.id != exclude_plan_id)
        return await self.db.scalar(stmt) is not None


class ShippingRoutePlanNodeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_plan_nodes(self, plan_id: int) -> list[ShippingRoutePlanNode]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlanNode)
                .where(ShippingRoutePlanNode.plan_id == plan_id)
                .order_by(ShippingRoutePlanNode.node_order.asc(), ShippingRoutePlanNode.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def clear_plan_nodes(self, plan_id: int) -> None:
        await self.db.execute(
            delete(ShippingRoutePlanNode).where(ShippingRoutePlanNode.plan_id == plan_id)
        )
        await self.db.flush()

    async def replace_plan_nodes(
        self,
        plan_id: int,
        rows: list[dict[str, Any]],
    ) -> list[ShippingRoutePlanNode]:
        await self.clear_plan_nodes(plan_id)
        entities: list[ShippingRoutePlanNode] = []
        for item in rows:
            entity = ShippingRoutePlanNode(plan_id=plan_id, **item)
            self.db.add(entity)
            entities.append(entity)
        await self.db.flush()
        for entity in entities:
            await self.db.refresh(entity)
        return await self.list_plan_nodes(plan_id)


class ShippingRoutePlanSegmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_segments(self, plan_id: int) -> list[ShippingRoutePlanSegment]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlanSegment)
                .where(ShippingRoutePlanSegment.plan_id == plan_id)
                .order_by(ShippingRoutePlanSegment.sort_order.asc(), ShippingRoutePlanSegment.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def get_segment(self, segment_id: int) -> ShippingRoutePlanSegment | None:
        return await self.db.scalar(select(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.id == segment_id))

    async def create_segment(self, plan_id: int, data: dict[str, Any]) -> ShippingRoutePlanSegment:
        row = ShippingRoutePlanSegment(plan_id=plan_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_segment(self, segment_id: int, data: dict[str, Any]) -> ShippingRoutePlanSegment | None:
        row = await self.get_segment(segment_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_segment(self, segment_id: int) -> bool:
        row = await self.get_segment(segment_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def reorder_segments(self, plan_id: int, ordered_ids: list[int]) -> int:
        sorted_count = 0
        for index, segment_id in enumerate(ordered_ids):
            row = await self.db.scalar(
                select(ShippingRoutePlanSegment).where(
                    ShippingRoutePlanSegment.id == segment_id,
                    ShippingRoutePlanSegment.plan_id == plan_id,
                )
            )
            if row is None:
                continue
            row.sort_order = index + 1
            sorted_count += 1
        await self.db.flush()
        return sorted_count


class ShippingRoutePlanSegmentPointRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_points(self, segment_id: int) -> list[ShippingRoutePlanSegmentPoint]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlanSegmentPoint)
                .where(ShippingRoutePlanSegmentPoint.segment_id == segment_id)
                .order_by(ShippingRoutePlanSegmentPoint.point_no.asc(), ShippingRoutePlanSegmentPoint.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def get_point(self, point_id: int) -> ShippingRoutePlanSegmentPoint | None:
        return await self.db.scalar(
            select(ShippingRoutePlanSegmentPoint).where(ShippingRoutePlanSegmentPoint.id == point_id)
        )

    async def create_point(self, segment_id: int, data: dict[str, Any]) -> ShippingRoutePlanSegmentPoint:
        row = ShippingRoutePlanSegmentPoint(segment_id=segment_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_point(self, point_id: int, data: dict[str, Any]) -> ShippingRoutePlanSegmentPoint | None:
        row = await self.get_point(point_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_point(self, point_id: int) -> bool:
        row = await self.get_point(point_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def reorder_points(self, segment_id: int, ordered_ids: list[int]) -> int:
        sorted_count = 0
        for index, point_id in enumerate(ordered_ids):
            row = await self.db.scalar(
                select(ShippingRoutePlanSegmentPoint).where(
                    ShippingRoutePlanSegmentPoint.id == point_id,
                    ShippingRoutePlanSegmentPoint.segment_id == segment_id,
                )
            )
            if row is None:
                continue
            row.point_no = index + 1
            sorted_count += 1
        await self.db.flush()
        return sorted_count


class RouteNodeLookupRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_node(self, node_id: int) -> TransportNode | None:
        return await self.db.scalar(select(TransportNode).where(TransportNode.id == node_id, TransportNode.deleted_at.is_(None)))

    async def get_constraint_point(self, constraint_point_id: int) -> NavigationConstraintPoint | None:
        return await self.db.scalar(
            select(NavigationConstraintPoint).where(NavigationConstraintPoint.id == constraint_point_id)
        )

    async def get_region(self, region_id: int) -> Region | None:
        return await self.db.scalar(
            select(Region).where(Region.id == region_id, Region.deleted_at.is_(None))
        )
