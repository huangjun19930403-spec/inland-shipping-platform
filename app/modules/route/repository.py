"""route 模块 repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
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
        origin_region_id: int | None,
        destination_region_id: int | None,
        transport_org_type_code: str | None,
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
        if origin_region_id is not None:
            stmt = stmt.where(ShippingRoute.origin_region_id == origin_region_id)
        if destination_region_id is not None:
            stmt = stmt.where(ShippingRoute.destination_region_id == destination_region_id)
        if transport_org_type_code:
            stmt = stmt.where(ShippingRoute.transport_org_type_code == transport_org_type_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoute.id.desc()).offset((page - 1) * page_size).limit(page_size)
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

    async def soft_delete_route(self, route_id: int) -> bool:
        row = await self.get_route_by_id(route_id)
        if row is None:
            return False
        from datetime import datetime
        row.deleted_at = datetime.utcnow()
        await self.db.flush()
        return True

    async def exists_route_code(self, code: str, exclude_route_id: int | None = None) -> bool:
        stmt = select(ShippingRoute).where(ShippingRoute.code == code, ShippingRoute.deleted_at.is_(None))
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
        plan_type_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShippingRoutePlan], int]:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id)
        if plan_type_code:
            stmt = stmt.where(ShippingRoutePlan.plan_type_code == plan_type_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(stmt.order_by(ShippingRoutePlan.id.desc()).offset((page - 1) * page_size).limit(page_size))
        ).scalars().all()
        return list(rows), total

    async def list_all_plans(self, route_id: int) -> list[ShippingRoutePlan]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id).order_by(ShippingRoutePlan.id.desc())
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

    async def delete_plan(self, plan_id: int) -> bool:
        row = await self.get_plan_by_id(plan_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def exists_plan_code(self, plan_code: str, exclude_plan_id: int | None = None) -> bool:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == plan_code)
        if exclude_plan_id is not None:
            stmt = stmt.where(ShippingRoutePlan.id != exclude_plan_id)
        return await self.db.scalar(stmt) is not None


class ShippingRouteLineRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_line_by_id(self, line_id: int) -> ShippingRouteLine | None:
        return await self.db.scalar(select(ShippingRouteLine).where(ShippingRouteLine.id == line_id))

    async def list_lines(self, plan_id: int) -> list[ShippingRouteLine]:
        rows = (
            await self.db.execute(
                select(ShippingRouteLine)
                .where(ShippingRouteLine.plan_id == plan_id)
                .order_by(ShippingRouteLine.priority.asc(), ShippingRouteLine.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def create_line(self, plan_id: int, data: dict[str, Any]) -> ShippingRouteLine:
        row = ShippingRouteLine(plan_id=plan_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_line(self, line_id: int, data: dict[str, Any]) -> ShippingRouteLine | None:
        row = await self.get_line_by_id(line_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_line(self, line_id: int) -> bool:
        row = await self.get_line_by_id(line_id)
        if row is None:
            return False
        await self.clear_line_structure(line_id)
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def exists_line_code(self, plan_id: int, line_code: str, exclude_line_id: int | None = None) -> bool:
        stmt = select(ShippingRouteLine).where(ShippingRouteLine.plan_id == plan_id, ShippingRouteLine.line_code == line_code)
        if exclude_line_id is not None:
            stmt = stmt.where(ShippingRouteLine.id != exclude_line_id)
        return await self.db.scalar(stmt) is not None

    async def main_line_exists(self, plan_id: int, exclude_line_id: int | None = None) -> bool:
        stmt = select(ShippingRouteLine).where(ShippingRouteLine.plan_id == plan_id, ShippingRouteLine.line_role_code == "MAIN")
        if exclude_line_id is not None:
            stmt = stmt.where(ShippingRouteLine.id != exclude_line_id)
        return await self.db.scalar(stmt) is not None

    async def list_nodes(self, line_id: int) -> list[ShippingRouteLineNode]:
        rows = (
            await self.db.execute(
                select(ShippingRouteLineNode).where(ShippingRouteLineNode.line_id == line_id).order_by(ShippingRouteLineNode.node_order.asc())
            )
        ).scalars().all()
        return list(rows)

    async def list_segments(self, line_id: int) -> list[ShippingRouteLineSegment]:
        rows = (
            await self.db.execute(
                select(ShippingRouteLineSegment).where(ShippingRouteLineSegment.line_id == line_id).order_by(ShippingRouteLineSegment.segment_no.asc())
            )
        ).scalars().all()
        return list(rows)

    async def get_track(self, line_id: int) -> ShippingRouteLineTrack | None:
        return await self.db.scalar(select(ShippingRouteLineTrack).where(ShippingRouteLineTrack.line_id == line_id))

    async def clear_line_structure(self, line_id: int) -> None:
        await self.db.execute(delete(ShippingRouteLineTrack).where(ShippingRouteLineTrack.line_id == line_id))
        await self.db.execute(delete(ShippingRouteLineSegment).where(ShippingRouteLineSegment.line_id == line_id))
        await self.db.execute(delete(ShippingRouteLineNode).where(ShippingRouteLineNode.line_id == line_id))
        await self.db.flush()

    async def replace_structure(
        self,
        line_id: int,
        nodes: list[dict[str, Any]],
        segments: list[dict[str, Any]],
    ) -> tuple[list[ShippingRouteLineNode], list[ShippingRouteLineSegment]]:
        await self.clear_line_structure(line_id)
        node_entities: list[ShippingRouteLineNode] = []
        order_to_node: dict[int, ShippingRouteLineNode] = {}
        for item in nodes:
            row = ShippingRouteLineNode(line_id=line_id, **item)
            self.db.add(row)
            node_entities.append(row)
            order_to_node[item["node_order"]] = row
        await self.db.flush()
        for row in node_entities:
            await self.db.refresh(row)
        segment_entities: list[ShippingRouteLineSegment] = []
        for item in segments:
            start_order = item.pop("start_node_order")
            end_order = item.pop("end_node_order")
            row = ShippingRouteLineSegment(
                line_id=line_id,
                start_line_node_id=order_to_node[start_order].id,
                end_line_node_id=order_to_node[end_order].id,
                **item,
            )
            self.db.add(row)
            segment_entities.append(row)
        await self.db.flush()
        for row in segment_entities:
            await self.db.refresh(row)
        return await self.list_nodes(line_id), await self.list_segments(line_id)

    async def upsert_track(self, line_id: int, data: dict[str, Any]) -> ShippingRouteLineTrack:
        row = await self.get_track(line_id)
        if row is None:
            row = ShippingRouteLineTrack(line_id=line_id, **data)
            self.db.add(row)
        else:
            for key, value in data.items():
                if key == "created_at":
                    continue
                setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row
