"""
航线数据访问层
"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import select, and_, func, delete as sql_delete
from sqlalchemy.orm import selectinload

from app.models.route import ShippingRoute, ShippingRoutePath
from app.repositories.base import BaseRepository


class RouteRepository(BaseRepository):
    model_class = ShippingRoute

    async def get_route(self, route_id: int) -> Optional[ShippingRoute]:
        result = await self._db.execute(
            select(ShippingRoute)
            .where(ShippingRoute.id == route_id)
            .options(selectinload(ShippingRoute.path_nodes))
        )
        return result.scalar_one_or_none()

    async def list_routes(
        self,
        origin_region_id: Optional[int] = None,
        dest_region_id: Optional[int] = None,
        status: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[Sequence[ShippingRoute], int]:
        conditions = []
        if origin_region_id is not None:
            conditions.append(ShippingRoute.origin_region_id == origin_region_id)
        if dest_region_id is not None:
            conditions.append(ShippingRoute.dest_region_id == dest_region_id)
        if status is not None:
            conditions.append(ShippingRoute.status == status)

        query = select(ShippingRoute)
        if conditions:
            query = query.where(and_(*conditions))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.options(selectinload(ShippingRoute.path_nodes))
            .order_by(ShippingRoute.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().unique().all(), total

    async def create_route(self, route: ShippingRoute) -> ShippingRoute:
        return await self.create(route)

    async def update_route(self, route_id: int, **kwargs) -> Optional[ShippingRoute]:
        route = await self.get_route(route_id)
        return await self.update(route, **kwargs) if route else None

    async def delete_route(self, route_id: int) -> bool:
        route = await self.get_route(route_id)
        if not route:
            return False
        await self.delete(route)
        return True

    # ─────────────────────────────────────────────────
    # ShippingRoutePath
    # ─────────────────────────────────────────────────

    async def get_route_paths(self, route_id: int) -> Sequence[ShippingRoutePath]:
        result = await self._db.execute(
            select(ShippingRoutePath)
            .where(ShippingRoutePath.route_id == route_id)
            .order_by(ShippingRoutePath.sequence)
        )
        return result.scalars().all()

    async def get_path_node(self, path_id: int) -> Optional[ShippingRoutePath]:
        result = await self._db.execute(
            select(ShippingRoutePath).where(ShippingRoutePath.id == path_id)
        )
        return result.scalar_one_or_none()

    async def create_path_node(self, path_node: ShippingRoutePath) -> ShippingRoutePath:
        return await self.create(path_node)

    async def delete_path_node(self, path_id: int) -> bool:
        path = await self.get_path_node(path_id)
        if not path:
            return False
        await self.delete(path)
        return True

    async def delete_route_paths(self, route_id: int) -> None:
        await self._db.execute(
            sql_delete(ShippingRoutePath).where(
                ShippingRoutePath.route_id == route_id
            )
        )
