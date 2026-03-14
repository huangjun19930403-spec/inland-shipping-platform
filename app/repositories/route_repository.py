"""
航线数据访问层
"""
from typing import Optional, Sequence

from sqlalchemy import select
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
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[ShippingRoute], int]:
        filters = []
        if origin_region_id:
            filters.append(ShippingRoute.origin_region_id == origin_region_id)
        if dest_region_id:
            filters.append(ShippingRoute.dest_region_id == dest_region_id)

        from sqlalchemy import and_, func
        query = select(ShippingRoute)
        if filters:
            query = query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(query.offset(offset).limit(limit))
        return result.scalars().all(), total

    async def create_route(self, route: ShippingRoute) -> ShippingRoute:
        return await self.create(route)

    async def create_path_node(
        self, path_node: ShippingRoutePath
    ) -> ShippingRoutePath:
        return await self.create(path_node)

    async def delete_route_paths(self, route_id: int) -> None:
        from sqlalchemy import delete
        await self._db.execute(
            delete(ShippingRoutePath).where(
                ShippingRoutePath.route_id == route_id
            )
        )
