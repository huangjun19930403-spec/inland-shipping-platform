"""Round 7 vessel node and route spatial observation service."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.config_keys import (
    ES_HISTORY_CONFIG_PROFILE,
    ES_HISTORY_INDEX_PREFIX,
    ES_HOST,
    VESSEL_SPATIAL_DIRECTION_TOLERANCE_DEG,
    VESSEL_SPATIAL_HISTORY_MAX_POINTS,
    VESSEL_SPATIAL_MIN_COVERAGE_RATE,
    VESSEL_SPATIAL_NODE_DEFAULT_RADIUS_KM,
    VESSEL_SPATIAL_NODE_STAY_MINUTES,
    VESSEL_SPATIAL_ROUTE_BUFFER_KM,
    VESSEL_SPATIAL_SNAPSHOT_TTL_SECONDS,
)
from app.integrations.es.history_client import HistoryEsClient
from app.models.address import NavigationConstraintPoint, NavigationConstraintProfile, TransportNode
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanTrackVersion,
    ShippingRoutePlanTrackVersionSegment,
)
from app.models.vessel import (
    VesselAisSnapshot,
    VesselCapacityDimension,
    VesselLatestPositionSnapshot,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselProfile,
    VesselProfileSummary,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.vessel.spatial_math import (
    ais_freshness_level,
    avg as avg_value,
    code_distribution,
    confidence_level as resolve_confidence_level,
    coverage_rate as calc_coverage_rate,
    distance_km,
    first_value,
    freshness_distribution as build_freshness_distribution,
    jsonable,
    line_length_km,
    parse_datetime,
    parse_linestring,
    point_line_distance_km,
    query_hash,
    route_direction_consistency,
    source_status_name,
    to_decimal,
    to_float,
    valid_lon_lat,
    within_distance_km,
)
from app.modules.vessel.schemas import (
    PageResponse,
    VesselAisNodeSituationQuery,
    VesselAisNodeSituationResponse,
    VesselAisNodeVesselsQuery,
    VesselAisNodeVesselsResponse,
    VesselAisRouteSegmentVesselsQuery,
    VesselAisRouteSegmentVesselsResponse,
    VesselAisRouteSituationQuery,
    VesselAisRouteSituationResponse,
    VesselAssetDistributionItemResponse,
    VesselNavigationConstraintEvidenceResponse,
    VesselNavigationConstraintQuery,
    VesselNavigationConstraintResponse,
    VesselNodeObservationVesselResponse,
    VesselNodeSituationSummary,
    VesselRouteSegmentMatchSampleResponse,
    VesselRouteSegmentObservationResponse,
    VesselRouteSituationSummary,
    VesselShipTypeDistributionItemResponse,
    VesselSpatialSnapshotMeta,
    VesselSpatialSnapshotResponse,
)


@dataclass(slots=True)
class _LatestPositionRow:
    position: VesselLatestPositionSnapshot
    profile: VesselProfile | None
    summary: VesselProfileSummary | None
    capacity: VesselCapacityDimension | None


@dataclass(slots=True)
class _HistorySearchResult:
    points_by_mmsi: dict[str, list[dict[str, Any]]]
    partial: bool
    error_message: str | None
    failed_batches: list[dict[str, Any]]
    source_status_code: str
    source_indices: list[str]


def _utcnow() -> datetime:
    return datetime.utcnow()


class VesselSpatialAnalysisService:
    """Spatial observation layer for Round 7."""

    def __init__(self, db: AsyncSession, *, history_client: HistoryEsClient | None = None) -> None:
        self.db = db
        self.runtime_config = RuntimeConfigService(db)
        self.history_client = history_client or HistoryEsClient(runtime_config=self.runtime_config)

    async def node_situation(self, query: VesselAisNodeSituationQuery) -> VesselAisNodeSituationResponse:
        now = _utcnow()
        node = await self.db.get(TransportNode, query.node_id)
        if node is None:
            raise NotFoundError("TransportNode", query.node_id)
        radius_km = float(query.radius_km) if query.radius_km is not None else await self._node_default_radius_km()
        query_payload = query.model_dump(mode="json")
        query_payload["radius_km"] = radius_km

        if not valid_lon_lat(node.longitude, node.latitude):
            snapshot = await self._persist_spatial_snapshot(
                observation_type_code="NODE",
                query_payload=query_payload,
                source_snapshot=None,
                status_code="NOT_COMPUTABLE",
                source_status_code="EMPTY",
                generated_at=now,
                stat_time=None,
                window_start=now - timedelta(hours=query.time_window_hours),
                window_end=now,
                not_computable_reasons=["NODE_COORD_MISSING"],
                uncertainty_notes=["节点缺少经纬度，不能用最近城市或最近节点替代"],
            )
            node_item = await self._persist_node_item(snapshot, node, radius_km, ["NODE_COORD_MISSING"])
            constraints = await self._persist_constraint_evidence(snapshot.snapshot_id, "NODE", node.id, [])
            await self.db.commit()
            return VesselAisNodeSituationResponse(
                source_status=snapshot.source_status_code,
                source_status_name=source_status_name(snapshot.source_status_code),
                generated_at=now,
                message="节点缺少经纬度，空间观测不可计算",
                snapshot=self._snapshot_meta(snapshot),
                summary=self._node_summary(node_item),
                vessels=[],
                constraints=constraints,
            )

        source_snapshot = await self._latest_ais_snapshot()
        if source_snapshot is None:
            snapshot = await self._persist_spatial_snapshot(
                observation_type_code="NODE",
                query_payload=query_payload,
                source_snapshot=None,
                status_code="NOT_COMPUTABLE",
                source_status_code="EMPTY",
                generated_at=now,
                stat_time=None,
                window_start=now - timedelta(hours=query.time_window_hours),
                window_end=now,
                not_computable_reasons=["LATEST_AIS_SNAPSHOT_MISSING"],
                uncertainty_notes=["缺少可用 AIS 快照，不能生成节点空间观测"],
            )
            node_item = await self._persist_node_item(snapshot, node, radius_km, ["LATEST_AIS_SNAPSHOT_MISSING"])
            constraints = await self._navigation_constraint_items("NODE", node_id=node.id, radius_km=radius_km, snapshot_id=snapshot.snapshot_id)
            await self.db.commit()
            return VesselAisNodeSituationResponse(
                source_status=snapshot.source_status_code,
                source_status_name=source_status_name(snapshot.source_status_code),
                generated_at=now,
                message="缺少可用 AIS 快照",
                snapshot=self._snapshot_meta(snapshot),
                summary=self._node_summary(node_item),
                vessels=[],
                constraints=constraints,
            )

        latest_rows = await self._latest_position_rows(source_snapshot.snapshot_id, query)
        freshness_distribution = build_freshness_distribution([row.position for row in latest_rows])
        active_rows: list[tuple[_LatestPositionRow, float]] = []
        stale_position_count = 0
        reported_limit = now - timedelta(minutes=query.reported_within_minutes or 1440)
        for row in latest_rows:
            if not valid_lon_lat(row.position.longitude, row.position.latitude):
                continue
            distance = distance_km(node.longitude, node.latitude, row.position.longitude, row.position.latitude)
            if distance is None or distance > radius_km:
                continue
            if row.position.position_time and row.position.position_time < reported_limit:
                stale_position_count += 1
                continue
            active_rows.append((row, distance))

        history = await self._search_history_positions(
            [row.position.mmsi for row, _ in active_rows],
            now - timedelta(hours=query.time_window_hours),
            now,
        )
        stay_minutes = await self._node_stay_minutes()
        vessel_items = await self._persist_node_vessels(
            snapshot_id=None,
            node=node,
            rows=active_rows,
            radius_km=radius_km,
            history=history,
            stay_minutes=stay_minutes,
        )
        stay_count = sum(1 for item in vessel_items if item.match_status_code == "STAY")
        passby_count = sum(1 for item in vessel_items if item.match_status_code in {"PASSBY", "NEARBY"})
        inflow_count = sum(1 for item in vessel_items if item.direction_status_code == "INFLOW")
        outflow_count = sum(1 for item in vessel_items if item.direction_status_code == "OUTFLOW")
        matched_position_count = len(active_rows)
        coverage_rate = calc_coverage_rate(matched_position_count, source_snapshot.queried_mmsi_count or len(latest_rows))
        not_computable: list[str] = []
        uncertainty_notes: list[str] = []
        status_code = "READY"
        source_status_code = "AVAILABLE"
        if history.source_status_code == "UNCONFIGURED":
            status_code = "PARTIAL" if active_rows else "NOT_COMPUTABLE"
            source_status_code = "UNCONFIGURED"
            not_computable.append("HISTORICAL_AIS_UNCONFIGURED")
            uncertainty_notes.append("历史 ES 未配置，停留、流入和流出分项不可计算")
        elif history.partial:
            status_code = "PARTIAL"
            source_status_code = "PARTIAL"
            not_computable.append("HISTORICAL_AIS_PARTIAL")
        if coverage_rate is not None and coverage_rate < await self._min_coverage_rate():
            status_code = "PARTIAL" if matched_position_count else "NOT_COMPUTABLE"
            not_computable.append("LOW_COVERAGE")
            uncertainty_notes.append("AIS 覆盖率低，节点观测置信度降低")
        confidence_level = resolve_confidence_level(coverage_rate, bool(active_rows), history.partial or history.source_status_code == "UNCONFIGURED")
        snapshot = await self._persist_spatial_snapshot(
            observation_type_code="NODE",
            query_payload=query_payload,
            source_snapshot=source_snapshot,
            status_code=status_code,
            source_status_code=source_status_code,
            generated_at=now,
            stat_time=source_snapshot.generated_at,
            window_start=now - timedelta(hours=query.time_window_hours),
            window_end=now,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            freshness_distribution=freshness_distribution,
            source_indices=sorted(set((source_snapshot.source_indices_json or []) + history.source_indices)),
            failed_batches=history.failed_batches,
            unmatched_mmsi_count=source_snapshot.unmatched_mmsi_count,
            invalid_position_count=source_snapshot.invalid_position_count,
            stale_position_count=source_snapshot.stale_position_count if hasattr(source_snapshot, "stale_position_count") else stale_position_count,
            matched_position_count=matched_position_count,
            active_vessel_count=len(vessel_items),
            not_computable_reasons=not_computable,
            uncertainty_notes=uncertainty_notes,
            refresh_error=history.error_message,
        )
        node_item = await self._persist_node_item(
            snapshot,
            node,
            radius_km,
            not_computable,
            active_vessel_count=len(vessel_items),
            stay_vessel_count=stay_count,
            passby_vessel_count=passby_count,
            inflow_count=inflow_count,
            outflow_count=outflow_count,
            unmatched_mmsi_count=source_snapshot.unmatched_mmsi_count,
            invalid_position_count=source_snapshot.invalid_position_count,
            stale_position_count=stale_position_count,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            freshness_distribution=freshness_distribution,
            ship_type_distribution=code_distribution(vessel_items, "ship_type_code", code_key="ship_type_code", name_key="ship_type_name"),
            risk_distribution=code_distribution(vessel_items, "risk_level"),
            latest_position_time=max((item.position_time for item in vessel_items if item.position_time), default=None),
        )
        await self._store_node_vessel_rows(snapshot.snapshot_id, node.id, vessel_items)
        constraints = await self._navigation_constraint_items("NODE", node_id=node.id, radius_km=radius_km, snapshot_id=snapshot.snapshot_id)
        await self.db.commit()
        return VesselAisNodeSituationResponse(
            source_status=snapshot.source_status_code,
            source_status_name=source_status_name(snapshot.source_status_code),
            generated_at=now,
            snapshot=self._snapshot_meta(snapshot),
            summary=self._node_summary(node_item),
            vessels=vessel_items[:50],
            constraints=constraints,
        )

    async def node_vessels(self, query: VesselAisNodeVesselsQuery) -> VesselAisNodeVesselsResponse:
        if not query.query_snapshot_id:
            return VesselAisNodeVesselsResponse(items=[], total=0, page=query.page, page_size=query.page_size, query_snapshot_id=None, refresh_required=True)
        snapshot = await self._spatial_snapshot(query.query_snapshot_id)
        if snapshot is None or snapshot.expires_at <= _utcnow():
            return VesselAisNodeVesselsResponse(items=[], total=0, page=query.page, page_size=query.page_size, query_snapshot_id=query.query_snapshot_id, refresh_required=True, snapshot_hit=False, snapshot_status_code="EXPIRED" if snapshot else None)
        conditions = [
            VesselNodeObservationVessel.snapshot_id == query.query_snapshot_id,
            VesselNodeObservationVessel.node_id == query.node_id,
        ]
        if query.ship_type_code:
            conditions.append(VesselNodeObservationVessel.ship_type_code == query.ship_type_code)
        if query.quality_level:
            conditions.append(VesselNodeObservationVessel.quality_level == query.quality_level)
        if query.risk_level:
            conditions.append(VesselNodeObservationVessel.risk_level == query.risk_level)
        total = await self.db.scalar(select(func.count()).select_from(VesselNodeObservationVessel).where(*conditions)) or 0
        rows = (await self.db.scalars(
            select(VesselNodeObservationVessel)
            .where(*conditions)
            .order_by(VesselNodeObservationVessel.distance_km.asc(), VesselNodeObservationVessel.id.asc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )).all()
        return VesselAisNodeVesselsResponse(
            items=[self._node_vessel_response(row) for row in rows],
            total=total,
            page=query.page,
            page_size=query.page_size,
            query_snapshot_id=query.query_snapshot_id,
            snapshot_hit=True,
            refresh_required=False,
            snapshot_status_code=snapshot.status_code,
            is_partial=snapshot.status_code == "PARTIAL",
            error_message=snapshot.refresh_error,
        )

    async def route_situation(self, query: VesselAisRouteSituationQuery) -> VesselAisRouteSituationResponse:
        now = _utcnow()
        if query.plan_id is None and query.route_id is None:
            raise ValidationError("plan_id 或 route_id 必须至少提供一个")
        plan, route_id, route_reason = await self._resolve_route_plan(query)
        query_payload = query.model_dump(mode="json")
        source_snapshot = await self._latest_ais_snapshot()
        if plan is None:
            snapshot = await self._persist_spatial_snapshot(
                observation_type_code="ROUTE",
                query_payload=query_payload,
                source_snapshot=source_snapshot,
                status_code="NOT_COMPUTABLE",
                source_status_code="EMPTY" if source_snapshot is None else "AVAILABLE",
                generated_at=now,
                stat_time=source_snapshot.generated_at if source_snapshot else None,
                window_start=now - timedelta(hours=query.time_window_hours),
                window_end=now,
                not_computable_reasons=[route_reason or "MAIN_LINE_MISSING"],
                uncertainty_notes=["未找到可分析的主线或指定路线"],
            )
            await self.db.commit()
            return VesselAisRouteSituationResponse(
                source_status=snapshot.source_status_code,
                source_status_name=source_status_name(snapshot.source_status_code),
                generated_at=now,
                message=route_reason,
                snapshot=self._snapshot_meta(snapshot),
                summary=VesselRouteSituationSummary(route_id=query.route_id, plan_id=0, not_computable_reasons=[route_reason or "DEFAULT_PLAN_MISSING"]),
                segments=[],
                samples=[],
                constraints=[],
            )
        if source_snapshot is None:
            snapshot = await self._persist_spatial_snapshot(
                observation_type_code="ROUTE",
                query_payload=query_payload,
                source_snapshot=None,
                status_code="NOT_COMPUTABLE",
                source_status_code="EMPTY",
                generated_at=now,
                stat_time=None,
                window_start=now - timedelta(hours=query.time_window_hours),
                window_end=now,
                not_computable_reasons=["LATEST_AIS_SNAPSHOT_MISSING"],
                uncertainty_notes=["缺少可用 AIS 快照，不能生成航线空间观测"],
            )
            await self.db.commit()
            return VesselAisRouteSituationResponse(
                source_status=snapshot.source_status_code,
                source_status_name=source_status_name(snapshot.source_status_code),
                generated_at=now,
                message="缺少可用 AIS 快照",
                snapshot=self._snapshot_meta(snapshot),
                summary=VesselRouteSituationSummary(route_id=route_id, plan_id=plan.id, plan_name=plan.plan_name, not_computable_reasons=["LATEST_AIS_SNAPSHOT_MISSING"]),
            )

        latest_rows_all = await self._latest_position_rows(source_snapshot.snapshot_id, query)
        reported_limit = now - timedelta(minutes=query.reported_within_minutes or 1440)
        latest_rows: list[_LatestPositionRow] = []
        stale_position_count = 0
        for row in latest_rows_all:
            if not row.position.position_time or row.position.position_time < reported_limit:
                stale_position_count += 1
                continue
            latest_rows.append(row)
        history = await self._search_history_positions(
            [row.position.mmsi for row in latest_rows],
            now - timedelta(hours=query.time_window_hours),
            now,
        )
        segments = (await self.db.scalars(
            select(ShippingRoutePlanSegment)
            .where(ShippingRoutePlanSegment.plan_id == plan.id)
            .order_by(ShippingRoutePlanSegment.segment_no.asc(), ShippingRoutePlanSegment.id.asc())
        )).all()
        current_version = (
            await self.db.scalar(select(ShippingRoutePlanTrackVersion).where(ShippingRoutePlanTrackVersion.id == plan.current_track_version_id))
            if plan.current_track_version_id
            else None
        )
        version_segment_rows = (
            (
                await self.db.scalars(
                    select(ShippingRoutePlanTrackVersionSegment)
                    .where(ShippingRoutePlanTrackVersionSegment.version_id == current_version.id)
                    .order_by(ShippingRoutePlanTrackVersionSegment.segment_no.asc())
                )
            ).all()
            if current_version and current_version.version_status_code == "READY"
            else []
        )
        version_segment_by_segment_id = {row.segment_id: row for row in version_segment_rows}
        buffer_km = await self._route_buffer_km()
        direction_tolerance_deg = await self._direction_tolerance_deg()
        active_vessel_count = len({row.position.mmsi for row in latest_rows})
        observation_rows: list[VesselRouteSegmentObservationItem] = []
        sample_rows: list[VesselRouteSegmentMatchSample] = []
        not_computable: set[str] = set()
        for segment in segments:
            version_segment = version_segment_by_segment_id.get(segment.id)
            geometry = parse_linestring(version_segment.geometry_json if version_segment else None)
            if version_segment is None or len(geometry) < 2:
                not_computable.add("ROUTE_GEOMETRY_MISSING")
                observation_rows.append(self._route_segment_item(
                    route_id,
                    plan.id,
                    segment,
                    geometry_source=current_version.source_type_code if current_version else None,
                    geometry_json=version_segment.geometry_json if version_segment else None,
                    active_vessel_count=active_vessel_count,
                    geometry_status_code="MISSING",
                    not_computable_reasons=["ROUTE_GEOMETRY_MISSING"],
                ))
                continue
            matches = self._match_segment_samples(segment, geometry, latest_rows, history.points_by_mmsi, buffer_km, direction_tolerance_deg)
            reliable_matches = [item for item in matches if item.match_status_code != "LOW_CONFIDENCE"]
            sample_rows.extend(matches)
            observation_rows.append(self._route_segment_item(
                route_id,
                plan.id,
                segment,
                geometry_source=current_version.source_type_code if current_version else None,
                geometry_json=version_segment.geometry_json,
                active_vessel_count=active_vessel_count,
                geometry_status_code="READY",
                matched_vessel_count=len({item.mmsi for item in reliable_matches}),
                point_count=sum(item.point_count for item in reliable_matches),
                gap_count=sum(item.gap_count for item in reliable_matches),
                covered_ratio=avg_value([to_float(item.covered_ratio) for item in reliable_matches]),
                average_match_score=avg_value([to_float(item.match_score) for item in reliable_matches]),
                coverage_rate=calc_coverage_rate(len({item.mmsi for item in reliable_matches}), active_vessel_count),
                confidence_level=resolve_confidence_level(calc_coverage_rate(len({item.mmsi for item in reliable_matches}), active_vessel_count), bool(reliable_matches), history.partial),
            ))
        reliable_sample_rows = [item for item in sample_rows if item.match_status_code != "LOW_CONFIDENCE"]
        matched_vessels = len({item.mmsi for item in reliable_sample_rows})
        coverage_rate = calc_coverage_rate(matched_vessels, active_vessel_count)
        status_code = "READY"
        source_status_code = "AVAILABLE"
        uncertainty_notes: list[str] = []
        if not segments or not_computable:
            status_code = "PARTIAL" if sample_rows else "NOT_COMPUTABLE"
            uncertainty_notes.append("部分航段缺少 READY LineString，不能生成精确航线段结论")
        if history.source_status_code == "UNCONFIGURED":
            status_code = "NOT_COMPUTABLE"
            source_status_code = "UNCONFIGURED"
            not_computable.add("HISTORICAL_AIS_UNCONFIGURED")
            uncertainty_notes.append("历史 ES 未配置，航线段匹配不可计算")
        elif history.partial:
            status_code = "PARTIAL"
            source_status_code = "PARTIAL"
            not_computable.add("HISTORICAL_AIS_PARTIAL")
        if coverage_rate is not None and coverage_rate < await self._min_coverage_rate():
            status_code = "PARTIAL" if sample_rows else "NOT_COMPUTABLE"
            not_computable.add("LOW_COVERAGE")
        if not active_vessel_count:
            status_code = "NOT_COMPUTABLE"
            not_computable.add("TRACK_SAMPLE_INSUFFICIENT")
            if stale_position_count:
                uncertainty_notes.append("最新位置已超过上报时效，仅能作为低可信解释，不能生成高可信航线样本")
            else:
                uncertainty_notes.append("缺少符合筛选条件和上报时效的 AIS 样本，航线段观测不可计算")
        elif sample_rows and not reliable_sample_rows:
            status_code = "PARTIAL"
            not_computable.add("TRACK_SAMPLE_INSUFFICIENT")
            uncertainty_notes.append("航线段样本方向一致性不足，仅保留低可信解释")
        confidence_level = resolve_confidence_level(coverage_rate, bool(sample_rows), history.partial or history.source_status_code == "UNCONFIGURED")
        snapshot = await self._persist_spatial_snapshot(
            observation_type_code="ROUTE",
            query_payload=query_payload,
            source_snapshot=source_snapshot,
            status_code=status_code,
            source_status_code=source_status_code,
            generated_at=now,
            stat_time=source_snapshot.generated_at,
            window_start=now - timedelta(hours=query.time_window_hours),
            window_end=now,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            freshness_distribution=build_freshness_distribution([row.position for row in latest_rows_all]),
            source_indices=sorted(set((source_snapshot.source_indices_json or []) + history.source_indices)),
            failed_batches=history.failed_batches,
            unmatched_mmsi_count=source_snapshot.unmatched_mmsi_count,
            invalid_position_count=source_snapshot.invalid_position_count,
            stale_position_count=stale_position_count,
            matched_position_count=matched_vessels,
            active_vessel_count=active_vessel_count,
            not_computable_reasons=sorted(not_computable),
            uncertainty_notes=uncertainty_notes,
            refresh_error=history.error_message,
        )
        for item in observation_rows:
            item.snapshot_id = snapshot.snapshot_id
            self.db.add(item)
        for item in sample_rows:
            item.snapshot_id = snapshot.snapshot_id
            self.db.add(item)
        await self.db.flush()
        constraints = await self._navigation_constraint_items("ROUTE_PLAN", plan_id=plan.id, snapshot_id=snapshot.snapshot_id)
        await self.db.commit()
        return VesselAisRouteSituationResponse(
            source_status=snapshot.source_status_code,
            source_status_name=source_status_name(snapshot.source_status_code),
            generated_at=now,
            snapshot=self._snapshot_meta(snapshot),
            summary=VesselRouteSituationSummary(
                route_id=route_id,
                plan_id=plan.id,
                plan_name=plan.plan_name,
                segment_count=len(segments),
                matched_segment_count=sum(1 for item in observation_rows if item.matched_vessel_count > 0),
                matched_vessel_count=matched_vessels,
                active_vessel_count=active_vessel_count,
                coverage_rate=to_decimal(coverage_rate),
                confidence_level=confidence_level,
                not_computable_reasons=sorted(not_computable),
            ),
            segments=[self._route_segment_response(item) for item in observation_rows],
            samples=[self._route_sample_response(item) for item in sample_rows[:50]],
            constraints=constraints,
        )

    async def route_segment_vessels(self, query: VesselAisRouteSegmentVesselsQuery) -> VesselAisRouteSegmentVesselsResponse:
        if not query.query_snapshot_id:
            return VesselAisRouteSegmentVesselsResponse(items=[], total=0, page=query.page, page_size=query.page_size, query_snapshot_id=None, refresh_required=True)
        snapshot = await self._spatial_snapshot(query.query_snapshot_id)
        if snapshot is None or snapshot.expires_at <= _utcnow():
            return VesselAisRouteSegmentVesselsResponse(items=[], total=0, page=query.page, page_size=query.page_size, query_snapshot_id=query.query_snapshot_id, refresh_required=True, snapshot_hit=False, snapshot_status_code="EXPIRED" if snapshot else None)
        conditions = [
            VesselRouteSegmentMatchSample.snapshot_id == query.query_snapshot_id,
            VesselRouteSegmentMatchSample.segment_id == query.segment_id,
        ]
        total = await self.db.scalar(select(func.count()).select_from(VesselRouteSegmentMatchSample).where(*conditions)) or 0
        rows = (await self.db.scalars(
            select(VesselRouteSegmentMatchSample)
            .where(*conditions)
            .order_by(VesselRouteSegmentMatchSample.match_score.desc(), VesselRouteSegmentMatchSample.id.asc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )).all()
        return VesselAisRouteSegmentVesselsResponse(
            items=[self._route_sample_response(row) for row in rows],
            total=total,
            page=query.page,
            page_size=query.page_size,
            query_snapshot_id=query.query_snapshot_id,
            snapshot_hit=True,
            refresh_required=False,
            snapshot_status_code=snapshot.status_code,
            is_partial=snapshot.status_code == "PARTIAL",
            error_message=snapshot.refresh_error,
        )

    async def navigation_constraints(self, query: VesselNavigationConstraintQuery) -> VesselNavigationConstraintResponse:
        context_type = query.context_type
        context_id = query.node_id if context_type == "NODE" else query.plan_id if context_type == "ROUTE_PLAN" else query.segment_id
        if context_id is None:
            raise ValidationError("context_type 与对应 id 参数不匹配")
        items = await self._navigation_constraint_items(context_type, node_id=query.node_id, plan_id=query.plan_id, segment_id=query.segment_id)
        source_status = "AVAILABLE" if any(item.status_code != "MISSING_SOURCE" for item in items) else "EMPTY"
        return VesselNavigationConstraintResponse(
            generated_at=_utcnow(),
            context_type_code=context_type,
            context_id=context_id,
            source_status=source_status,
            uncertainty_notes=[] if source_status == "AVAILABLE" else ["缺少通航约束来源，状态保持 UNKNOWN/MISSING_SOURCE"],
            items=items,
        )

    async def spatial_snapshot(self, snapshot_id: str) -> VesselSpatialSnapshotResponse:
        snapshot = await self._spatial_snapshot(snapshot_id)
        if snapshot is None:
            raise NotFoundError("VesselSpatialObservationSnapshot", snapshot_id)
        node_item = await self.db.scalar(select(VesselNodeObservationItem).where(VesselNodeObservationItem.snapshot_id == snapshot_id))
        route_items = (await self.db.scalars(select(VesselRouteSegmentObservationItem).where(VesselRouteSegmentObservationItem.snapshot_id == snapshot_id).order_by(VesselRouteSegmentObservationItem.segment_no.asc()))).all()
        constraints = (await self.db.scalars(select(VesselNavigationConstraintEvidence).where(VesselNavigationConstraintEvidence.snapshot_id == snapshot_id).order_by(VesselNavigationConstraintEvidence.id.asc()))).all()
        route_summary = None
        if route_items:
            first = route_items[0]
            route_summary = VesselRouteSituationSummary(
                route_id=first.route_id,
                plan_id=first.plan_id,
                segment_count=len(route_items),
                matched_segment_count=sum(1 for item in route_items if item.matched_vessel_count > 0),
                matched_vessel_count=snapshot.matched_position_count,
                active_vessel_count=snapshot.active_vessel_count,
                coverage_rate=to_decimal(snapshot.coverage_rate),
                confidence_level=snapshot.confidence_level,
                not_computable_reasons=snapshot.not_computable_reasons_json or [],
            )
        return VesselSpatialSnapshotResponse(
            snapshot=self._snapshot_meta(snapshot, refresh_required=snapshot.expires_at <= _utcnow()),
            node=self._node_summary(node_item) if node_item else None,
            route=route_summary,
            segments=[self._route_segment_response(item) for item in route_items],
            constraints=[self._constraint_response(item) for item in constraints],
        )

    async def _latest_ais_snapshot(self) -> VesselAisSnapshot | None:
        now = _utcnow()
        return await self.db.scalar(
            select(VesselAisSnapshot)
            .where(VesselAisSnapshot.status_code.in_(["READY", "PARTIAL"]), VesselAisSnapshot.expires_at > now)
            .order_by(VesselAisSnapshot.generated_at.desc(), VesselAisSnapshot.id.desc())
            .limit(1)
        )

    async def _spatial_snapshot(self, snapshot_id: str) -> VesselSpatialObservationSnapshot | None:
        return await self.db.scalar(select(VesselSpatialObservationSnapshot).where(VesselSpatialObservationSnapshot.snapshot_id == snapshot_id))

    async def _latest_position_rows(self, snapshot_id: str, query: Any) -> list[_LatestPositionRow]:
        stmt = (
            select(VesselLatestPositionSnapshot, VesselProfile, VesselProfileSummary, VesselCapacityDimension)
            .outerjoin(VesselProfile, VesselProfile.id == VesselLatestPositionSnapshot.vessel_profile_id)
            .outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .where(VesselLatestPositionSnapshot.snapshot_id == snapshot_id, VesselLatestPositionSnapshot.valid_position_flag.is_(True))
        )
        if getattr(query, "ship_type_code", None):
            stmt = stmt.where(or_(VesselProfile.ship_type_code == query.ship_type_code, VesselProfileSummary.ship_type_code == query.ship_type_code))
        if getattr(query, "quality_level", None):
            stmt = stmt.where(VesselProfileSummary.data_quality_level == query.quality_level)
        if getattr(query, "risk_level", None):
            stmt = stmt.where(VesselProfileSummary.risk_level == query.risk_level)
        if getattr(query, "deadweight_min", None) is not None:
            stmt = stmt.where(or_(VesselCapacityDimension.deadweight_ton >= query.deadweight_min, VesselProfileSummary.deadweight_ton >= query.deadweight_min))
        if getattr(query, "deadweight_max", None) is not None:
            stmt = stmt.where(or_(VesselCapacityDimension.deadweight_ton <= query.deadweight_max, VesselProfileSummary.deadweight_ton <= query.deadweight_max))
        if getattr(query, "draft_max", None) is not None:
            stmt = stmt.where(or_(VesselCapacityDimension.design_draft_m <= query.draft_max, VesselCapacityDimension.max_draft_m <= query.draft_max, VesselProfileSummary.design_draft_m <= query.draft_max))
        rows = (await self.db.execute(stmt)).all()
        return [_LatestPositionRow(position=position, profile=profile, summary=summary, capacity=capacity) for position, profile, summary, capacity in rows]

    async def _search_history_positions(self, mmsi_values: list[str], start_at: datetime, end_at: datetime) -> _HistorySearchResult:
        unique_values = [value for value in dict.fromkeys(mmsi_values) if value]
        if not unique_values:
            return _HistorySearchResult({}, False, None, [], "EMPTY", [])
        host = await self.runtime_config.get_value(ES_HOST, settings.ES_HOST or "", profile_code=ES_HISTORY_CONFIG_PROFILE)
        if not (host or "").strip():
            return _HistorySearchResult(
                {},
                False,
                "历史 ES 未配置",
                [{"batch_index": "history", "mmsi_count": len(unique_values), "sample_mmsi": unique_values[:5], "error_code": "HISTORICAL_AIS_UNCONFIGURED", "error_message": "历史 ES 未配置"}],
                "UNCONFIGURED",
                [],
            )
        index_prefix = await self.runtime_config.get_value(ES_HISTORY_INDEX_PREFIX, settings.ES_HISTORY_INDEX_PREFIX or "", profile_code=ES_HISTORY_CONFIG_PROFILE)
        index = f"{index_prefix or settings.ES_HISTORY_INDEX_PREFIX}*"
        max_points = await self.runtime_config.get_int(VESSEL_SPATIAL_HISTORY_MAX_POINTS, settings.VESSEL_SPATIAL_HISTORY_MAX_POINTS, profile_code=ES_HISTORY_CONFIG_PROFILE)
        body = {
            "size": max(1, int(max_points)),
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"mmsi.keyword": unique_values}},
                        {"range": {"position_time": {"gte": start_at.isoformat(), "lte": end_at.isoformat()}}},
                    ]
                }
            },
            "_source": ["mmsi", "MMSI", "lon", "lng", "longitude", "lat", "latitude", "position_time", "time", "@timestamp", "source_index", "speed", "speed_kn", "course", "cog", "heading"],
            "sort": [{"position_time": {"order": "asc"}}, {"@timestamp": {"order": "asc"}}],
        }
        try:
            payload = await self.history_client.search(index, body)
        except Exception as exc:  # noqa: BLE001
            return _HistorySearchResult({}, True, str(exc), [{"batch_index": "history", "mmsi_count": len(unique_values), "sample_mmsi": unique_values[:5], "error_message": str(exc)}], "ERROR", [])
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        points_by_mmsi: dict[str, list[dict[str, Any]]] = defaultdict(list)
        source_indices: set[str] = set()
        for hit in hits:
            source = hit.get("_source") or {}
            mmsi = str(first_value(source, ["mmsi", "MMSI"]) or "").strip()
            lon = to_float(first_value(source, ["longitude", "lon", "lng"]))
            lat = to_float(first_value(source, ["latitude", "lat"]))
            point_time = parse_datetime(first_value(source, ["position_time", "time", "@timestamp"]))
            if not mmsi or lon is None or lat is None or not valid_lon_lat(lon, lat):
                continue
            source_index = hit.get("_index") or source.get("source_index")
            if source_index:
                source_indices.add(str(source_index))
            points_by_mmsi[mmsi].append({
                "mmsi": mmsi,
                "longitude": lon,
                "latitude": lat,
                "position_time": point_time,
                "source_index": source_index,
                "speed_kn": to_float(first_value(source, ["speed_kn", "speed"])),
                "course_deg": to_float(first_value(source, ["course", "cog"])),
                "heading_deg": to_float(first_value(source, ["heading"])),
            })
        return _HistorySearchResult(dict(points_by_mmsi), False, None, [], "AVAILABLE", sorted(source_indices))

    async def _persist_spatial_snapshot(
        self,
        *,
        observation_type_code: str,
        query_payload: dict[str, Any],
        source_snapshot: VesselAisSnapshot | None,
        status_code: str,
        source_status_code: str,
        generated_at: datetime,
        stat_time: datetime | None,
        window_start: datetime | None,
        window_end: datetime | None,
        coverage_rate: float | None = None,
        confidence_level: str = "UNKNOWN",
        freshness_distribution: dict[str, int] | None = None,
        source_indices: list[str] | None = None,
        failed_batches: list[dict[str, Any]] | None = None,
        unmatched_mmsi_count: int = 0,
        invalid_position_count: int = 0,
        stale_position_count: int = 0,
        matched_position_count: int = 0,
        active_vessel_count: int = 0,
        not_computable_reasons: list[str] | None = None,
        quality_warnings: list[str] | None = None,
        uncertainty_notes: list[str] | None = None,
        refresh_error: str | None = None,
    ) -> VesselSpatialObservationSnapshot:
        snapshot_id = f"vsp-{uuid.uuid4().hex}"
        expires_at = generated_at + timedelta(seconds=await self._snapshot_ttl_seconds())
        snapshot = VesselSpatialObservationSnapshot(
            snapshot_id=snapshot_id,
            source_snapshot_id=source_snapshot.snapshot_id if source_snapshot else None,
            observation_type_code=observation_type_code,
            query_hash=query_hash(query_payload),
            query_params_json=jsonable(query_payload),
            status_code=status_code,
            source_status_code=source_status_code,
            stat_time=stat_time,
            window_start=window_start,
            window_end=window_end,
            generated_at=generated_at,
            expires_at=expires_at,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            freshness_distribution_json=freshness_distribution or {},
            source_indices_json=source_indices or [],
            failed_batch_count=len(failed_batches or []),
            failed_batches_json=failed_batches or [],
            unmatched_mmsi_count=unmatched_mmsi_count,
            invalid_position_count=invalid_position_count,
            stale_position_count=stale_position_count,
            matched_position_count=matched_position_count,
            active_vessel_count=active_vessel_count,
            not_computable_reasons_json=not_computable_reasons or [],
            quality_warnings_json=quality_warnings or [],
            uncertainty_notes_json=uncertainty_notes or [],
            refresh_error=refresh_error,
            created_at=generated_at,
            updated_at=generated_at,
        )
        self.db.add(snapshot)
        await self.db.flush()
        return snapshot

    async def _persist_node_item(
        self,
        snapshot: VesselSpatialObservationSnapshot,
        node: TransportNode,
        radius_km: float,
        not_computable_reasons: list[str],
        *,
        active_vessel_count: int = 0,
        stay_vessel_count: int = 0,
        passby_vessel_count: int = 0,
        inflow_count: int = 0,
        outflow_count: int = 0,
        unmatched_mmsi_count: int = 0,
        invalid_position_count: int = 0,
        stale_position_count: int = 0,
        coverage_rate: float | None = None,
        confidence_level: str = "UNKNOWN",
        freshness_distribution: dict[str, int] | None = None,
        ship_type_distribution: list[dict[str, Any]] | None = None,
        risk_distribution: list[dict[str, Any]] | None = None,
        latest_position_time: datetime | None = None,
    ) -> VesselNodeObservationItem:
        item = VesselNodeObservationItem(
            snapshot_id=snapshot.snapshot_id,
            node_id=node.id,
            node_name=node.name,
            node_type_code=node.node_type_code,
            city_code=node.city_code,
            radius_km=radius_km,
            longitude=node.longitude,
            latitude=node.latitude,
            active_vessel_count=active_vessel_count,
            stay_vessel_count=stay_vessel_count,
            passby_vessel_count=passby_vessel_count,
            inflow_count=inflow_count,
            outflow_count=outflow_count,
            unmatched_mmsi_count=unmatched_mmsi_count,
            invalid_position_count=invalid_position_count,
            stale_position_count=stale_position_count,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            freshness_distribution_json=freshness_distribution or {},
            ship_type_distribution_json=ship_type_distribution or [],
            risk_distribution_json=risk_distribution or [],
            latest_position_time=latest_position_time,
            not_computable_reasons_json=not_computable_reasons,
            created_at=snapshot.generated_at,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def _persist_node_vessels(
        self,
        *,
        snapshot_id: str | None,
        node: TransportNode,
        rows: list[tuple[_LatestPositionRow, float]],
        radius_km: float,
        history: _HistorySearchResult,
        stay_minutes: int,
    ) -> list[VesselNodeObservationVesselResponse]:
        result: list[VesselNodeObservationVesselResponse] = []
        for row, distance in rows:
            history_points = history.points_by_mmsi.get(row.position.mmsi) or []
            inside_times = [
                point["position_time"]
                for point in history_points
                if point.get("position_time") and within_distance_km(node.longitude, node.latitude, point.get("longitude"), point.get("latitude"), radius_km)
            ]
            stay_duration = None
            if inside_times:
                stay_duration = int((max(inside_times) - min(inside_times)).total_seconds() // 60)
            match_status = "STAY" if stay_duration is not None and stay_duration >= stay_minutes else "PASSBY" if history_points else "NEARBY"
            direction = self._node_direction_status(node, radius_km, history_points, stay_duration, stay_minutes)
            result.append(VesselNodeObservationVesselResponse(
                vessel_profile_id=row.profile.id if row.profile else row.position.vessel_profile_id,
                mmsi=row.position.mmsi,
                ship_name=(row.summary.ship_name if row.summary else None) or (row.profile.ship_name if row.profile else None),
                ship_type_code=(row.summary.ship_type_code if row.summary else None) or (row.profile.ship_type_code if row.profile else None),
                deadweight_ton=to_decimal((row.summary.deadweight_ton if row.summary else None) or (row.capacity.deadweight_ton if row.capacity else None)),
                longitude=to_decimal(row.position.longitude),
                latitude=to_decimal(row.position.latitude),
                distance_km=to_decimal(round(distance, 3)),
                position_time=row.position.position_time,
                source_index=row.position.source_index,
                freshness_level=row.position.freshness_level,
                match_status_code=match_status,
                stay_duration_minutes=stay_duration,
                direction_status_code=direction,
                risk_level=row.summary.risk_level if row.summary else None,
                quality_level=row.summary.data_quality_level if row.summary else None,
            ))
        return result

    async def _store_node_vessel_rows(self, snapshot_id: str, node_id: int, items: list[VesselNodeObservationVesselResponse]) -> None:
        await self.db.execute(delete(VesselNodeObservationVessel).where(VesselNodeObservationVessel.snapshot_id == snapshot_id))
        for item in items:
            self.db.add(VesselNodeObservationVessel(
                snapshot_id=snapshot_id,
                node_id=node_id,
                vessel_profile_id=item.vessel_profile_id,
                mmsi=item.mmsi,
                ship_name=item.ship_name,
                ship_type_code=item.ship_type_code,
                deadweight_ton=item.deadweight_ton,
                longitude=item.longitude,
                latitude=item.latitude,
                distance_km=item.distance_km,
                position_time=item.position_time,
                source_index=item.source_index,
                freshness_level=item.freshness_level,
                match_status_code=item.match_status_code,
                stay_duration_minutes=item.stay_duration_minutes,
                direction_status_code=item.direction_status_code,
                risk_level=item.risk_level,
                quality_level=item.quality_level,
                created_at=_utcnow(),
            ))
        await self.db.flush()

    def _node_direction_status(
        self,
        node: TransportNode,
        radius_km: float,
        history_points: list[dict[str, Any]],
        stay_duration_minutes: int | None,
        min_stay_minutes: int,
    ) -> str:
        ordered = [point for point in history_points if point.get("position_time")]
        if len(ordered) < 2:
            return "UNKNOWN"
        ordered.sort(key=lambda item: item["position_time"])
        if stay_duration_minutes is None or stay_duration_minutes < min_stay_minutes:
            return "PASSBY"
        first_inside = within_distance_km(node.longitude, node.latitude, ordered[0].get("longitude"), ordered[0].get("latitude"), radius_km)
        last_inside = within_distance_km(node.longitude, node.latitude, ordered[-1].get("longitude"), ordered[-1].get("latitude"), radius_km)
        if not first_inside and last_inside:
            return "INFLOW"
        if first_inside and not last_inside:
            return "OUTFLOW"
        if first_inside and last_inside:
            return "STAYING"
        return "PASSBY"

    async def _resolve_route_plan(self, query: VesselAisRouteSituationQuery) -> tuple[ShippingRoutePlan | None, int | None, str | None]:
        if query.plan_id is not None:
            plan = await self.db.get(ShippingRoutePlan, query.plan_id)
            if plan is None:
                return None, query.route_id, "ROUTE_PLAN_NOT_FOUND"
            return plan, plan.route_id, None
        route = await self.db.get(ShippingRoute, query.route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", query.route_id)
        plan = await self.db.scalar(
            select(ShippingRoutePlan)
            .where(ShippingRoutePlan.route_id == query.route_id, ShippingRoutePlan.is_default.is_(True))
            .order_by(ShippingRoutePlan.display_order.asc(), ShippingRoutePlan.id.asc())
            .limit(1)
        )
        return plan, query.route_id, None if plan else "DEFAULT_PLAN_MISSING"

    def _match_segment_samples(
        self,
        segment: ShippingRoutePlanSegment,
        geometry: list[tuple[float, float]],
        latest_rows: list[_LatestPositionRow],
        history_points: dict[str, list[dict[str, Any]]],
        buffer_km: float,
        direction_tolerance_deg: float,
    ) -> list[VesselRouteSegmentMatchSample]:
        rows_by_mmsi = {row.position.mmsi: row for row in latest_rows}
        result: list[VesselRouteSegmentMatchSample] = []
        line_length = max(line_length_km(geometry), 0.1)
        for mmsi, points in history_points.items():
            matched_points: list[dict[str, Any]] = []
            for point in points:
                distance = point_line_distance_km((float(point["longitude"]), float(point["latitude"])), geometry)
                if distance is not None and distance <= buffer_km:
                    matched_points.append(point)
            if not matched_points:
                continue
            matched_points.sort(key=lambda item: item.get("position_time") or datetime.min)
            gap_count = sum(
                1
                for index in range(len(matched_points) - 1)
                if matched_points[index].get("position_time")
                and matched_points[index + 1].get("position_time")
                and (matched_points[index + 1]["position_time"] - matched_points[index]["position_time"]).total_seconds() > 6 * 3600
            )
            row = rows_by_mmsi.get(mmsi)
            covered_ratio = min(100.0, len(matched_points) * max(buffer_km, 0.1) / line_length * 100)
            direction_consistency = route_direction_consistency(geometry, matched_points)
            if direction_consistency is None:
                direction_consistency = 0.0
            direction_deviation = (100.0 - direction_consistency) / 100.0 * 180.0
            low_direction_confidence = direction_deviation > direction_tolerance_deg
            match_score = max(0.0, min(100.0, covered_ratio - gap_count * 5 - (100.0 - direction_consistency) * 0.4))
            latest_time = max((item.get("position_time") for item in matched_points if item.get("position_time")), default=None)
            age = int((_utcnow() - latest_time).total_seconds() // 60) if latest_time else None
            confidence_level = "LOW" if low_direction_confidence else resolve_confidence_level(covered_ratio, True, False)
            match_status_code = "LOW_CONFIDENCE" if low_direction_confidence else "MATCHED" if gap_count == 0 else "PARTIAL"
            result.append(VesselRouteSegmentMatchSample(
                snapshot_id="",
                segment_id=segment.id,
                vessel_profile_id=row.profile.id if row and row.profile else None,
                mmsi=mmsi,
                ship_name=((row.summary.ship_name if row and row.summary else None) or (row.profile.ship_name if row and row.profile else None)) if row else None,
                ship_type_code=((row.summary.ship_type_code if row and row.summary else None) or (row.profile.ship_type_code if row and row.profile else None)) if row else None,
                deadweight_ton=((row.summary.deadweight_ton if row and row.summary else None) or (row.capacity.deadweight_ton if row and row.capacity else None)) if row else None,
                match_score=match_score,
                covered_ratio=covered_ratio,
                direction_consistency=direction_consistency,
                point_count=len(matched_points),
                gap_count=gap_count,
                latest_position_time=latest_time,
                source_index=matched_points[-1].get("source_index"),
                freshness_level=ais_freshness_level(age),
                confidence_level=confidence_level,
                match_status_code=match_status_code,
                created_at=_utcnow(),
            ))
        return result

    def _route_segment_item(
        self,
        route_id: int | None,
        plan_id: int,
        segment: ShippingRoutePlanSegment,
        *,
        geometry_source: str | None,
        geometry_json: dict[str, Any] | None,
        active_vessel_count: int,
        geometry_status_code: str,
        matched_vessel_count: int = 0,
        point_count: int = 0,
        gap_count: int = 0,
        covered_ratio: float | None = None,
        average_match_score: float | None = None,
        coverage_rate: float | None = None,
        confidence_level: str = "UNKNOWN",
        not_computable_reasons: list[str] | None = None,
    ) -> VesselRouteSegmentObservationItem:
        return VesselRouteSegmentObservationItem(
            snapshot_id="",
            route_id=route_id,
            plan_id=plan_id,
            segment_id=segment.id,
            segment_no=segment.segment_no,
            segment_name=f"航段 {segment.segment_no}",
            geometry_status_code=geometry_status_code,
            geometry_source=geometry_source,
            geometry_json=geometry_json,
            matched_vessel_count=matched_vessel_count,
            active_vessel_count=active_vessel_count,
            point_count=point_count,
            gap_count=gap_count,
            covered_ratio=covered_ratio,
            average_match_score=average_match_score,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            not_computable_reasons_json=not_computable_reasons or [],
            created_at=_utcnow(),
        )

    async def _navigation_constraint_items(
        self,
        context_type: str,
        *,
        node_id: int | None = None,
        plan_id: int | None = None,
        segment_id: int | None = None,
        radius_km: float | None = None,
        snapshot_id: str | None = None,
    ) -> list[VesselNavigationConstraintEvidenceResponse]:
        context_id = node_id if context_type == "NODE" else plan_id if context_type == "ROUTE_PLAN" else segment_id
        if context_id is None:
            raise ValidationError("context_type 与对应 id 参数不匹配")
        points: list[NavigationConstraintPoint] = []
        if context_type == "NODE":
            node = await self.db.get(TransportNode, node_id)
            if node:
                candidates = (await self.db.scalars(select(NavigationConstraintPoint).where(NavigationConstraintPoint.status == 1, NavigationConstraintPoint.city_code == node.city_code))).all()
                if valid_lon_lat(node.longitude, node.latitude) and radius_km is not None:
                    points = [point for point in candidates if within_distance_km(node.longitude, node.latitude, point.longitude, point.latitude, radius_km)]
                else:
                    points = list(candidates)
        elif context_type == "ROUTE_PLAN":
            constraint_ids = (await self.db.scalars(
                select(ShippingRoutePlanPoint.constraint_point_id)
                .where(ShippingRoutePlanPoint.plan_id == plan_id, ShippingRoutePlanPoint.constraint_point_id.is_not(None))
            )).all()
            if constraint_ids:
                points = list((await self.db.scalars(select(NavigationConstraintPoint).where(NavigationConstraintPoint.id.in_(constraint_ids)))).all())
        else:
            segment = await self.db.get(ShippingRoutePlanSegment, segment_id)
            if segment:
                constraint_ids = (await self.db.scalars(
                    select(ShippingRoutePlanPoint.constraint_point_id)
                    .where(
                        ShippingRoutePlanPoint.id.in_([segment.start_plan_point_id, segment.end_plan_point_id]),
                        ShippingRoutePlanPoint.constraint_point_id.is_not(None),
                    )
                )).all()
                if constraint_ids:
                    points = list((await self.db.scalars(select(NavigationConstraintPoint).where(NavigationConstraintPoint.id.in_(constraint_ids)))).all())
        return await self._persist_constraint_evidence(snapshot_id, context_type, context_id, points)

    async def _persist_constraint_evidence(
        self,
        snapshot_id: str | None,
        context_type: str,
        context_id: int,
        points: list[NavigationConstraintPoint],
    ) -> list[VesselNavigationConstraintEvidenceResponse]:
        if snapshot_id:
            await self.db.execute(delete(VesselNavigationConstraintEvidence).where(VesselNavigationConstraintEvidence.snapshot_id == snapshot_id, VesselNavigationConstraintEvidence.context_type_code == context_type, VesselNavigationConstraintEvidence.context_id == context_id))
        if not points:
            evidence = VesselNavigationConstraintEvidence(
                snapshot_id=snapshot_id,
                context_type_code=context_type,
                context_id=context_id,
                constraint_point_id=None,
                constraint_name=None,
                constraint_type_code=None,
                status_code="MISSING_SOURCE",
                source_type_code="BASE_DATA",
                source_ref=None,
                observed_at=_utcnow(),
                value_json={},
                confidence_level="UNKNOWN",
                unavailable_reason="MISSING_SOURCE",
                created_at=_utcnow(),
            )
            if snapshot_id:
                self.db.add(evidence)
                await self.db.flush()
            return [self._constraint_response(evidence)]
        profiles = {
            profile.constraint_point_id: profile
            for profile in (await self.db.scalars(select(NavigationConstraintProfile).where(NavigationConstraintProfile.constraint_point_id.in_([point.id for point in points])))).all()
        }
        responses: list[VesselNavigationConstraintEvidenceResponse] = []
        now = _utcnow()
        for point in points:
            profile = profiles.get(point.id)
            profile_complete = bool(
                profile
                and (
                    profile.max_tonnage is not None
                    or profile.max_allowed_draft_m is not None
                    or profile.min_water_depth_m is not None
                    or profile.under_keel_clearance_m is not None
                    or profile.max_air_draft_m is not None
                    or profile.max_beam_m is not None
                    or profile.max_length_m is not None
                    or profile.allowed_time_window
                    or profile.restriction_rule_json
                    or profile.rule_description
                    or profile.warning_message
                )
            )
            status_code = "AVAILABLE"
            confidence_level = "MEDIUM"
            unavailable_reason = None
            if point.valid_to and point.valid_to < now:
                status_code = "STALE"
                confidence_level = "LOW"
                unavailable_reason = "EXPIRED"
            elif point.valid_from and point.valid_from > now:
                status_code = "STALE"
                confidence_level = "LOW"
                unavailable_reason = "NOT_YET_EFFECTIVE"
            elif profile is None:
                status_code = "UNKNOWN"
                confidence_level = "UNKNOWN"
                unavailable_reason = "PROFILE_MISSING"
            elif not profile_complete:
                status_code = "UNKNOWN"
                confidence_level = "UNKNOWN"
                unavailable_reason = "PROFILE_INCOMPLETE"
            value = {
                "longitude": jsonable(point.longitude),
                "latitude": jsonable(point.latitude),
                "severity_level": point.severity_level,
                "description": point.description,
                "profile": {
                    "max_tonnage": jsonable(profile.max_tonnage),
                    "max_allowed_draft_m": jsonable(profile.max_allowed_draft_m),
                    "min_water_depth_m": jsonable(profile.min_water_depth_m),
                    "warning_message": profile.warning_message,
                } if profile else {},
            }
            evidence = VesselNavigationConstraintEvidence(
                snapshot_id=snapshot_id,
                context_type_code=context_type,
                context_id=context_id,
                constraint_point_id=point.id,
                constraint_name=point.name,
                constraint_type_code=point.constraint_type_code,
                status_code=status_code,
                source_type_code="BASE_DATA",
                source_ref=point.code,
                observed_at=now,
                expires_at=point.valid_to,
                value_json=value,
                confidence_level=confidence_level,
                unavailable_reason=unavailable_reason,
                created_at=now,
            )
            if snapshot_id:
                self.db.add(evidence)
                await self.db.flush()
            responses.append(self._constraint_response(evidence))
        return responses

    def _snapshot_meta(self, snapshot: VesselSpatialObservationSnapshot, *, refresh_required: bool = False) -> VesselSpatialSnapshotMeta:
        expired = snapshot.expires_at <= _utcnow()
        return VesselSpatialSnapshotMeta(
            snapshot_id=snapshot.snapshot_id,
            source_snapshot_id=snapshot.source_snapshot_id,
            observation_type_code=snapshot.observation_type_code,
            status_code="EXPIRED" if expired else snapshot.status_code,
            source_status_code=snapshot.source_status_code,
            stat_time=snapshot.stat_time,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            generated_at=snapshot.generated_at,
            expires_at=snapshot.expires_at,
            refresh_required=refresh_required or expired,
            coverage_rate=to_decimal(snapshot.coverage_rate),
            confidence_level=snapshot.confidence_level,
            freshness_distribution=snapshot.freshness_distribution_json or {},
            source_indices=snapshot.source_indices_json or [],
            failed_batch_count=snapshot.failed_batch_count,
            failed_batches=snapshot.failed_batches_json or [],
            unmatched_mmsi_count=snapshot.unmatched_mmsi_count,
            invalid_position_count=snapshot.invalid_position_count,
            stale_position_count=snapshot.stale_position_count,
            matched_position_count=snapshot.matched_position_count,
            active_vessel_count=snapshot.active_vessel_count,
            not_computable_reasons=snapshot.not_computable_reasons_json or [],
            quality_warnings=snapshot.quality_warnings_json or [],
            uncertainty_notes=snapshot.uncertainty_notes_json or [],
            refresh_error=snapshot.refresh_error,
        )

    def _node_summary(self, item: VesselNodeObservationItem) -> VesselNodeSituationSummary:
        return VesselNodeSituationSummary(
            node_id=item.node_id,
            node_name=item.node_name,
            node_type_code=item.node_type_code,
            city_code=item.city_code,
            radius_km=to_decimal(item.radius_km) or Decimal("0"),
            longitude=to_decimal(item.longitude),
            latitude=to_decimal(item.latitude),
            active_vessel_count=item.active_vessel_count,
            stay_vessel_count=item.stay_vessel_count,
            passby_vessel_count=item.passby_vessel_count,
            inflow_count=item.inflow_count,
            outflow_count=item.outflow_count,
            unmatched_mmsi_count=item.unmatched_mmsi_count,
            invalid_position_count=item.invalid_position_count,
            stale_position_count=item.stale_position_count,
            coverage_rate=to_decimal(item.coverage_rate),
            confidence_level=item.confidence_level,
            freshness_distribution=item.freshness_distribution_json or {},
            ship_type_distribution=[
                VesselShipTypeDistributionItemResponse(
                    ship_type_code=entry.get("ship_type_code"),
                    ship_type_name=entry.get("ship_type_name"),
                    count=int(entry.get("count") or 0),
                )
                for entry in (item.ship_type_distribution_json or [])
            ],
            risk_distribution=[
                VesselAssetDistributionItemResponse(
                    code=entry.get("code"),
                    name=entry.get("name") or entry.get("code"),
                    count=int(entry.get("count") or 0),
                )
                for entry in (item.risk_distribution_json or [])
            ],
            latest_position_time=item.latest_position_time,
            not_computable_reasons=item.not_computable_reasons_json or [],
        )

    def _node_vessel_response(self, row: VesselNodeObservationVessel) -> VesselNodeObservationVesselResponse:
        return VesselNodeObservationVesselResponse(
            id=row.id,
            vessel_profile_id=row.vessel_profile_id,
            mmsi=row.mmsi,
            ship_name=row.ship_name,
            ship_type_code=row.ship_type_code,
            deadweight_ton=to_decimal(row.deadweight_ton),
            longitude=to_decimal(row.longitude),
            latitude=to_decimal(row.latitude),
            distance_km=to_decimal(row.distance_km),
            position_time=row.position_time,
            source_index=row.source_index,
            freshness_level=row.freshness_level,
            match_status_code=row.match_status_code,
            stay_duration_minutes=row.stay_duration_minutes,
            direction_status_code=row.direction_status_code,
            risk_level=row.risk_level,
            quality_level=row.quality_level,
        )

    def _route_segment_response(self, row: VesselRouteSegmentObservationItem) -> VesselRouteSegmentObservationResponse:
        return VesselRouteSegmentObservationResponse(
            id=row.id,
            route_id=row.route_id,
            plan_id=row.plan_id,
            segment_id=row.segment_id,
            segment_no=row.segment_no,
            segment_name=row.segment_name,
            geometry_status_code=row.geometry_status_code,
            geometry_source=row.geometry_source,
            geometry_json=row.geometry_json,
            matched_vessel_count=row.matched_vessel_count,
            active_vessel_count=row.active_vessel_count,
            point_count=row.point_count,
            gap_count=row.gap_count,
            covered_ratio=to_decimal(row.covered_ratio),
            average_match_score=to_decimal(row.average_match_score),
            coverage_rate=to_decimal(row.coverage_rate),
            confidence_level=row.confidence_level,
            not_computable_reasons=row.not_computable_reasons_json or [],
        )

    def _route_sample_response(self, row: VesselRouteSegmentMatchSample) -> VesselRouteSegmentMatchSampleResponse:
        return VesselRouteSegmentMatchSampleResponse(
            id=row.id,
            segment_id=row.segment_id,
            vessel_profile_id=row.vessel_profile_id,
            mmsi=row.mmsi,
            ship_name=row.ship_name,
            ship_type_code=row.ship_type_code,
            deadweight_ton=to_decimal(row.deadweight_ton),
            match_score=to_decimal(row.match_score),
            covered_ratio=to_decimal(row.covered_ratio),
            direction_consistency=to_decimal(row.direction_consistency),
            point_count=row.point_count,
            gap_count=row.gap_count,
            latest_position_time=row.latest_position_time,
            source_index=row.source_index,
            freshness_level=row.freshness_level,
            confidence_level=row.confidence_level,
            match_status_code=row.match_status_code,
        )

    def _constraint_response(self, row: VesselNavigationConstraintEvidence) -> VesselNavigationConstraintEvidenceResponse:
        return VesselNavigationConstraintEvidenceResponse(
            id=row.id,
            snapshot_id=row.snapshot_id,
            context_type_code=row.context_type_code,
            context_id=row.context_id,
            constraint_point_id=row.constraint_point_id,
            constraint_name=row.constraint_name,
            constraint_type_code=row.constraint_type_code,
            status_code=row.status_code,
            source_type_code=row.source_type_code,
            source_ref=row.source_ref,
            observed_at=row.observed_at,
            expires_at=row.expires_at,
            value=row.value_json or {},
            confidence_level=row.confidence_level,
            unavailable_reason=row.unavailable_reason,
        )

    async def _node_default_radius_km(self) -> float:
        return float(await self.runtime_config.get_float(VESSEL_SPATIAL_NODE_DEFAULT_RADIUS_KM, settings.VESSEL_SPATIAL_NODE_DEFAULT_RADIUS_KM, profile_code=ES_HISTORY_CONFIG_PROFILE))

    async def _node_stay_minutes(self) -> int:
        return int(await self.runtime_config.get_int(VESSEL_SPATIAL_NODE_STAY_MINUTES, settings.VESSEL_SPATIAL_NODE_STAY_MINUTES, profile_code=ES_HISTORY_CONFIG_PROFILE))

    async def _route_buffer_km(self) -> float:
        return float(await self.runtime_config.get_float(VESSEL_SPATIAL_ROUTE_BUFFER_KM, settings.VESSEL_SPATIAL_ROUTE_BUFFER_KM, profile_code=ES_HISTORY_CONFIG_PROFILE))

    async def _direction_tolerance_deg(self) -> float:
        return float(await self.runtime_config.get_float(VESSEL_SPATIAL_DIRECTION_TOLERANCE_DEG, settings.VESSEL_SPATIAL_DIRECTION_TOLERANCE_DEG, profile_code=ES_HISTORY_CONFIG_PROFILE))

    async def _min_coverage_rate(self) -> float:
        return float(await self.runtime_config.get_float(VESSEL_SPATIAL_MIN_COVERAGE_RATE, settings.VESSEL_SPATIAL_MIN_COVERAGE_RATE, profile_code=ES_HISTORY_CONFIG_PROFILE))

    async def _snapshot_ttl_seconds(self) -> int:
        return int(await self.runtime_config.get_int(VESSEL_SPATIAL_SNAPSHOT_TTL_SECONDS, settings.VESSEL_SPATIAL_SNAPSHOT_TTL_SECONDS, profile_code=ES_HISTORY_CONFIG_PROFILE))
