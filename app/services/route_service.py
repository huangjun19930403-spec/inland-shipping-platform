"""航线业务服务层"""
import logging
from typing import List, Optional

from app.core.exceptions import NotFoundError
from app.models.route import (
    ShippingRoute,
    ShippingRoutePath,
    ShippingRoutePathNode,
    ShippingRoutePathSegment,
)
from app.repositories.route_repository import RouteRepository
from app.utils.route_helpers import gen_route_code, gen_route_path_code

logger = logging.getLogger(__name__)


class RouteService:
    """航线业务服务"""

    def __init__(self, route_repo: RouteRepository) -> None:
        self._route = route_repo

    # ---------- 航线 ----------

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
        created_by: Optional[int] = None,
        **kwargs,
    ) -> ShippingRoute:
        route = ShippingRoute(
            code=gen_route_code(),
            name=name,
            origin_region_id=origin_region_id,
            dest_region_id=dest_region_id,
            created_by=created_by,
            **kwargs,
        )
        saved = await self._route.create_route(route)

        default_path = ShippingRoutePath(
            route_id=saved.id,
            code=gen_route_path_code(),
            name="默认路线",
            sort_order=0,
            status=1,
        )
        await self._route.create_path(default_path)

        await self._route.save()
        logger.info("[RouteService] route created id=%s name=%s", saved.id, name)
        return await self._route.get_route(saved.id)

    async def update_route(self, route_id: int, **kwargs) -> ShippingRoute:
        await self.get_route(route_id)
        updated = await self._route.update_route(route_id, **kwargs)
        await self._route.save()
        return updated

    async def delete_route(self, route_id: int) -> None:
        await self.get_route(route_id)
        await self._route.delete_route_paths(route_id)
        await self._route.delete_route(route_id)
        await self._route.save()

    # ---------- 路线方案 ----------

    async def list_route_paths(self, route_id: int) -> List[ShippingRoutePath]:
        await self.get_route(route_id)
        return list(await self._route.get_route_paths(route_id))

    async def get_route_path(self, route_id: int, path_id: int) -> ShippingRoutePath:
        await self.get_route(route_id)
        path = await self._route.get_path(path_id)
        if not path or path.route_id != route_id:
            raise NotFoundError("ShippingRoutePath", path_id)
        return path

    async def create_route_path(
        self,
        route_id: int,
        name: str,
        description: Optional[str] = None,
        sort_order: int = 0,
        status: int = 1,
    ) -> ShippingRoutePath:
        await self.get_route(route_id)
        path = ShippingRoutePath(
            route_id=route_id,
            code=gen_route_path_code(),
            name=name,
            description=description,
            sort_order=sort_order,
            status=status,
        )
        saved = await self._route.create_path(path)
        await self._route.save()
        logger.info("[RouteService] path created id=%s route_id=%s", saved.id, route_id)
        return await self._route.get_path(saved.id)

    async def update_route_path(self, route_id: int, path_id: int, **kwargs) -> ShippingRoutePath:
        path = await self.get_route_path(route_id, path_id)
        await self._route.update_path(path.id, **kwargs)
        await self._route.save()
        return await self._route.get_path(path.id)

    async def delete_route_path(self, route_id: int, path_id: int) -> None:
        path = await self.get_route_path(route_id, path_id)
        deleted = await self._route.delete_path(path.id)
        if not deleted:
            raise NotFoundError("ShippingRoutePath", path_id)
        await self._route.save()

    # ---------- 路径节点（兼容保留） ----------

    async def add_path_node(
        self,
        route_id: int,
        path_id: int,
        node_id: int,
        sequence: int,
        distance_from_start: Optional[float] = None,
        node_role: str = "WAYPOINT",
    ) -> ShippingRoutePathNode:
        await self.get_route_path(route_id, path_id)
        node = ShippingRoutePathNode(
            path_id=path_id,
            node_id=node_id,
            sequence=sequence,
            distance_from_start=distance_from_start,
            node_role=node_role,
        )
        saved = await self._route.create_path_node(node)
        await self._route.save()
        return saved

    async def set_path_nodes(self, route_id: int, path_id: int, nodes: list) -> ShippingRoutePath:
        await self.get_route_path(route_id, path_id)
        await self._route.delete_path_nodes(path_id)
        for n in nodes:
            node = ShippingRoutePathNode(
                path_id=path_id,
                node_id=n["node_id"],
                sequence=n["sequence"],
                distance_from_start=n.get("distance_from_start"),
                node_role=n.get("node_role", "WAYPOINT"),
            )
            await self._route.create_path_node(node)
        await self._route.save()
        return await self._route.get_path(path_id)

    async def delete_path_node(self, route_id: int, path_id: int, node_id: int) -> None:
        await self.get_route_path(route_id, path_id)
        deleted = await self._route.delete_path_node(node_id)
        if not deleted:
            raise NotFoundError("ShippingRoutePathNode", node_id)
        await self._route.save()

    # ---------- 路径段（一期主表达） ----------

    async def list_path_segments(self, route_id: int, path_id: int) -> List[ShippingRoutePathSegment]:
        await self.get_route_path(route_id, path_id)
        return list(await self._route.get_path_segments(path_id))

    async def add_path_segment(
        self,
        route_id: int,
        path_id: int,
        **kwargs,
    ) -> ShippingRoutePathSegment:
        await self.get_route_path(route_id, path_id)
        segment = ShippingRoutePathSegment(path_id=path_id, **kwargs)
        saved = await self._route.create_path_segment(segment)
        await self._route.save()
        return saved

    async def set_path_segments(self, route_id: int, path_id: int, segments: list[dict]) -> ShippingRoutePath:
        await self.get_route_path(route_id, path_id)
        await self._route.delete_path_segments(path_id)
        for s in segments:
            seg = ShippingRoutePathSegment(path_id=path_id, **s)
            await self._route.create_path_segment(seg)
        await self._route.save()
        return await self._route.get_path(path_id)

    async def update_path_segment(
        self,
        route_id: int,
        path_id: int,
        segment_id: int,
        **kwargs,
    ) -> ShippingRoutePathSegment:
        await self.get_route_path(route_id, path_id)
        segment = await self._route.get_path_segment(segment_id)
        if not segment or segment.path_id != path_id:
            raise NotFoundError("ShippingRoutePathSegment", segment_id)
        await self._route.update_path_segment(segment_id, **kwargs)
        await self._route.save()
        return await self._route.get_path_segment(segment_id)

    async def delete_path_segment(self, route_id: int, path_id: int, segment_id: int) -> None:
        await self.get_route_path(route_id, path_id)
        segment = await self._route.get_path_segment(segment_id)
        if not segment or segment.path_id != path_id:
            raise NotFoundError("ShippingRoutePathSegment", segment_id)
        await self._route.delete_path_segment(segment_id)
        await self._route.save()
