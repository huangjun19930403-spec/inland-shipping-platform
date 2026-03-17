"""
地址/节点数据访问层
封装内河航运地理节点相关数据库操作
"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import select, and_, or_, func, delete as sql_delete
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
        conditions = [Waterway.deleted_at.is_(None)]
        if status is not None:
            conditions.append(Waterway.status == status)
        result = await self._db.execute(
            select(Waterway).where(and_(*conditions)).order_by(Waterway.sort_order)
        )
        return result.scalars().all()

    async def list_waterways_paged(
        self,
        name: Optional[str] = None,
        code: Optional[str] = None,
        status: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[Sequence[Waterway], int]:
        conditions = [Waterway.deleted_at.is_(None)]
        if name:
            conditions.append(Waterway.name.ilike(f"%{name}%"))
        if code:
            conditions.append(Waterway.code == code)
        if status is not None:
            conditions.append(Waterway.status == status)

        q = select(Waterway).where(and_(*conditions))

        count_result = await self._db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            q.order_by(Waterway.sort_order, Waterway.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def get_waterway(self, waterway_id: int) -> Optional[Waterway]:
        result = await self._db.execute(
            select(Waterway).where(
                Waterway.id == waterway_id,
                Waterway.deleted_at.is_(None),
            )
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

    async def get_max_sibling_waterway_code(
        self, parent_id: Optional[int]
    ) -> Optional[str]:
        """获取同 parent_id 下字典序最大的 code（含已软删记录，避免编码复用）"""
        if parent_id is None:
            condition = Waterway.parent_id.is_(None)
        else:
            condition = Waterway.parent_id == parent_id
        result = await self._db.execute(
            select(Waterway.code)
            .where(condition)
            .order_by(Waterway.code.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────
    # Region（商业区域）
    # ─────────────────────────────────────────────────

    async def list_regions(self, status: Optional[int] = None) -> Sequence[Region]:
        conditions = [Region.deleted_at.is_(None)]
        if status is not None:
            conditions.append(Region.status == status)
        result = await self._db.execute(
            select(Region).where(and_(*conditions)).order_by(Region.sort_order)
        )
        return result.scalars().all()

    async def list_regions_paged(
        self,
        name: Optional[str] = None,
        status: Optional[int] = None,
        audit_status: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[Sequence[Region], int]:
        conditions = [Region.deleted_at.is_(None)]
        if name:
            conditions.append(Region.name.ilike(f"%{name}%"))
        if status is not None:
            conditions.append(Region.status == status)
        if audit_status is not None:
            conditions.append(Region.audit_status == audit_status)

        q = select(Region).where(and_(*conditions))

        count_result = await self._db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            q.order_by(Region.sort_order, Region.id).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_region(self, region_id: int) -> Optional[Region]:
        result = await self._db.execute(
            select(Region).where(
                Region.id == region_id,
                Region.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_max_region_code(self) -> Optional[str]:
        """获取字典序最大的区域编码（含已软删，避免编码复用）"""
        result = await self._db.execute(
            select(Region.code).order_by(Region.code.desc()).limit(1)
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
            .where(
                TransportNode.region_id == region_id,
                TransportNode.deleted_at.is_(None),
            )
            .options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()

    async def get_waterways_by_ids(self, ids: list[int]) -> Sequence[Waterway]:
        if not ids:
            return []
        result = await self._db.execute(
            select(Waterway).where(
                Waterway.id.in_(ids),
                Waterway.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def get_admin_regions_by_ids(self, ids: list[int]) -> Sequence[AdminRegion]:
        if not ids:
            return []
        result = await self._db.execute(
            select(AdminRegion).where(AdminRegion.id.in_(ids))
        )
        return result.scalars().all()

    async def get_city_coords(self) -> Sequence[tuple]:
        result = await self._db.execute(
            select(AdminRegion.id, AdminRegion.longitude, AdminRegion.latitude)
            .where(
                AdminRegion.level == 2,
                AdminRegion.longitude.is_not(None),
                AdminRegion.latitude.is_not(None),
            )
        )
        return result.all()

    async def list_regions_with_boundaries(self) -> Sequence[Region]:
        """查询所有启用且有边界坐标的区域（用于节点-区域归属计算）"""
        result = await self._db.execute(
            select(Region).where(
                Region.deleted_at.is_(None),
                Region.boundary_coordinates.is_not(None),
                Region.status == 1,
            )
        )
        return result.scalars().all()

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
        conditions = [NodeType.deleted_at.is_(None)]
        if status is not None:
            conditions.append(NodeType.status == status)
        result = await self._db.execute(
            select(NodeType).where(and_(*conditions)).order_by(NodeType.sort_order)
        )
        return result.scalars().all()

    async def get_node_type(self, node_type_id: int) -> Optional[NodeType]:
        result = await self._db.execute(
            select(NodeType).where(
                NodeType.id == node_type_id,
                NodeType.deleted_at.is_(None),
            )
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
            .where(
                TransportNode.id == node_id,
                TransportNode.deleted_at.is_(None),
            )
            .options(selectinload(TransportNode.aliases))
        )
        return result.scalar_one_or_none()

    async def get_node_by_code(self, code: str) -> Optional[TransportNode]:
        result = await self._db.execute(
            select(TransportNode).where(
                TransportNode.code == code,
                TransportNode.deleted_at.is_(None),
            )
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
        conditions = [TransportNode.deleted_at.is_(None)]
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

        base_q = select(TransportNode).where(and_(*conditions))

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
            select(NodeAlias.node_id)
            .where(
                NodeAlias.alias_name.ilike(f"%{q}%"),
                NodeAlias.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        cond = and_(
            TransportNode.deleted_at.is_(None),
            or_(
                TransportNode.name.ilike(f"%{q}%"),
                TransportNode.id.in_(alias_sub),
            ),
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
            select(TransportNode)
            .where(TransportNode.deleted_at.is_(None))
            .options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()

    async def list_all_nodes_with_coords(self) -> Sequence[TransportNode]:
        """查询所有未删除、有经纬度的节点（用于一键归属计算）"""
        result = await self._db.execute(
            select(TransportNode).where(
                TransportNode.deleted_at.is_(None),
                TransportNode.longitude.is_not(None),
                TransportNode.latitude.is_not(None),
            )
        )
        return result.scalars().all()

    async def create_node(self, node: TransportNode) -> TransportNode:
        self._db.add(node)
        await self._db.flush()
        result = await self._db.execute(
            select(TransportNode)
            .options(selectinload(TransportNode.aliases))
            .where(TransportNode.id == node.id)
        )
        return result.scalar_one()

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
            select(NodeAlias).where(
                NodeAlias.node_id == node_id,
                NodeAlias.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def create_alias(self, alias: NodeAlias) -> NodeAlias:
        return await self.create(alias)

    async def delete_alias(self, alias_id: int) -> bool:
        result = await self._db.execute(
            select(NodeAlias).where(
                NodeAlias.id == alias_id,
                NodeAlias.deleted_at.is_(None),
            )
        )
        alias = result.scalar_one_or_none()
        if not alias:
            return False
        await self.delete(alias)
        return True

    # ─────────────────────────────────────────────────
    # RegionAddressRelation（节点-区域归属）
    # ─────────────────────────────────────────────────

    async def get_region_relation(
        self, region_id: int, node_id: int
    ) -> Optional[RegionAddressRelation]:
        result = await self._db.execute(
            select(RegionAddressRelation).where(
                RegionAddressRelation.region_id == region_id,
                RegionAddressRelation.transport_node_id == node_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_region_relation(
        self, region_id: int, node_id: int, is_primary: int = 1
    ) -> RegionAddressRelation:
        relation = RegionAddressRelation(
            region_id=region_id,
            transport_node_id=node_id,
            is_primary=is_primary,
        )
        self._db.add(relation)
        await self._db.flush()
        return relation

    async def upsert_region_relation(self, region_id: int, node_id: int) -> None:
        """插入区域-节点关系（若已存在则跳过）"""
        existing = await self.get_region_relation(region_id, node_id)
        if not existing:
            await self.create_region_relation(region_id, node_id)

    async def delete_region_relations_for_node(self, node_id: int) -> None:
        """硬删除节点的所有区域关系（归属重算时使用）"""
        await self._db.execute(
            sql_delete(RegionAddressRelation).where(
                RegionAddressRelation.transport_node_id == node_id
            )
        )
        await self._db.flush()

    async def sync_node_region_relations(
        self, node_id: int, region_ids: list[int]
    ) -> None:
        """同步节点-区域归属：清除旧记录，按新的 region_ids 插入"""
        await self.delete_region_relations_for_node(node_id)
        for rid in region_ids:
            await self.create_region_relation(rid, node_id)

    async def get_node_region_relations(
        self, node_id: int
    ) -> Sequence[RegionAddressRelation]:
        result = await self._db.execute(
            select(RegionAddressRelation).where(
                RegionAddressRelation.transport_node_id == node_id
            )
        )
        return result.scalars().all()
