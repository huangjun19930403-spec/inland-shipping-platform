"""Navigation channel query service."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationChannelSegment,
    NavigationChannelSourceAudit,
)
from app.modules.address.schemas import (
    NavigationChannelBoundaryResponse,
    NavigationChannelDetailResponse,
    NavigationChannelResponse,
    NavigationChannelSegmentResponse,
    NavigationChannelSourceAuditResponse,
    NavigationChannelSummaryResponse,
    PageResponse,
)


CHANNEL_LABELS = {
    "type": {
        "MAIN_LINE": "干线航道",
        "MAIN_RIVER_CHANNEL": "干流航道",
        "TRIBUTARY_CHANNEL": "支流航道",
        "CANAL": "运河航道",
        "DELTA_WATERWAY": "三角洲水道",
        "CHANNEL_NETWORK": "高等级航道网",
        "PLANNED_CHANNEL": "规划航道",
    },
    "planning": {
        "NATIONAL_CORE": "国家核心航道",
        "NATIONAL_IMPORTANT": "国家重要航道",
        "NATIONAL_NETWORK": "国家高等级航道网",
        "PROVINCIAL_HIGH_GRADE": "省级高等级航道",
        "REGIONAL_IMPORTANT": "区域重要航道",
        "PLANNED_GAP": "规划待补航道",
        "REVIEW": "待复核航道",
    },
    "ais": {"INCLUDED": "纳入 AIS 航道归属", "EXCLUDED": "暂不参与 AIS 归属"},
    "geometry": {"AVAILABLE": "有航道边界", "MISSING": "缺少航道边界", "INVALID": "航道边界异常", "UNKNOWN": "未知"},
    "quality": {
        "PRECISE_SOURCE": "精确来源",
        "HIGH_CONFIDENCE": "高可信",
        "MEDIUM_CONFIDENCE": "中可信",
        "CARRIER_COMPOSITE": "承载合并",
        "LOW_CONFIDENCE_CARRIER": "低可信承载",
        "REVIEW": "待复核",
        "MISSING": "缺少航道边界",
        "UNKNOWN": "未知",
    },
    "connectivity": {"CONNECTED": "连续", "REPAIRED": "修复连续", "PARTIAL": "局部连续", "MISSING": "缺失", "UNKNOWN": "未知"},
    "repair": {"NONE": "未修复", "REVIEW_CORRIDOR": "走廊修复待复核", "REVIEW_FALLBACK": "兜底修复待复核", "MISSING": "待补边界"},
    "segment": {
        "MAIN_CORRIDOR": "主航道走廊",
        "NATURAL_WATERWAY": "天然水道段",
        "CANAL_SECTION": "运河段",
        "LAKE_PASSAGE": "湖区通航段",
        "REPAIR_CORRIDOR": "修复走廊",
        "PLANNED_SECTION": "规划段",
    },
}


def _label(group: str, code: str | None, fallback: str = "未知") -> str:
    return CHANNEL_LABELS[group].get(code or "UNKNOWN", code or fallback)


def _paths_by_precision(boundary: NavigationChannelBoundary | None, precision: str) -> list[list[list[float]]]:
    if boundary is None:
        return []
    return {
        "high": boundary.boundary_paths_high,
        "medium": boundary.boundary_paths_medium,
        "low": boundary.boundary_paths_low,
    }.get(precision) or []


def _boundary_status(boundary: NavigationChannelBoundary | SimpleNamespace | None) -> tuple[str, str, str, str]:
    if boundary is None:
        return "MISSING", "MISSING", "MISSING", "MISSING"
    return (
        boundary.geometry_status_code,
        boundary.boundary_quality_code,
        boundary.connectivity_status_code,
        boundary.repair_status_code,
    )


def _to_channel_response(
    row: NavigationChannel,
    boundary: NavigationChannelBoundary | SimpleNamespace | None,
) -> NavigationChannelResponse:
    geometry_status_code, boundary_quality_code, connectivity_status_code, repair_status_code = _boundary_status(boundary)
    return NavigationChannelResponse(
        id=row.id,
        channel_code=row.channel_code,
        channel_name=row.channel_name,
        official_name=row.official_name,
        display_name=row.display_name,
        alias_names=row.alias_names or [],
        parent_channel_code=row.parent_channel_code,
        channel_type_code=row.channel_type_code,
        channel_type_name=_label("type", row.channel_type_code),
        planning_level_code=row.planning_level_code,
        planning_level_name=_label("planning", row.planning_level_code),
        planning_basis_code=row.planning_basis_code,
        start_place=row.start_place,
        end_place=row.end_place,
        via_city_names=row.via_city_names or [],
        via_port_names=row.via_port_names or [],
        technical_grade_current_code=row.technical_grade_current_code,
        technical_grade_planned_code=row.technical_grade_planned_code,
        ais_scope_code=row.ais_scope_code,
        ais_scope_name=_label("ais", row.ais_scope_code),
        display_priority=row.display_priority,
        review_required=row.review_required,
        segment_count=row.segment_count,
        source_summary=row.source_summary,
        source_audit_summary=row.source_audit_summary or {},
        source_version=row.source_version,
        is_enabled=row.is_enabled,
        has_boundary=bool(boundary and geometry_status_code == "AVAILABLE"),
        geometry_status_code=geometry_status_code,
        geometry_status_name=_label("geometry", geometry_status_code),
        boundary_quality_code=boundary_quality_code,
        boundary_quality_name=_label("quality", boundary_quality_code),
        connectivity_status_code=connectivity_status_code,
        connectivity_status_name=_label("connectivity", connectivity_status_code),
        repair_status_code=repair_status_code,
        repair_status_name=_label("repair", repair_status_code, "未修复"),
        imported_at=boundary.imported_at if boundary else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_channel_detail_response(
    row: NavigationChannel,
    boundary: NavigationChannelBoundary | SimpleNamespace | None,
) -> NavigationChannelDetailResponse:
    base = _to_channel_response(row, boundary).model_dump()
    return NavigationChannelDetailResponse(
        **base,
        center_longitude=boundary.center_longitude if boundary else None,
        center_latitude=boundary.center_latitude if boundary else None,
        display_center_longitude=boundary.display_center_longitude if boundary else None,
        display_center_latitude=boundary.display_center_latitude if boundary else None,
        ring_count=boundary.ring_count if boundary else 0,
        point_count=boundary.point_count if boundary else 0,
        bbox_min_lng=boundary.bbox_min_lng if boundary else None,
        bbox_min_lat=boundary.bbox_min_lat if boundary else None,
        bbox_max_lng=boundary.bbox_max_lng if boundary else None,
        bbox_max_lat=boundary.bbox_max_lat if boundary else None,
        coverage_policy_code=boundary.coverage_policy_code if boundary else None,
        geometry_coordinate_system_code=boundary.geometry_coordinate_system_code if boundary else "WGS84",
        boundary_coordinate_system_code=boundary.boundary_coordinate_system_code if boundary else "GCJ02",
    )


def _to_channel_boundary_response(
    row: NavigationChannel,
    boundary: NavigationChannelBoundary | None,
    precision: str,
) -> NavigationChannelBoundaryResponse:
    paths = _paths_by_precision(boundary, precision)
    geometry_status_code, boundary_quality_code, connectivity_status_code, repair_status_code = _boundary_status(boundary)
    return NavigationChannelBoundaryResponse(
        channel_code=row.channel_code,
        channel_name=row.channel_name,
        parent_channel_code=row.parent_channel_code,
        channel_type_code=row.channel_type_code,
        channel_type_name=_label("type", row.channel_type_code),
        planning_level_code=row.planning_level_code,
        planning_level_name=_label("planning", row.planning_level_code),
        precision=precision,
        boundary_paths=paths,
        has_boundary=bool(paths),
        geometry_status_code=geometry_status_code,
        geometry_status_name=_label("geometry", geometry_status_code),
        boundary_quality_code=boundary_quality_code,
        boundary_quality_name=_label("quality", boundary_quality_code),
        connectivity_status_code=connectivity_status_code,
        connectivity_status_name=_label("connectivity", connectivity_status_code),
        repair_status_code=repair_status_code,
        repair_status_name=_label("repair", repair_status_code, "未修复"),
        center_longitude=boundary.center_longitude if boundary else None,
        center_latitude=boundary.center_latitude if boundary else None,
        display_center_longitude=boundary.display_center_longitude if boundary else None,
        display_center_latitude=boundary.display_center_latitude if boundary else None,
        geometry_coordinate_system_code=boundary.geometry_coordinate_system_code if boundary else "WGS84",
        boundary_coordinate_system_code=boundary.boundary_coordinate_system_code if boundary else "GCJ02",
    )


def _to_channel_segment_response(channel: NavigationChannel, row: NavigationChannelSegment) -> NavigationChannelSegmentResponse:
    return NavigationChannelSegmentResponse(
        id=row.id,
        channel_code=channel.channel_code,
        channel_name=channel.channel_name,
        segment_code=row.segment_code,
        segment_name=row.segment_name,
        segment_kind_code=row.segment_kind_code,
        segment_kind_name=_label("segment", row.segment_kind_code),
        sequence_no=row.sequence_no,
        start_place=row.start_place,
        end_place=row.end_place,
        via_city_names=row.via_city_names or [],
        source_water_names=row.source_water_names or [],
        source_summary=row.source_summary,
        geometry_status_code=row.geometry_status_code,
        geometry_status_name=_label("geometry", row.geometry_status_code),
        boundary_quality_code=row.boundary_quality_code,
        boundary_quality_name=_label("quality", row.boundary_quality_code),
        connectivity_status_code=row.connectivity_status_code,
        connectivity_status_name=_label("connectivity", row.connectivity_status_code),
        repair_status_code=row.repair_status_code,
        repair_status_name=_label("repair", row.repair_status_code, "未修复"),
        review_required=row.review_required,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_channel_source_audit_response(row: NavigationChannelSourceAudit) -> NavigationChannelSourceAuditResponse:
    return NavigationChannelSourceAuditResponse(
        id=row.id,
        channel_code=row.channel_code,
        segment_code=row.segment_code,
        source_name=row.source_name,
        source_layer_name=row.source_layer_name,
        source_object_id=row.source_object_id,
        source_level=row.source_level,
        decision_code=row.decision_code,
        role_code=row.role_code,
        reason_code=row.reason_code,
        source_remark=row.source_remark,
        review_required=row.review_required,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class NavigationChannelService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _enabled_channel(self, channel_code: str) -> NavigationChannel:
        row = await self.db.scalar(
            select(NavigationChannel).where(
                NavigationChannel.channel_code == channel_code,
                NavigationChannel.is_enabled.is_(True),
            )
        )
        if row is None:
            raise NotFoundError("NavigationChannel", channel_code)
        return row

    async def _current_boundary(self, channel_id: int) -> NavigationChannelBoundary | None:
        return await self.db.scalar(
            select(NavigationChannelBoundary)
            .where(
                NavigationChannelBoundary.channel_id == channel_id,
                NavigationChannelBoundary.is_current.is_(True),
            )
            .limit(1)
        )

    async def _current_boundary_detail(self, channel_id: int) -> SimpleNamespace | None:
        row = (
            await self.db.execute(
                select(
                    NavigationChannelBoundary.id,
                    NavigationChannelBoundary.geometry_status_code,
                    NavigationChannelBoundary.imported_at,
                    NavigationChannelBoundary.center_longitude,
                    NavigationChannelBoundary.center_latitude,
                    NavigationChannelBoundary.display_center_longitude,
                    NavigationChannelBoundary.display_center_latitude,
                    NavigationChannelBoundary.boundary_quality_code,
                    NavigationChannelBoundary.connectivity_status_code,
                    NavigationChannelBoundary.repair_status_code,
                    NavigationChannelBoundary.coverage_policy_code,
                    NavigationChannelBoundary.geometry_coordinate_system_code,
                    NavigationChannelBoundary.boundary_coordinate_system_code,
                    NavigationChannelBoundary.ring_count,
                    NavigationChannelBoundary.point_count,
                    NavigationChannelBoundary.bbox_min_lng,
                    NavigationChannelBoundary.bbox_min_lat,
                    NavigationChannelBoundary.bbox_max_lng,
                    NavigationChannelBoundary.bbox_max_lat,
                )
                .where(
                    NavigationChannelBoundary.channel_id == channel_id,
                    NavigationChannelBoundary.is_current.is_(True),
                )
                .limit(1)
            )
        ).first()
        return SimpleNamespace(**row._mapping) if row is not None else None

    async def _group_counts(self, field, *, boundary: bool = False) -> dict[str, int]:
        stmt = select(field, func.count()).where(NavigationChannel.is_enabled.is_(True)).group_by(field)
        if boundary:
            stmt = (
                select(field, func.count())
                .select_from(NavigationChannelBoundary)
                .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                .where(NavigationChannel.is_enabled.is_(True), NavigationChannelBoundary.is_current.is_(True))
                .group_by(field)
            )
        return {str(code or "UNKNOWN"): int(count) for code, count in (await self.db.execute(stmt)).all()}

    async def summary(self) -> NavigationChannelSummaryResponse:
        total_count = int((await self.db.execute(select(func.count()).select_from(NavigationChannel))).scalar_one() or 0)
        enabled_count = int(
            (await self.db.execute(select(func.count()).select_from(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)))).scalar_one() or 0
        )
        boundary_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(NavigationChannelBoundary)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                    .where(
                        NavigationChannel.is_enabled.is_(True),
                        NavigationChannelBoundary.is_current.is_(True),
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    )
                )
            ).scalar_one()
            or 0
        )
        version_row = await self.db.scalar(
            select(NavigationChannel.source_version)
            .where(NavigationChannel.is_enabled.is_(True))
            .group_by(NavigationChannel.source_version)
            .order_by(func.count().desc(), NavigationChannel.source_version.desc())
            .limit(1)
        )
        return NavigationChannelSummaryResponse(
            total_count=total_count,
            boundary_count=boundary_count,
            enabled_count=enabled_count,
            channel_type_counts=await self._group_counts(NavigationChannel.channel_type_code),
            planning_level_counts=await self._group_counts(NavigationChannel.planning_level_code),
            ais_scope_counts=await self._group_counts(NavigationChannel.ais_scope_code),
            boundary_quality_counts=await self._group_counts(NavigationChannelBoundary.boundary_quality_code, boundary=True),
            connectivity_status_counts=await self._group_counts(NavigationChannelBoundary.connectivity_status_code, boundary=True),
            repair_status_counts=await self._group_counts(NavigationChannelBoundary.repair_status_code, boundary=True),
            current_source_version=version_row,
        )

    async def list_navigation_channels(
        self,
        *,
        keyword: str | None,
        channel_type_code: str | None,
        planning_level_code: str | None,
        ais_scope_code: str | None,
        geometry_status_code: str | None,
        boundary_quality_code: str | None,
        connectivity_status_code: str | None,
        repair_status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[NavigationChannelResponse]:
        stmt = (
            select(
                NavigationChannel,
                NavigationChannelBoundary.id.label("boundary_id"),
                NavigationChannelBoundary.geometry_status_code,
                NavigationChannelBoundary.imported_at,
                NavigationChannelBoundary.boundary_quality_code,
                NavigationChannelBoundary.connectivity_status_code,
                NavigationChannelBoundary.repair_status_code,
            )
            .outerjoin(
                NavigationChannelBoundary,
                (NavigationChannelBoundary.channel_id == NavigationChannel.id)
                & (NavigationChannelBoundary.is_current.is_(True)),
            )
            .where(NavigationChannel.is_enabled.is_(True))
        )
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    NavigationChannel.channel_code.ilike(like_value),
                    NavigationChannel.channel_name.ilike(like_value),
                    NavigationChannel.official_name.ilike(like_value),
                    NavigationChannel.display_name.ilike(like_value),
                    NavigationChannel.source_summary.ilike(like_value),
                )
            )
        if channel_type_code:
            stmt = stmt.where(NavigationChannel.channel_type_code == channel_type_code)
        if planning_level_code:
            stmt = stmt.where(NavigationChannel.planning_level_code == planning_level_code)
        if ais_scope_code:
            stmt = stmt.where(NavigationChannel.ais_scope_code == ais_scope_code)
        if geometry_status_code:
            stmt = stmt.where(NavigationChannelBoundary.geometry_status_code == geometry_status_code)
        if boundary_quality_code:
            stmt = stmt.where(NavigationChannelBoundary.boundary_quality_code == boundary_quality_code)
        if connectivity_status_code:
            stmt = stmt.where(NavigationChannelBoundary.connectivity_status_code == connectivity_status_code)
        if repair_status_code:
            stmt = stmt.where(NavigationChannelBoundary.repair_status_code == repair_status_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(NavigationChannel.display_priority.asc(), NavigationChannel.sort_order.asc(), NavigationChannel.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items: list[NavigationChannelResponse] = []
        for channel, boundary_id, status_code, imported_at, quality_code, connectivity_code, repair_code in rows:
            boundary = (
                SimpleNamespace(
                    geometry_status_code=status_code,
                    imported_at=imported_at,
                    boundary_quality_code=quality_code,
                    connectivity_status_code=connectivity_code,
                    repair_status_code=repair_code,
                )
                if boundary_id
                else None
            )
            items.append(_to_channel_response(channel, boundary))
        return PageResponse[NavigationChannelResponse](total=total, page=page, page_size=page_size, items=items)

    async def get_navigation_channel_detail(self, channel_code: str) -> NavigationChannelDetailResponse:
        channel = await self._enabled_channel(channel_code)
        boundary = await self._current_boundary_detail(channel.id)
        return _to_channel_detail_response(channel, boundary)

    async def get_navigation_channel_boundary(
        self,
        channel_code: str,
        precision: str,
    ) -> NavigationChannelBoundaryResponse:
        normalized_precision = precision if precision in {"low", "medium", "high"} else "medium"
        channel = await self._enabled_channel(channel_code)
        boundary = await self._current_boundary(channel.id)
        return _to_channel_boundary_response(channel, boundary, normalized_precision)

    async def list_navigation_channel_segments(self, channel_code: str) -> list[NavigationChannelSegmentResponse]:
        channel = await self._enabled_channel(channel_code)
        rows = (
            await self.db.execute(
                select(NavigationChannelSegment)
                .where(NavigationChannelSegment.channel_id == channel.id)
                .order_by(NavigationChannelSegment.sort_order.asc(), NavigationChannelSegment.sequence_no.asc())
            )
        ).scalars().all()
        return [_to_channel_segment_response(channel, row) for row in rows]

    async def list_navigation_channel_source_audit(self, channel_code: str) -> list[NavigationChannelSourceAuditResponse]:
        channel = await self._enabled_channel(channel_code)
        rows = (
            await self.db.execute(
                select(NavigationChannelSourceAudit)
                .where(NavigationChannelSourceAudit.channel_id == channel.id)
                .order_by(NavigationChannelSourceAudit.id.asc())
            )
        ).scalars().all()
        return [_to_channel_source_audit_response(row) for row in rows]
