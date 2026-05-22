"""Response assembly and quality gap checks for candidate analysis."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select

from app.models.address import Region, RegionBoundaryVersion, TransportNode
from app.models.route import ShippingRoute, ShippingRoutePlan, ShippingRoutePlanSegment, ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersionSegment
from app.models.vessel import (
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
)
from app.modules.vessel.display_helpers import data_source_codes
from app.modules.vessel.schemas import (
    VesselCandidateAnalysisAnnotationResponse,
    VesselCandidateAnalysisItemResponse,
    VesselCandidateAnalysisResponse,
    VesselCandidateContextQualityGap,
)


class VesselCandidateResponseMixin:
    """Build candidate analysis responses and source quality gaps."""

    async def _to_response(self, analysis: VesselCandidateAnalysis, *, include_items: bool) -> VesselCandidateAnalysisResponse:
        items: list[VesselCandidateAnalysisItemResponse] = []
        if include_items:
            item_rows = (
                await self.db.execute(
                    select(VesselCandidateAnalysisItem)
                    .where(VesselCandidateAnalysisItem.analysis_id == analysis.id)
                    .order_by(desc(VesselCandidateAnalysisItem.fit_score), VesselCandidateAnalysisItem.id)
                )
            ).scalars().all()
            annotations = await self._annotations_by_item([row.id for row in item_rows])
            positions = await self._latest_positions_for_items(analysis, item_rows)
            items = [self._item_response(row, annotations.get(row.id, []), positions.get(row.vessel_profile_id)) for row in item_rows]
        return VesselCandidateAnalysisResponse(
            id=analysis.id,
            context_type_code=analysis.context_type_code,
            source_layer_code=analysis.source_layer_code,
            freight_id=analysis.freight_id,
            freight_candidate_id=analysis.freight_candidate_id,
            origin_node_id=analysis.origin_node_id,
            destination_node_id=analysis.destination_node_id,
            route_id=analysis.route_id,
            plan_id=analysis.plan_id,
            origin_city_code=analysis.origin_city_code,
            destination_city_code=analysis.destination_city_code,
            region_id=analysis.region_id,
            context=analysis.context_json or {},
            filters=analysis.filters_json or {},
            source_ais_snapshot_id=analysis.source_ais_snapshot_id,
            source_spatial_snapshot_id=analysis.source_spatial_snapshot_id,
            query_hash=analysis.query_hash,
            status_code=analysis.status_code,
            coverage_rate=analysis.coverage_rate,
            confidence_level=analysis.confidence_level,
            candidate_count=analysis.candidate_count,
            low_confidence_count=analysis.low_confidence_count,
            not_computable_reasons=analysis.not_computable_reasons_json or [],
            uncertainty_notes=analysis.uncertainty_notes_json or [],
            data_sources=data_source_codes(analysis.data_sources_json),
            analysis_center_path=self._analysis_center_path(analysis),
            source_context_path=self._source_context_path(analysis),
            context_quality_gaps=await self._context_quality_gaps(analysis),
            boundary_notice="候选适配只输出分析判断和不确定性，不代表可接货、不产生运输承诺。",
            uncertainty_explain=self._candidate_uncertainty_explain(analysis),
            route_layers=[],
            regional_supply_demand=self._regional_supply_demand(analysis),
            generated_at=analysis.generated_at,
            expires_at=analysis.expires_at,
            items=items,
        )

    @staticmethod
    def _candidate_uncertainty_explain(analysis: VesselCandidateAnalysis) -> str:
        reasons = [*(analysis.uncertainty_notes_json or []), *(analysis.not_computable_reasons_json or [])]
        return " / ".join(str(item) for item in reasons[:6]) or "暂无明显不确定性，仍需结合实时 AIS 和业务核验。"

    @staticmethod
    def _regional_supply_demand(analysis: VesselCandidateAnalysis) -> dict[str, Any] | None:
        context = analysis.context_json or {}
        value = context.get("regional_supply_demand") or context.get("supply_demand") or context.get("region_supply_demand")
        return value if isinstance(value, dict) else None

    @staticmethod
    def _analysis_center_path(analysis: VesselCandidateAnalysis) -> str:
        params = ["tab=candidate"]
        if analysis.generated_at:
            day = analysis.generated_at.date().isoformat()
            params.extend([f"date_from={day}", f"date_to={day}"])
        return f"/analysis/ships?{'&'.join(params)}"

    @staticmethod
    def _source_context_path(analysis: VesselCandidateAnalysis) -> str | None:
        for value, path in (
            (analysis.freight_id, f"/freight/detail/{analysis.freight_id}" if analysis.freight_id else None),
            (analysis.freight_candidate_id, f"/freight/candidates?candidate_id={analysis.freight_candidate_id}" if analysis.freight_candidate_id else None),
            (analysis.origin_node_id, f"/address/nodes/{analysis.origin_node_id}" if analysis.origin_node_id else None),
            (analysis.route_id, f"/route/detail/{analysis.route_id}" if analysis.route_id else None),
            (analysis.region_id, f"/address/regions?region_id={analysis.region_id}" if analysis.region_id else None),
        ):
            if value:
                return path
        return None

    async def _context_quality_gaps(self, analysis: VesselCandidateAnalysis) -> list[VesselCandidateContextQualityGap]:
        gaps: list[VesselCandidateContextQualityGap] = []
        if analysis.origin_node_id:
            node = await self.db.get(TransportNode, analysis.origin_node_id)
            if node is None:
                gaps.append(self._quality_gap("TRANSPORT_NODE", analysis.origin_node_id, None, "origin_node_id", "NODE_MISSING", "起运节点不存在或已不可用，空间分析无法稳定定位。", f"/address/nodes/{analysis.origin_node_id}"))
            elif node.longitude is None or node.latitude is None:
                gaps.append(self._quality_gap("TRANSPORT_NODE", node.id, node.name, "longitude,latitude", "NODE_COORDINATE_MISSING", "节点缺少经纬度，候选船与节点距离只能降级计算。", f"/address/nodes/{node.id}/edit"))
        if analysis.route_id:
            gaps.extend(await self._route_quality_gaps(analysis.route_id))
        if analysis.region_id:
            gaps.extend(await self._region_quality_gaps(analysis.region_id))
        if analysis.source_spatial_snapshot_id is None and (analysis.origin_node_id or analysis.route_id or analysis.region_id):
            gaps.append(self._quality_gap("VESSEL_SPATIAL_OBSERVATION", None, None, "source_spatial_snapshot_id", "SPATIAL_SNAPSHOT_MISSING", "本次分析没有可复盘的空间观测快照，建议先刷新 AIS 空间态势。", "/vessels/node-route-analysis"))
        return gaps

    async def _route_quality_gaps(self, route_id: int) -> list[VesselCandidateContextQualityGap]:
        route = await self.db.get(ShippingRoute, route_id)
        if route is None:
            return [self._quality_gap("SHIPPING_ROUTE", route_id, None, "route_id", "ROUTE_MISSING", "航线不存在或已不可用，无法做航线匹配复盘。", f"/route/detail/{route_id}")]
        gaps: list[VesselCandidateContextQualityGap] = []
        for count, field_name, reason_code, message in (
            (await self._route_segment_count(route.id), "segments", "ROUTE_SEGMENT_MISSING", "航线缺少保存的航段，候选分析无法判断航线关系。"),
            (await self._route_track_count(route.id), "track", "ROUTE_TRACK_MISSING", "航线缺少地图轨迹，空间匹配可信度会下降。"),
        ):
            if count == 0:
                gaps.append(self._quality_gap("SHIPPING_ROUTE", route.id, route.name, field_name, reason_code, message, f"/route/detail/{route.id}"))
        return gaps

    async def _region_quality_gaps(self, region_id: int) -> list[VesselCandidateContextQualityGap]:
        region = await self.db.get(Region, region_id)
        if region is None:
            return [self._quality_gap("REGION", region_id, None, "region_id", "REGION_MISSING", "区域不存在或已不可用，供需分布无法复盘。", f"/address/regions?region_id={region_id}")]
        if not region.current_boundary_version_id:
            return [self._quality_gap("REGION", region.id, region.name, "current_boundary_version_id", "REGION_BOUNDARY_MISSING", "区域缺少当前边界版本，空间供需分析无法精确落区。", f"/address/regions?region_id={region.id}")]
        boundary = await self.db.get(RegionBoundaryVersion, region.current_boundary_version_id)
        if boundary is None or not boundary.geometry_json:
            return [self._quality_gap("REGION_BOUNDARY", region.current_boundary_version_id, region.name, "geometry_json", "REGION_BOUNDARY_GEOMETRY_MISSING", "区域当前边界缺少几何数据，空间供需分析无法精确落区。", f"/address/regions?region_id={region.id}")]
        return []

    async def _route_segment_count(self, route_id: int) -> int:
        return int(
            await self.db.scalar(
                select(func.count(ShippingRoutePlanSegment.id))
                .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanSegment.plan_id)
                .where(ShippingRoutePlan.route_id == route_id)
            )
            or 0
        )

    async def _route_track_count(self, route_id: int) -> int:
        return int(
            await self.db.scalar(
                select(func.count(ShippingRoutePlanTrackVersionSegment.id))
                .select_from(ShippingRoutePlanTrackVersionSegment)
                .join(ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersion.id == ShippingRoutePlanTrackVersionSegment.version_id)
                .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
                .where(
                    ShippingRoutePlan.route_id == route_id,
                    ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
                    ShippingRoutePlanTrackVersion.version_status_code == "READY",
                )
            )
            or 0
        )

    @staticmethod
    def _quality_gap(object_type: str, object_id: int | str | None, object_name: str | None, field_name: str, reason_code: str, message: str, target_path: str | None) -> VesselCandidateContextQualityGap:
        return VesselCandidateContextQualityGap(object_type=object_type, object_id=object_id, object_name=object_name, field_name=field_name, reason_code=reason_code, message=message, target_path=target_path)

    def _item_response(
        self,
        row: VesselCandidateAnalysisItem,
        annotations: list[VesselCandidateAnalysisAnnotationResponse],
        latest_position: VesselLatestPositionSnapshot | None = None,
    ) -> VesselCandidateAnalysisItemResponse:
        return VesselCandidateAnalysisItemResponse(
            id=row.id,
            analysis_id=row.analysis_id,
            vessel_profile_id=row.vessel_profile_id,
            mmsi=row.mmsi,
            ship_name=row.ship_name,
            ship_type_code=row.ship_type_code,
            deadweight_ton=row.deadweight_ton,
            design_draft_m=row.design_draft_m,
            longitude=latest_position.longitude if latest_position is not None else None,
            latitude=latest_position.latitude if latest_position is not None else None,
            latest_position_time=row.latest_position_time,
            ais_freshness_level=row.ais_freshness_level,
            risk_level=row.risk_level,
            quality_level=row.quality_level,
            fit_score=row.fit_score,
            candidate_value_level=row.candidate_value_level,
            confidence_level=row.confidence_level,
            node_distance_km=row.node_distance_km,
            route_match_score=row.route_match_score,
            direction_consistency=row.direction_consistency,
            constraint_status_code=row.constraint_status_code,
            score_parts=row.score_parts_json or {},
            risk_reasons=row.risk_reasons_json or [],
            uncertainty_reasons=row.uncertainty_reasons_json or [],
            not_computable_reasons=row.not_computable_reasons_json or [],
            data_sources=data_source_codes(row.data_sources_json),
            annotations=annotations,
        )

    async def _latest_positions_for_items(
        self,
        analysis: VesselCandidateAnalysis,
        rows: list[VesselCandidateAnalysisItem],
    ) -> dict[int, VesselLatestPositionSnapshot]:
        if not analysis.source_ais_snapshot_id:
            return {}
        vessel_ids = [row.vessel_profile_id for row in rows if row.vessel_profile_id]
        if not vessel_ids:
            return {}
        position_rows = (
            await self.db.scalars(
                select(VesselLatestPositionSnapshot)
                .where(
                    VesselLatestPositionSnapshot.snapshot_id == analysis.source_ais_snapshot_id,
                    VesselLatestPositionSnapshot.vessel_profile_id.in_(vessel_ids),
                    VesselLatestPositionSnapshot.valid_position_flag.is_(True),
                    VesselLatestPositionSnapshot.longitude.is_not(None),
                    VesselLatestPositionSnapshot.latitude.is_not(None),
                )
                .order_by(VesselLatestPositionSnapshot.position_time.desc().nullslast())
            )
        ).all()
        result: dict[int, VesselLatestPositionSnapshot] = {}
        for row in position_rows:
            if row.vessel_profile_id is not None:
                result.setdefault(row.vessel_profile_id, row)
        return result

    async def _annotations_by_item(self, item_ids: list[int]) -> dict[int, list[VesselCandidateAnalysisAnnotationResponse]]:
        if not item_ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselCandidateAnalysisAnnotation)
                .where(VesselCandidateAnalysisAnnotation.item_id.in_(item_ids))
                .order_by(VesselCandidateAnalysisAnnotation.created_at)
            )
        ).scalars().all()
        result: dict[int, list[VesselCandidateAnalysisAnnotationResponse]] = {}
        for row in rows:
            result.setdefault(row.item_id, []).append(self._annotation_response(row))
        return result

    @staticmethod
    def _annotation_response(row: VesselCandidateAnalysisAnnotation) -> VesselCandidateAnalysisAnnotationResponse:
        return VesselCandidateAnalysisAnnotationResponse(
            id=row.id,
            analysis_id=row.analysis_id,
            item_id=row.item_id,
            annotation_type_code=row.annotation_type_code,
            comment=row.comment,
            created_by=row.created_by,
            created_at=row.created_at,
            source_version=row.source_version_json or {},
        )
