"""
地址/节点业务服务层
职责：内河运输节点、水系、区域相关业务逻辑
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import json
import logging
from typing import Optional

from app.core.exceptions import NotFoundError, ConflictError
from app.models.address import TransportNode, NodeAlias
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

    async def list_waterways(self):
        return await self._address.list_waterways()

    # ─────────────────────────────────────────────────
    # 行政区域
    # ─────────────────────────────────────────────────

    async def list_admin_regions(
        self, parent_id: Optional[int] = None, level: Optional[int] = None
    ):
        return await self._address.list_admin_regions(parent_id=parent_id, level=level)

    # ─────────────────────────────────────────────────
    # 商业区域
    # ─────────────────────────────────────────────────

    async def list_regions(self, waterway_id: Optional[int] = None):
        return await self._address.list_regions(waterway_id=waterway_id)

    # ─────────────────────────────────────────────────
    # 节点类型
    # ─────────────────────────────────────────────────

    async def list_node_types(self):
        return await self._address.list_node_types()

    # ─────────────────────────────────────────────────
    # 运输节点
    # ─────────────────────────────────────────────────

    async def list_nodes(
        self,
        waterway_id: Optional[int] = None,
        region_id: Optional[int] = None,
        node_type_id: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._address.list_nodes(
            waterway_id=waterway_id,
            region_id=region_id,
            node_type_id=node_type_id,
            keyword=keyword,
            offset=offset,
            limit=page_size,
        )
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
        region_id: Optional[int],
        node_type_id: Optional[int],
        latitude: Optional[float],
        longitude: Optional[float],
        operator_id: int,
        **kwargs,
    ) -> TransportNode:
        # 检查code唯一性
        existing = await self._address.get_node_by_code(code)
        if existing:
            raise ConflictError(f"Node code '{code}' already exists")

        node = TransportNode(
            name=name,
            code=code,
            waterway_id=waterway_id,
            region_id=region_id,
            node_type_id=node_type_id,
            latitude=latitude,
            longitude=longitude,
            **kwargs,
        )
        saved = await self._address.create_node(node)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="TRANSPORT_NODE",
            target_id=saved.id,
            after_data={"name": name, "code": code},
        )
        await self._address.save()
        logger.info(f"[AddressService] node created id={saved.id} code={code}")
        return saved

    async def update_node(
        self, node_id: int, operator_id: int, **kwargs
    ) -> TransportNode:
        node = await self.get_node(node_id)
        before = {"name": node.name, "code": node.code}

        updated = await self._address.update_node(node_id, **kwargs)
        await self._record_audit(
            operator_id=operator_id,
            action="UPDATE",
            target_type="TRANSPORT_NODE",
            target_id=node_id,
            before_data=before,
            after_data=kwargs,
        )
        await self._address.save()
        return updated

    # ─────────────────────────────────────────────────
    # 节点别名
    # ─────────────────────────────────────────────────

    async def add_alias(
        self, node_id: int, alias_name: str, operator_id: int
    ) -> NodeAlias:
        node = await self.get_node(node_id)

        alias = NodeAlias(
            transport_node_id=node_id,
            alias_name=alias_name,
        )
        saved = await self._address.create_alias(alias)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="NODE_ALIAS",
            target_id=saved.id,
            after_data={"node_id": node_id, "alias_name": alias_name},
        )
        await self._address.save()
        return saved

    async def delete_alias(self, alias_id: int, operator_id: int) -> None:
        deleted = await self._address.delete_alias(alias_id)
        if not deleted:
            raise NotFoundError("NodeAlias", alias_id)
        await self._record_audit(
            operator_id=operator_id,
            action="DELETE",
            target_type="NODE_ALIAS",
            target_id=alias_id,
        )
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
