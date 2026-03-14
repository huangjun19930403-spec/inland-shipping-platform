"""
地址/节点数据访问层
封装内河航运地理节点相关数据库操作
"""
from typing import Optional, Sequence

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.address import (
    Waterway,
    Region,
    AdminRegion,
    NodeType,
    TransportNode,
    NodeAlias,
    RegionAddressRelation,
)
from app.repositories.base import BaseRepository


class AddressRepository(BaseRepository):
    model_class = TransportNode

    # ─────────────────────────────────────────────────
    # Waterway
    # ─────────────────────────────────────────────────

    async def list_waterways(self) -> Sequence[Waterway]:
        result = await self._db.execute(select(Waterway))
        return result.scalars().all()

    async def get_waterway(self, waterway_id: int) -> Optional[Waterway]:
        result = await self._db.execute(
            select(Waterway).where(Waterway.id == waterway_id)
        )
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────
    # Region
    # ─────────────────────────────────────────────────

    async def list_regions(
        self, waterway_id: Optional[int] = None
    ) -> Sequence[Region]:
        query = select(Region)
        if waterway_id:
            query = query.where(Region.waterway_id == waterway_id)
        result = await self._db.execute(query)
        return result.scalars().all()

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
        keyword: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[TransportNode], int]:
        filters = []
        if waterway_id:
            filters.append(TransportNode.waterway_id == waterway_id)
        if region_id:
            filters.append(TransportNode.region_id == region_id)
        if node_type_id:
            filters.append(TransportNode.node_type_id == node_type_id)
        if keyword:
            filters.append(TransportNode.name.ilike(f"%{keyword}%"))

        query = select(TransportNode)
        if filters:
            query = query.where(and_(*filters))

        from sqlalchemy import func
        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_all_nodes_with_aliases(self) -> Sequence[TransportNode]:
        """获取全部节点及别名，用于AI模糊匹配"""
        result = await self._db.execute(
            select(TransportNode).options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()

    async def create_node(self, node: TransportNode) -> TransportNode:
        return await self.create(node)

    async def update_node(
        self, node_id: int, **kwargs
    ) -> Optional[TransportNode]:
        node = await self.get_node(node_id)
        if node:
            return await self.update(node, **kwargs)
        return None

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
        if alias:
            await self.delete(alias)
            return True
        return False

    # ─────────────────────────────────────────────────
    # NodeType
    # ─────────────────────────────────────────────────

    async def list_node_types(self) -> Sequence[NodeType]:
        result = await self._db.execute(select(NodeType))
        return result.scalars().all()

    # ─────────────────────────────────────────────────
    # AdminRegion
    # ─────────────────────────────────────────────────

    async def list_admin_regions(
        self, parent_id: Optional[int] = None, level: Optional[int] = None
    ) -> Sequence[AdminRegion]:
        filters = []
        if parent_id is not None:
            filters.append(AdminRegion.parent_id == parent_id)
        if level is not None:
            filters.append(AdminRegion.level == level)

        query = select(AdminRegion)
        if filters:
            query = query.where(and_(*filters))
        result = await self._db.execute(query)
        return result.scalars().all()
