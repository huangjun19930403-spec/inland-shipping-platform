"""
地址/节点业务服务层
职责：内河运输节点、水系、区域相关业务逻辑
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import json
import logging
from typing import Optional

from app.core.exceptions import NotFoundError, ConflictError
from app.models.address import (
    Waterway, Region, AdminRegion, NodeType, TransportNode, NodeAlias,
)
from app.models.audit import AuditRecord
from app.repositories.address_repository import AddressRepository
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class AddressService:
    """地址/节点业务服务"""

    def __init__(
        self,
        address_repo: AddressRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self._address = address_repo
        self._audit = audit_repo

    # ─────────────────────────────────────────────────
    # 水系
    # ─────────────────────────────────────────────────

    async def list_waterways(self, status: Optional[int] = None):
        return await self._address.list_waterways(status=status)

    async def create_waterway(self, name: str, code: str, operator_id: int, **kwargs) -> Waterway:
        ww = Waterway(name=name, code=code, **kwargs)
        saved = await self._address.create_waterway(ww)
        await self._record_audit(operator_id, "CREATE", "WATERWAY", saved.id,
                                 after_data={"name": name, "code": code})
        await self._address.save()
        return saved

    async def update_waterway(self, waterway_id: int, operator_id: int, **kwargs) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        before = {"name": ww.name}
        updated = await self._address.update_waterway(waterway_id, **kwargs)
        await self._record_audit(operator_id, "UPDATE", "WATERWAY", waterway_id,
                                 before_data=before, after_data=kwargs)
        await self._address.save()
        return updated

    async def delete_waterway(self, waterway_id: int, operator_id: int) -> None:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        await self._address.delete_waterway(waterway_id)
        await self._record_audit(operator_id, "DELETE", "WATERWAY", waterway_id)
        await self._address.save()

    async def enable_waterway(self, waterway_id: int, operator_id: int) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        updated = await self._address.update_waterway(waterway_id, status=1)
        await self._record_audit(operator_id, "ENABLE", "WATERWAY", waterway_id,
                                 before_data={"status": ww.status}, after_data={"status": 1})
        await self._address.save()
        return updated

    async def disable_waterway(self, waterway_id: int, operator_id: int) -> Waterway:
        ww = await self._address.get_waterway(waterway_id)
        if not ww:
            raise NotFoundError("Waterway", waterway_id)
        updated = await self._address.update_waterway(waterway_id, status=0)
        await self._record_audit(operator_id, "DISABLE", "WATERWAY", waterway_id,
                                 before_data={"status": ww.status}, after_data={"status": 0})
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

    async def create_region(self, name: str, code: str, operator_id: int, **kwargs) -> Region:
        region = Region(name=name, code=code, **kwargs)
        saved = await self._address.create_region(region)
        await self._record_audit(operator_id, "CREATE", "REGION", saved.id,
                                 after_data={"name": name, "code": code})
        await self._address.save()
        return saved

    async def update_region(self, region_id: int, operator_id: int, **kwargs) -> Region:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        before = {"name": region.name}
        updated = await self._address.update_region(region_id, **kwargs)
        await self._record_audit(operator_id, "UPDATE", "REGION", region_id,
                                 before_data=before, after_data=kwargs)
        await self._address.save()
        return updated

    async def delete_region(self, region_id: int, operator_id: int) -> None:
        region = await self._address.get_region(region_id)
        if not region:
            raise NotFoundError("Region", region_id)
        await self._address.delete_region(region_id)
        await self._record_audit(operator_id, "DELETE", "REGION", region_id)
        await self._address.save()

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
        await self._record_audit(operator_id, "CREATE", "TRANSPORT_NODE", saved.id,
                                 after_data={"name": name, "code": code})
        await self._address.save()
        return saved

    async def update_node(self, node_id: int, operator_id: int, **kwargs) -> TransportNode:
        node = await self.get_node(node_id)
        before = {"name": node.name, "code": node.code}
        updated = await self._address.update_node(node_id, **kwargs)
        await self._record_audit(operator_id, "UPDATE", "TRANSPORT_NODE", node_id,
                                 before_data=before, after_data=kwargs)
        await self._address.save()
        return updated

    async def delete_node(self, node_id: int, operator_id: int) -> None:
        node = await self.get_node(node_id)
        await self._address.delete_node(node_id)
        await self._record_audit(operator_id, "DELETE", "TRANSPORT_NODE", node_id,
                                 before_data={"name": node.name})
        await self._address.save()

    async def approve_node(self, node_id: int, auditor_id: int, remark: str = "") -> TransportNode:
        await self.get_node(node_id)
        updated = await self._address.update_node(node_id, audit_status=1)
        await self._record_audit(auditor_id, "APPROVE", "TRANSPORT_NODE", node_id,
                                 after_data={"audit_status": 1, "remark": remark})
        await self._address.save()
        return updated

    async def reject_node(self, node_id: int, auditor_id: int, remark: str) -> TransportNode:
        await self.get_node(node_id)
        updated = await self._address.update_node(node_id, audit_status=2)
        await self._record_audit(auditor_id, "REJECT", "TRANSPORT_NODE", node_id,
                                 after_data={"audit_status": 2, "remark": remark})
        await self._address.save()
        return updated

    # ─────────────────────────────────────────────────
    # 节点别名
    # ─────────────────────────────────────────────────

    async def add_alias(self, node_id: int, alias_name: str, operator_id: int) -> NodeAlias:
        await self.get_node(node_id)
        alias = NodeAlias(transport_node_id=node_id, alias_name=alias_name)
        saved = await self._address.create_alias(alias)
        await self._record_audit(operator_id, "CREATE", "NODE_ALIAS", saved.id,
                                 after_data={"node_id": node_id, "alias_name": alias_name})
        await self._address.save()
        return saved

    async def delete_alias(self, node_id: int, alias_id: int, operator_id: int) -> None:
        deleted = await self._address.delete_alias(alias_id)
        if not deleted:
            raise NotFoundError("NodeAlias", alias_id)
        await self._record_audit(operator_id, "DELETE", "NODE_ALIAS", alias_id)
        await self._address.save()

    # ─────────────────────────────────────────────────
    # 内部辅助
    # ─────────────────────────────────────────────────

    async def _record_audit(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        before_data: Optional[dict] = None,
        after_data: Optional[dict] = None,
    ) -> None:
        record = AuditRecord(
            operator_id=operator_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            audit_status="APPROVED",
            before_data=json.dumps(before_data, ensure_ascii=False) if before_data else None,
            after_data=json.dumps(after_data, ensure_ascii=False) if after_data else None,
        )
        await self._audit.create_record(record)
