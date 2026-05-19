"""清理早期 E2E_* 本地测试数据。"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import (
    NavigationConstraintPoint,
    NavigationConstraintProfile,
    NodeAlias,
    Region,
    RegionBoundaryVersion,
    RegionCityRelation,
    TransportNode,
    TransportNodeBusinessCategory,
    TransportNodeContact,
    TransportNodeHandlingMode,
    TransportNodePackagingForm,
    TransportNodePhoto,
    TransportNodeProfile,
)
from app.models.storage import StorageFile
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentResult,
)


async def purge_legacy_e2e_data() -> None:
    async with AsyncSessionLocal() as session:
        e2e_routes = (
            (
                await session.execute(
                    select(ShippingRoute.id).where(
                        (ShippingRoute.code.like("E2E%")) | (ShippingRoute.name.like("%E2E%"))
                    )
                )
            )
            .scalars()
            .all()
        )
        if e2e_routes:
            e2e_plans = (
                (await session.execute(select(ShippingRoutePlan.id).where(ShippingRoutePlan.route_id.in_(e2e_routes))))
                .scalars()
                .all()
            )
            if e2e_plans:
                segment_ids = (
                    (await session.execute(select(ShippingRoutePlanSegment.id).where(ShippingRoutePlanSegment.plan_id.in_(e2e_plans))))
                    .scalars()
                    .all()
                )
                if segment_ids:
                    await session.execute(delete(ShippingRoutePlanSegmentResult).where(ShippingRoutePlanSegmentResult.segment_id.in_(segment_ids)))
                await session.execute(delete(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.plan_id.in_(e2e_plans)))
                await session.execute(delete(ShippingRoutePlanPoint).where(ShippingRoutePlanPoint.plan_id.in_(e2e_plans)))
                await session.execute(delete(ShippingRoutePlan).where(ShippingRoutePlan.id.in_(e2e_plans)))
            await session.execute(delete(ShippingRoute).where(ShippingRoute.id.in_(e2e_routes)))

        e2e_nodes = (
            (
                await session.execute(
                    select(TransportNode.id).where(
                        (TransportNode.code.like("E2E%")) | (TransportNode.name.like("%E2E%"))
                    )
                )
            )
            .scalars()
            .all()
        )
        if e2e_nodes:
            photo_file_ids = (
                (
                    await session.execute(
                        select(TransportNodePhoto.file_id).where(TransportNodePhoto.node_id.in_(e2e_nodes))
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(delete(TransportNodePhoto).where(TransportNodePhoto.node_id.in_(e2e_nodes)))
            if photo_file_ids:
                await session.execute(delete(StorageFile).where(StorageFile.id.in_(photo_file_ids)))
            await session.execute(delete(TransportNodeContact).where(TransportNodeContact.node_id.in_(e2e_nodes)))
            await session.execute(delete(NodeAlias).where(NodeAlias.node_id.in_(e2e_nodes)))
            await session.execute(delete(TransportNodeProfile).where(TransportNodeProfile.node_id.in_(e2e_nodes)))
            await session.execute(delete(TransportNodeBusinessCategory).where(TransportNodeBusinessCategory.node_id.in_(e2e_nodes)))
            await session.execute(delete(TransportNodePackagingForm).where(TransportNodePackagingForm.node_id.in_(e2e_nodes)))
            await session.execute(delete(TransportNodeHandlingMode).where(TransportNodeHandlingMode.node_id.in_(e2e_nodes)))
            await session.execute(delete(TransportNode).where(TransportNode.id.in_(e2e_nodes)))

        e2e_constraints = (
            (
                await session.execute(
                    select(NavigationConstraintPoint.id).where(
                        (NavigationConstraintPoint.code.like("E2E%"))
                        | (NavigationConstraintPoint.name.like("%E2E%"))
                        | (NavigationConstraintPoint.name.like("自动化新增约束点-%"))
                    )
                )
            )
            .scalars()
            .all()
        )
        if e2e_constraints:
            await session.execute(
                delete(NavigationConstraintProfile).where(
                    NavigationConstraintProfile.constraint_point_id.in_(e2e_constraints)
                )
            )
            await session.execute(delete(NavigationConstraintPoint).where(NavigationConstraintPoint.id.in_(e2e_constraints)))

        e2e_regions = (
            (
                await session.execute(
                    select(Region.id).where((Region.code.like("E2E%")) | (Region.name.like("%E2E%")))
                )
            )
            .scalars()
            .all()
        )
        if e2e_regions:
            await session.execute(delete(RegionBoundaryVersion).where(RegionBoundaryVersion.region_id.in_(e2e_regions)))
            await session.execute(delete(RegionCityRelation).where(RegionCityRelation.region_id.in_(e2e_regions)))
            await session.execute(delete(Region).where(Region.id.in_(e2e_regions)))

        await session.commit()

    print("purge_legacy_e2e_data completed")


if __name__ == "__main__":
    asyncio.run(purge_legacy_e2e_data())
