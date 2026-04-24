"""address 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import (
    AdminRegion,
    AdminRegionBoundary,
    NavigationConstraintPoint,
    NodeAlias,
    Region,
    RegionBoundaryVersion,
    RegionCityRelation,
    TransportNode,
    TransportNodeBusinessCategory,
    TransportNodeHandlingMode,
    TransportNodePackagingForm,
    TransportNodeProfile,
)


class AdminRegionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_regions(
        self,
        level: int | None,
        parent_code: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AdminRegion], int]:
        stmt = select(AdminRegion)
        if level is not None:
            stmt = stmt.where(AdminRegion.level == level)
        if parent_code:
            stmt = stmt.where(AdminRegion.parent_code == parent_code)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AdminRegion.code.ilike(like_value),
                    AdminRegion.name.ilike(like_value),
                    AdminRegion.short_name.ilike(like_value),
                )
            )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(AdminRegion.level.asc(), AdminRegion.sort_order.asc(), AdminRegion.code.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_region_by_code(self, admin_code: str) -> AdminRegion | None:
        return await self.db.scalar(select(AdminRegion).where(AdminRegion.code == admin_code))

    async def get_children(self, parent_code: str) -> list[AdminRegion]:
        return list(
            (
                await self.db.execute(
                    select(AdminRegion)
                    .where(AdminRegion.parent_code == parent_code)
                    .order_by(AdminRegion.sort_order.asc(), AdminRegion.code.asc())
                )
            )
            .scalars()
            .all()
        )

    async def list_cities(self) -> list[AdminRegion]:
        return list(
            (
                await self.db.execute(
                    select(AdminRegion)
                    .where(AdminRegion.level == 2, AdminRegion.status == 1)
                    .order_by(AdminRegion.sort_order.asc(), AdminRegion.code.asc())
                )
            )
            .scalars()
            .all()
        )

    async def list_districts_by_city(self, city_code: str) -> list[AdminRegion]:
        return list(
            (
                await self.db.execute(
                    select(AdminRegion)
                    .where(
                        AdminRegion.level == 3,
                        AdminRegion.parent_code == city_code,
                        AdminRegion.status == 1,
                    )
                    .order_by(AdminRegion.sort_order.asc(), AdminRegion.code.asc())
                )
            )
            .scalars()
            .all()
        )


class RegionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_business_regions(
        self,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Region], int]:
        stmt = select(Region)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Region.code.ilike(like_value),
                    Region.name.ilike(like_value),
                    Region.short_name.ilike(like_value),
                )
            )
        if status is not None:
            stmt = stmt.where(Region.status == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(Region.sort_order.asc(), Region.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_business_region(self, region_id: int) -> Region | None:
        return await self.db.scalar(select(Region).where(Region.id == region_id))

    async def get_business_region_by_code(self, code: str) -> Region | None:
        return await self.db.scalar(select(Region).where(Region.code == code))

    async def create_business_region(self, data: dict[str, Any]) -> Region:
        entity = Region(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_business_region(self, region_id: int, data: dict[str, Any]) -> Region | None:
        entity = await self.get_business_region(region_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def list_region_boundaries(self, region_id: int) -> list[RegionBoundaryVersion]:
        return list(
            (
                await self.db.execute(
                    select(RegionBoundaryVersion)
                    .where(RegionBoundaryVersion.region_id == region_id)
                    .order_by(RegionBoundaryVersion.version_no.desc(), RegionBoundaryVersion.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def create_boundary_version(self, region_id: int, data: dict[str, Any]) -> RegionBoundaryVersion:
        entity = RegionBoundaryVersion(region_id=region_id, **data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_boundary_version(self, version_id: int) -> RegionBoundaryVersion | None:
        return await self.db.scalar(select(RegionBoundaryVersion).where(RegionBoundaryVersion.id == version_id))

    async def set_current_boundary_version(self, region_id: int, version_id: int) -> bool:
        target = await self.db.scalar(
            select(RegionBoundaryVersion).where(
                RegionBoundaryVersion.id == version_id,
                RegionBoundaryVersion.region_id == region_id,
            )
        )
        if target is None:
            return False
        boundaries = await self.list_region_boundaries(region_id)
        for item in boundaries:
            item.is_current = item.id == version_id
        region = await self.get_business_region(region_id)
        if region is not None:
            region.current_boundary_version_id = version_id
        await self.db.flush()
        return True

    async def list_region_city_relations(self, region_id: int) -> list[RegionCityRelation]:
        return list(
            (
                await self.db.execute(
                    select(RegionCityRelation)
                    .where(RegionCityRelation.region_id == region_id)
                    .order_by(RegionCityRelation.sort_order.asc(), RegionCityRelation.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def replace_region_cities(self, region_id: int, city_codes: list[str]) -> list[RegionCityRelation]:
        city_rows = []
        if city_codes:
            city_rows = list(
                (
                    await self.db.execute(select(AdminRegion).where(AdminRegion.code.in_(city_codes), AdminRegion.level == 2))
                )
                .scalars()
                .all()
            )
        city_id_by_code = {row.code: row.id for row in city_rows}
        await self.db.execute(delete(RegionCityRelation).where(RegionCityRelation.region_id == region_id))
        now = datetime.utcnow()
        results: list[RegionCityRelation] = []
        for index, code in enumerate(city_codes):
            city_id = city_id_by_code.get(code)
            if city_id is None:
                continue
            relation = RegionCityRelation(
                region_id=region_id,
                city_region_id=city_id,
                relation_type_code="INCLUDED",
                is_primary=index == 0,
                sort_order=index + 1,
                created_at=now,
                updated_at=now,
            )
            self.db.add(relation)
            results.append(relation)
        await self.db.flush()
        return results


class TransportNodeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_nodes(
        self,
        keyword: str | None,
        city_code: str | None,
        status: int | None,
        category_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TransportNode], int]:
        stmt = select(TransportNode)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    TransportNode.code.ilike(like_value),
                    TransportNode.name.ilike(like_value),
                    TransportNode.short_name.ilike(like_value),
                )
            )
        if city_code:
            stmt = stmt.where(TransportNode.city_code == city_code)
        if status is not None:
            stmt = stmt.where(TransportNode.status == status)
        if category_code:
            stmt = stmt.join(
                TransportNodeBusinessCategory,
                TransportNodeBusinessCategory.node_id == TransportNode.id,
            ).where(TransportNodeBusinessCategory.business_category_code == category_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(TransportNode.sort_order.asc(), TransportNode.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_node(self, node_id: int) -> TransportNode | None:
        return await self.db.scalar(select(TransportNode).where(TransportNode.id == node_id))

    async def get_node_by_code(self, code: str) -> TransportNode | None:
        return await self.db.scalar(select(TransportNode).where(TransportNode.code == code))

    async def create_node(self, data: dict[str, Any]) -> TransportNode:
        entity = TransportNode(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_node(self, node_id: int, data: dict[str, Any]) -> TransportNode | None:
        entity = await self.get_node(node_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_node_profile(self, node_id: int) -> TransportNodeProfile | None:
        return await self.db.scalar(select(TransportNodeProfile).where(TransportNodeProfile.node_id == node_id))

    async def upsert_node_profile(self, node_id: int, data: dict[str, Any]) -> TransportNodeProfile:
        profile = await self.get_node_profile(node_id)
        now = datetime.utcnow()
        if profile is None:
            profile = TransportNodeProfile(node_id=node_id, updated_at=now, **data)
            self.db.add(profile)
        else:
            for key, value in data.items():
                setattr(profile, key, value)
            profile.updated_at = now
        await self.db.flush()
        await self.db.refresh(profile)
        return profile

    async def list_node_aliases(self, node_id: int) -> list[NodeAlias]:
        return list(
            (
                await self.db.execute(
                    select(NodeAlias)
                    .where(NodeAlias.node_id == node_id)
                    .order_by(NodeAlias.is_primary.desc(), NodeAlias.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def replace_node_aliases(self, node_id: int, aliases: list[str]) -> list[NodeAlias]:
        await self.db.execute(delete(NodeAlias).where(NodeAlias.node_id == node_id))
        now = datetime.utcnow()
        rows: list[NodeAlias] = []
        for idx, alias in enumerate(aliases):
            value = alias.strip()
            if not value:
                continue
            entity = NodeAlias(
                node_id=node_id,
                alias_name=value,
                alias_type_code="CUSTOM_ALIAS",
                source_type_code="MANUAL",
                is_primary=idx == 0,
                created_at=now,
                updated_at=now,
            )
            self.db.add(entity)
            rows.append(entity)
        await self.db.flush()
        return rows

    async def replace_node_business_categories(self, node_id: int, category_codes: list[str]) -> None:
        await self.db.execute(
            delete(TransportNodeBusinessCategory).where(TransportNodeBusinessCategory.node_id == node_id)
        )
        now = datetime.utcnow()
        for code in category_codes:
            self.db.add(
                TransportNodeBusinessCategory(
                    node_id=node_id,
                    business_category_code=code,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_node_packaging_forms(self, node_id: int, form_codes: list[str]) -> None:
        await self.db.execute(
            delete(TransportNodePackagingForm).where(TransportNodePackagingForm.node_id == node_id)
        )
        now = datetime.utcnow()
        for code in form_codes:
            self.db.add(
                TransportNodePackagingForm(
                    node_id=node_id,
                    packaging_form_code=code,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_node_handling_modes(self, node_id: int, mode_codes: list[str]) -> None:
        await self.db.execute(
            delete(TransportNodeHandlingMode).where(TransportNodeHandlingMode.node_id == node_id)
        )
        now = datetime.utcnow()
        for code in mode_codes:
            self.db.add(
                TransportNodeHandlingMode(
                    node_id=node_id,
                    handling_mode_code=code,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def list_node_business_categories(self, node_id: int) -> list[str]:
        rows = (
            await self.db.execute(
                select(TransportNodeBusinessCategory.business_category_code).where(
                    TransportNodeBusinessCategory.node_id == node_id
                )
            )
        ).all()
        return [row[0] for row in rows]

    async def list_node_packaging_forms(self, node_id: int) -> list[str]:
        rows = (
            await self.db.execute(
                select(TransportNodePackagingForm.packaging_form_code).where(
                    TransportNodePackagingForm.node_id == node_id
                )
            )
        ).all()
        return [row[0] for row in rows]

    async def list_node_handling_modes(self, node_id: int) -> list[str]:
        rows = (
            await self.db.execute(
                select(TransportNodeHandlingMode.handling_mode_code).where(
                    TransportNodeHandlingMode.node_id == node_id
                )
            )
        ).all()
        return [row[0] for row in rows]


class NavigationConstraintPointRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_constraint_points(
        self,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[NavigationConstraintPoint], int]:
        stmt = select(NavigationConstraintPoint)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    NavigationConstraintPoint.code.ilike(like_value),
                    NavigationConstraintPoint.name.ilike(like_value),
                    NavigationConstraintPoint.description.ilike(like_value),
                )
            )
        if status is not None:
            stmt = stmt.where(NavigationConstraintPoint.status == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(NavigationConstraintPoint.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def get_constraint_point(self, point_id: int) -> NavigationConstraintPoint | None:
        return await self.db.scalar(
            select(NavigationConstraintPoint).where(NavigationConstraintPoint.id == point_id)
        )

    async def get_constraint_point_by_code(self, code: str) -> NavigationConstraintPoint | None:
        return await self.db.scalar(
            select(NavigationConstraintPoint).where(NavigationConstraintPoint.code == code)
        )

    async def create_constraint_point(self, data: dict[str, Any]) -> NavigationConstraintPoint:
        entity = NavigationConstraintPoint(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_constraint_point(
        self,
        point_id: int,
        data: dict[str, Any],
    ) -> NavigationConstraintPoint | None:
        entity = await self.get_constraint_point(point_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity
