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
    TransportNodeHandlingMode,
    TransportNodePackagingForm,
    TransportNodeProfile,
)
from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
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
            e2e_lines = (
                (await session.execute(select(ShippingRouteLine.id).where(ShippingRouteLine.plan_id.in_(e2e_plans))))
                .scalars()
                .all()
                if e2e_plans
                else []
            )
            if e2e_lines:
                await session.execute(delete(ShippingRouteLineTrack).where(ShippingRouteLineTrack.line_id.in_(e2e_lines)))
                await session.execute(delete(ShippingRouteLineSegment).where(ShippingRouteLineSegment.line_id.in_(e2e_lines)))
                await session.execute(delete(ShippingRouteLineNode).where(ShippingRouteLineNode.line_id.in_(e2e_lines)))
                await session.execute(delete(ShippingRouteLine).where(ShippingRouteLine.id.in_(e2e_lines)))
            if e2e_plans:
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
