"""Shipping opportunity read model for freight-driven decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.address import TransportNode
from app.models.commodity import CommodityStandard
from app.models.freight import Freight, FreightNormalizationSuggestion
from app.models.route import ShippingRoute
from app.models.vessel import VesselCandidateAnalysis
from app.modules.freight.schemas import (
    PageResponse,
    ShippingOpportunityActionResponse,
    ShippingOpportunityContextResponse,
    ShippingOpportunityDetailResponse,
    ShippingOpportunityLineageResponse,
    ShippingOpportunityQualityResponse,
    ShippingOpportunitySummaryResponse,
)


class ShippingOpportunityService:
    """Builds a production-facing opportunity view from existing freight facts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_opportunities(
        self,
        *,
        keyword: str | None = None,
        status_code: str | None = None,
        source_type: str | None = None,
        origin_city_code: str | None = None,
        destination_city_code: str | None = None,
        commodity_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[ShippingOpportunitySummaryResponse]:
        stmt = self._base_query(
            keyword=keyword,
            status_code=status_code,
            source_type=source_type,
            origin_city_code=origin_city_code,
            destination_city_code=destination_city_code,
            commodity_id=commodity_id,
        )
        total = await self._count(stmt)
        rows = (
            (
                await self.db.execute(
                    stmt.order_by(Freight.created_at.desc(), Freight.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        context = await self._load_context(rows)
        items = [self._summary(row, context) for row in rows]
        return PageResponse[ShippingOpportunitySummaryResponse](total=total, page=page, page_size=page_size, items=items)

    async def get_opportunity(self, freight_id: int) -> ShippingOpportunityDetailResponse:
        row = await self.db.get(Freight, freight_id)
        if not row or row.deleted_at is not None:
            raise NotFoundError("Freight", freight_id)
        context = await self._load_context([row])
        summary = self._summary(row, context)
        route = context["route_by_pair"].get((row.origin_region_id_cache, row.destination_region_id_cache))
        analysis = context["candidate_by_freight"].get(row.id)
        return ShippingOpportunityDetailResponse(
            **summary.model_dump(),
            raw_origin_text=row.raw_origin_text,
            raw_destination_text=row.raw_destination_text,
            origin_match_level_code=row.origin_match_level_code,
            destination_match_level_code=row.destination_match_level_code,
            commodity_match_level_code=row.commodity_match_level_code,
            route_id=getattr(route, "id", None),
            route_name=getattr(route, "name", None),
            candidate_analysis_id=getattr(analysis, "id", None),
            candidate_count=getattr(analysis, "candidate_count", 0) or 0,
            latest_candidate_analysis_at=getattr(analysis, "generated_at", None),
        )

    def _base_query(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_type: str | None,
        origin_city_code: str | None,
        destination_city_code: str | None,
        commodity_id: int | None,
    ):
        stmt = select(Freight).where(Freight.deleted_at.is_(None))
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Freight.freight_no.like(like),
                    Freight.cargo_title.like(like),
                    Freight.publisher_org_name.like(like),
                    Freight.raw_commodity_name.like(like),
                    Freight.raw_origin_text.like(like),
                    Freight.raw_destination_text.like(like),
                )
            )
        if status_code:
            stmt = stmt.where(Freight.status_code == status_code)
        if source_type:
            stmt = stmt.where(Freight.source_type_code == source_type)
        if origin_city_code:
            stmt = stmt.where(Freight.origin_city_code == origin_city_code)
        if destination_city_code:
            stmt = stmt.where(Freight.destination_city_code == destination_city_code)
        if commodity_id:
            stmt = stmt.where(Freight.commodity_standard_id == commodity_id)
        return stmt

    async def _count(self, stmt) -> int:
        return int(await self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)

    async def _load_context(self, rows: list[Freight]) -> dict[str, Any]:
        freight_ids = [row.id for row in rows]
        node_ids = {value for row in rows for value in (row.origin_node_id, row.destination_node_id) if value}
        commodity_ids = {row.commodity_standard_id for row in rows if row.commodity_standard_id}
        region_pairs = {
            (row.origin_region_id_cache, row.destination_region_id_cache)
            for row in rows
            if row.origin_region_id_cache and row.destination_region_id_cache
        }
        return {
            "node_by_id": await self._nodes(node_ids),
            "commodity_by_id": await self._commodities(commodity_ids),
            "route_by_pair": await self._routes(region_pairs),
            "candidate_by_freight": await self._candidate_analyses(freight_ids),
            "quality_issue_count_by_freight": await self._quality_issue_counts(freight_ids),
            "generated_at": datetime.utcnow(),
        }

    async def _nodes(self, node_ids: set[int]) -> dict[int, TransportNode]:
        if not node_ids:
            return {}
        rows = (await self.db.execute(select(TransportNode).where(TransportNode.id.in_(node_ids)))).scalars().all()
        return {row.id: row for row in rows}

    async def _commodities(self, commodity_ids: set[int]) -> dict[int, CommodityStandard]:
        if not commodity_ids:
            return {}
        rows = (await self.db.execute(select(CommodityStandard).where(CommodityStandard.id.in_(commodity_ids)))).scalars().all()
        return {row.id: row for row in rows}

    async def _routes(self, region_pairs: set[tuple[int, int]]) -> dict[tuple[int, int], ShippingRoute]:
        if not region_pairs:
            return {}
        rows = (
            await self.db.execute(
                select(ShippingRoute).where(
                    ShippingRoute.deleted_at.is_(None),
                    tuple_(ShippingRoute.origin_region_id, ShippingRoute.destination_region_id).in_(region_pairs),
                )
            )
        ).scalars().all()
        return {(row.origin_region_id, row.destination_region_id): row for row in rows}

    async def _candidate_analyses(self, freight_ids: list[int]) -> dict[int, VesselCandidateAnalysis]:
        if not freight_ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselCandidateAnalysis)
                .where(VesselCandidateAnalysis.freight_id.in_(freight_ids))
                .order_by(VesselCandidateAnalysis.freight_id, VesselCandidateAnalysis.generated_at.desc())
            )
        ).scalars().all()
        latest: dict[int, VesselCandidateAnalysis] = {}
        for row in rows:
            if row.freight_id and row.freight_id not in latest:
                latest[row.freight_id] = row
        return latest

    async def _quality_issue_counts(self, freight_ids: list[int]) -> dict[int, int]:
        if not freight_ids:
            return {}
        rows = (
            await self.db.execute(
                select(FreightNormalizationSuggestion.freight_id, func.count())
                .where(
                    FreightNormalizationSuggestion.freight_id.in_(freight_ids),
                    FreightNormalizationSuggestion.status_code != "APPLIED",
                )
                .group_by(FreightNormalizationSuggestion.freight_id)
            )
        ).all()
        return {int(freight_id): int(count) for freight_id, count in rows}

    def _summary(self, row: Freight, context: dict[str, Any]) -> ShippingOpportunitySummaryResponse:
        origin_node = context["node_by_id"].get(row.origin_node_id)
        destination_node = context["node_by_id"].get(row.destination_node_id)
        commodity = context["commodity_by_id"].get(row.commodity_standard_id)
        route = context["route_by_pair"].get((row.origin_region_id_cache, row.destination_region_id_cache))
        candidate_analysis = context["candidate_by_freight"].get(row.id)
        issue_count = context["quality_issue_count_by_freight"].get(row.id, 0)
        completeness, missing_reasons = self._completeness(row)
        uncertainty = self._uncertainty_reasons(row, route, candidate_analysis, issue_count)
        route_status = self._route_status(row, route)
        capacity_status = self._capacity_status(row, candidate_analysis)
        pricing_status = self._pricing_status(row)
        confidence = self._confidence(completeness, missing_reasons, uncertainty, issue_count)
        return ShippingOpportunitySummaryResponse(
            freight_id=row.id,
            freight_no=row.freight_no,
            cargo_title=row.cargo_title,
            source_type_code=row.source_type_code,
            source_channel_code=row.source_channel_code,
            status_code=row.status_code,
            origin_node_id=row.origin_node_id,
            origin_node_name=getattr(origin_node, "name", None),
            origin_city_code=row.origin_city_code,
            origin_display=self._location_display(row.raw_origin_text, origin_node, row.origin_city_code),
            destination_node_id=row.destination_node_id,
            destination_node_name=getattr(destination_node, "name", None),
            destination_city_code=row.destination_city_code,
            destination_display=self._location_display(row.raw_destination_text, destination_node, row.destination_city_code),
            commodity_standard_id=row.commodity_standard_id,
            commodity_standard_name=getattr(commodity, "name", None),
            raw_commodity_name=row.raw_commodity_name,
            estimated_tonnage=row.estimated_tonnage,
            min_tonnage=row.min_tonnage,
            max_tonnage=row.max_tonnage,
            raw_tonnage_text=row.raw_tonnage_text,
            unit_price=row.unit_price,
            total_price=row.total_price,
            price_unit=row.price_unit,
            route_status_code=route_status,
            capacity_status_code=capacity_status,
            pricing_status_code=pricing_status,
            data_quality_status_code="HAS_OPEN_ISSUES" if issue_count else "NO_OPEN_ISSUES",
            completeness_score=completeness,
            context=self._opportunity_context(row),
            lineage=self._lineage(row, context["generated_at"]),
            quality=ShippingOpportunityQualityResponse(
                coverage_rate=completeness,
                confidence_level=confidence,
                not_computable_reasons=missing_reasons,
                uncertainty_reasons=uncertainty,
                issue_count=issue_count,
            ),
            actions=self._actions(row, route_status, capacity_status, pricing_status, missing_reasons),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _location_display(raw_text: str | None, node: TransportNode | None, city_code: str | None) -> str | None:
        if node:
            return node.name
        return raw_text or city_code

    @staticmethod
    def _opportunity_context(row: Freight) -> ShippingOpportunityContextResponse:
        return ShippingOpportunityContextResponse(
            freight_id=row.id,
            date_from=row.published_at or row.created_at,
            date_to=row.expired_at,
            filters={
                "freight_id": row.id,
                "origin_node_id": row.origin_node_id,
                "destination_node_id": row.destination_node_id,
                "origin_city_code": row.origin_city_code,
                "destination_city_code": row.destination_city_code,
                "commodity_standard_id": row.commodity_standard_id,
                "status_code": row.status_code,
            },
        )

    @staticmethod
    def _lineage(row: Freight, generated_at: datetime) -> ShippingOpportunityLineageResponse:
        refs = {
            "freight_id": row.id,
            "freight_no": row.freight_no,
            "source_ref_no": row.source_ref_no,
            "source_batch_id": row.source_batch_id,
            "source_tms_inbound_id": row.source_tms_inbound_id,
            "source_clue_id": row.source_clue_id,
            "source_candidate_id": row.source_candidate_id,
        }
        tables = ["freight"]
        if row.source_batch_id:
            tables.append("freight_batch_task")
        if row.source_tms_inbound_id:
            tables.append("freight_tms_inbound")
        if row.source_clue_id:
            tables.append("freight_clue")
        if row.source_candidate_id:
            tables.append("freight_candidate")
        return ShippingOpportunityLineageResponse(
            source_tables=tables,
            source_refs={key: value for key, value in refs.items() if value is not None},
            data_versions=[f"source_type:{row.source_type_code}", f"source_channel:{row.source_channel_code or 'UNKNOWN'}"],
            sample_count=1,
            generated_at=generated_at,
        )

    @staticmethod
    def _completeness(row: Freight) -> tuple[float, list[str]]:
        checks = [
            ("ORIGIN_NODE_MISSING", bool(row.origin_node_id)),
            ("DESTINATION_NODE_MISSING", bool(row.destination_node_id)),
            ("COMMODITY_STANDARD_MISSING", bool(row.commodity_standard_id)),
            ("TONNAGE_MISSING", bool(row.estimated_tonnage or row.min_tonnage or row.max_tonnage)),
            ("PRICE_MISSING", bool(row.unit_price or row.total_price)),
        ]
        missing = [code for code, ok in checks if not ok]
        return round((len(checks) - len(missing)) / len(checks), 4), missing

    @staticmethod
    def _uncertainty_reasons(
        row: Freight,
        route: ShippingRoute | None,
        candidate_analysis: VesselCandidateAnalysis | None,
        issue_count: int,
    ) -> list[str]:
        reasons: list[str] = []
        if row.origin_match_level_code == "RAW":
            reasons.append("ORIGIN_ONLY_RAW_TEXT")
        if row.destination_match_level_code == "RAW":
            reasons.append("DESTINATION_ONLY_RAW_TEXT")
        if row.commodity_match_level_code == "RAW":
            reasons.append("COMMODITY_ONLY_RAW_TEXT")
        if row.origin_node_id and row.destination_node_id and not route:
            reasons.append("ROUTE_MODEL_NOT_BOUND")
        if row.origin_node_id and row.destination_node_id and not candidate_analysis:
            reasons.append("CAPACITY_MATCH_NOT_RUN")
        if issue_count:
            reasons.append("OPEN_DATA_QUALITY_ISSUES")
        return reasons

    @staticmethod
    def _route_status(row: Freight, route: ShippingRoute | None) -> str:
        if not row.origin_node_id or not row.destination_node_id:
            return "NOT_COMPUTABLE"
        return "READY" if route else "PENDING_ROUTE_MODEL"

    @staticmethod
    def _capacity_status(row: Freight, analysis: VesselCandidateAnalysis | None) -> str:
        if not (row.origin_node_id and row.destination_node_id and row.commodity_standard_id):
            return "NOT_COMPUTABLE"
        if analysis:
            return analysis.status_code
        return "MATCH_NOT_RUN"

    @staticmethod
    def _pricing_status(row: Freight) -> str:
        if row.unit_price or row.total_price:
            return "HAS_PRICE_EVIDENCE"
        if row.origin_node_id and row.destination_node_id and row.commodity_standard_id:
            return "READY_FOR_QUOTE"
        return "NOT_COMPUTABLE"

    @staticmethod
    def _confidence(completeness: float, missing: list[str], uncertainty: list[str], issue_count: int) -> str:
        if missing:
            return "LOW"
        if completeness >= 0.8 and not uncertainty and issue_count == 0:
            return "HIGH"
        if completeness >= 0.6:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _actions(
        row: Freight,
        route_status: str,
        capacity_status: str,
        pricing_status: str,
        missing_reasons: list[str],
    ) -> list[ShippingOpportunityActionResponse]:
        actions = [
            ShippingOpportunityActionResponse(
                action_code="OPEN_FREIGHT_DETAIL",
                title="查看货源详情",
                target_route=f"/freight/detail/{row.id}",
                query={"freight_id": row.id},
            )
        ]
        if missing_reasons or row.origin_match_level_code == "RAW" or row.destination_match_level_code == "RAW":
            actions.append(
                ShippingOpportunityActionResponse(
                    action_code="OPEN_FREIGHT_CLEANING",
                    title="进入货源清洗",
                    target_route="/freight/normalization",
                    query={"freight_id": row.id, "reason_codes": missing_reasons},
                )
            )
        actions.append(
            ShippingOpportunityActionResponse(
                action_code="OPEN_CANDIDATE_VESSELS",
                title="船货适配分析",
                target_route="/vessels/candidate-analysis",
                query={"context_type_code": "FREIGHT_SAMPLE", "freight_id": row.id},
                disabled_reason=None if capacity_status != "NOT_COMPUTABLE" else "缺少节点或标准货品，无法计算适配船舶",
            )
        )
        actions.append(
            ShippingOpportunityActionResponse(
                action_code="OPEN_QUOTE_SIMULATOR",
                title="进入报价测算",
                target_route="/analysis/quote-simulator",
                query={
                    "freight_id": row.id,
                    "origin_node_id": row.origin_node_id,
                    "destination_node_id": row.destination_node_id,
                    "commodity_standard_id": row.commodity_standard_id,
                },
                disabled_reason=None if pricing_status != "NOT_COMPUTABLE" else "缺少起终点或标准货品，无法报价",
            )
        )
        if route_status == "PENDING_ROUTE_MODEL":
            actions.append(
                ShippingOpportunityActionResponse(
                    action_code="OPEN_ROUTE_PLANNING",
                    title="补齐航线模型",
                    target_route="/route/list",
                    query={
                        "origin_region_id": row.origin_region_id_cache,
                        "destination_region_id": row.destination_region_id_cache,
                    },
                )
            )
        return actions
