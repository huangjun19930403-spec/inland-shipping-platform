"""地址/节点数据访问层"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import and_, delete as sql_delete, func, or_, select, text
from sqlalchemy.orm import selectinload

from app.models.address import (
    AdminRegion,
    NodeAlias,
    NodeType,
    Region,
    RegionAddressRelation,
    RegionCityRelation,
    RegionWaterwayRelation,
    TransportNode,
    TransportNodeProfile,
    Waterway,
)
from app.repositories.base import BaseRepository


class AddressRepository(BaseRepository):
    model_class = TransportNode

    def _node_load_options(self):
        return (
            selectinload(TransportNode.aliases),
            selectinload(TransportNode.profile),
            selectinload(TransportNode.region_relations),
        )

    def _region_load_options(self):
        return (
            selectinload(Region.waterway_relations).selectinload(RegionWaterwayRelation.waterway),
            selectinload(Region.city_relations).selectinload(RegionCityRelation.admin_region),
            selectinload(Region.node_relations),
        )

    # ---------- Waterway ----------

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
        total = (
            await self._db.execute(select(func.count()).select_from(q.subquery()))
        ).scalar_one()

        result = await self._db.execute(
            q.order_by(Waterway.sort_order, Waterway.id).offset(offset).limit(limit)
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

    async def next_code_seq(self, scope: str) -> int:
        result = await self._db.execute(
            text(
                """
                INSERT INTO code_sequence (scope, next_val)
                VALUES (:scope, 1)
                ON CONFLICT (scope)
                DO UPDATE SET next_val = code_sequence.next_val + 1
                RETURNING next_val
                """
            ),
            {"scope": scope},
        )
        return result.scalar_one()

    # ---------- Region ----------

    async def list_regions(self, status: Optional[int] = None) -> Sequence[Region]:
        conditions = [Region.deleted_at.is_(None)]
        if status is not None:
            conditions.append(Region.status == status)
        result = await self._db.execute(
            select(Region)
            .where(and_(*conditions))
            .options(*self._region_load_options())
            .order_by(Region.sort_order)
        )
        return result.scalars().unique().all()

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
        total = (
            await self._db.execute(select(func.count()).select_from(q.subquery()))
        ).scalar_one()

        result = await self._db.execute(
            q.options(*self._region_load_options())
            .order_by(Region.sort_order, Region.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().unique().all(), total

    async def get_region(self, region_id: int) -> Optional[Region]:
        result = await self._db.execute(
            select(Region)
            .where(
                Region.id == region_id,
                Region.deleted_at.is_(None),
            )
            .options(*self._region_load_options())
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
            .join(
                RegionAddressRelation,
                RegionAddressRelation.transport_node_id == TransportNode.id,
            )
            .where(
                RegionAddressRelation.region_id == region_id,
                TransportNode.deleted_at.is_(None),
            )
            .options(*self._node_load_options())
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
        result = await self._db.execute(select(AdminRegion).where(AdminRegion.id.in_(ids)))
        return result.scalars().all()

    async def get_city_coords(self) -> Sequence[tuple]:
        result = await self._db.execute(
            select(AdminRegion.id, AdminRegion.longitude, AdminRegion.latitude).where(
                AdminRegion.level == 2,
                AdminRegion.longitude.is_not(None),
                AdminRegion.latitude.is_not(None),
            )
        )
        return result.all()

    async def list_city_centroids(self) -> Sequence[tuple]:
        result = await self._db.execute(
            select(
                AdminRegion.id,
                AdminRegion.code,
                AdminRegion.name,
                AdminRegion.parent_code,
                AdminRegion.longitude,
                AdminRegion.latitude,
            ).where(
                AdminRegion.level == 2,
                AdminRegion.status == 1,
                AdminRegion.longitude.is_not(None),
                AdminRegion.latitude.is_not(None),
            )
        )
        return result.all()

    async def list_regions_with_boundaries(self) -> Sequence[Region]:
        result = await self._db.execute(
            select(Region).where(
                Region.deleted_at.is_(None),
                Region.boundary_coordinates.is_not(None),
                Region.status == 1,
            )
        )
        return result.scalars().all()

    async def replace_region_waterway_relations(
        self, region_id: int, waterway_ids: list[int], source: str = "MANUAL"
    ) -> None:
        await self._db.execute(
            sql_delete(RegionWaterwayRelation).where(
                RegionWaterwayRelation.region_id == region_id
            )
        )
        for wid in sorted(set(waterway_ids)):
            self._db.add(
                RegionWaterwayRelation(
                    region_id=region_id,
                    waterway_id=wid,
                    relation_type="MAIN",
                    source=source,
                )
            )
        await self._db.flush()

    async def replace_region_city_relations(
        self, region_id: int, admin_region_ids: list[int], source: str = "SYSTEM_GEO"
    ) -> None:
        await self._db.execute(
            sql_delete(RegionCityRelation).where(RegionCityRelation.region_id == region_id)
        )
        for aid in sorted(set(admin_region_ids)):
            self._db.add(
                RegionCityRelation(
                    region_id=region_id,
                    admin_region_id=aid,
                    relation_type="MAIN",
                    source=source,
                )
            )
        await self._db.flush()

    # ---------- AdminRegion ----------

    async def list_admin_regions(
        self,
        parent_id: Optional[int] = None,
        level: Optional[int] = None,
        parent_code: Optional[str] = None,
    ) -> Sequence[AdminRegion]:
        conditions = []
        if level is not None:
            conditions.append(AdminRegion.level == level)

        resolved_parent_code = parent_code
        if not resolved_parent_code and parent_id is not None:
            p = await self.get_admin_region(parent_id)
            resolved_parent_code = p.code if p else None

        if resolved_parent_code:
            conditions.append(AdminRegion.parent_code == resolved_parent_code)

        q = select(AdminRegion)
        if conditions:
            q = q.where(and_(*conditions))
        result = await self._db.execute(q.order_by(AdminRegion.code))
        return result.scalars().all()

    async def get_admin_region(self, region_id: int) -> Optional[AdminRegion]:
        result = await self._db.execute(select(AdminRegion).where(AdminRegion.id == region_id))
        return result.scalar_one_or_none()

    async def get_admin_region_by_code(self, code: str) -> Optional[AdminRegion]:
        result = await self._db.execute(
            select(AdminRegion).where(AdminRegion.code == code)
        )
        return result.scalar_one_or_none()

    async def create_admin_region(self, region: AdminRegion) -> AdminRegion:
        return await self.create(region)

    async def update_admin_region(self, region_id: int, **kwargs) -> Optional[AdminRegion]:
        region = await self.get_admin_region(region_id)
        return await self.update(region, **kwargs) if region else None

    # ---------- NodeType ----------

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

    # ---------- TransportNode ----------

    async def get_node(self, node_id: int) -> Optional[TransportNode]:
        result = await self._db.execute(
            select(TransportNode)
            .where(
                TransportNode.id == node_id,
                TransportNode.deleted_at.is_(None),
            )
            .options(*self._node_load_options())
        )
        return result.scalar_one_or_none()

    async def get_node_by_code(self, code: str) -> Optional[TransportNode]:
        result = await self._db.execute(
            select(TransportNode)
            .where(
                TransportNode.code == code,
                TransportNode.deleted_at.is_(None),
            )
            .options(*self._node_load_options())
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
        node_conditions = [TransportNode.deleted_at.is_(None)]
        if waterway_id is not None:
            node_conditions.append(TransportNode.waterway_id == waterway_id)
        if node_type_id is not None:
            node_conditions.append(TransportNode.node_type_id == node_type_id)
        if audit_status is not None:
            node_conditions.append(TransportNode.audit_status == audit_status)
        if status is not None:
            node_conditions.append(TransportNode.status == status)
        if keyword:
            node_conditions.append(
                or_(
                    TransportNode.name.ilike(f"%{keyword}%"),
                    TransportNode.code.ilike(f"%{keyword}%"),
                )
            )

        base_stmt = select(TransportNode)
        count_stmt = select(func.count(func.distinct(TransportNode.id)))

        if region_id is not None:
            base_stmt = base_stmt.join(
                RegionAddressRelation,
                RegionAddressRelation.transport_node_id == TransportNode.id,
            ).where(RegionAddressRelation.region_id == region_id)
            count_stmt = count_stmt.select_from(TransportNode).join(
                RegionAddressRelation,
                RegionAddressRelation.transport_node_id == TransportNode.id,
            ).where(RegionAddressRelation.region_id == region_id)
        else:
            count_stmt = count_stmt.select_from(TransportNode)

        base_stmt = base_stmt.where(and_(*node_conditions))
        count_stmt = count_stmt.where(and_(*node_conditions))

        total = (await self._db.execute(count_stmt)).scalar_one()

        result = await self._db.execute(
            base_stmt
            .options(*self._node_load_options())
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
        total = (
            await self._db.execute(select(func.count(TransportNode.id)).where(cond))
        ).scalar_one()

        result = await self._db.execute(
            select(TransportNode)
            .where(cond)
            .options(*self._node_load_options())
            .order_by(TransportNode.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().unique().all(), total

    async def get_all_nodes_with_aliases(self) -> Sequence[TransportNode]:
        result = await self._db.execute(
            select(TransportNode)
            .where(TransportNode.deleted_at.is_(None))
            .options(*self._node_load_options())
        )
        return result.scalars().unique().all()

    async def list_all_nodes_with_coords(self) -> Sequence[TransportNode]:
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
            .options(*self._node_load_options())
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

    async def upsert_node_profile(self, node_id: int, **kwargs) -> Optional[TransportNodeProfile]:
        node = await self.get_node(node_id)
        if not node:
            return None
        profile = node.profile
        if profile is None:
            profile = TransportNodeProfile(transport_node_id=node_id, **kwargs)
            self._db.add(profile)
        else:
            for k, v in kwargs.items():
                setattr(profile, k, v)
        await self._db.flush()
        return profile

    # ---------- NodeAlias ----------

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

    async def get_primary_region_by_city_code(self, city_code: str) -> Optional[int]:
        result = await self._db.execute(
            select(RegionCityRelation.region_id)
            .join(
                AdminRegion,
                AdminRegion.id == RegionCityRelation.admin_region_id,
            )
            .join(Region, Region.id == RegionCityRelation.region_id)
            .where(
                AdminRegion.code == city_code,
                Region.deleted_at.is_(None),
                Region.status == 1,
            )
            .order_by(
                (RegionCityRelation.relation_type == "MAIN").desc(),
                RegionCityRelation.id.asc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ---------- RegionAddressRelation ----------

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
        self,
        region_id: int,
        node_id: int,
        is_primary: int = 1,
        relation_type: str = "BELONGS",
        source: str = "SYSTEM_GEO",
    ) -> RegionAddressRelation:
        relation = RegionAddressRelation(
            region_id=region_id,
            transport_node_id=node_id,
            is_primary=is_primary,
            relation_type=relation_type,
            source=source,
        )
        self._db.add(relation)
        await self._db.flush()
        return relation

    async def upsert_region_relation(
        self,
        region_id: int,
        node_id: int,
        is_primary: int = 1,
        relation_type: str = "BELONGS",
        source: str = "SYSTEM_GEO",
    ) -> None:
        existing = await self.get_region_relation(region_id, node_id)
        if not existing:
            await self.create_region_relation(
                region_id,
                node_id,
                is_primary=is_primary,
                relation_type=relation_type,
                source=source,
            )
        else:
            existing.is_primary = is_primary
            existing.relation_type = relation_type
            existing.source = source
            await self._db.flush()

    async def delete_region_relations_for_node(self, node_id: int) -> None:
        await self._db.execute(
            sql_delete(RegionAddressRelation).where(
                RegionAddressRelation.transport_node_id == node_id
            )
        )
        await self._db.flush()

    async def sync_node_region_relations(
        self,
        node_id: int,
        region_ids: list[int],
        primary_region_id: Optional[int] = None,
        source: str = "SYSTEM_GEO",
        relation_type: str = "BELONGS",
    ) -> None:
        await self.delete_region_relations_for_node(node_id)
        region_ids = list(dict.fromkeys(region_ids))
        if primary_region_id is None and region_ids:
            primary_region_id = region_ids[0]

        for rid in region_ids:
            await self.create_region_relation(
                rid,
                node_id,
                is_primary=1 if rid == primary_region_id else 0,
                relation_type=relation_type,
                source=source,
            )

    async def get_node_region_relations(
        self, node_id: int
    ) -> Sequence[RegionAddressRelation]:
        result = await self._db.execute(
            select(RegionAddressRelation)
            .where(RegionAddressRelation.transport_node_id == node_id)
            .order_by(RegionAddressRelation.is_primary.desc(), RegionAddressRelation.id)
        )
        return result.scalars().all()

    async def get_node_primary_region_id(self, node_id: int) -> Optional[int]:
        result = await self._db.execute(
            select(RegionAddressRelation.region_id)
            .where(
                RegionAddressRelation.transport_node_id == node_id,
                RegionAddressRelation.is_primary == 1,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
