"""
航线业务服务层
职责：航线管理、路径节点、航线推荐
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import logging
from typing import Optional

from app.core.exceptions import NotFoundError
from app.models.route import ShippingRoute, ShippingRoutePath
from app.repositories.route_repository import RouteRepository

logger = logging.getLogger(__name__)


class RouteService:
    """航线业务服务"""

    def __init__(self, route_repo: RouteRepository) -> None:
        self._route = route_repo

    async def list_routes(
        self,
        origin_region_id: Optional[int] = None,
        dest_region_id: Optional[int] = None,
        status: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._route.list_routes(
            origin_region_id=origin_region_id,
            dest_region_id=dest_region_id,
            status=status,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_route(self, route_id: int) -> ShippingRoute:
        route = await self._route.get_route(route_id)
        if not route:
            raise NotFoundError("ShippingRoute", route_id)
        return route

    async def create_route(
        self,
        name: str,
        origin_region_id: int,
        dest_region_id: int,
        description: Optional[str] = None,
        path_nodes: Optional[list] = None,
        **kwargs,
    ) -> ShippingRoute:
        route = ShippingRoute(
            name=name,
            origin_region_id=origin_region_id,
            dest_region_id=dest_region_id,
            description=description,
            **kwargs,
        )
        saved = await self._route.create_route(route)
        if path_nodes:
            for pn in path_nodes:
                path = ShippingRoutePath(
                    route_id=saved.id,
                    node_id=pn["node_id"],
                    sequence=pn["sequence"],
                    distance_km=pn.get("distance_km"),
                )
                await self._route.create_path_node(path)
        await self._route.save()
        logger.info(f"[RouteService] route created id={saved.id} name={name}")
        return saved

    async def update_route(self, route_id: int, **kwargs) -> ShippingRoute:
        route = await self.get_route(route_id)
        updated = await self._route.update_route(route_id, **kwargs)
        await self._route.save()
        return updated

    async def delete_route(self, route_id: int) -> None:
        await self.get_route(route_id)
        await self._route.delete_route_paths(route_id)
        await self._route.delete_route(route_id)
        await self._route.save()

    # ─────────────────────────────────────────────────
    # 路径节点
    # ─────────────────────────────────────────────────

    async def get_route_path(self, route_id: int):
        await self.get_route(route_id)
        return await self._route.get_route_paths(route_id)

    async def add_route_path(
        self, route_id: int, node_id: int, sequence: int, distance_km: Optional[float] = None
    ) -> ShippingRoutePath:
        await self.get_route(route_id)
        path = ShippingRoutePath(
            route_id=route_id, node_id=node_id,
            sequence=sequence, distance_km=distance_km,
        )
        saved = await self._route.create_path_node(path)
        await self._route.save()
        return saved

    async def delete_route_path(self, route_id: int, path_id: int) -> None:
        deleted = await self._route.delete_path_node(path_id)
        if not deleted:
            raise NotFoundError("ShippingRoutePath", path_id)
        await self._route.save()

    async def update_route_paths(self, route_id: int, path_nodes: list) -> ShippingRoute:
        """替换航线路径节点"""
        await self.get_route(route_id)
        await self._route.delete_route_paths(route_id)
        for pn in path_nodes:
            path = ShippingRoutePath(
                route_id=route_id, node_id=pn["node_id"],
                sequence=pn["sequence"], distance_km=pn.get("distance_km"),
            )
            await self._route.create_path_node(path)
        await self._route.save()
        return await self.get_route(route_id)
