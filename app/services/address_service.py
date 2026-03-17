"""
地址/节点业务服务层
职责：内河运输节点、水系、区域相关业务逻辑
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError, ConflictError, BadRequestError
from app.models.address import (
    Waterway, Region, AdminRegion, NodeType, TransportNode, NodeAlias,
)
from app.repositories.address_repository import AddressRepository
from app.services.audit_service import AuditService
from app.utils.waterway_code_generator import WaterwayCodeGenerator
from app.utils.region_helpers import (
    generate_region_code,
    compute_centroid,
    filter_cities_in_polygon,
)

logger = logging.getLogger(__name__)

# 模块级单例：无状态工具类，整个进程复用同一实例
_waterway_code_gen = WaterwayCodeGenerator()
# 编码冲突时最大重试次数（高并发下同级别的竞争插入）
_CODE_GEN_MAX_RETRIES = 3


class AddressService:
    """地址/节点业务服务"""

    def __init__(
        self,
        address_repo: AddressRepository,
        audit_svc: AuditService,
    ) -> None:
        self._address = address_repo
        self._audit_svc = audit_svc

    # ─────────────────────────────────────────────────
    # 水系
    # ─────────────────────────────────────────────────

    async def list_waterways(self, status: Optional[int] = None):
        return await self._address.list_waterways(status=status)

    async def create_waterway(self, name: str, operator_id: int, **kwargs) -> Waterway:
        """
        新增水系，编码由系统自动生成（WW-LL-NNN 格式）。

        并发安全策略
        ────────────
        1. 查询同 parent_id 下当前最大编码，生成候选编码。
        2. 执行 flush；若触发唯一约束冲突（并发插入导致序号碰撞），
           回滚本次 flush 并重新查询最大编码，最多重试 _CODE_GEN_MAX_RETRIES 次。
        3. 数据库层的 UNIQUE 约束是最终防线，保证绝对唯一性。
        """
        level: int = kwargs.get("level", 1)
        parent_id: Optional[int] = kwargs.get("parent_id")

        # 若有父级，提前校验并缓存父级编码（用于继承流域段 WW）
        parent_code: Optional[str] = None
        if parent_id is not None:
            parent_ww = await self._address.get_waterway(parent_id)
            if not parent_ww:
                raise NotFoundError("Waterway (parent)", parent_id)
            parent_code = parent_ww.code

        for attempt in range(_CODE_GEN_MAX_RETRIES):
            max_sibling = await self._address.get_max_sibling_waterway_code(parent_id)
            code = _waterway_code_gen.generate(
                name=name,
                level=level,
                parent_id=parent_id,
                parent_code=parent_code,
                max_sibling_code=max_sibling,
            )
            try:
                ww = Waterway(name=name, code=code, **kwargs)
                saved = await self._address.create_waterway(ww)
                await self._audit_svc.submit_for_audit(
                    target_type="WATERWAY", target_id=saved.id,
                    target_name=name, action="CREATE",
                    submitter_id=operator_id,
                    after_data={"name": name, "code": code},
                )
                await self._address.save()
                return saved
            except IntegrityError:
                await self._address.rollback()
                if attempt < _CODE_GEN_MAX_RETRIES - 1:
                    logger.warning(
                        "水系编码 %r 冲突（并发写入），第 %d 次重试",
                        code, attempt + 1,
                    )
                else:
                    logger.error(
                        "水系编码生成失败：%d 次重试后仍冲突，name=%r parent_id=%s",
                        _CODE_GEN_MAX_RETRIES, name, parent_id,
                    )
                    raise

        # 理论上不可达，满足类型检查器
        raise RuntimeError("create_waterway: unexpected exit from retry loop")

    async def update_waterway(self, waterway_id: int, operator_id: int, **kwargs) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        before = {"name": ww.name}
        updated = await self._address.update_waterway(waterway_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="WATERWAY", target_id=waterway_id,
            target_name=ww.name, action="UPDATE",
            submitter_id=operator_id,
            before_data=before, after_data=kwargs,
        )
        await self._address.save()
        return updated

    async def delete_waterway(self, waterway_id: int, operator_id: int) -> None:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        await self._address.delete_waterway(waterway_id)
        await self._audit_svc.record_operation(
            target_type="WATERWAY", target_id=waterway_id,
            target_name=ww.name, action="DELETE",
            operator_id=operator_id,
            before_data={"name": ww.name},
        )
        await self._address.save()

    async def toggle_waterway_status(self, waterway_id: int) -> Waterway:
        """启用 / 停用水系（自动取反当前 status，无需审批）。"""
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
            name=name, code=code, status=status, offset=offset, limit=page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ─────────────────────────────────────────────────
    # 商业区域
    # ─────────────────────────────────────────────────

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
            name=name, status=status, audit_status=audit_status,
            offset=offset, limit=page_size,
        )
        # 展开主要水系和城市（名称直接从冗余字段读取，无需二次查询）
        detail_items = []
        for region in items:
            rivers_info = list(
                await self._address.get_waterways_by_ids(region.main_rivers)
            ) if region.main_rivers else []
            cities_info = list(
                await self._address.get_admin_regions_by_ids(region.main_cities)
            ) if region.main_cities else []
            detail_items.append({
                "region": region,
                "rivers_info": rivers_info,
                "cities_info": cities_info,
            })
        return {
            "items": detail_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _resolve_region_geo(
        self,
        boundary_coordinates: Optional[list],
    ) -> tuple[Optional[float], Optional[float], list[int]]:
        """
        根据边界坐标计算质心和圈内城市 ID。
        Returns: (center_lng, center_lat, city_ids)
        """
        if not boundary_coordinates:
            return None, None, []
        center_lng, center_lat = compute_centroid(boundary_coordinates)
        city_coords = await self._address.get_city_coords()
        city_tuples = [(row[0], float(row[1]), float(row[2])) for row in city_coords]
        city_ids = filter_cities_in_polygon(city_tuples, boundary_coordinates)
        return center_lng, center_lat, city_ids

    async def create_region(self, name: str, operator_id: int, **kwargs) -> Region:
        """
        新增区域：
        - code 自动生成（RG-NNN）
        - 质心和城市列表由 boundary_coordinates 自动计算
        - 初始 audit_status=0（待审核），status=0（停用）
        - main_rivers_names / main_cities_names 写入时自动查表填充
        """
        max_code = await self._address.get_max_region_code()
        code = generate_region_code(max_code)

        boundary = kwargs.pop("boundary_coordinates", None)
        center_lng, center_lat, city_ids = await self._resolve_region_geo(boundary)

        # 查询水系名称（冗余存储）
        river_ids = kwargs.get("main_rivers") or []
        rivers_names = None
        if river_ids:
            wws = await self._address.get_waterways_by_ids(river_ids)
            rivers_names = [w.name for w in wws] or None

        # 查询城市名称（冗余存储）
        cities_names = None
        if city_ids:
            ars = await self._address.get_admin_regions_by_ids(city_ids)
            cities_names = [r.name for r in ars] or None

        region = Region(
            name=name,
            code=code,
            boundary_coordinates=boundary,
            center_longitude=center_lng,
            center_latitude=center_lat,
            main_cities=city_ids if city_ids else None,
            main_cities_names=cities_names,
            main_rivers_names=rivers_names,
            submitter_id=operator_id,
            audit_status=0,
            status=0,
            **kwargs,
        )
        saved = await self._address.create_region(region)
        await self._audit_svc.submit_for_audit(
            target_type="REGION", target_id=saved.id,
            target_name=name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": name, "code": code},
        )
        await self._address.save()
        return saved

    async def update_region(self, region_id: int, operator_id: int, **kwargs) -> Region:
        """
        修改区域：
        - 仅允许在 status=0（停用）状态下修改
        - 修改后 audit_status 重置为 0（待审核）
        - 若传入 boundary_coordinates，重新计算质心和城市
        """
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        if region.status != 0:
            raise BadRequestError("只能修改停用状态（status=0）的区域数据")

        before = {"name": region.name, "code": region.code}

        boundary = kwargs.pop("boundary_coordinates", None)
        if boundary is not None:
            center_lng, center_lat, city_ids = await self._resolve_region_geo(boundary)
            kwargs["boundary_coordinates"] = boundary
            kwargs["center_longitude"] = center_lng
            kwargs["center_latitude"] = center_lat
            kwargs["main_cities"] = city_ids if city_ids else None
            # 同步更新城市名称冗余字段
            if city_ids:
                ars = await self._address.get_admin_regions_by_ids(city_ids)
                kwargs["main_cities_names"] = [r.name for r in ars] or None
            else:
                kwargs["main_cities_names"] = None

        # main_rivers 变更时同步更新水系名称冗余字段
        if "main_rivers" in kwargs:
            river_ids = kwargs["main_rivers"] or []
            if river_ids:
                wws = await self._address.get_waterways_by_ids(river_ids)
                kwargs["main_rivers_names"] = [w.name for w in wws] or None
            else:
                kwargs["main_rivers_names"] = None

        kwargs["audit_status"] = 0  # 修改后需重新审核

        updated = await self._address.update_region(region_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="REGION", target_id=region_id,
            target_name=region.name, action="UPDATE",
            submitter_id=operator_id,
            before_data=before, after_data=kwargs,
        )
        await self._address.save()
        return updated

    async def delete_region(self, region_id: int, operator_id: int) -> None:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        await self._address.delete_region(region_id)
        await self._audit_svc.record_operation(
            target_type="REGION", target_id=region_id,
            target_name=region.name, action="DELETE", operator_id=operator_id,
        )
        await self._address.save()

    async def approve_region(self, region_id: int, auditor_id: int, remark: str = "") -> Region:
        """审批通过：audit_status=1，同时启用区域（status=1）。"""
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        updated = await self._address.update_region(
            region_id, audit_status=1, status=1, auditor_id=auditor_id,
            audit_remark=remark or None,
        )
        await self._audit_svc.record_operation(
            target_type="REGION", target_id=region_id,
            target_name=region.name, action="APPROVE", operator_id=auditor_id,
            audit_result="APPROVED", remark=remark or None,
        )
        await self._address.save()
        return updated

    async def reject_region(self, region_id: int, auditor_id: int, remark: str) -> Region:
        """审批驳回：audit_status=2，保持 status=0（停用）。"""
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        updated = await self._address.update_region(
            region_id, audit_status=2, auditor_id=auditor_id, audit_remark=remark,
        )
        await self._audit_svc.record_operation(
            target_type="REGION", target_id=region_id,
            target_name=region.name, action="REJECT", operator_id=auditor_id,
            audit_result="REJECTED", remark=remark,
        )
        await self._address.save()
        return updated

    async def toggle_region_status(self, region_id: int) -> Region:
        """启用 / 停用区域（自动取反，无需审批）。"""
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        new_status = 0 if region.status == 1 else 1
        updated = await self._address.update_region(region_id, status=new_status)
        await self._address.save()
        return updated

    async def get_nodes_in_region(self, region_id: int):
        return await self._address.get_nodes_in_region(region_id)

    # ─────────────────────────────────────────────────
    # 行政区划
    # ─────────────────────────────────────────────────

    async def list_admin_regions(
        self,
        level: Optional[int] = None,
        parent_code: Optional[str] = None,
        parent_id: Optional[int] = None,
    ):
        return await self._address.list_admin_regions(
            level=level, parent_code=parent_code, parent_id=parent_id
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

    # ─────────────────────────────────────────────────
    # 节点类型
    # ─────────────────────────────────────────────────

    async def list_node_types(self, status: Optional[int] = None):
        return await self._address.list_node_types(status=status)

    async def create_node_type(self, name: str, code: str, operator_id: int, **kwargs) -> NodeType:
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

    # ─────────────────────────────────────────────────
    # 运输节点
    # ─────────────────────────────────────────────────

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

    async def create_node(
        self,
        name: str,
        code: str,
        waterway_id: int,
        operator_id: int,
        region_id: Optional[int] = None,
        node_type_id: Optional[int] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        submitter_id: Optional[int] = None,
        **kwargs,
    ) -> TransportNode:
        existing = await self._address.get_node_by_code(code)
        if existing:
            raise ConflictError(f"Node code '{code}' already exists")
        node = TransportNode(
            name=name, code=code, waterway_id=waterway_id,
            region_id=region_id, node_type_id=node_type_id,
            latitude=latitude, longitude=longitude,
            submitter_id=submitter_id or operator_id,
            audit_status=0,
            **kwargs,
        )
        saved = await self._address.create_node(node)
        await self._audit_svc.submit_for_audit(
            target_type="TRANSPORT_NODE", target_id=saved.id,
            target_name=name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": name, "code": code},
        )
        await self._address.save()
        return saved

    async def update_node(self, node_id: int, operator_id: int, **kwargs) -> TransportNode:
        node = await self.get_node(node_id)
        before = {"name": node.name, "code": node.code}
        updated = await self._address.update_node(node_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="TRANSPORT_NODE", target_id=node_id,
            target_name=node.name, action="UPDATE",
            submitter_id=operator_id,
            before_data=before, after_data=kwargs,
        )
        await self._address.save()
        return updated

    async def delete_node(self, node_id: int, operator_id: int) -> None:
        node = await self.get_node(node_id)
        await self._address.delete_node(node_id)
        await self._audit_svc.record_operation(
            target_type="TRANSPORT_NODE", target_id=node_id,
            target_name=node.name, action="DELETE", operator_id=operator_id,
            before_data={"name": node.name},
        )
        await self._address.save()

    async def approve_node(self, node_id: int, auditor_id: int, remark: str = "") -> TransportNode:
        node = await self.get_node(node_id)
        updated = await self._address.update_node(node_id, audit_status=1)
        await self._audit_svc.record_operation(
            target_type="TRANSPORT_NODE", target_id=node_id,
            target_name=node.name, action="APPROVE", operator_id=auditor_id,
            audit_result="APPROVED", remark=remark or None,
        )
        await self._address.save()
        return updated

    async def reject_node(self, node_id: int, auditor_id: int, remark: str) -> TransportNode:
        node = await self.get_node(node_id)
        updated = await self._address.update_node(node_id, audit_status=2)
        await self._audit_svc.record_operation(
            target_type="TRANSPORT_NODE", target_id=node_id,
            target_name=node.name, action="REJECT", operator_id=auditor_id,
            audit_result="REJECTED", remark=remark,
        )
        await self._address.save()
        return updated

    # ─────────────────────────────────────────────────
    # 节点别名
    # ─────────────────────────────────────────────────

    async def add_alias(self, node_id: int, alias_name: str, operator_id: int) -> NodeAlias:
        node = await self.get_node(node_id)
        alias = NodeAlias(node_id=node_id, alias_name=alias_name)
        saved = await self._address.create_alias(alias)
        await self._audit_svc.record_operation(
            target_type="NODE_ALIAS", target_id=saved.id,
            target_name=alias_name, action="CREATE", operator_id=operator_id,
            after_data={"node_id": node_id, "node_name": node.name, "alias_name": alias_name},
        )
        await self._address.save()
        return saved

    async def delete_alias(self, node_id: int, alias_id: int, operator_id: int) -> None:
        deleted = await self._address.delete_alias(alias_id)
        if not deleted:
            raise NotFoundError("NodeAlias", alias_id)
        await self._audit_svc.record_operation(
            target_type="NODE_ALIAS", target_id=alias_id,
            target_name=str(alias_id), action="DELETE", operator_id=operator_id,
        )
        await self._address.save()

