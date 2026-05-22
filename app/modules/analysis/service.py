"""analysis 模块 service。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.address import AdminRegion, AdminRegionBoundary, Region, TransportNode
from app.models.analysis import (
    AnalysisJobDefinition,
    AnalysisJobRun,
    FactCandidateFitDaily,
    FactFreightCityDaily,
    FactFreightCommodityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightNodeDaily,
    FactFreightPriceDaily,
    FactRegionDaily,
    FactRegionSupplyDemandDaily,
    FactShipCityDaily,
    FactShipDaily,
    FactShipFlowDaily,
    FactVesselAisFreshnessDaily,
    FactVesselAssetDaily,
    FactVesselQualityDaily,
    FactVesselRiskDaily,
    FactVesselTrajectoryDaily,
)
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.dictionary import StdDict, StdDictItem
from app.models.vessel import VesselProfileSummary
from app.modules.address.boundary_utils import (
    boundary_paths_for_precision,
    extract_geojson_polygons,
    serialize_boundary_paths,
)
from app.modules.analysis.schemas import (
    AnalysisActionBlock,
    AnalysisContextBlock,
    AnalysisLineageBlock,
    AnalysisOverviewResponse,
    AnalysisQualityBlock,
    BoundaryHeatMapItem,
    ChartPoint,
    FlowAnalysisOverviewResponse,
    FlowAnalysisQuery,
    FlowMapItem,
    FreightAnalysisOverviewResponse,
    HeatMapItem,
    MetricCard,
    MetricEvidence,
    PriceAnalysisOverviewResponse,
    RegionSupplyDemandAnalysisResponse,
    RegionAnalysisOverviewResponse,
    ShipAnalysisOverviewResponse,
    VesselAssetAnalysisResponse,
    VesselCandidateFitAnalysisResponse,
    VesselQualityAnalysisResponse,
    VesselRiskAnalysisResponse,
    VesselTrajectoryAnalysisResponse,
)
from app.modules.analysis.flow_route_geometry import FlowRouteGeometryMixin, _FLOW_ROUTE_GEOMETRY_CACHE, _FLOW_ROUTE_GEOMETRY_REDIS_CLIENT
from app.modules.analysis.freight_insights import build_freight_insights
from app.modules.analysis.flow_workbench import (
    enrich_flow_relationships,
    flow_corridor_items,
    freight_structure_links,
    ship_quality_points,
)
from app.modules.analysis.job_views import AnalysisJobViewMixin
from app.modules.analysis.quote_route_service import QuoteRouteEstimateService
from app.modules.system.runtime_config import RuntimeConfigService


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _ratio(value: float, total: float) -> float | None:
    if not total:
        return None
    return round(value / total, 4)


def _confidence_from_rate(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 0.85:
        return "HIGH"
    if value >= 0.65:
        return "MEDIUM"
    if value > 0:
        return "LOW"
    return "UNKNOWN"


def _freshness_level_from_rate(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 0.75:
        return "FRESH"
    if value >= 0.45:
        return "RECENT"
    if value > 0:
        return "STALE"
    return "UNKNOWN"


def _pair_ais_freshness(left: tuple[float, str] | None, right: tuple[float, str] | None) -> tuple[float | None, str | None]:
    rates = [item[0] for item in (left, right) if item is not None]
    if not rates:
        return None, "UNKNOWN"
    rate = round(sum(rates) / len(rates), 4)
    return rate, _freshness_level_from_rate(rate)


def _metric(code: str, title: str, value: Any, unit: str | None = None, description: str | None = None) -> MetricCard:
    numeric = _num(value)
    if numeric.is_integer():
        display_value: int | float = int(numeric)
    else:
        display_value = round(numeric, 2)
    return MetricCard(code=code, title=title, value=display_value, unit=unit, description=description)


def _reasons(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _evidence(
    code: str,
    value: Any,
    *,
    unit: str | None,
    start: date,
    end: date,
    row: Any | None = None,
    last_successful_run_at: datetime | None = None,
    extra: dict | None = None,
) -> MetricEvidence:
    numeric_value: float | int | None
    if value is None:
        numeric_value = None
    else:
        numeric = _num(value)
        numeric_value = int(numeric) if numeric.is_integer() else round(numeric, 4)
    return MetricEvidence(
        metric_code=code,
        value=numeric_value,
        unit=unit,
        date_from=start,
        date_to=end,
        source_layer_code=getattr(row, "source_layer_code", None) if row is not None else None,
        sample_count=getattr(row, "sample_count", None) if row is not None else None,
        coverage_rate=round(_num(getattr(row, "coverage_rate", None)), 2) if row is not None and getattr(row, "coverage_rate", None) is not None else None,
        confidence_level=getattr(row, "confidence_level", None) if row is not None else None,
        not_computable_reasons=_reasons(getattr(row, "not_computable_reasons_json", None)) if row is not None else [],
        uncertainty_reasons=_reasons(getattr(row, "uncertainty_reasons_json", None)) if row is not None else [],
        generated_at=getattr(row, "generated_at", None) if row is not None else None,
        source_updated_at=getattr(row, "source_updated_at", None) if row is not None else None,
        last_successful_run_at=last_successful_run_at,
        extra=extra,
    )


def _flow_conditions(model: Any, start: date, end: date, query: FlowAnalysisQuery | None, *, include_commodity: bool = False) -> list[Any]:
    conditions = [model.stat_date >= start, model.stat_date <= end]
    if not query:
        return conditions
    for field in ("origin_node_id", "destination_node_id", "origin_region_id", "destination_region_id"):
        value = getattr(query, field)
        if value is not None:
            conditions.append(getattr(model, field) == value)
    if include_commodity and query.commodity_standard_id is not None:
        conditions.append(model.commodity_standard_id == query.commodity_standard_id)
    return conditions


class AnalysisDashboardService(FlowRouteGeometryMixin, AnalysisJobViewMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runtime_config = RuntimeConfigService(db)

    async def _date_range(self, date_from: date | None, date_to: date | None) -> tuple[date, date]:
        latest = await self.db.scalar(select(func.max(FactFreightDaily.stat_date)))
        latest = latest or await self.db.scalar(select(func.max(FactShipDaily.stat_date)))
        end = date_to or latest or date.today()
        start = date_from or (end - timedelta(days=89))
        return start, end

    async def _dict_labels(self, dict_codes: list[str]) -> dict[str, dict[str, str]]:
        rows = (
            await self.db.execute(
                select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
                .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
                .where(StdDict.dict_code.in_(dict_codes), StdDictItem.status == 1)
            )
        ).all()
        labels: dict[str, dict[str, str]] = {code: {} for code in dict_codes}
        for dict_code, item_code, item_name in rows:
            labels.setdefault(dict_code, {})[item_code] = item_name
        return labels

    async def _ship_city_ais_metrics(self) -> dict[str, tuple[float, str]]:
        fresh_expr = case(
            (VesselProfileSummary.ais_freshness_level.in_(["FRESH", "RECENT"]), 1),
            else_=0,
        )
        rows = (
            await self.db.execute(
                select(
                    VesselProfileSummary.latest_city_code,
                    func.count(VesselProfileSummary.id),
                    func.sum(fresh_expr),
                )
                .where(VesselProfileSummary.latest_city_code.is_not(None))
                .group_by(VesselProfileSummary.latest_city_code)
            )
        ).all()
        metrics: dict[str, tuple[float, str]] = {}
        for city_code, total, fresh in rows:
            count = int(_num(total))
            rate = round(_num(fresh) / count, 4) if count else 0.0
            metrics[str(city_code)] = (rate, _freshness_level_from_rate(rate))
        return metrics

    async def _ship_city_capacity_metrics(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(VesselProfileSummary.latest_city_code, func.count(VesselProfileSummary.id))
                .where(VesselProfileSummary.latest_city_code.is_not(None))
                .group_by(VesselProfileSummary.latest_city_code)
            )
        ).all()
        return {str(city_code): int(_num(count)) for city_code, count in rows}

    @staticmethod
    def _workbench_meta(
        start: date,
        end: date,
        *,
        source_tables: list[str],
        sample_count: int,
        actions: list[AnalysisActionBlock],
        data_versions: list[str] | None = None,
        not_computable_reasons: list[str] | None = None,
        uncertainty_reasons: list[str] | None = None,
        filters: dict | None = None,
    ) -> dict[str, Any]:
        confidence = "HIGH" if sample_count > 0 and not not_computable_reasons else "UNKNOWN"
        coverage_rate = 100.0 if sample_count > 0 and not not_computable_reasons else 0.0
        return {
            "context": AnalysisContextBlock(date_from=start, date_to=end, filters=filters or {}),
            "lineage": AnalysisLineageBlock(
                source_tables=source_tables,
                data_versions=data_versions or ["FORMAL_ANALYSIS_V1"],
                sample_count=int(sample_count),
                generated_at=datetime.now(UTC).replace(tzinfo=None),
            ),
            "quality": AnalysisQualityBlock(
                coverage_rate=coverage_rate,
                confidence_level=confidence,
                not_computable_reasons=not_computable_reasons or ([] if sample_count > 0 else ["SOURCE_MISSING"]),
                uncertainty_reasons=uncertainty_reasons or [],
            ),
            "actions": actions,
        }

    async def get_overview(self, date_from: date | None, date_to: date | None) -> AnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        freight = await self._freight_totals(start, end)
        ship = await self._ship_totals(start, end)
        region_count = await self.db.scalar(
            select(func.count(func.distinct(FactRegionDaily.region_id))).where(
                FactRegionDaily.stat_date >= start,
                FactRegionDaily.stat_date <= end,
                FactRegionDaily.region_id.is_not(None),
            )
        )
        jobs = await self.list_jobs(None, None, start, end, 1, 5)
        return AnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_daily", "fact_ship_daily", "fact_region_daily"],
                sample_count=int(freight["freight_count"] + ship["ship_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_INSIGHT", title="查看货源洞察", target_route="/analysis/freight"),
                    AnalysisActionBlock(action_code="OPEN_CAPACITY_CENTER", title="查看运力中心", target_route="/analysis/ships"),
                ],
            ),
            metrics=[
                _metric("freight_count", "货源量", freight["freight_count"], "条"),
                _metric("freight_tonnage", "货源吨位", freight["total_tonnage"], "吨"),
                _metric("active_ship_count", "活跃船舶", ship["active_ship_count"], "艘"),
                _metric("region_count", "覆盖区域", region_count or 0, "个"),
            ],
            recent_jobs=jobs.items,
        )

    async def _freight_totals(self, start: date, end: date) -> dict[str, float]:
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(FactFreightDaily.freight_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.confirmed_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.candidate_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.source_inbound_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.total_tonnage), 0),
                    func.coalesce(func.sum(FactFreightDaily.total_estimated_amount), 0),
                    func.avg(FactFreightDaily.avg_unit_price),
                ).where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
            )
        ).one()
        return {
            "freight_count": _num(row[0]),
            "confirmed_count": _num(row[1]),
            "candidate_count": _num(row[2]),
            "source_inbound_count": _num(row[3]),
            "total_tonnage": _num(row[4]),
            "total_amount": _num(row[5]),
            "avg_unit_price": _num(row[6]),
        }

    async def _ship_totals(self, start: date, end: date) -> dict[str, float]:
        latest_date = await self.db.scalar(
            select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end)
        )
        if latest_date is None:
            return {"ship_count": 0, "active_ship_count": 0, "total_deadweight_ton": 0}
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(FactShipDaily.ship_count), 0),
                    func.coalesce(func.sum(FactShipDaily.active_ship_count), 0),
                    func.coalesce(func.sum(FactShipDaily.total_deadweight_ton), 0),
                ).where(FactShipDaily.stat_date == latest_date)
            )
        ).one()
        return {"ship_count": _num(row[0]), "active_ship_count": _num(row[1]), "total_deadweight_ton": _num(row[2])}

    async def freight_overview(self, date_from: date | None, date_to: date | None) -> FreightAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        totals = await self._freight_totals(start, end)
        raw_quality = await self._freight_raw_quality()
        trend = await self.freight_trend(start, end)
        node_ranking = await self.freight_node_ranking(start, end, 12)
        commodity_structure = await self.freight_commodity_structure(start, end)
        price_distribution = await self.freight_price_distribution(start, end)
        hot_routes = await self.freight_hot_routes(start, end, 8)
        return FreightAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["freight", "freight_candidate", "fact_freight_daily", "fact_freight_flow_daily"],
                sample_count=int(totals["freight_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_LIST", title="查看机会样本库", target_route="/freight/list"),
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_QUALITY", title="处理货源清洗", target_route="/freight/normalization"),
                ],
                uncertainty_reasons=["分页列表指标不得替代本接口聚合结果"],
            ),
            metrics=[
                _metric("freight_count", "货源量", totals["freight_count"], "条"),
                _metric("confirmed_count", "确认货源", totals["confirmed_count"], "条"),
                _metric("total_tonnage", "总吨位", totals["total_tonnage"], "吨"),
                _metric("avg_unit_price", "平均运价", totals["avg_unit_price"], "元/吨"),
                _metric("raw_level_count", "待清洗货源", raw_quality["raw_level_count"], "条", "原文级装卸地或货品仍需清洗提升"),
            ],
            insights=build_freight_insights(
                totals=totals,
                raw_quality=raw_quality,
                trend=trend,
                node_ranking=node_ranking,
                commodity_structure=commodity_structure,
                price_distribution=price_distribution,
                hot_routes=hot_routes,
                start=start,
                end=end,
            ),
            trend=trend,
            node_ranking=node_ranking,
            commodity_structure=commodity_structure,
            price_distribution=price_distribution,
            hot_routes=hot_routes,
        )

    async def _freight_raw_quality(self) -> dict[str, int]:
        raw_level_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(
                        Freight.origin_match_level_code == "RAW",
                        Freight.destination_match_level_code == "RAW",
                        Freight.commodity_match_level_code == "RAW",
                        Freight.origin_city_code.is_(None),
                        Freight.destination_city_code.is_(None),
                        Freight.commodity_standard_id.is_(None),
                    ),
                )
            )
            or 0
        )
        return {"raw_level_count": raw_level_count}

    async def freight_trend(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(FactFreightDaily)
                .where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
                .order_by(FactFreightDaily.stat_date.asc())
            )
        ).scalars().all()
        return [
            ChartPoint(
                name=row.stat_date.strftime("%m-%d"),
                date=row.stat_date,
                value=row.freight_count,
                extra={"tonnage": _num(row.total_tonnage), "avg_unit_price": _num(row.avg_unit_price)},
            )
            for row in rows
        ]

    async def freight_commodity_structure(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(
                    CommodityStandard.name,
                    func.sum(FactFreightCommodityDaily.freight_count),
                    func.sum(FactFreightCommodityDaily.total_tonnage),
                )
                .join(CommodityStandard, CommodityStandard.id == FactFreightCommodityDaily.commodity_standard_id)
                .where(FactFreightCommodityDaily.stat_date >= start, FactFreightCommodityDaily.stat_date <= end)
                .group_by(CommodityStandard.name)
                .order_by(func.sum(FactFreightCommodityDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total), extra={"tonnage": _num(row[2])})
            for row in rows
        ]

    async def freight_node_ranking(self, start: date, end: date, limit: int = 12) -> list[HeatMapItem]:
        rows = (
            await self.db.execute(
                select(
                    FactFreightNodeDaily.node_id,
                    FactFreightNodeDaily.node_name,
                    TransportNode.longitude,
                    TransportNode.latitude,
                    FactFreightNodeDaily.city_code,
                    FactFreightNodeDaily.primary_region_id,
                    func.sum(FactFreightNodeDaily.heat_value),
                    func.sum(FactFreightNodeDaily.freight_count),
                    func.sum(FactFreightNodeDaily.inbound_count),
                    func.sum(FactFreightNodeDaily.outbound_count),
                    func.sum(FactFreightNodeDaily.total_tonnage),
                )
                .join(TransportNode, TransportNode.id == FactFreightNodeDaily.node_id)
                .where(FactFreightNodeDaily.stat_date >= start, FactFreightNodeDaily.stat_date <= end)
                .group_by(
                    FactFreightNodeDaily.node_id,
                    FactFreightNodeDaily.node_name,
                    TransportNode.longitude,
                    TransportNode.latitude,
                    FactFreightNodeDaily.city_code,
                    FactFreightNodeDaily.primary_region_id,
                )
                .order_by(func.sum(FactFreightNodeDaily.heat_value).desc())
                .limit(limit)
            )
        ).all()
        values = [_num(row[6]) for row in rows]
        high = max(values) if values else 0
        return [
            HeatMapItem(
                id=row[0],
                node_id=row[0],
                region_id=row[5],
                name=row[1] or str(row[0]),
                longitude=_num(row[2]) if row[2] is not None else None,
                latitude=_num(row[3]) if row[3] is not None else None,
                value=round(_num(row[6]), 2),
                level="HIGH" if high and _num(row[6]) >= high * 0.66 else "MEDIUM" if high and _num(row[6]) >= high * 0.33 else "LOW",
                freight_count=int(_num(row[7])),
                inbound_count=int(_num(row[8])),
                outbound_count=int(_num(row[9])),
                tonnage=round(_num(row[10]), 2),
            )
            for row in rows
        ]

    async def freight_tonnage_distribution(self, start: date, end: date) -> list[ChartPoint]:
        buckets = [
            ("600吨以下", 0, 600),
            ("600-1500吨", 600, 1500),
            ("1500-3000吨", 1500, 3000),
            ("3000-6000吨", 3000, 6000),
            ("6000吨以上", 6000, None),
        ]
        rows = (
            await self.db.execute(
                select(FactFreightFlowDaily.total_tonnage, FactFreightFlowDaily.freight_count)
                .where(FactFreightFlowDaily.stat_date >= start, FactFreightFlowDaily.stat_date <= end)
            )
        ).all()
        counts = {name: 0 for name, _, _ in buckets}
        for tonnage, count in rows:
            value = _num(tonnage)
            for name, low, high in buckets:
                if value >= low and (high is None or value < high):
                    counts[name] += int(count or 0)
                    break
        total = sum(counts.values())
        return [ChartPoint(name=name, value=value, ratio=_ratio(value, total)) for name, value in counts.items()]

    async def freight_price_distribution(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(
                    FactFreightPriceDaily.price_bucket_name,
                    func.sum(FactFreightPriceDaily.freight_count),
                    func.avg(FactFreightPriceDaily.avg_unit_price),
                )
                .where(FactFreightPriceDaily.stat_date >= start, FactFreightPriceDaily.stat_date <= end)
                .group_by(FactFreightPriceDaily.price_bucket_code, FactFreightPriceDaily.price_bucket_name)
                .order_by(func.min(FactFreightPriceDaily.min_unit_price).asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total), extra={"avg_unit_price": _num(row[2])})
            for row in rows
        ]

    async def freight_hot_routes(
        self,
        start: date,
        end: date,
        limit: int = 10,
        *,
        route_geometry_mode: str = "cache",
        force_refresh_routes: bool = False,
        query: FlowAnalysisQuery | None = None,
    ) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
        origin_city = aliased(AdminRegion)
        destination_city = aliased(AdminRegion)
        city_capacity = await self._ship_city_capacity_metrics()
        conditions = _flow_conditions(FactFreightFlowDaily, start, end, query, include_commodity=True)
        rows = (
            await self.db.execute(
                select(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    origin_city.name,
                    destination_city.name,
                    FactFreightFlowDaily.origin_city_code,
                    FactFreightFlowDaily.destination_city_code,
                    CommodityStandard.name,
                    func.sum(FactFreightFlowDaily.freight_count),
                    func.sum(FactFreightFlowDaily.total_tonnage),
                    func.avg(FactFreightFlowDaily.avg_unit_price),
                )
                .outerjoin(origin, origin.id == FactFreightFlowDaily.origin_node_id)
                .outerjoin(destination, destination.id == FactFreightFlowDaily.destination_node_id)
                .outerjoin(origin_city, origin_city.code == FactFreightFlowDaily.origin_city_code)
                .outerjoin(destination_city, destination_city.code == FactFreightFlowDaily.destination_city_code)
                .outerjoin(CommodityStandard, CommodityStandard.id == FactFreightFlowDaily.commodity_standard_id)
                .where(*conditions)
                .group_by(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    origin_city.name,
                    destination_city.name,
                    FactFreightFlowDaily.origin_city_code,
                    FactFreightFlowDaily.destination_city_code,
                    CommodityStandard.name,
                )
                .order_by(func.sum(FactFreightFlowDaily.freight_count).desc())
                .limit(limit)
            )
        ).all()
        items = []
        for row in rows:
            nearby_capacity = round((city_capacity.get(str(row[10]), 0) + city_capacity.get(str(row[11]), 0)) / 2)
            items.append(
                FlowMapItem(
                origin_id=row[0],
                origin_name=row[1] or row[8] or row[10] or "未知起点",
                origin_city_code=row[10],
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5] or row[9] or row[11] or "未知终点",
                destination_city_code=row[11],
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                commodity_name=row[12],
                value=int(_num(row[13])),
                freight_count=int(_num(row[13])),
                tonnage=round(_num(row[14]), 2),
                avg_unit_price=round(_num(row[15]), 2),
                active_ship_count=nearby_capacity,
                confidence_level=_confidence_from_rate(min(1.0, nearby_capacity / max(1, _num(row[13])))),
            )
            )
        if route_geometry_mode == "none":
            return items
        return await self._attach_flow_route_geometries(
            items,
            segment_type="ANALYSIS_FREIGHT_FLOW_MAP",
            generate_missing=route_geometry_mode == "generate",
            force_refresh=force_refresh_routes,
        )

    async def ship_overview(self, date_from: date | None, date_to: date | None) -> ShipAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        totals = await self._ship_totals(start, end)
        active_city_count = await self.db.scalar(
            select(func.count(func.distinct(FactShipCityDaily.city_code))).where(
                FactShipCityDaily.stat_date >= start,
                FactShipCityDaily.stat_date <= end,
                FactShipCityDaily.active_ship_count > 0,
            )
        )
        return ShipAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["vessel_profile", "fact_ship_daily", "fact_ship_city_daily"],
                sample_count=int(totals["ship_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_CAPACITY_POOL", title="查看船舶台账", target_route="/vessels/assets"),
                    AnalysisActionBlock(action_code="OPEN_CANDIDATE_FIT", title="查看船货适配", target_route="/vessels/candidate-analysis"),
                ],
            ),
            metrics=[
                _metric("ship_count", "船舶总量", totals["ship_count"], "艘"),
                _metric("active_ship_count", "活跃船舶", totals["active_ship_count"], "艘"),
                _metric("deadweight", "总载重吨", totals["total_deadweight_ton"], "吨"),
                _metric("active_city_count", "活跃城市", active_city_count or 0, "个"),
            ],
            type_distribution=await self.ship_type_distribution(start, end),
            age_distribution=await self.ship_age_distribution(start, end),
            deadweight_distribution=await self.ship_deadweight_distribution(start, end),
            active_trend=await self.ship_active_trend(start, end),
        )

    async def ship_type_distribution(self, start: date, end: date) -> list[ChartPoint]:
        labels = await self._dict_labels(["SHIP_TYPE"])
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.ship_type_code, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest)
                .group_by(FactShipDaily.ship_type_code)
                .order_by(func.sum(FactShipDaily.ship_count).desc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=labels.get("SHIP_TYPE", {}).get(row[0] or "", row[0] or "未知船型"), value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total))
            for row in rows
        ]

    async def ship_age_distribution(self, start: date, end: date) -> list[ChartPoint]:
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.age_bucket_name, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest, FactShipDaily.age_bucket_name.is_not(None))
                .group_by(FactShipDaily.age_bucket_code, FactShipDaily.age_bucket_name)
                .order_by(FactShipDaily.age_bucket_code.asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [ChartPoint(name=row[0] or "未知船龄", value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total)) for row in rows]

    async def ship_deadweight_distribution(self, start: date, end: date) -> list[ChartPoint]:
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.deadweight_bucket_name, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest, FactShipDaily.deadweight_bucket_name.is_not(None))
                .group_by(FactShipDaily.deadweight_bucket_code, FactShipDaily.deadweight_bucket_name)
                .order_by(FactShipDaily.deadweight_bucket_code.asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [ChartPoint(name=row[0] or "未知载重", value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total)) for row in rows]

    async def ship_active_trend(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(FactShipDaily.stat_date, func.sum(FactShipDaily.active_ship_count))
                .where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end)
                .group_by(FactShipDaily.stat_date)
                .order_by(FactShipDaily.stat_date.asc())
            )
        ).all()
        return [ChartPoint(name=row[0].strftime("%m-%d"), date=row[0], value=int(_num(row[1]))) for row in rows]

    async def ship_flow_map(
        self,
        start: date,
        end: date,
        limit: int = 30,
        *,
        route_geometry_mode: str = "cache",
        force_refresh_routes: bool = False,
        query: FlowAnalysisQuery | None = None,
    ) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
        conditions = _flow_conditions(FactShipFlowDaily, start, end, query)
        city_ais_metrics = await self._ship_city_ais_metrics()
        rows = (
            await self.db.execute(
                select(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    FactShipFlowDaily.origin_city_code,
                    FactShipFlowDaily.destination_city_code,
                    func.sum(FactShipFlowDaily.ship_count),
                    func.sum(FactShipFlowDaily.voyage_count),
                    func.sum(FactShipFlowDaily.total_deadweight_ton),
                    func.avg(FactShipFlowDaily.coverage_rate),
                    func.max(FactShipFlowDaily.confidence_level),
                )
                .join(origin, origin.id == FactShipFlowDaily.origin_node_id)
                .join(destination, destination.id == FactShipFlowDaily.destination_node_id)
                .where(*conditions)
                .group_by(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    FactShipFlowDaily.origin_city_code,
                    FactShipFlowDaily.destination_city_code,
                )
                .order_by(func.sum(FactShipFlowDaily.voyage_count).desc())
                .limit(limit)
            )
        ).all()
        items = []
        for row in rows:
            ship_count = int(_num(row[10]))
            voyage_count = int(_num(row[11]))
            total_deadweight = _num(row[12])
            ais_rate, ais_level = _pair_ais_freshness(
                city_ais_metrics.get(row[8]),
                city_ais_metrics.get(row[9]),
            )
            coverage_rate = _num(row[13]) if row[13] is not None else None
            confidence = row[14] or _confidence_from_rate(coverage_rate or ais_rate)
            items.append(
                FlowMapItem(
                origin_id=row[0],
                origin_name=row[1],
                origin_city_code=row[8],
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5],
                destination_city_code=row[9],
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                value=voyage_count,
                ship_count=ship_count,
                active_ship_count=ship_count,
                voyage_count=voyage_count,
                tonnage=round(total_deadweight, 2),
                avg_deadweight_ton=round(total_deadweight / ship_count, 2) if ship_count else None,
                ais_freshness_rate=ais_rate,
                ais_freshness_level=ais_level,
                confidence_level=confidence,
            )
            )
        if query:
            if query.deadweight_min is not None:
                items = [item for item in items if (item.avg_deadweight_ton or 0) >= query.deadweight_min]
            if query.deadweight_max is not None:
                items = [item for item in items if (item.avg_deadweight_ton or 0) <= query.deadweight_max]
            if query.ais_freshness_level:
                target_level = query.ais_freshness_level.upper()
                items = [item for item in items if str(item.ais_freshness_level or "").upper() == target_level]
        if route_geometry_mode == "none":
            return items
        return await self._attach_flow_route_geometries(
            items,
            segment_type="ANALYSIS_SHIP_FLOW_MAP",
            generate_missing=route_geometry_mode == "generate",
            force_refresh=force_refresh_routes,
        )

    async def region_overview(
        self,
        date_from: date | None,
        date_to: date | None,
        *,
        include_boundary: bool = False,
        boundary_precision: str = "low",
    ) -> RegionAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(Region.name, func.sum(FactRegionDaily.freight_count), func.sum(FactRegionDaily.total_tonnage))
                .join(Region, Region.id == FactRegionDaily.region_id)
                .where(FactRegionDaily.stat_date >= start, FactRegionDaily.stat_date <= end)
                .group_by(Region.name)
                .order_by(func.sum(FactRegionDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        total_freight = sum(_num(row[1]) for row in rows)
        heat = await self.region_heat_map(
            start,
            end,
            include_boundary=include_boundary,
            boundary_precision=boundary_precision,
        )
        return RegionAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["region", "fact_region_daily", "admin_region_boundary"],
                sample_count=int(total_freight),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FLOW_ANALYSIS", title="查看区域流向", target_route="/analysis/flows"),
                    AnalysisActionBlock(action_code="OPEN_ROUTE_LIST", title="查看航线列表", target_route="/route/list"),
                ],
            ),
            metrics=[
                _metric("region_count", "活跃区域", len(rows), "个"),
                _metric("freight_count", "区域货源", total_freight, "条"),
                _metric("heat_city_count", "热力城市", len(heat), "个"),
            ],
            region_ranking=[
                ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total_freight), extra={"tonnage": _num(row[2])})
                for row in rows
            ],
            heat_map=heat,
        )

    async def region_heat_map(
        self,
        start: date,
        end: date,
        *,
        include_boundary: bool = False,
        boundary_precision: str = "low",
    ) -> list[BoundaryHeatMapItem]:
        rows = (
            await self.db.execute(
                select(
                    AdminRegion.id,
                    FactFreightCityDaily.city_code,
                    func.max(FactFreightCityDaily.city_name),
                    AdminRegion.name,
                    AdminRegion.longitude,
                    AdminRegion.latitude,
                    func.max(FactFreightCityDaily.primary_region_id),
                    AdminRegionBoundary.id,
                    AdminRegionBoundary.center_longitude,
                    AdminRegionBoundary.center_latitude,
                    func.sum(FactFreightCityDaily.heat_value),
                    func.sum(FactFreightCityDaily.freight_count),
                    func.sum(FactFreightCityDaily.inbound_count),
                    func.sum(FactFreightCityDaily.outbound_count),
                    func.sum(FactFreightCityDaily.total_tonnage),
                    func.avg(FactFreightCityDaily.avg_unit_price),
                )
                .outerjoin(AdminRegion, AdminRegion.code == FactFreightCityDaily.city_code)
                .outerjoin(
                    AdminRegionBoundary,
                    (AdminRegionBoundary.admin_region_id == AdminRegion.id) & (AdminRegionBoundary.is_current.is_(True)),
                )
                .where(FactFreightCityDaily.stat_date >= start, FactFreightCityDaily.stat_date <= end)
                .group_by(
                    FactFreightCityDaily.city_code,
                    AdminRegion.id,
                    AdminRegion.name,
                    AdminRegion.longitude,
                    AdminRegion.latitude,
                    AdminRegionBoundary.id,
                    AdminRegionBoundary.center_longitude,
                    AdminRegionBoundary.center_latitude,
                )
                .order_by(func.sum(FactFreightCityDaily.heat_value).desc())
            )
        ).all()
        boundary_geometry_by_admin_id: dict[int, dict] = {}
        if include_boundary:
            admin_region_ids = [int(row[0]) for row in rows if row[0] is not None and row[7] is not None]
            if admin_region_ids:
                boundary_rows = (
                    await self.db.execute(
                        select(AdminRegionBoundary.admin_region_id, AdminRegionBoundary.geometry_json)
                        .where(
                            AdminRegionBoundary.admin_region_id.in_(admin_region_ids),
                            AdminRegionBoundary.is_current.is_(True),
                        )
                    )
                ).all()
                boundary_geometry_by_admin_id = {int(row[0]): row[1] for row in boundary_rows if row[1]}

        values = [_num(row[10]) for row in rows]
        high = max(values) if values else 0
        items: list[BoundaryHeatMapItem] = []
        for row in rows:
            boundary_paths = None
            if include_boundary and row[0] is not None:
                polygons = extract_geojson_polygons(boundary_geometry_by_admin_id.get(int(row[0])) or {})
                boundary_paths = serialize_boundary_paths(boundary_paths_for_precision(polygons, boundary_precision))

            center_longitude = row[8] if row[8] is not None else row[4]
            center_latitude = row[9] if row[9] is not None else row[5]
            value = _num(row[10])
            items.append(
                BoundaryHeatMapItem(
                    id=row[0],
                    city_code=row[1],
                    region_id=row[6],
                    name=row[3] or row[2] or row[1] or "未知城市",
                    value=round(value, 2),
                    level="HIGH"
                    if high and value >= high * 0.66
                    else "MEDIUM"
                    if high and value >= high * 0.33
                    else "LOW",
                    boundary_paths=boundary_paths,
                    has_boundary=bool(boundary_paths) if include_boundary else bool(row[7]),
                    boundary_precision=boundary_precision if boundary_paths else None,
                    center_longitude=_num(center_longitude) if center_longitude is not None else None,
                    center_latitude=_num(center_latitude) if center_latitude is not None else None,
                    freight_count=int(_num(row[11])),
                    inbound_count=int(_num(row[12])),
                    outbound_count=int(_num(row[13])),
                    tonnage=round(_num(row[14]), 2),
                    avg_unit_price=round(_num(row[15]), 2) if row[15] is not None else None,
                )
            )
        return items

    def _flow_query_filters(self, query: FlowAnalysisQuery) -> dict[str, Any]:
        return {key: value for key, value in query.model_dump().items() if value not in (None, "", "all")}

    async def flow_overview(self, query: FlowAnalysisQuery) -> FlowAnalysisOverviewResponse:
        start, end = await self._date_range(query.date_from, query.date_to)
        include_freight = query.subject in {"all", "freight"}
        include_ship = query.subject in {"all", "ship"}
        freight_flows = await self.freight_hot_routes(start, end, 20, query=query) if include_freight else []
        ship_flows = await self.ship_flow_map(start, end, 20, query=query) if include_ship else []
        companion_freight_flows = freight_flows
        companion_ship_flows = ship_flows
        if include_freight and not include_ship:
            companion_ship_flows = await self.ship_flow_map(start, end, 20, route_geometry_mode="none")
        if include_ship and not include_freight:
            companion_freight_flows = await self.freight_hot_routes(start, end, 20, route_geometry_mode="none")
        enrich_flow_relationships(companion_freight_flows, companion_ship_flows)

        freight_count = sum(item.freight_count or 0 for item in freight_flows)
        freight_tonnage = sum(item.tonnage or 0 for item in freight_flows)
        freight_matched_capacity = sum(item.active_ship_count or 0 for item in freight_flows)
        freight_issue_count = sum(1 for item in freight_flows if item.risk_level_code in {"MEDIUM", "HIGH"})
        ship_active_count = sum(item.active_ship_count or item.ship_count or 0 for item in ship_flows)
        ship_voyage_count = sum(item.voyage_count or 0 for item in ship_flows)
        avg_ais_freshness = (
            sum((item.ais_freshness_rate or 0) * (item.active_ship_count or item.ship_count or 0) for item in ship_flows)
            / max(1, ship_active_count)
        )
        return_opportunity_count = sum(item.return_opportunity_count or 0 for item in ship_flows)

        return FlowAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_flow_daily", "fact_ship_flow_daily", "shipping_route_plan_track_version_segment"],
                sample_count=len(freight_flows) + len(ship_flows),
                actions=[
                    AnalysisActionBlock(action_code="PRECOMPUTE_FLOW_ROUTES", title="生成 AMMS 流向轨迹", target_route="/analysis/flows"),
                    AnalysisActionBlock(action_code="OPEN_ROUTE_LIST", title="查看航线规划", target_route="/route/list"),
                ],
                uncertainty_reasons=["流向地图只使用 READY 轨迹绘制，失败或待生成状态需查看 route_not_computable_reasons"],
                filters=self._flow_query_filters(query),
            ),
            metrics=[
                _metric("freight_flow_count", "货源流向", len(freight_flows), "条"),
                _metric("ship_flow_count", "船舶流向", len(ship_flows), "条"),
                _metric("top_freight_route", "最热货源流向", freight_flows[0].freight_count if freight_flows else 0, "条"),
                _metric("top_ship_route", "最热船舶流向", ship_flows[0].voyage_count if ship_flows else 0, "航次"),
            ],
            freight_flows=freight_flows,
            ship_flows=ship_flows,
            freight_summary=[
                _metric("freight_total_count", "总货源", freight_count, "条"),
                _metric("freight_total_tonnage", "发布货量", freight_tonnage, "吨"),
                _metric("matched_capacity", "匹配运力", freight_matched_capacity, "艘"),
                _metric("freight_issue_count", "需关注流向", freight_issue_count, "条"),
            ],
            freight_structure=freight_structure_links(freight_flows),
            freight_corridors=flow_corridor_items(freight_flows, subject="freight"),
            ship_summary=[
                _metric("active_ship_count", "活跃船舶", ship_active_count, "艘"),
                _metric("voyage_count", "识别航次", ship_voyage_count, "航次"),
                _metric("ais_freshness_rate", "AIS 新鲜率", round(avg_ais_freshness * 100, 2), "%"),
                _metric("return_opportunity_count", "返程机会", return_opportunity_count, "条"),
            ],
            ship_quality=ship_quality_points(ship_flows),
            ship_corridors=flow_corridor_items(ship_flows, subject="ship"),
            ship_flow_details=flow_corridor_items(ship_flows, subject="ship", limit=20),
        )

    async def price_overview(self, date_from: date | None, date_to: date | None) -> PriceAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        price_rows = (
            await self.db.execute(
                select(FactFreightDaily.stat_date, func.avg(FactFreightDaily.avg_unit_price))
                .where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
                .group_by(FactFreightDaily.stat_date)
                .order_by(FactFreightDaily.stat_date.asc())
            )
        ).all()
        commodity_rows = (
            await self.db.execute(
                select(CommodityStandard.name, func.avg(FactFreightCommodityDaily.avg_unit_price), func.sum(FactFreightCommodityDaily.freight_count))
                .join(CommodityStandard, CommodityStandard.id == FactFreightCommodityDaily.commodity_standard_id)
                .where(FactFreightCommodityDaily.stat_date >= start, FactFreightCommodityDaily.stat_date <= end)
                .group_by(CommodityStandard.name)
                .order_by(func.sum(FactFreightCommodityDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        route_prices = await self.freight_hot_routes(start, end, 10)
        latest_price = _num(price_rows[-1][1]) if price_rows else 0
        return PriceAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_daily", "fact_freight_price_daily", "fact_freight_commodity_daily"],
                sample_count=len(price_rows),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_QUOTE_SIMULATOR", title="进入智能报价测算", target_route="/analysis/quote-simulator"),
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_LIST", title="查看有价货源", target_route="/freight/list"),
                ],
            ),
            metrics=[
                _metric("avg_unit_price", "平均运价", latest_price, "元/吨"),
                _metric("priced_routes", "有价线路", len(route_prices), "条"),
                _metric("commodity_price_count", "覆盖货品", len(commodity_rows), "类"),
            ],
            price_trend=[
                ChartPoint(name=row[0].strftime("%m-%d"), date=row[0], value=round(_num(row[1]), 2))
                for row in price_rows
            ],
            price_distribution=await self.freight_price_distribution(start, end),
            commodity_prices=[
                ChartPoint(name=row[0], value=round(_num(row[1]), 2), extra={"freight_count": int(_num(row[2]))})
                for row in commodity_rows
            ],
            route_prices=route_prices,
        )

    async def _last_successful_run_at(self, job_code: str) -> datetime | None:
        row = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if row and row.last_status_code == "SUCCESS":
            return row.last_finished_at
        latest = await self.db.scalar(
            select(func.max(AnalysisJobRun.finished_at)).where(
                AnalysisJobRun.job_code == job_code,
                AnalysisJobRun.status_code == "SUCCESS",
            )
        )
        return latest

    def _source_status(self, rows: list[Any], start: date, end: date, last_successful_run_at: datetime | None) -> list[MetricEvidence]:
        if not rows:
            return [
                MetricEvidence(
                    metric_code="source_status",
                    value=None,
                    unit=None,
                    date_from=start,
                    date_to=end,
                    source_layer_code="NOT_AVAILABLE",
                    sample_count=0,
                    coverage_rate=0,
                    confidence_level="UNKNOWN",
                    not_computable_reasons=["SOURCE_MISSING"],
                    uncertainty_reasons=["分析事实未生成"],
                    last_successful_run_at=last_successful_run_at,
                )
            ]
        buckets: dict[tuple[str | None, str | None], dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "sample": 0, "coverage": [], "reasons": set(), "updated": None, "generated": None}
        )
        for row in rows:
            key = (getattr(row, "source_layer_code", None), getattr(row, "confidence_level", None))
            item = buckets[key]
            item["count"] += 1
            item["sample"] += int(getattr(row, "sample_count", None) or 0)
            coverage = getattr(row, "coverage_rate", None)
            if coverage is not None:
                item["coverage"].append(_num(coverage))
            item["reasons"].update(_reasons(getattr(row, "not_computable_reasons_json", None)))
            for field, attr in (("updated", "source_updated_at"), ("generated", "generated_at")):
                value = getattr(row, attr, None)
                if value and (item[field] is None or value > item[field]):
                    item[field] = value
        return [
            MetricEvidence(
                metric_code="source_status",
                value=item["count"],
                unit="条",
                date_from=start,
                date_to=end,
                source_layer_code=source_layer,
                sample_count=item["sample"],
                coverage_rate=round(sum(item["coverage"]) / len(item["coverage"]), 2) if item["coverage"] else None,
                confidence_level=confidence,
                not_computable_reasons=sorted(item["reasons"]),
                generated_at=item["generated"],
                source_updated_at=item["updated"],
                last_successful_run_at=last_successful_run_at,
            )
            for (source_layer, confidence), item in sorted(buckets.items(), key=lambda pair: str(pair[0]))
        ]

    async def vessel_asset_analysis(self, date_from: date | None, date_to: date | None) -> VesselAssetAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselAssetDaily)
                .where(FactVesselAssetDaily.stat_date >= start, FactVesselAssetDaily.stat_date <= end)
                .order_by(FactVesselAssetDaily.stat_date.asc())
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_ASSET_DAILY")
        latest_date = max((row.stat_date for row in rows), default=None)
        latest_rows = [row for row in rows if row.stat_date == latest_date] if latest_date else []
        quality_totals: dict[str, int] = defaultdict(int)
        risk_totals: dict[str, int] = defaultdict(int)
        for row in latest_rows:
            quality_totals[row.quality_level] += int(row.profile_count or 0)
            risk_totals[row.risk_level] += int(row.profile_count or 0)
        return VesselAssetAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("profile_count", sum(row.profile_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("trusted_profile_count", sum(row.trusted_profile_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("low_quality_count", sum(row.low_quality_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("active_sample_count", sum(row.active_sample_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            quality_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(quality_totals.items())],
            risk_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(risk_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_trajectory_analysis(self, date_from: date | None, date_to: date | None) -> VesselTrajectoryAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselTrajectoryDaily)
                .where(FactVesselTrajectoryDaily.stat_date >= start, FactVesselTrajectoryDaily.stat_date <= end)
                .order_by(FactVesselTrajectoryDaily.stat_date.asc())
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_TRAJECTORY_DAILY")
        by_date: dict[date, list[FactVesselTrajectoryDaily]] = defaultdict(list)
        gap_buckets: dict[str, int] = defaultdict(int)
        for row in rows:
            by_date[row.stat_date].append(row)
            gap_buckets["有断点" if int(row.gap_count or 0) > 0 else "无断点"] += 1
        coverage_trend = []
        for stat_date, day_rows in sorted(by_date.items()):
            coverages = [_num(row.coverage_rate) for row in day_rows if row.coverage_rate is not None]
            coverage_trend.append(ChartPoint(name=stat_date.strftime("%m-%d"), date=stat_date, value=round(sum(coverages) / len(coverages), 2) if coverages else 0))
        return VesselTrajectoryAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("route_match_count", sum(row.route_match_count or 0 for row in rows), unit="次", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("gap_count", sum(row.gap_count or 0 for row in rows), unit="个", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("not_computable_count", sum(1 for row in rows if row.not_computable_reasons_json), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            coverage_trend=coverage_trend,
            gap_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(gap_buckets.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_quality_analysis(self, date_from: date | None, date_to: date | None) -> VesselQualityAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselQualityDaily).where(FactVesselQualityDaily.stat_date >= start, FactVesselQualityDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_QUALITY_DAILY")
        issue_totals: dict[str, int] = defaultdict(int)
        severity_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            count = int(row.opened_count or 0) + int(row.closed_count or 0)
            issue_totals[row.issue_type_code] += count
            severity_totals[row.severity_code] += count
        return VesselQualityAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("opened_count", sum(row.opened_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("closed_count", sum(row.closed_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("avg_close_hours", sum(_num(row.avg_close_hours) for row in rows) / len(rows) if rows else None, unit="小时", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            issue_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(issue_totals.items())],
            severity_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(severity_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_risk_analysis(self, date_from: date | None, date_to: date | None) -> VesselRiskAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselRiskDaily).where(FactVesselRiskDaily.stat_date >= start, FactVesselRiskDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_RISK_DAILY")
        level_totals: dict[str, int] = defaultdict(int)
        type_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            level_totals[row.risk_level] += int(row.risk_count or 0)
            type_totals[row.risk_type_code] += int(row.risk_count or 0)
        return VesselRiskAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("risk_count", sum(row.risk_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("high_count", sum(row.high_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("unknown_count", sum(row.unknown_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            risk_level_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(level_totals.items())],
            risk_type_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(type_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_candidate_fit_analysis(self, date_from: date | None, date_to: date | None) -> VesselCandidateFitAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactCandidateFitDaily).where(FactCandidateFitDaily.stat_date >= start, FactCandidateFitDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_CANDIDATE_FIT_DAILY")
        value_totals: dict[str, int] = defaultdict(int)
        annotation_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            value_totals[row.candidate_value_level] += int(row.candidate_item_count or 0)
            for key, value in (row.annotation_distribution_json or {}).items():
                annotation_totals[str(key)] += int(value or 0)
        return VesselCandidateFitAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("analysis_count", sum(row.analysis_count or 0 for row in rows), unit="次", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("candidate_item_count", sum(row.candidate_item_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("low_confidence_count", sum(row.low_confidence_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("not_computable_count", sum(row.not_computable_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            value_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(value_totals.items())],
            annotation_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(annotation_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def region_supply_demand_analysis(self, date_from: date | None, date_to: date | None) -> RegionSupplyDemandAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactRegionSupplyDemandDaily).where(
                    FactRegionSupplyDemandDaily.stat_date >= start,
                    FactRegionSupplyDemandDaily.stat_date <= end,
                )
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_REGION_SUPPLY_DEMAND_DAILY")
        tension_distribution: dict[str, int] = defaultdict(int)
        not_computable_distribution: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.tension_index is None:
                tension_distribution["不可计算"] += 1
            elif _num(row.tension_index) >= 1.5:
                tension_distribution["高张力"] += 1
            elif _num(row.tension_index) >= 0.8:
                tension_distribution["中张力"] += 1
            else:
                tension_distribution["低张力"] += 1
            for reason in _reasons(row.not_computable_reasons_json):
                not_computable_distribution[reason] += 1
        return RegionSupplyDemandAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("demand_sample_count", sum(row.demand_sample_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("ais_supply_count", sum(row.ais_supply_count or 0 for row in rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("trusted_supply", sum(row.trusted_supply or 0 for row in rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("unmatched_mmsi_count", sum(row.unmatched_mmsi_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            tension_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(tension_distribution.items())],
            not_computable_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(not_computable_distribution.items())],
            source_status=self._source_status(rows, start, end, last),
        )
