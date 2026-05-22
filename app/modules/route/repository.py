"""route 模块 repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import FactVesselRouteSegmentDaily
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentResult,
    ShippingRoutePlanTrackVersion,
    ShippingRoutePlanTrackVersionSegment,
)
from app.models.vessel import (
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselNavigationConstraintEvidence,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
)


class ShippingRouteRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_route_by_id(self, route_id: int) -> ShippingRoute | None:
        return await self.db.scalar(
            select(ShippingRoute).where(ShippingRoute.id == route_id, ShippingRoute.deleted_at.is_(None))
        )

    async def list_routes_with_stats(
        self,
        *,
        keyword: str | None,
        origin_endpoint_type_code: str | None,
        origin_region_id: int | None,
        origin_city_code: str | None,
        origin_node_id: int | None,
        destination_endpoint_type_code: str | None,
        destination_region_id: int | None,
        destination_city_code: str | None,
        destination_node_id: int | None,
        transport_org_type_code: str | None,
        plan_type_code: str | None,
        has_plan: bool | None,
        has_default_plan: bool | None,
        track_status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple], int]:
        plan_count_sq = (
            select(func.count(ShippingRoutePlan.id))
            .where(ShippingRoutePlan.route_id == ShippingRoute.id)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        point_count_sq = (
            select(func.count(ShippingRoutePlanPoint.id))
            .select_from(ShippingRoutePlanPoint)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanPoint.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlanPoint.structure_revision == ShippingRoutePlan.structure_revision,
            )
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        segment_count_sq = (
            select(func.count(ShippingRoutePlanSegment.id))
            .select_from(ShippingRoutePlanSegment)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanSegment.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlanSegment.structure_revision == ShippingRoutePlan.structure_revision,
            )
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        selected_result_count_sq = (
            select(func.count(ShippingRoutePlanTrackVersionSegment.id))
            .select_from(ShippingRoutePlanTrackVersionSegment)
            .join(ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersion.id == ShippingRoutePlanTrackVersionSegment.version_id)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
                ShippingRoutePlanTrackVersion.version_status_code == "READY",
            )
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        track_version_count_sq = (
            select(func.count(ShippingRoutePlanTrackVersion.id))
            .select_from(ShippingRoutePlanTrackVersion)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        failed_count_sq = (
            select(func.count(ShippingRoutePlanTrackVersion.id))
            .select_from(ShippingRoutePlanTrackVersion)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
                ShippingRoutePlanTrackVersion.version_status_code == "FAILED",
            )
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        default_plan_id_sq = (
            select(ShippingRoutePlan.id)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        default_plan_name_sq = (
            select(ShippingRoutePlan.plan_name)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        current_track_version_id_sq = (
            select(ShippingRoutePlan.current_track_version_id)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        current_track_version_no_sq = (
            select(ShippingRoutePlanTrackVersion.version_no)
            .select_from(ShippingRoutePlan)
            .join(ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersion.id == ShippingRoutePlan.current_track_version_id)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        current_track_source_sq = (
            select(ShippingRoutePlanTrackVersion.source_type_code)
            .select_from(ShippingRoutePlan)
            .join(ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersion.id == ShippingRoutePlan.current_track_version_id)
            .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        track_status_expr = case(
            (failed_count_sq > 0, "FAILED"),
            (segment_count_sq == 0, "NOT_GENERATED"),
            (selected_result_count_sq == segment_count_sq, "READY"),
            (selected_result_count_sq > 0, "PARTIAL"),
            else_="NOT_GENERATED",
        )
        track_generated_at_sq = (
            select(func.max(ShippingRoutePlanTrackVersion.generated_at))
            .select_from(ShippingRoutePlanTrackVersion)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
            )
            .correlate(ShippingRoute)
            .scalar_subquery()
        )
        track_error_sq = (
            select(ShippingRoutePlanTrackVersion.error_message)
            .select_from(ShippingRoutePlanTrackVersion)
            .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
            .where(
                ShippingRoutePlan.route_id == ShippingRoute.id,
                ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
                ShippingRoutePlanTrackVersion.error_message.is_not(None),
            )
            .order_by(ShippingRoutePlanTrackVersion.generated_at.desc(), ShippingRoutePlanTrackVersion.id.desc())
            .limit(1)
            .correlate(ShippingRoute)
            .scalar_subquery()
        )

        filters = [ShippingRoute.deleted_at.is_(None)]
        if keyword:
            like_value = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    ShippingRoute.code.ilike(like_value),
                    ShippingRoute.name.ilike(like_value),
                    ShippingRoute.description.ilike(like_value),
                )
            )
        if origin_endpoint_type_code:
            filters.append(ShippingRoute.origin_endpoint_type_code == origin_endpoint_type_code)
        if origin_region_id is not None:
            filters.append(ShippingRoute.origin_region_id == origin_region_id)
        if origin_city_code:
            filters.append(ShippingRoute.origin_city_code == origin_city_code)
        if origin_node_id is not None:
            filters.append(ShippingRoute.origin_node_id == origin_node_id)
        if destination_endpoint_type_code:
            filters.append(ShippingRoute.destination_endpoint_type_code == destination_endpoint_type_code)
        if destination_region_id is not None:
            filters.append(ShippingRoute.destination_region_id == destination_region_id)
        if destination_city_code:
            filters.append(ShippingRoute.destination_city_code == destination_city_code)
        if destination_node_id is not None:
            filters.append(ShippingRoute.destination_node_id == destination_node_id)
        if transport_org_type_code:
            filters.append(ShippingRoute.transport_org_type_code == transport_org_type_code)
        if plan_type_code:
            filters.append(
                select(ShippingRoutePlan.id)
                .where(ShippingRoutePlan.route_id == ShippingRoute.id, ShippingRoutePlan.plan_type_code == plan_type_code)
                .exists()
            )
        if has_plan is not None:
            filters.append(plan_count_sq > 0 if has_plan else plan_count_sq == 0)
        if has_default_plan is not None:
            filters.append(default_plan_id_sq.is_not(None) if has_default_plan else default_plan_id_sq.is_(None))
        if track_status:
            filters.append(track_status_expr == track_status)

        count_stmt = select(ShippingRoute.id).where(*filters)
        total = int((await self.db.execute(select(func.count()).select_from(count_stmt.subquery()))).scalar_one())
        stmt = (
            select(
                ShippingRoute,
                plan_count_sq.label("plan_count"),
                point_count_sq.label("point_count"),
                segment_count_sq.label("segment_count"),
                selected_result_count_sq.label("selected_result_count"),
                current_track_version_id_sq.label("current_track_version_id"),
                current_track_version_no_sq.label("current_track_version_no"),
                current_track_source_sq.label("current_track_source_type_code"),
                track_version_count_sq.label("track_version_count"),
                default_plan_id_sq.label("default_plan_id"),
                default_plan_name_sq.label("default_plan_name"),
                track_status_expr.label("track_status"),
                track_error_sq.label("track_error_message"),
                track_generated_at_sq.label("track_generated_at"),
            )
            .where(*filters)
            .order_by(ShippingRoute.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.db.execute(stmt)).all()), total

    async def create_route(self, data: dict[str, Any]) -> ShippingRoute:
        row = ShippingRoute(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_route(self, route_id: int, data: dict[str, Any]) -> ShippingRoute | None:
        row = await self.get_route_by_id(route_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def hard_delete_route(self, route_id: int) -> bool:
        row = await self.db.scalar(select(ShippingRoute).where(ShippingRoute.id == route_id))
        if row is None:
            return False

        plan_ids = list(
            (
                await self.db.scalars(
                    select(ShippingRoutePlan.id).where(ShippingRoutePlan.route_id == route_id)
                )
            ).all()
        )
        segment_ids: list[int] = []
        version_ids: list[int] = []
        if plan_ids:
            segment_ids = list(
                (
                    await self.db.scalars(
                        select(ShippingRoutePlanSegment.id).where(ShippingRoutePlanSegment.plan_id.in_(plan_ids))
                    )
                ).all()
            )
            version_ids = list(
                (
                    await self.db.scalars(
                        select(ShippingRoutePlanTrackVersion.id).where(ShippingRoutePlanTrackVersion.plan_id.in_(plan_ids))
                    )
                ).all()
            )

        analysis_filters = [VesselCandidateAnalysis.route_id == route_id]
        if plan_ids:
            analysis_filters.append(VesselCandidateAnalysis.plan_id.in_(plan_ids))
        analysis_ids = list(
            (
                await self.db.scalars(
                    select(VesselCandidateAnalysis.id).where(or_(*analysis_filters))
                )
            ).all()
        )
        if analysis_ids:
            await self.db.execute(
                delete(VesselCandidateAnalysisAnnotation).where(
                    VesselCandidateAnalysisAnnotation.analysis_id.in_(analysis_ids)
                )
            )
            await self.db.execute(
                delete(VesselCandidateAnalysisItem).where(VesselCandidateAnalysisItem.analysis_id.in_(analysis_ids))
            )
            await self.db.execute(delete(VesselCandidateAnalysis).where(VesselCandidateAnalysis.id.in_(analysis_ids)))

        observation_filters = [VesselRouteSegmentObservationItem.route_id == route_id]
        fact_filters = [FactVesselRouteSegmentDaily.route_id == route_id]
        if plan_ids:
            observation_filters.append(VesselRouteSegmentObservationItem.plan_id.in_(plan_ids))
            fact_filters.append(FactVesselRouteSegmentDaily.plan_id.in_(plan_ids))
        if segment_ids:
            observation_filters.append(VesselRouteSegmentObservationItem.segment_id.in_(segment_ids))
            fact_filters.append(FactVesselRouteSegmentDaily.segment_id.in_(segment_ids))
            await self.db.execute(
                delete(VesselRouteSegmentMatchSample).where(VesselRouteSegmentMatchSample.segment_id.in_(segment_ids))
            )
        await self.db.execute(delete(VesselRouteSegmentObservationItem).where(or_(*observation_filters)))
        await self.db.execute(delete(FactVesselRouteSegmentDaily).where(or_(*fact_filters)))

        evidence_filters = []
        if plan_ids:
            evidence_filters.append(
                and_(
                    VesselNavigationConstraintEvidence.context_type_code == "ROUTE_PLAN",
                    VesselNavigationConstraintEvidence.context_id.in_(plan_ids),
                )
            )
        if segment_ids:
            evidence_filters.append(
                and_(
                    VesselNavigationConstraintEvidence.context_type_code == "ROUTE_SEGMENT",
                    VesselNavigationConstraintEvidence.context_id.in_(segment_ids),
                )
            )
        if evidence_filters:
            await self.db.execute(delete(VesselNavigationConstraintEvidence).where(or_(*evidence_filters)))

        version_segment_filters = []
        if version_ids:
            version_segment_filters.append(ShippingRoutePlanTrackVersionSegment.version_id.in_(version_ids))
        if segment_ids:
            version_segment_filters.append(ShippingRoutePlanTrackVersionSegment.segment_id.in_(segment_ids))
            await self.db.execute(
                delete(ShippingRoutePlanSegmentResult).where(ShippingRoutePlanSegmentResult.segment_id.in_(segment_ids))
            )
        if version_segment_filters:
            await self.db.execute(delete(ShippingRoutePlanTrackVersionSegment).where(or_(*version_segment_filters)))
        if version_ids:
            await self.db.execute(delete(ShippingRoutePlanTrackVersion).where(ShippingRoutePlanTrackVersion.id.in_(version_ids)))
        if segment_ids:
            await self.db.execute(delete(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.id.in_(segment_ids)))
        if plan_ids:
            await self.db.execute(delete(ShippingRoutePlanPoint).where(ShippingRoutePlanPoint.plan_id.in_(plan_ids)))
            await self.db.execute(delete(ShippingRoutePlan).where(ShippingRoutePlan.id.in_(plan_ids)))

        await self.db.delete(row)
        await self.db.flush()
        return True

    async def exists_route_code(self, code: str, exclude_route_id: int | None = None) -> bool:
        stmt = select(ShippingRoute).where(ShippingRoute.code == code, ShippingRoute.deleted_at.is_(None))
        if exclude_route_id is not None:
            stmt = stmt.where(ShippingRoute.id != exclude_route_id)
        return await self.db.scalar(stmt) is not None


class ShippingRoutePlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_plan_by_id(self, plan_id: int) -> ShippingRoutePlan | None:
        return await self.db.scalar(select(ShippingRoutePlan).where(ShippingRoutePlan.id == plan_id))

    async def list_plans(
        self,
        route_id: int,
        plan_type_code: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShippingRoutePlan], int]:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id)
        if plan_type_code:
            stmt = stmt.where(ShippingRoutePlan.plan_type_code == plan_type_code)
        if status_code:
            stmt = stmt.where(ShippingRoutePlan.status_code == status_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_all_plans(self, route_id: int) -> list[ShippingRoutePlan]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlan)
                .where(ShippingRoutePlan.route_id == route_id)
                .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def next_display_order(self, route_id: int) -> int:
        value = await self.db.scalar(
            select(func.max(ShippingRoutePlan.display_order)).where(ShippingRoutePlan.route_id == route_id)
        )
        return int(value or 0) + 1

    async def create_plan(self, route_id: int, data: dict[str, Any]) -> ShippingRoutePlan:
        row = ShippingRoutePlan(route_id=route_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_plan(self, plan_id: int, data: dict[str, Any]) -> ShippingRoutePlan | None:
        row = await self.get_plan_by_id(plan_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_plan(self, plan_id: int) -> bool:
        row = await self.get_plan_by_id(plan_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def clear_default_for_route(self, route_id: int, exclude_plan_id: int | None = None) -> None:
        stmt = update(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id)
        if exclude_plan_id is not None:
            stmt = stmt.where(ShippingRoutePlan.id != exclude_plan_id)
        await self.db.execute(stmt.values(is_default=False))
        await self.db.flush()

    async def exists_plan_code(self, plan_code: str, exclude_plan_id: int | None = None) -> bool:
        stmt = select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == plan_code)
        if exclude_plan_id is not None:
            stmt = stmt.where(ShippingRoutePlan.id != exclude_plan_id)
        return await self.db.scalar(stmt) is not None


class ShippingRoutePlanStructureRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_points(self, plan_id: int, structure_revision: int | None = None) -> list[ShippingRoutePlanPoint]:
        stmt = select(ShippingRoutePlanPoint).where(ShippingRoutePlanPoint.plan_id == plan_id)
        if structure_revision is not None:
            stmt = stmt.where(ShippingRoutePlanPoint.structure_revision == structure_revision)
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoutePlanPoint.point_order.asc(), ShippingRoutePlanPoint.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def list_segments(self, plan_id: int, structure_revision: int | None = None) -> list[ShippingRoutePlanSegment]:
        stmt = select(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.plan_id == plan_id)
        if structure_revision is not None:
            stmt = stmt.where(ShippingRoutePlanSegment.structure_revision == structure_revision)
        rows = (
            await self.db.execute(
                stmt.order_by(ShippingRoutePlanSegment.segment_no.asc(), ShippingRoutePlanSegment.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def get_segment_by_id(self, segment_id: int) -> ShippingRoutePlanSegment | None:
        return await self.db.scalar(select(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.id == segment_id))

    async def list_track_versions(self, plan_id: int) -> list[ShippingRoutePlanTrackVersion]:
        rows = (
            await self.db.execute(
                select(ShippingRoutePlanTrackVersion)
                .where(ShippingRoutePlanTrackVersion.plan_id == plan_id)
                .order_by(ShippingRoutePlanTrackVersion.version_no.desc(), ShippingRoutePlanTrackVersion.id.desc())
            )
        ).scalars().all()
        return list(rows)

    async def get_track_version_by_id(self, version_id: int) -> ShippingRoutePlanTrackVersion | None:
        return await self.db.scalar(select(ShippingRoutePlanTrackVersion).where(ShippingRoutePlanTrackVersion.id == version_id))

    async def list_track_version_segments(self, version_ids: list[int]) -> list[ShippingRoutePlanTrackVersionSegment]:
        if not version_ids:
            return []
        rows = (
            await self.db.execute(
                select(ShippingRoutePlanTrackVersionSegment)
                .where(ShippingRoutePlanTrackVersionSegment.version_id.in_(version_ids))
                .order_by(
                    ShippingRoutePlanTrackVersionSegment.version_id.asc(),
                    ShippingRoutePlanTrackVersionSegment.segment_no.asc(),
                    ShippingRoutePlanTrackVersionSegment.id.asc(),
                )
            )
        ).scalars().all()
        return list(rows)

    async def next_track_version_no(self, plan_id: int) -> int:
        value = await self.db.scalar(
            select(func.max(ShippingRoutePlanTrackVersion.version_no)).where(ShippingRoutePlanTrackVersion.plan_id == plan_id)
        )
        return int(value or 0) + 1

    async def create_track_version(
        self,
        plan_id: int,
        data: dict[str, Any],
        segments: list[dict[str, Any]],
    ) -> ShippingRoutePlanTrackVersion:
        row = ShippingRoutePlanTrackVersion(
            plan_id=plan_id,
            version_no=await self.next_track_version_no(plan_id),
            **data,
        )
        self.db.add(row)
        await self.db.flush()
        for item in segments:
            self.db.add(ShippingRoutePlanTrackVersionSegment(version_id=row.id, **item))
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def set_current_track_version(
        self,
        plan: ShippingRoutePlan,
        version: ShippingRoutePlanTrackVersion,
    ) -> None:
        await self.db.execute(
            update(ShippingRoutePlanTrackVersion)
            .where(ShippingRoutePlanTrackVersion.plan_id == plan.id)
            .values(is_current=False)
        )
        version.is_current = True
        plan.current_track_version_id = version.id
        await self.db.flush()

    async def delete_track_version(
        self,
        plan: ShippingRoutePlan,
        version: ShippingRoutePlanTrackVersion,
    ) -> None:
        await self.db.execute(
            update(ShippingRoutePlanTrackVersion)
            .where(ShippingRoutePlanTrackVersion.parent_version_id == version.id)
            .values(parent_version_id=None)
        )
        await self.db.execute(
            delete(ShippingRoutePlanTrackVersionSegment).where(ShippingRoutePlanTrackVersionSegment.version_id == version.id)
        )
        await self.db.execute(delete(ShippingRoutePlanTrackVersion).where(ShippingRoutePlanTrackVersion.id == version.id))
        if plan.current_track_version_id == version.id:
            plan.current_track_version_id = None
        await self.db.flush()

    async def clear_track_versions(self, plan_id: int) -> None:
        version_ids = [row.id for row in await self.list_track_versions(plan_id)]
        if version_ids:
            await self.db.execute(
                delete(ShippingRoutePlanTrackVersionSegment).where(ShippingRoutePlanTrackVersionSegment.version_id.in_(version_ids))
            )
            await self.db.execute(delete(ShippingRoutePlanTrackVersion).where(ShippingRoutePlanTrackVersion.id.in_(version_ids)))
        await self.db.execute(update(ShippingRoutePlan).where(ShippingRoutePlan.id == plan_id).values(current_track_version_id=None))
        await self.db.flush()

    async def clear_current_track_version(self, plan: ShippingRoutePlan) -> None:
        await self.db.execute(
            update(ShippingRoutePlanTrackVersion)
            .where(ShippingRoutePlanTrackVersion.plan_id == plan.id)
            .values(is_current=False)
        )
        plan.current_track_version_id = None
        await self.db.flush()

    async def replace_structure(
        self,
        plan: ShippingRoutePlan,
        points: list[dict[str, Any]],
    ) -> tuple[list[ShippingRoutePlanPoint], list[ShippingRoutePlanSegment]]:
        new_revision = int(plan.structure_revision or 1) + 1
        await self.clear_current_track_version(plan)
        plan.structure_revision = new_revision

        point_entities: list[ShippingRoutePlanPoint] = []
        for item in points:
            row = ShippingRoutePlanPoint(plan_id=plan.id, structure_revision=new_revision, **item)
            self.db.add(row)
            point_entities.append(row)
        await self.db.flush()
        for row in point_entities:
            await self.db.refresh(row)

        segment_entities: list[ShippingRoutePlanSegment] = []
        for idx in range(len(point_entities) - 1):
            start = point_entities[idx]
            end = point_entities[idx + 1]
            row = ShippingRoutePlanSegment(
                plan_id=plan.id,
                structure_revision=new_revision,
                segment_no=idx + 1,
                start_plan_point_id=start.id,
                end_plan_point_id=end.id,
                transport_mode_code=start.transport_mode_after_code or "WATER",
                generation_status_code="NOT_GENERATED",
            )
            self.db.add(row)
            segment_entities.append(row)
        await self.db.flush()
        for row in segment_entities:
            await self.db.refresh(row)
        return await self.list_points(plan.id, new_revision), await self.list_segments(plan.id, new_revision)

    async def delete_plan_structure(self, plan_id: int) -> None:
        await self.clear_track_versions(plan_id)
        segment_ids = [row.id for row in await self.list_segments(plan_id)]
        if segment_ids:
            await self.db.execute(delete(ShippingRoutePlanSegmentResult).where(ShippingRoutePlanSegmentResult.segment_id.in_(segment_ids)))
        await self.db.execute(delete(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.plan_id == plan_id))
        await self.db.execute(delete(ShippingRoutePlanPoint).where(ShippingRoutePlanPoint.plan_id == plan_id))
        await self.db.flush()
