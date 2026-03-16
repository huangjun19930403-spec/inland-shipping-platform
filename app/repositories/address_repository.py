"""
地址/节点数据访问层
封装内河航运地理节点相关数据库操作
"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from app.models.address import (
    Waterway, Region, AdminRegion, NodeType,
    TransportNode, NodeAlias, RegionAddressRelation,
)
from app.repositories.base import BaseRepository


class AddressRepository(BaseRepository):
    model_class = TransportNode

    # ─────────────────────────────────────────────────
    # Waterway
    # ─────────────────────────────────────────────────

    async def list_waterways(self, status: Optional[int] = None) -> Sequence[Waterway]:
        q = select(Waterway)
        if status is not None:
            q = q.where(Waterway.status == status)
        result = await self._db.execute(q.order_by(Waterway.sort_order))
        return result.scalars().all()

    async def get_waterway(self, waterway_id: int) -> Optional[Waterway]:
        result = await self._db.execute(
            select(Waterway).where(Waterway.id == waterway_id)
        )
        return result.scalar_one_or_none()

    async def create_waterway(self, waterway: Waterway) -> Waterway:
        return await self.create(waterway)

    async def update_waterway(self, waterway_id: int, **kwargs) -> Optional[Waterway]:
        ww = await self.get_waterway(waterway_id)
        return await self.update(ww, **kwargs) if ww else None

    async def delete_waterway(self, waterway_id: int) -> bool:
        ww = await self.get_waterway(waterway_id)
        if not ww:
            return False
        await self.delete(ww)
        return True

    # ─────────────────────────────────────────────────
    # Region（商业区域）
    # ─────────────────────────────────────────────────

    async def list_regions(self, status: Optional[int] = None) -> Sequence[Region]:
        q = select(Region)
        if status is not None:
            q = q.where(Region.status == status)
        result = await self._db.execute(q.order_by(Region.sort_order))
        return result.scalars().all()

    async def get_region(self, region_id: int) -> Optional[Region]:
        result = await self._db.execute(
            select(Region).where(Region.id == region_id)
        )
        return result.scalar_one_or_none()

    async def create_region(self, region: Region) -> Region:
        return await self.create(region)

    async def update_region(self, region_id: int, **kwargs) -> Optional[Region]:
        region = await self.get_region(region_id)
        return await self.update(region, **kwargs) if region else None

    async def delete_region(self, region_id: int) -> bool:
        region = await self.get_region(region_id)
        if not region:
            return False
        await self.delete(region)
        return True

    async def get_nodes_in_region(self, region_id: int) -> Sequence[TransportNode]:
        result = await self._db.execute(
            select(TransportNode)
            .where(TransportNode.region_id == region_id)
            .options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()

    # ─────────────────────────────────────────────────
    # AdminRegion（行政区划）
    # ─────────────────────────────────────────────────

    async def list_admin_regions(
        self,
        parent_id: Optional[int] = None,
        level: Optional[int] = None,
        parent_code: Optional[str] = None,
    ) -> Sequence[AdminRegion]:
        conditions = []
        if level is not None:
            conditions.append(AdminRegion.level == level)
        if parent_code is not None:
            parent_res = await self._db.execute(
                select(AdminRegion).where(AdminRegion.code == parent_code)
            )
            parent = parent_res.scalar_one_or_none()
            if parent:
                conditions.append(AdminRegion.parent_id == parent.id)
        elif parent_id is not None:
            conditions.append(AdminRegion.parent_id == parent_id)

        q = select(AdminRegion)
        if conditions:
            q = q.where(and_(*conditions))
        result = await self._db.execute(q.order_by(AdminRegion.code))
        return result.scalars().all()

    async def get_admin_region(self, region_id: int) -> Optional[AdminRegion]:
        result = await self._db.execute(
            select(AdminRegion).where(AdminRegion.id == region_id)
        )
        return result.scalar_one_or_none()

    async def create_admin_region(self, region: AdminRegion) -> AdminRegion:
        return await self.create(region)

    async def update_admin_region(self, region_id: int, **kwargs) -> Optional[AdminRegion]:
        region = await self.get_admin_region(region_id)
        return await self.update(region, **kwargs) if region else None

    # ─────────────────────────────────────────────────
    # NodeType
    # ─────────────────────────────────────────────────

    async def list_node_types(self, status: Optional[int] = None) -> Sequence[NodeType]:
        q = select(NodeType)
        if status is not None:
            q = q.where(NodeType.status == status)
        result = await self._db.execute(q.order_by(NodeType.sort_order))
        return result.scalars().all()

    async def get_node_type(self, node_type_id: int) -> Optional[NodeType]:
        result = await self._db.execute(
            select(NodeType).where(NodeType.id == node_type_id)
        )
        return result.scalar_one_or_none()

    async def create_node_type(self, nt: NodeType) -> NodeType:
        return await self.create(nt)

    async def update_node_type(self, node_type_id: int, **kwargs) -> Optional[NodeType]:
        nt = await self.get_node_type(node_type_id)
        return await self.update(nt, **kwargs) if nt else None

    async def delete_node_type(self, node_type_id: int) -> bool:
        nt = await self.get_node_type(node_type_id)
        if not nt:
            return False
        await self.delete(nt)
        return True

    # ─────────────────────────────────────────────────
    # TransportNode
    # ─────────────────────────────────────────────────

    async def get_node(self, node_id: int) -> Optional[TransportNode]:
        result = await self._db.execute(
            select(TransportNode)
            .where(TransportNode.id == node_id)
            .options(selectinload(TransportNode.aliases))
        )
        return result.scalar_one_or_none()

    async def get_node_by_code(self, code: str) -> Optional[TransportNode]:
        result = await self._db.execute(
            select(TransportNode).where(TransportNode.code == code)
        )
        return result.scalar_one_or_none()

    async def list_nodes(
        self,
        waterway_id: Optional[int] = None,
        region_id: Optional[int] = None,
        node_type_id: Optional[int] = None,
        audit_status: Optional[int] = None,
        status: Optional[int] = None,
        keyword: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[Sequence[TransportNode], int]:
        conditions = []
        if waterway_id is not None:
            conditions.append(TransportNode.waterway_id == waterway_id)
        if region_id is not None:
            conditions.append(TransportNode.region_id == region_id)
        if node_type_id is not None:
            conditions.append(TransportNode.node_type_id == node_type_id)
        if audit_status is not None:
            conditions.append(TransportNode.audit_status == audit_status)
        if status is not None:
            conditions.append(TransportNode.status == status)
        if keyword:
            conditions.append(
                or_(
                    TransportNode.name.ilike(f"%{keyword}%"),
                    TransportNode.code.ilike(f"%{keyword}%"),
                )
            )

        base_q = select(TransportNode)
        if conditions:
            base_q = base_q.where(and_(*conditions))

        count_result = await self._db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            base_q.options(selectinload(TransportNode.aliases))
            .order_by(TransportNode.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().unique().all(), total

    async def search_nodes_by_alias(
        self, q: str, offset: int = 0, limit: int = 20
    ) -> Tuple[Sequence[TransportNode], int]:
        alias_sub = (
            select(NodeAlias.transport_node_id)
            .where(NodeAlias.alias_name.ilike(f"%{q}%"))
            .scalar_subquery()
        )
        cond = or_(
            TransportNode.name.ilike(f"%{q}%"),
            TransportNode.id.in_(alias_sub),
        )
        count_result = await self._db.execute(
            select(func.count(TransportNode.id)).where(cond)
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            select(TransportNode)
            .where(cond)
            .options(selectinload(TransportNode.aliases))
            .order_by(TransportNode.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().unique().all(), total

    async def get_all_nodes_with_aliases(self) -> Sequence[TransportNode]:
        result = await self._db.execute(
            select(TransportNode).options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()

    async def create_node(self, node: TransportNode) -> TransportNode:
        return await self.create(node)

    async def update_node(self, node_id: int, **kwargs) -> Optional[TransportNode]:
        node = await self.get_node(node_id)
        return await self.update(node, **kwargs) if node else None

    async def delete_node(self, node_id: int) -> bool:
        node = await self.get_node(node_id)
        if not node:
            return False
        await self.delete(node)
        return True

    # ─────────────────────────────────────────────────
    # NodeAlias
    # ─────────────────────────────────────────────────

    async def get_aliases_by_node(self, node_id: int) -> Sequence[NodeAlias]:
        result = await self._db.execute(
            select(NodeAlias).where(NodeAlias.transport_node_id == node_id)
        )
        return result.scalars().all()

    async def create_alias(self, alias: NodeAlias) -> NodeAlias:
        return await self.create(alias)

    async def delete_alias(self, alias_id: int) -> bool:
        result = await self._db.execute(
            select(NodeAlias).where(NodeAlias.id == alias_id)
        )
        alias = result.scalar_one_or_none()
        if not alias:
            return False
        await self.delete(alias)
        return True
