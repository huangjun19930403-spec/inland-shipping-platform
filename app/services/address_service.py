"""地址/节点业务服务层"""
import logging
import uuid
from typing import Optional

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.address import AdminRegion, NodeAlias, NodeType, Region, TransportNode, Waterway
from app.repositories.address_repository import AddressRepository
from app.services.audit_service import AuditService
from app.utils.region_helpers import compute_centroid, filter_cities_in_polygon, point_in_polygon
from app.utils.waterway_code_generator import WaterwayCodeGenerator

logger = logging.getLogger(__name__)
_waterway_code_gen = WaterwayCodeGenerator()


def _gen_node_type_code() -> str:
    return f"NT-{uuid.uuid4().hex[:12].upper()}"


def _gen_transport_node_code() -> str:
    return f"TN-{uuid.uuid4().hex[:12].upper()}"


class AddressService:
    """地址/节点业务服务"""

    def __init__(
        self,
        address_repo: AddressRepository,
        audit_svc: AuditService,
    ) -> None:
        self._address = address_repo
        self._audit_svc = audit_svc

    # ---------- 水系 ----------

    async def list_waterways(self, status: Optional[int] = None):
        return await self._address.list_waterways(status=status)

    async def create_waterway(self, name: str, operator_id: int, **kwargs) -> Waterway:
        level: int = kwargs.get("level", 1)
        parent_id: Optional[int] = kwargs.get("parent_id")

        parent_code: Optional[str] = None
        if parent_id is not None:
            parent_ww = await self._address.get_waterway(parent_id)
            if not parent_ww:
                raise NotFoundError("Waterway (parent)", parent_id)
            parent_code = parent_ww.code

        scope = f"ww:{parent_id if parent_id is not None else 'root'}"
        seq = await self._address.next_code_seq(scope)
        code = _waterway_code_gen.generate(
            name=name,
            level=level,
            parent_id=parent_id,
            parent_code=parent_code,
            seq=seq,
        )

        ww = Waterway(name=name, code=code, **kwargs)
        saved = await self._address.create_waterway(ww)
        await self._audit_svc.submit_for_audit(
            target_type="WATERWAY",
            target_id=saved.id,
            target_name=name,
            action="CREATE",
            submitter_id=operator_id,
            after_data={"name": name, "code": code},
        )
        await self._address.save()
        return saved

    async def update_waterway(self, waterway_id: int, operator_id: int, **kwargs) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        before = {"name": ww.name}
        updated = await self._address.update_waterway(waterway_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="WATERWAY",
            target_id=waterway_id,
            target_name=ww.name,
            action="UPDATE",
            submitter_id=operator_id,
            before_data=before,
            after_data=kwargs,
        )
        await self._address.save()
        return updated

    async def delete_waterway(self, waterway_id: int, operator_id: int) -> None:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        await self._address.delete_waterway(waterway_id)
        await self._audit_svc.record_operation(
            target_type="WATERWAY",
            target_id=waterway_id,
            target_name=ww.name,
            action="DELETE",
            operator_id=operator_id,
            before_data={"name": ww.name},
        )
        await self._address.save()

    async def toggle_waterway_status(self, waterway_id: int) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        new_status = 0 if ww.status == 1 else 1
        updated = await self._address.update_waterway(waterway_id, status=new_status)
        await self._address.save()
        return updated

    async def list_waterways_paged(
        self,
        name: Optional[str] = None,
        code: Optional[str] = None,
        status: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._address.list_waterways_paged(
            name=name,
            code=code,
            status=status,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ---------- 区域 ----------

    async def list_regions(self, status: Optional[int] = None):
        return await self._address.list_regions(status=status)

    async def list_regions_paged(
        self,
        name: Optional[str] = None,
        status: Optional[int] = None,
        audit_status: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._address.list_regions_paged(
            name=name,
            status=status,
            audit_status=audit_status,
            offset=offset,
            limit=page_size,
        )
        detail_items = []
        for region in items:
            rivers_info = [r.waterway for r in (region.waterway_relations or []) if r.waterway]
            cities_info = [r.admin_region for r in (region.city_relations or []) if r.admin_region]
            detail_items.append(
                {
                    "region": region,
                    "rivers_info": rivers_info,
                    "cities_info": cities_info,
                }
            )

        return {
            "items": detail_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _resolve_region_geo(self, boundary_coordinates: Optional[list]) -> tuple[Optional[float], Optional[float], list[int]]:
        if not boundary_coordinates:
            return None, None, []
        center_lng, center_lat = compute_centroid(boundary_coordinates)
        city_coords = await self._address.get_city_coords()
        city_tuples = [(row[0], float(row[1]), float(row[2])) for row in city_coords]
        city_ids = filter_cities_in_polygon(city_tuples, boundary_coordinates)
        return center_lng, center_lat, city_ids

    async def create_region(self, name: str, operator_id: int, **kwargs) -> Region:
        seq = await self._address.next_code_seq("region")
        code = f"RG-{seq:03d}"

        boundary = kwargs.pop("boundary_coordinates", None)
        waterway_ids = kwargs.pop("waterway_ids", None) or []

        center_lng, center_lat, city_ids = await self._resolve_region_geo(boundary)

        region = Region(
            name=name,
            code=code,
            boundary_coordinates=boundary,
            center_longitude=center_lng,
            center_latitude=center_lat,
            submitter_id=operator_id,
            audit_status=0,
            status=0,
            **kwargs,
        )
        saved = await self._address.create_region(region)

        await self._address.replace_region_waterway_relations(
            saved.id, waterway_ids, source="MANUAL"
        )
        await self._address.replace_region_city_relations(
            saved.id, city_ids, source="SYSTEM_GEO"
        )

        await self._audit_svc.submit_for_audit(
            target_type="REGION",
            target_id=saved.id,
            target_name=name,
            action="CREATE",
            submitter_id=operator_id,
            after_data={
                "name": name,
                "code": code,
                "waterway_ids": waterway_ids,
                "city_ids": city_ids,
            },
        )
        await self._address.save()
        return saved

    async def update_region(self, region_id: int, operator_id: int, **kwargs) -> Region:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        if region.status != 0:
            raise BadRequestError("只能修改停用状态（status=0）的区域数据")

        before = {"name": region.name, "code": region.code}

        boundary = kwargs.pop("boundary_coordinates", None)
        waterway_ids = kwargs.pop("waterway_ids", None)

        city_ids = None
        if boundary is not None:
            center_lng, center_lat, city_ids = await self._resolve_region_geo(boundary)
            kwargs["boundary_coordinates"] = boundary
            kwargs["center_longitude"] = center_lng
            kwargs["center_latitude"] = center_lat

        kwargs["audit_status"] = 0
        updated = await self._address.update_region(region_id, **kwargs)

        if waterway_ids is not None:
            await self._address.replace_region_waterway_relations(
                region_id,
                waterway_ids,
                source="MANUAL",
            )
        if city_ids is not None:
            await self._address.replace_region_city_relations(
                region_id,
                city_ids,
                source="SYSTEM_GEO",
            )

        await self._audit_svc.submit_for_audit(
            target_type="REGION",
            target_id=region_id,
            target_name=region.name,
            action="UPDATE",
            submitter_id=operator_id,
            before_data=before,
            after_data=kwargs,
        )
        await self._address.save()
        return updated

    async def delete_region(self, region_id: int, operator_id: int) -> None:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        await self._address.delete_region(region_id)
        await self._audit_svc.record_operation(
            target_type="REGION",
            target_id=region_id,
            target_name=region.name,
            action="DELETE",
            operator_id=operator_id,
        )
        await self._address.save()

    async def toggle_region_status(self, region_id: int) -> Region:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        new_status = 0 if region.status == 1 else 1
        updated = await self._address.update_region(region_id, status=new_status)
        await self._address.save()
        return updated

    async def get_nodes_in_region(self, region_id: int):
        return await self._address.get_nodes_in_region(region_id)

    # ---------- 行政区划 ----------

    async def list_admin_regions(
        self,
        level: Optional[int] = None,
        parent_code: Optional[str] = None,
        parent_id: Optional[int] = None,
    ):
        return await self._address.list_admin_regions(
            level=level,
            parent_code=parent_code,
            parent_id=parent_id,
        )

    async def create_admin_region(self, name: str, code: str, **kwargs) -> AdminRegion:
        region = AdminRegion(name=name, code=code, **kwargs)
        saved = await self._address.create_admin_region(region)
        await self._address.save()
        return saved

    async def update_admin_region(self, region_id: int, **kwargs) -> AdminRegion:
        region = await self._address.get_admin_region(region_id)
        if not region:
            raise NotFoundError("AdminRegion", region_id)
        updated = await self._address.update_admin_region(region_id, **kwargs)
        await self._address.save()
        return updated

    # ---------- 节点类型 ----------

    async def list_node_types(self, status: Optional[int] = None):
        return await self._address.list_node_types(status=status)

    async def create_node_type(self, name: str, operator_id: int, **kwargs) -> NodeType:
        code = _gen_node_type_code()
        nt = NodeType(name=name, code=code, **kwargs)
        saved = await self._address.create_node_type(nt)
        await self._address.save()
        return saved

    async def update_node_type(self, node_type_id: int, operator_id: int, **kwargs) -> NodeType:
        nt = await self._address.get_node_type(node_type_id)
        if not nt:
            raise NotFoundError("NodeType", node_type_id)
        updated = await self._address.update_node_type(node_type_id, **kwargs)
        await self._address.save()
        return updated

    async def delete_node_type(self, node_type_id: int, operator_id: int) -> None:
        nt = await self._address.get_node_type(node_type_id)
        if not nt:
            raise NotFoundError("NodeType", node_type_id)
        await self._address.delete_node_type(node_type_id)
        await self._address.save()

    # ---------- 节点 ----------

    async def list_nodes(
        self,
        audit_status: Optional[int] = None,
        region_id: Optional[int] = None,
        waterway_id: Optional[int] = None,
        status: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._address.list_nodes(
            waterway_id=waterway_id,
            region_id=region_id,
            audit_status=audit_status,
            status=status,
            keyword=keyword,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def search_nodes(self, q: str, page: int = 1, page_size: int = 20) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._address.search_nodes_by_alias(q, offset=offset, limit=page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_node(self, node_id: int) -> TransportNode:
        node = await self._address.get_node(node_id)
        if not node:
            raise NotFoundError("TransportNode", node_id)
        return node

    async def _match_regions_by_point(self, lng: float, lat: float) -> list[int]:
        regions = await self._address.list_regions_with_boundaries()
        return [
            region.id
            for region in regions
            if region.boundary_coordinates and point_in_polygon(lng, lat, region.boundary_coordinates)
        ]

    async def _sync_node_profile(self, node_id: int, profile_data: dict) -> None:
        allowed = {"river_km", "max_tonnage", "berth_count", "annual_throughput", "extra_attributes"}
        payload = {k: v for k, v in profile_data.items() if k in allowed}
        if payload:
            await self._address.upsert_node_profile(node_id, **payload)

    async def create_node(
        self,
        name: str,
        operator_id: int,
        waterway_id: Optional[int] = None,
        submitter_id: Optional[int] = None,
        latitude=None,
        longitude=None,
        **kwargs,
    ) -> TransportNode:
        code = _gen_transport_node_code()

        profile_data = kwargs.pop("profile", None) or {}
        region_ids = kwargs.pop("region_ids", None)
        primary_region_id = kwargs.pop("primary_region_id", None)

        node = TransportNode(
            name=name,
            code=code,
            waterway_id=waterway_id,
            latitude=latitude,
            longitude=longitude,
            submitter_id=submitter_id or operator_id,
            audit_status=0,
            **kwargs,
        )
        saved = await self._address.create_node(node)

        await self._sync_node_profile(saved.id, profile_data)

        if region_ids is not None:
            await self._address.sync_node_region_relations(
                saved.id,
                region_ids,
                primary_region_id=primary_region_id,
                source="MANUAL",
            )
        elif latitude is not None and longitude is not None:
            try:
                matched_region_ids = await self._match_regions_by_point(
                    float(longitude),
                    float(latitude),
                )
                await self._address.sync_node_region_relations(
                    saved.id,
                    matched_region_ids,
                    source="SYSTEM_GEO",
                )
            except Exception as exc:
                logger.warning("节点区域自动归属失败 node_id=%s: %s", saved.id, exc)

        await self._audit_svc.submit_for_audit(
            target_type="TRANSPORT_NODE",
            target_id=saved.id,
            target_name=name,
            action="CREATE",
            submitter_id=operator_id,
            after_data={"name": name, "code": code},
        )
        await self._address.save()
        return await self.get_node(saved.id)

    async def update_node(self, node_id: int, operator_id: int, **kwargs) -> TransportNode:
        node = await self.get_node(node_id)
        before = {"name": node.name, "code": node.code}

        profile_data = kwargs.pop("profile", None)
        region_ids = kwargs.pop("region_ids", None)
        primary_region_id = kwargs.pop("primary_region_id", None)

        updated = await self._address.update_node(node_id, **kwargs)

        if profile_data is not None:
            await self._sync_node_profile(node_id, profile_data)

        if region_ids is not None:
            await self._address.sync_node_region_relations(
                node_id,
                region_ids,
                primary_region_id=primary_region_id,
                source="MANUAL",
            )
        else:
            new_lat = kwargs.get("latitude")
            new_lng = kwargs.get("longitude")
            if new_lat is not None or new_lng is not None:
                lat = new_lat if new_lat is not None else (float(updated.latitude) if updated.latitude else None)
                lng = new_lng if new_lng is not None else (float(updated.longitude) if updated.longitude else None)
                if lat is not None and lng is not None:
                    matched_region_ids = await self._match_regions_by_point(float(lng), float(lat))
                    await self._address.sync_node_region_relations(
                        node_id,
                        matched_region_ids,
                        source="SYSTEM_GEO",
                    )

        await self._audit_svc.submit_for_audit(
            target_type="TRANSPORT_NODE",
            target_id=node_id,
            target_name=node.name,
            action="UPDATE",
            submitter_id=operator_id,
            before_data=before,
            after_data=kwargs,
        )
        await self._address.save()
        return await self.get_node(node_id)

    async def delete_node(self, node_id: int, operator_id: int) -> None:
        node = await self.get_node(node_id)
        await self._address.delete_node(node_id)
        await self._audit_svc.record_operation(
            target_type="TRANSPORT_NODE",
            target_id=node_id,
            target_name=node.name,
            action="DELETE",
            operator_id=operator_id,
            before_data={"name": node.name},
        )
        await self._address.save()

    async def reassign_all_nodes(self) -> dict:
        regions = await self._address.list_regions_with_boundaries()
        nodes = await self._address.list_all_nodes_with_coords()

        processed = 0
        for node in nodes:
            try:
                lng = float(node.longitude)
                lat = float(node.latitude)
                matching_ids = [
                    r.id
                    for r in regions
                    if r.boundary_coordinates and point_in_polygon(lng, lat, r.boundary_coordinates)
                ]
                await self._address.sync_node_region_relations(
                    node.id,
                    matching_ids,
                    source="SYSTEM_GEO",
                )
                processed += 1
            except Exception as exc:
                logger.warning("归属计算失败 node_id=%s: %s", node.id, exc)

        await self._address.save()
        logger.info("[AddressService] 一键归属完成，处理节点 %d 个", processed)
        return {"processed_nodes": processed, "active_regions": len(regions)}

    # ---------- 节点别名 ----------

    async def add_alias(self, node_id: int, alias_name: str, operator_id: int) -> NodeAlias:
        node = await self.get_node(node_id)
        alias = NodeAlias(node_id=node_id, alias_name=alias_name)
        saved = await self._address.create_alias(alias)
        await self._audit_svc.record_operation(
            target_type="NODE_ALIAS",
            target_id=saved.id,
            target_name=alias_name,
            action="CREATE",
            operator_id=operator_id,
            after_data={"node_id": node_id, "node_name": node.name, "alias_name": alias_name},
        )
        await self._address.save()
        return saved

    async def delete_alias(self, node_id: int, alias_id: int, operator_id: int) -> None:
        deleted = await self._address.delete_alias(alias_id)
        if not deleted:
            raise NotFoundError("NodeAlias", alias_id)
        await self._audit_svc.record_operation(
            target_type="NODE_ALIAS",
            target_id=alias_id,
            target_name=str(alias_id),
            action="DELETE",
            operator_id=operator_id,
        )
        await self._address.save()
