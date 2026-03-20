"""航线数据访问层"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import and_, delete as sql_delete, func, select
from sqlalchemy.orm import selectinload

from app.models.route import (
    ShippingRoute,
    ShippingRoutePath,
    ShippingRoutePathNode,
    ShippingRoutePathSegment,
)
from app.repositories.base import BaseRepository


class RouteRepository(BaseRepository):
    model_class = ShippingRoute

    def _route_load_options(self):
        return (
            selectinload(ShippingRoute.paths)
            .selectinload(ShippingRoutePath.nodes),
            selectinload(ShippingRoute.paths)
            .selectinload(ShippingRoutePath.segments),
        )

    # ---------- ShippingRoute ----------

    async def get_route(self, route_id: int) -> Optional[ShippingRoute]:
        result = await self._db.execute(
            select(ShippingRoute)
            .where(ShippingRoute.id == route_id)
            .options(*self._route_load_options())
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

        total = (
            await self._db.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()

        result = await self._db.execute(
            query
            .options(*self._route_load_options())
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

    # ---------- ShippingRoutePath ----------

    async def get_path(self, path_id: int, load_children: bool = True) -> Optional[ShippingRoutePath]:
        q = select(ShippingRoutePath).where(ShippingRoutePath.id == path_id)
        if load_children:
            q = q.options(
                selectinload(ShippingRoutePath.nodes),
                selectinload(ShippingRoutePath.segments),
            )
        result = await self._db.execute(q)
        return result.scalar_one_or_none()

    async def get_route_paths(self, route_id: int) -> Sequence[ShippingRoutePath]:
        result = await self._db.execute(
            select(ShippingRoutePath)
            .where(ShippingRoutePath.route_id == route_id)
            .options(
                selectinload(ShippingRoutePath.nodes),
                selectinload(ShippingRoutePath.segments),
            )
            .order_by(ShippingRoutePath.sort_order)
        )
        return result.scalars().all()

    async def create_path(self, path: ShippingRoutePath) -> ShippingRoutePath:
        return await self.create(path)

    async def update_path(self, path_id: int, **kwargs) -> Optional[ShippingRoutePath]:
        path = await self.get_path(path_id)
        return await self.update(path, **kwargs) if path else None

    async def delete_path(self, path_id: int) -> bool:
        path = await self.get_path(path_id, load_children=False)
        if not path:
            return False
        await self._db.execute(
            sql_delete(ShippingRoutePathNode).where(
                ShippingRoutePathNode.path_id == path_id
            )
        )
        await self._db.execute(
            sql_delete(ShippingRoutePathSegment).where(
                ShippingRoutePathSegment.path_id == path_id
            )
        )
        await self._db.delete(path)
        await self._db.flush()
        return True

    async def delete_route_paths(self, route_id: int) -> None:
        paths = await self.get_route_paths(route_id)
        for p in paths:
            await self._db.execute(
                sql_delete(ShippingRoutePathNode).where(
                    ShippingRoutePathNode.path_id == p.id
                )
            )
            await self._db.execute(
                sql_delete(ShippingRoutePathSegment).where(
                    ShippingRoutePathSegment.path_id == p.id
                )
            )
        await self._db.execute(
            sql_delete(ShippingRoutePath).where(ShippingRoutePath.route_id == route_id)
        )

    # ---------- ShippingRoutePathNode ----------

    async def get_path_nodes(self, path_id: int) -> Sequence[ShippingRoutePathNode]:
        result = await self._db.execute(
            select(ShippingRoutePathNode)
            .where(ShippingRoutePathNode.path_id == path_id)
            .order_by(ShippingRoutePathNode.sequence)
        )
        return result.scalars().all()

    async def get_path_node(self, node_id: int) -> Optional[ShippingRoutePathNode]:
        result = await self._db.execute(
            select(ShippingRoutePathNode).where(ShippingRoutePathNode.id == node_id)
        )
        return result.scalar_one_or_none()

    async def create_path_node(self, node: ShippingRoutePathNode) -> ShippingRoutePathNode:
        return await self.create(node)

    async def delete_path_node(self, node_id: int) -> bool:
        node = await self.get_path_node(node_id)
        if not node:
            return False
        await self._db.delete(node)
        await self._db.flush()
        return True

    async def delete_path_nodes(self, path_id: int) -> None:
        await self._db.execute(
            sql_delete(ShippingRoutePathNode).where(
                ShippingRoutePathNode.path_id == path_id
            )
        )

    # ---------- ShippingRoutePathSegment ----------

    async def get_path_segments(self, path_id: int) -> Sequence[ShippingRoutePathSegment]:
        result = await self._db.execute(
            select(ShippingRoutePathSegment)
            .where(ShippingRoutePathSegment.path_id == path_id)
            .order_by(ShippingRoutePathSegment.sequence)
        )
        return result.scalars().all()

    async def get_path_segment(self, segment_id: int) -> Optional[ShippingRoutePathSegment]:
        result = await self._db.execute(
            select(ShippingRoutePathSegment).where(ShippingRoutePathSegment.id == segment_id)
        )
        return result.scalar_one_or_none()

    async def create_path_segment(self, segment: ShippingRoutePathSegment) -> ShippingRoutePathSegment:
        return await self.create(segment)

    async def update_path_segment(self, segment_id: int, **kwargs) -> Optional[ShippingRoutePathSegment]:
        segment = await self.get_path_segment(segment_id)
        return await self.update(segment, **kwargs) if segment else None

    async def delete_path_segment(self, segment_id: int) -> bool:
        segment = await self.get_path_segment(segment_id)
        if not segment:
            return False
        await self._db.delete(segment)
        await self._db.flush()
        return True

    async def delete_path_segments(self, path_id: int) -> None:
        await self._db.execute(
            sql_delete(ShippingRoutePathSegment).where(
                ShippingRoutePathSegment.path_id == path_id
            )
        )
