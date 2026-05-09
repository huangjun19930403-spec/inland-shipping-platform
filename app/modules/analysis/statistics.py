"""分析统计聚合执行器。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import AdminRegion, RegionCityRelation, TransportNode
from app.models.analysis import (
    AnalysisBucketDefinition,
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
    FactVesselNodeDaily,
    FactVesselQualityDaily,
    FactVesselRiskDaily,
    FactVesselRouteSegmentDaily,
    FactVesselTrajectoryDaily,
)
from app.models.commodity import CommodityStandard, CommodityType
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightTmsInbound
from app.models.vessel import (
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselDataQualityIssue,
    VesselLatestPositionSnapshot,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselProfile,
    VesselProfileSummary,
    VesselRiskSignal,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselOperatorPeriod,
)
from app.modules.analysis.job_catalog import ANALYSIS_JOB_SPEC_BY_CODE


DATA_VERSION = "FORMAL_ANALYSIS_V1"
LOCAL_SAMPLE_VERSION = "LOCAL_SAMPLE"
VALID_FREIGHT_STATUSES = {"PUBLISHED", "MATCHING", "EXPIRED", "CLOSED"}
SUCCESS_STATUS = {"status_code": "SUCCESS", "status_name": "成功"}
ROUND9_VERSION = "ROUND_9_FACT_V1"


@dataclass
class AggregationResult:
    job_code: str
    input_rows: int = 0
    output_rows: int = 0
    affected_rows: int = 0
    target_tables: list[str] | None = None
    extra: dict[str, Any] | None = None

    def as_summary(self) -> dict[str, Any]:
        return {
            "job_code": self.job_code,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "affected_rows": self.affected_rows,
            "target_tables": self.target_tables or [],
            **(self.extra or {}),
        }


def _money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _date_of(*values: Any) -> date | None:
    for value in values:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
    return None


def _coverage_confidence(coverage: Any, *, default_unknown: bool = False) -> str:
    if coverage is None:
        return "UNKNOWN" if default_unknown else "LOW"
    value = Decimal(str(coverage))
    if value >= Decimal("80"):
        return "HIGH"
    if value >= Decimal("50"):
        return "MEDIUM"
    if value > 0:
        return "LOW"
    return "UNKNOWN" if default_unknown else "LOW"


def _avg(values: list[Any]) -> Decimal | None:
    numbers = [Decimal(str(value)) for value in values if value is not None]
    if not numbers:
        return None
    return (sum(numbers) / Decimal(len(numbers))).quantize(Decimal("0.01"))


def _dwt_bucket_code(deadweight: Decimal | None) -> str:
    return _dwt_bucket(deadweight)[0]


def _merge_reason_list(*values: Any) -> list[str]:
    reasons: list[str] = []
    for value in values:
        if isinstance(value, list):
            candidates = value
        elif value:
            candidates = [value]
        else:
            candidates = []
        for candidate in candidates:
            text = str(candidate)
            if text and text not in reasons:
                reasons.append(text)
    return reasons


def _dates(start: date, end: date) -> list[date]:
    days = max((end - start).days, 0)
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _age_bucket(building_year: int | None, stat_date: date) -> tuple[str, str]:
    if not building_year or building_year > stat_date.year:
        return "AGE_UNKNOWN", "未知船龄"
    age = stat_date.year - building_year
    if age <= 5:
        return "AGE_0_5", "0-5年"
    if age <= 10:
        return "AGE_6_10", "6-10年"
    if age <= 20:
        return "AGE_11_20", "11-20年"
    if age <= 30:
        return "AGE_21_30", "21-30年"
    return "AGE_GT_30", "30年以上"


def _dwt_bucket(deadweight: Decimal | None) -> tuple[str, str]:
    value = deadweight or Decimal("0")
    if value <= 0:
        return "DWT_UNKNOWN", "未知载重"
    if value < Decimal("1000"):
        return "DWT_LT_1000", "1000吨以下"
    if value < Decimal("3000"):
        return "DWT_1000_3000", "1000-3000吨"
    if value < Decimal("6000"):
        return "DWT_3000_6000", "3000-6000吨"
    if value < Decimal("10000"):
        return "DWT_6000_10000", "6000-10000吨"
    return "DWT_GT_10000", "10000吨以上"


class AnalysisStatisticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run(
        self,
        job_code: str,
        start: date,
        end: date,
        *,
        force_rebuild: bool = False,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if start > end:
            raise ValueError("date_from must be earlier than date_to")
        if job_code == "ANALYSIS_ALL_DAILY":
            return await self._run_all(start, end, force_rebuild=force_rebuild, job_run_id=job_run_id)
        handlers = {
            "ANALYSIS_FREIGHT_DAILY": self.run_freight_daily,
            "ANALYSIS_FREIGHT_FLOW_DAILY": self.run_freight_flow_daily,
            "ANALYSIS_FREIGHT_COMMODITY_DAILY": self.run_freight_commodity_daily,
            "ANALYSIS_FREIGHT_PRICE_DAILY": self.run_freight_price_daily,
            "ANALYSIS_FREIGHT_CITY_DAILY": self.run_freight_city_daily,
            "ANALYSIS_FREIGHT_NODE_DAILY": self.run_freight_node_daily,
            "ANALYSIS_SHIP_DAILY": self.run_ship_daily,
            "ANALYSIS_SHIP_CITY_DAILY": self.run_ship_city_daily,
            "ANALYSIS_SHIP_FLOW_DAILY": self.run_ship_flow_daily,
            "ANALYSIS_REGION_DAILY": self.run_region_daily,
        }
        round9_handlers = {
            "ANALYSIS_VESSEL_ASSET_DAILY": self.run_vessel_asset_daily,
            "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY": self.run_vessel_ais_freshness_daily,
            "ANALYSIS_VESSEL_TRAJECTORY_DAILY": self.run_vessel_trajectory_daily,
            "ANALYSIS_VESSEL_NODE_DAILY": self.run_vessel_node_daily,
            "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY": self.run_vessel_route_segment_daily,
            "ANALYSIS_VESSEL_QUALITY_DAILY": self.run_vessel_quality_daily,
            "ANALYSIS_VESSEL_RISK_DAILY": self.run_vessel_risk_daily,
            "ANALYSIS_CANDIDATE_FIT_DAILY": self.run_candidate_fit_daily,
            "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY": self.run_region_supply_demand_daily,
        }
        if job_code in round9_handlers:
            return await round9_handlers[job_code](start, end, force_rebuild=force_rebuild, job_run_id=job_run_id)
        handler = handlers.get(job_code)
        if handler is None:
            raise ValueError(f"unsupported analysis job: {job_code}")
        return await handler(start, end, force_rebuild=force_rebuild)

    async def _run_all(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        ordered_codes = [
            "ANALYSIS_FREIGHT_DAILY",
            "ANALYSIS_FREIGHT_FLOW_DAILY",
            "ANALYSIS_FREIGHT_COMMODITY_DAILY",
            "ANALYSIS_FREIGHT_PRICE_DAILY",
            "ANALYSIS_FREIGHT_CITY_DAILY",
            "ANALYSIS_FREIGHT_NODE_DAILY",
            "ANALYSIS_SHIP_DAILY",
            "ANALYSIS_SHIP_CITY_DAILY",
            "ANALYSIS_SHIP_FLOW_DAILY",
            "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY",
            "ANALYSIS_VESSEL_ASSET_DAILY",
            "ANALYSIS_VESSEL_TRAJECTORY_DAILY",
            "ANALYSIS_VESSEL_NODE_DAILY",
            "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY",
            "ANALYSIS_VESSEL_QUALITY_DAILY",
            "ANALYSIS_VESSEL_RISK_DAILY",
            "ANALYSIS_CANDIDATE_FIT_DAILY",
            "ANALYSIS_REGION_DAILY",
            "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY",
        ]
        results: list[AggregationResult] = []
        failures: list[dict[str, str]] = []
        for code in ordered_codes:
            try:
                results.append(await self.run(code, start, end, force_rebuild=force_rebuild, job_run_id=job_run_id))
            except Exception as exc:  # pragma: no cover - defensive isolation for scheduled batches
                failures.append({"job_code": code, "error": str(exc)[:1000]})
        return AggregationResult(
            job_code="ANALYSIS_ALL_DAILY",
            input_rows=sum(item.input_rows for item in results),
            output_rows=sum(item.output_rows for item in results),
            affected_rows=sum(item.affected_rows for item in results),
            target_tables=sorted({table for item in results for table in (item.target_tables or [])}),
            extra={"children": [item.as_summary() for item in results], "failures": failures},
        )

    async def _clear(self, model, start: date, end: date) -> None:
        await self.db.execute(delete(model).where(model.stat_date >= start, model.stat_date <= end))

    async def _prepare_round9_fact_window(self, model, start: date, end: date, *, force_rebuild: bool) -> bool:
        if force_rebuild:
            await self._clear(model, start, end)
            return True
        existing = await self.db.scalar(
            select(func.count()).select_from(model).where(model.stat_date >= start, model.stat_date <= end)
        )
        return int(existing or 0) == 0

    def _skipped_round9_result(self, job_code: str, table_name: str) -> AggregationResult:
        return AggregationResult(
            job_code,
            0,
            0,
            0,
            [table_name],
            {"skipped": True, "reason": "EXISTING_SOURCE_VERSION_PRESERVED"},
        )

    async def _freights(self, start: date, end: date) -> list[Freight]:
        rows = (
            await self.db.execute(
                select(Freight)
                .where(Freight.deleted_at.is_(None), Freight.status_code.in_(VALID_FREIGHT_STATUSES))
                .order_by(Freight.id.asc())
            )
        ).scalars().all()
        return [row for row in rows if (stat_date := _date_of(row.published_at, row.confirmed_at, row.created_at)) and start <= stat_date <= end]

    async def _city_context(self) -> tuple[dict[str, AdminRegion], dict[str, int | None]]:
        cities = (
            await self.db.execute(select(AdminRegion).where(AdminRegion.level == 2, AdminRegion.status == 1))
        ).scalars().all()
        city_by_code = {row.code: row for row in cities}
        id_to_code = {row.id: row.code for row in cities}
        rels = (
            await self.db.execute(
                select(RegionCityRelation).order_by(
                    RegionCityRelation.is_primary.desc(),
                    RegionCityRelation.sort_order.asc(),
                    RegionCityRelation.id.asc(),
                )
            )
        ).scalars().all()
        primary_region_by_city: dict[str, int | None] = {}
        for rel in rels:
            code = id_to_code.get(rel.city_region_id)
            if code and code not in primary_region_by_city:
                primary_region_by_city[code] = rel.region_id
        return city_by_code, primary_region_by_city

    async def _node_map(self) -> dict[int, TransportNode]:
        rows = (await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None)))).scalars().all()
        return {row.id: row for row in rows}

    async def run_freight_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightDaily, start, end)
        freights = await self._freights(start, end)
        candidates = (await self.db.execute(select(FreightCandidate))).scalars().all()
        batches = (await self.db.execute(select(FreightBatchTask))).scalars().all()
        tms_inbounds = (await self.db.execute(select(FreightTmsInbound))).scalars().all()
        candidate_counts: dict[date, int] = defaultdict(int)
        inbound_counts: dict[date, int] = defaultdict(int)
        for row in candidates:
            if (dt := _date_of(row.confirmed_at, row.created_at)) and start <= dt <= end:
                candidate_counts[dt] += 1
        for row in batches:
            if (dt := _date_of(row.created_at)) and start <= dt <= end:
                inbound_counts[dt] += 1
        for row in tms_inbounds:
            if (dt := _date_of(row.processed_at, row.created_at)) and start <= dt <= end:
                inbound_counts[dt] += 1

        acc: dict[date, dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "confirmed": 0, "tonnage": Decimal("0"), "amount": Decimal("0")})
        for row in freights:
            dt = _date_of(row.published_at, row.confirmed_at, row.created_at)
            if dt is None:
                continue
            item = acc[dt]
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            price = _money(row.unit_price)
            item["count"] = int(item["count"]) + 1
            item["confirmed"] = int(item["confirmed"]) + (1 if row.confirmed_at else 0)
            item["tonnage"] = item["tonnage"] + tonnage
            item["amount"] = item["amount"] + (tonnage * price)

        now = datetime.utcnow()
        output = 0
        for stat_date in _dates(start, end):
            item = acc[stat_date]
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactFreightDaily(
                    stat_date=stat_date,
                    freight_count=int(item["count"]),
                    confirmed_count=int(item["confirmed"]),
                    candidate_count=candidate_counts[stat_date],
                    source_inbound_count=inbound_counts[stat_date],
                    total_tonnage=tonnage,
                    total_estimated_amount=amount.quantize(Decimal("0.01")) if amount else None,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_DAILY", len(freights), output, output, ["fact_freight_daily"])

    async def run_freight_flow_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightFlowDaily, start, end)
        freights = await self._freights(start, end)
        acc: dict[tuple, dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "tonnage": Decimal("0"), "amount": Decimal("0"), "min": None, "max": None})
        for row in freights:
            stat_date = _date_of(row.published_at, row.confirmed_at, row.created_at)
            if stat_date is None or not row.origin_city_code or not row.destination_city_code:
                continue
            key = (
                stat_date,
                row.origin_node_id,
                row.destination_node_id,
                row.origin_region_id_cache,
                row.destination_region_id_cache,
                row.origin_city_code,
                row.destination_city_code,
                row.commodity_standard_id,
            )
            item = acc[key]
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            price = _money(row.unit_price)
            item["count"] = int(item["count"]) + 1
            item["tonnage"] = item["tonnage"] + tonnage
            item["amount"] = item["amount"] + (tonnage * price)
            item["min"] = price if item["min"] is None or price < item["min"] else item["min"]
            item["max"] = price if item["max"] is None or price > item["max"] else item["max"]
        now = datetime.utcnow()
        for key, item in acc.items():
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactFreightFlowDaily(
                    stat_date=key[0],
                    origin_node_id=key[1],
                    destination_node_id=key[2],
                    origin_region_id=key[3],
                    destination_region_id=key[4],
                    origin_city_code=key[5],
                    destination_city_code=key[6],
                    commodity_standard_id=key[7],
                    freight_count=int(item["count"]),
                    total_tonnage=tonnage,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    min_unit_price=item["min"],
                    max_unit_price=item["max"],
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_FLOW_DAILY", len(freights), len(acc), len(acc), ["fact_freight_flow_daily"])

    async def run_freight_commodity_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightCommodityDaily, start, end)
        freights = await self._freights(start, end)
        commodities = (await self.db.execute(select(CommodityStandard))).scalars().all()
        types = (await self.db.execute(select(CommodityType))).scalars().all()
        type_category = {row.id: row.category_id for row in types}
        commodity_type = {row.id: row.type_id for row in commodities}
        commodity_category = {row.id: row.category_id or type_category.get(row.type_id) for row in commodities}
        acc: dict[tuple, dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "tonnage": Decimal("0"), "amount": Decimal("0")})
        for row in freights:
            stat_date = _date_of(row.published_at, row.confirmed_at, row.created_at)
            if stat_date is None:
                continue
            if row.commodity_standard_id is None:
                continue
            key = (stat_date, row.commodity_standard_id)
            item = acc[key]
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            price = _money(row.unit_price)
            item["count"] = int(item["count"]) + 1
            item["tonnage"] = item["tonnage"] + tonnage
            item["amount"] = item["amount"] + (tonnage * price)
        now = datetime.utcnow()
        for (stat_date, commodity_id), item in acc.items():
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactFreightCommodityDaily(
                    stat_date=stat_date,
                    commodity_standard_id=commodity_id,
                    commodity_category_id=commodity_category.get(commodity_id),
                    commodity_type_id=commodity_type.get(commodity_id),
                    freight_count=int(item["count"]),
                    total_tonnage=tonnage,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_COMMODITY_DAILY", len(freights), len(acc), len(acc), ["fact_freight_commodity_daily"])

    async def _price_buckets(self) -> list[tuple[str, str, Decimal | None, Decimal | None]]:
        rows = (
            await self.db.execute(
                select(AnalysisBucketDefinition)
                .where(AnalysisBucketDefinition.bucket_group_code == "FREIGHT_PRICE", AnalysisBucketDefinition.status == 1)
                .order_by(AnalysisBucketDefinition.sort_order.asc(), AnalysisBucketDefinition.id.asc())
            )
        ).scalars().all()
        if rows:
            return [(row.bucket_code, row.bucket_name, _money(row.min_value) if row.min_value is not None else None, _money(row.max_value) if row.max_value is not None else None) for row in rows]
        return [
            ("PRICE_LT_20", "20元/吨以下", None, Decimal("20")),
            ("PRICE_20_35", "20-35元/吨", Decimal("20"), Decimal("35")),
            ("PRICE_35_50", "35-50元/吨", Decimal("35"), Decimal("50")),
            ("PRICE_50_70", "50-70元/吨", Decimal("50"), Decimal("70")),
            ("PRICE_GT_70", "70元/吨以上", Decimal("70"), None),
        ]

    async def run_freight_price_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightPriceDaily, start, end)
        freights = await self._freights(start, end)
        buckets = await self._price_buckets()
        acc: dict[tuple, dict[str, Decimal | int | str | None]] = defaultdict(lambda: {"count": 0, "tonnage": Decimal("0"), "amount": Decimal("0"), "name": "", "min": None, "max": None})
        for row in freights:
            stat_date = _date_of(row.published_at, row.confirmed_at, row.created_at)
            price = _money(row.unit_price)
            if stat_date is None or price <= 0:
                continue
            bucket = next((b for b in buckets if (b[2] is None or price >= b[2]) and (b[3] is None or price < b[3])), buckets[-1])
            key = (stat_date, bucket[0])
            item = acc[key]
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            item["name"] = bucket[1]
            item["min"] = bucket[2]
            item["max"] = bucket[3]
            item["count"] = int(item["count"]) + 1
            item["tonnage"] = item["tonnage"] + tonnage
            item["amount"] = item["amount"] + (tonnage * price)
        now = datetime.utcnow()
        for (stat_date, bucket_code), item in acc.items():
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactFreightPriceDaily(
                    stat_date=stat_date,
                    price_bucket_code=bucket_code,
                    price_bucket_name=str(item["name"]),
                    min_unit_price=item["min"],
                    max_unit_price=item["max"],
                    freight_count=int(item["count"]),
                    total_tonnage=tonnage,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_PRICE_DAILY", len(freights), len(acc), len(acc), ["fact_freight_price_daily"])

    async def run_freight_city_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightCityDaily, start, end)
        freights = await self._freights(start, end)
        city_by_code, primary_region = await self._city_context()
        acc: dict[tuple[date, str], dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "tonnage": Decimal("0"), "amount": Decimal("0")})
        for row in freights:
            stat_date = _date_of(row.published_at, row.confirmed_at, row.created_at)
            if stat_date is None:
                continue
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            price = _money(row.unit_price)
            for city_code, inbound, outbound in ((row.origin_city_code, 0, 1), (row.destination_city_code, 1, 0)):
                if not city_code:
                    continue
                item = acc[(stat_date, city_code)]
                item["count"] = int(item["count"]) + 1
                item["in"] = int(item["in"]) + inbound
                item["out"] = int(item["out"]) + outbound
                item["tonnage"] = item["tonnage"] + tonnage
                item["amount"] = item["amount"] + (tonnage * price)
        now = datetime.utcnow()
        for (stat_date, city_code), item in acc.items():
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactFreightCityDaily(
                    stat_date=stat_date,
                    city_code=city_code,
                    city_name=getattr(city_by_code.get(city_code), "name", None),
                    primary_region_id=primary_region.get(city_code),
                    freight_count=int(item["count"]),
                    inbound_count=int(item["in"]),
                    outbound_count=int(item["out"]),
                    total_tonnage=tonnage,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    heat_value=Decimal(int(item["count"])) * Decimal("1.35") + (tonnage / Decimal("1000") if tonnage else Decimal("0")),
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_CITY_DAILY", len(freights), len(acc), len(acc), ["fact_freight_city_daily"])

    async def run_freight_node_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactFreightNodeDaily, start, end)
        freights = await self._freights(start, end)
        nodes = await self._node_map()
        _, primary_region = await self._city_context()
        acc: dict[tuple[date, int], dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "in": 0, "out": 0, "tonnage": Decimal("0"), "amount": Decimal("0")})
        for row in freights:
            stat_date = _date_of(row.published_at, row.confirmed_at, row.created_at)
            if stat_date is None:
                continue
            tonnage = _money(row.estimated_tonnage or row.max_tonnage or row.min_tonnage)
            price = _money(row.unit_price)
            for node_id, inbound, outbound in ((row.origin_node_id, 0, 1), (row.destination_node_id, 1, 0)):
                if node_id is None:
                    continue
                item = acc[(stat_date, int(node_id))]
                item["count"] = int(item["count"]) + 1
                item["in"] = int(item["in"]) + inbound
                item["out"] = int(item["out"]) + outbound
                item["tonnage"] = item["tonnage"] + tonnage
                item["amount"] = item["amount"] + (tonnage * price)
        now = datetime.utcnow()
        for (stat_date, node_id), item in acc.items():
            node = nodes.get(node_id)
            tonnage = item["tonnage"]
            amount = item["amount"]
            city_code = node.city_code if node is not None else None
            self.db.add(
                FactFreightNodeDaily(
                    stat_date=stat_date,
                    node_id=node_id,
                    node_name=node.name if node is not None else None,
                    city_code=city_code,
                    primary_region_id=primary_region.get(city_code) if city_code else None,
                    freight_count=int(item["count"]),
                    inbound_count=int(item["in"]),
                    outbound_count=int(item["out"]),
                    total_tonnage=tonnage,
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    heat_value=Decimal(int(item["count"])) * Decimal("1.5") + (tonnage / Decimal("1000") if tonnage else Decimal("0")),
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_FREIGHT_NODE_DAILY", len(freights), len(acc), len(acc), ["fact_freight_node_daily"])

    async def _ship_context(
        self,
    ) -> tuple[
        list[VesselProfile],
        dict[int, VesselCapacityDimension],
        dict[int, VesselBuildInfo],
        dict[int, VesselOperatorPeriod],
        dict[str, AdminRegion],
        dict[str, int | None],
    ]:
        ships = (
            await self.db.execute(select(VesselProfile).where(VesselProfile.deleted_at.is_(None)).order_by(VesselProfile.id.asc()))
        ).scalars().all()
        capacities = (await self.db.execute(select(VesselCapacityDimension))).scalars().all()
        builds = (await self.db.execute(select(VesselBuildInfo))).scalars().all()
        operations = (
            await self.db.execute(select(VesselOperatorPeriod).where(VesselOperatorPeriod.is_current.is_(True)))
        ).scalars().all()
        city_by_code, primary_region = await self._city_context()
        return (
            list(ships),
            {row.vessel_profile_id: row for row in capacities},
            {row.vessel_profile_id: row for row in builds},
            {row.vessel_profile_id: row for row in operations},
            city_by_code,
            primary_region,
        )

    async def run_ship_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactShipDaily, start, end)
        ships, capacities, builds, operations, _, _ = await self._ship_context()
        output = 0
        now = datetime.utcnow()
        for stat_date in _dates(start, end):
            acc: dict[tuple, dict[str, Decimal | int | str]] = defaultdict(lambda: {"count": 0, "active": 0, "dwt": Decimal("0"), "age_name": "", "dwt_name": ""})
            for ship in ships:
                capacity = capacities.get(ship.id)
                operation = operations.get(ship.id)
                deadweight = _money(capacity.deadweight_ton) if capacity and capacity.deadweight_ton is not None else Decimal("0")
                age_code, age_name = _age_bucket(getattr(builds.get(ship.id), "building_year", None), stat_date)
                dwt_code, dwt_name = _dwt_bucket(deadweight)
                status_code = ship.operation_status_code or getattr(operation, "dynamic_status_code", None) or "UNKNOWN"
                key = (ship.ship_type_code, ship.registry_city_code, ship.business_region_id, status_code, age_code, dwt_code)
                item = acc[key]
                item["count"] = int(item["count"]) + 1
                inactive_profile = ship.profile_status_code in {"INACTIVE", "TRANSFERRED", "ARCHIVED", "DECOMMISSIONED"}
                item["active"] = int(item["active"]) + (0 if inactive_profile or status_code == "SUSPENDED" else 1)
                item["dwt"] = item["dwt"] + deadweight
                item["age_name"] = age_name
                item["dwt_name"] = dwt_name
            for key, item in acc.items():
                self.db.add(
                    FactShipDaily(
                        stat_date=stat_date,
                        ship_type_code=key[0],
                        registry_city_code=key[1],
                        business_region_id=key[2],
                        operation_status_code=key[3],
                        age_bucket_code=key[4],
                        age_bucket_name=str(item["age_name"]),
                        deadweight_bucket_code=key[5],
                        deadweight_bucket_name=str(item["dwt_name"]),
                        ship_count=int(item["count"]),
                        active_ship_count=int(item["active"]),
                        total_deadweight_ton=item["dwt"],
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_SHIP_DAILY", len(ships), output, output, ["fact_ship_daily"])

    async def run_ship_city_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactShipCityDaily, start, end)
        ships, capacities, _, _, city_by_code, primary_region = await self._ship_context()
        city_codes = sorted(city_by_code)
        output = 0
        now = datetime.utcnow()
        for day_idx, stat_date in enumerate(_dates(start, end)):
            acc: dict[str, dict[str, Decimal | int]] = defaultdict(lambda: {"count": 0, "active": 0, "dwt": Decimal("0")})
            for ship in ships:
                fallback_city = city_codes[(ship.id + day_idx) % len(city_codes)] if city_codes else ship.registry_city_code
                city_code = ship.registry_city_code or fallback_city
                if not city_code:
                    continue
                capacity = capacities.get(ship.id)
                deadweight = _money(capacity.deadweight_ton) if capacity and capacity.deadweight_ton is not None else Decimal("0")
                item = acc[city_code]
                inactive_profile = ship.profile_status_code in {"INACTIVE", "TRANSFERRED", "ARCHIVED", "DECOMMISSIONED"}
                active = 0 if inactive_profile or (day_idx + ship.id) % 17 == 0 else 1
                item["count"] = int(item["count"]) + 1
                item["active"] = int(item["active"]) + active
                item["dwt"] = item["dwt"] + deadweight
            for city_code, item in acc.items():
                self.db.add(
                    FactShipCityDaily(
                        stat_date=stat_date,
                        city_code=city_code,
                        city_name=getattr(city_by_code.get(city_code), "name", None),
                        primary_region_id=primary_region.get(city_code),
                        ship_count=int(item["count"]),
                        active_ship_count=int(item["active"]),
                        total_deadweight_ton=item["dwt"],
                        heat_value=Decimal(int(item["active"])) + (item["dwt"] / Decimal("10000") if item["dwt"] else Decimal("0")),
                        data_version=LOCAL_SAMPLE_VERSION,
                        generated_at=now,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_SHIP_CITY_DAILY", len(ships), output, output, ["fact_ship_city_daily"], {"source_mode": "LOCAL_SAMPLE"})

    async def run_ship_flow_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactShipFlowDaily, start, end)
        ships, capacities, _, _, _, primary_region = await self._ship_context()
        nodes = list((await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None), TransportNode.status == 1).order_by(TransportNode.id.asc()))).scalars().all())
        if len(nodes) < 2:
            return AggregationResult("ANALYSIS_SHIP_FLOW_DAILY", len(ships), 0, 0, ["fact_ship_flow_daily"], {"source_mode": "LOCAL_SAMPLE"})
        output = 0
        now = datetime.utcnow()
        for day_idx, stat_date in enumerate(_dates(start, end)):
            for idx in range(min(6, max(1, len(nodes) // 3))):
                origin = nodes[(day_idx + idx * 3) % len(nodes)]
                destination = nodes[(day_idx * 2 + idx * 5 + 1) % len(nodes)]
                if origin.id == destination.id:
                    destination = nodes[(idx + 1) % len(nodes)]
                sample_ships = [ship for ship in ships if (ship.id + day_idx + idx) % 11 < 3]
                ship_count = max(len(sample_ships), 1)
                dwt = sum((_money(capacities.get(ship.id).deadweight_ton) if capacities.get(ship.id) and capacities.get(ship.id).deadweight_ton is not None else Decimal("0")) for ship in sample_ships)
                self.db.add(
                    FactShipFlowDaily(
                        stat_date=stat_date,
                        origin_node_id=origin.id,
                        destination_node_id=destination.id,
                        origin_region_id=primary_region.get(origin.city_code),
                        destination_region_id=primary_region.get(destination.city_code),
                        origin_city_code=origin.city_code,
                        destination_city_code=destination.city_code,
                        ship_count=ship_count,
                        voyage_count=ship_count + idx + 1,
                        total_deadweight_ton=dwt,
                        data_version=LOCAL_SAMPLE_VERSION,
                        generated_at=now,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_SHIP_FLOW_DAILY", len(ships), output, output, ["fact_ship_flow_daily"], {"source_mode": "LOCAL_SAMPLE"})

    async def run_region_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactRegionDaily, start, end)
        freight_rows = (
            await self.db.execute(select(FactFreightCityDaily).where(FactFreightCityDaily.stat_date >= start, FactFreightCityDaily.stat_date <= end))
        ).scalars().all()
        ship_rows = (
            await self.db.execute(select(FactShipCityDaily).where(FactShipCityDaily.stat_date >= start, FactShipCityDaily.stat_date <= end))
        ).scalars().all()
        acc: dict[tuple[date, int | None], dict[str, Decimal | int]] = defaultdict(lambda: {"freight": 0, "in": 0, "out": 0, "tonnage": Decimal("0"), "amount": Decimal("0"), "ship": 0, "heat": Decimal("0")})
        for row in freight_rows:
            item = acc[(row.stat_date, row.primary_region_id)]
            tonnage = _money(row.total_tonnage)
            avg_price = _money(row.avg_unit_price)
            item["freight"] = int(item["freight"]) + int(row.freight_count or 0)
            item["in"] = int(item["in"]) + int(row.inbound_count or 0)
            item["out"] = int(item["out"]) + int(row.outbound_count or 0)
            item["tonnage"] = item["tonnage"] + tonnage
            item["amount"] = item["amount"] + (tonnage * avg_price)
            item["heat"] = item["heat"] + _money(row.heat_value)
        for row in ship_rows:
            item = acc[(row.stat_date, row.primary_region_id)]
            item["ship"] = int(item["ship"]) + int(row.active_ship_count or row.ship_count or 0)
            item["heat"] = item["heat"] + _money(row.heat_value)
        now = datetime.utcnow()
        for (stat_date, region_id), item in acc.items():
            tonnage = item["tonnage"]
            amount = item["amount"]
            self.db.add(
                FactRegionDaily(
                    stat_date=stat_date,
                    region_id=region_id,
                    node_id=None,
                    freight_count=int(item["freight"]),
                    inbound_count=int(item["in"]),
                    outbound_count=int(item["out"]),
                    total_tonnage=tonnage,
                    ship_count=int(item["ship"]),
                    avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                    heat_value=item["heat"],
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )
        await self.db.flush()
        return AggregationResult("ANALYSIS_REGION_DAILY", len(freight_rows) + len(ship_rows), len(acc), len(acc), ["fact_region_daily"])

    async def run_vessel_asset_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselAssetDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_VESSEL_ASSET_DAILY", FactVesselAssetDaily.__tablename__)
        summaries = (await self.db.execute(select(VesselProfileSummary))).scalars().all()
        total = len(summaries)
        source_updated_at = max((row.source_updated_at or row.updated_at for row in summaries), default=None)
        source_versions = {
            "summary_version": sorted({row.summary_version for row in summaries if row.summary_version}),
            "source": "vessel_profile_summary",
        }
        output = 0
        now = _utcnow()
        for stat_date in _dates(start, end):
            acc: dict[tuple[str | None, str, str], dict[str, int]] = defaultdict(
                lambda: {"profile": 0, "trusted": 0, "low_quality": 0, "active": 0}
            )
            for row in summaries:
                quality = row.data_quality_level or "UNKNOWN"
                risk = row.risk_level or "UNKNOWN"
                key = (row.ship_type_code, quality, risk)
                item = acc[key]
                item["profile"] += 1
                item["trusted"] += 1 if row.identity_confidence_level in {"HIGH", "MEDIUM"} and quality in {"HIGH", "MEDIUM"} else 0
                item["low_quality"] += 1 if quality in {"LOW", "UNKNOWN"} else 0
                item["active"] += 1 if row.ais_freshness_level in {"FRESH", "RECENT"} else 0
            if not acc:
                acc[(None, "UNKNOWN", "UNKNOWN")] = {"profile": 0, "trusted": 0, "low_quality": 0, "active": 0}
            for (ship_type_code, quality, risk), item in acc.items():
                coverage = Decimal("100.00") if total else Decimal("0.00")
                reasons = [] if total else ["NO_ANALYSIS_SAMPLE"]
                self.db.add(
                    FactVesselAssetDaily(
                        stat_date=stat_date,
                        ship_type_code=ship_type_code,
                        quality_level=quality,
                        risk_level=risk,
                        profile_count=item["profile"],
                        trusted_profile_count=item["trusted"],
                        low_quality_count=item["low_quality"],
                        active_sample_count=item["active"],
                        source_layer_code="VESSEL_PROFILE_SUMMARY" if total else "NOT_AVAILABLE",
                        sample_count=total,
                        coverage_rate=coverage,
                        confidence_level=_coverage_confidence(coverage, default_unknown=not total),
                        not_computable_reasons_json=reasons,
                        uncertainty_reasons_json=[] if total else ["船舶摘要未生成，资产事实仅保留空事实"],
                        source_versions_json=source_versions,
                        source_updated_at=source_updated_at,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult(
            "ANALYSIS_VESSEL_ASSET_DAILY",
            total,
            output,
            output,
            ["fact_vessel_asset_daily"],
            {"source_layer": "VESSEL_PROFILE_SUMMARY", "not_computable": total == 0},
        )

    async def run_vessel_ais_freshness_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselAisFreshnessDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result(
                "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY", FactVesselAisFreshnessDaily.__tablename__
            )
        snapshots = (
            await self.db.execute(
                select(VesselAisSnapshot)
                .where(VesselAisSnapshot.generated_at >= datetime.combine(start, datetime.min.time()))
                .where(VesselAisSnapshot.generated_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
                .order_by(VesselAisSnapshot.generated_at.asc(), VesselAisSnapshot.id.asc())
            )
        ).scalars().all()
        snapshot_by_day: dict[date, VesselAisSnapshot] = {}
        for snapshot in snapshots:
            snapshot_by_day[_date_of(snapshot.generated_at) or start] = snapshot
        all_snapshot_ids = [row.snapshot_id for row in snapshots]
        city_items = (
            await self.db.execute(
                select(VesselAisCitySnapshotItem).where(VesselAisCitySnapshotItem.snapshot_id.in_(all_snapshot_ids))
            )
        ).scalars().all() if all_snapshot_ids else []
        positions = (
            await self.db.execute(
                select(VesselLatestPositionSnapshot).where(VesselLatestPositionSnapshot.snapshot_id.in_(all_snapshot_ids))
            )
        ).scalars().all() if all_snapshot_ids else []
        city_by_snapshot: dict[str, list[VesselAisCitySnapshotItem]] = defaultdict(list)
        for item in city_items:
            city_by_snapshot[item.snapshot_id].append(item)
        positions_by_snapshot: dict[str, list[VesselLatestPositionSnapshot]] = defaultdict(list)
        for row in positions:
            positions_by_snapshot[row.snapshot_id].append(row)

        output = 0
        now = _utcnow()
        for stat_date in _dates(start, end):
            snapshot = snapshot_by_day.get(stat_date)
            if snapshot is None:
                self.db.add(
                    FactVesselAisFreshnessDaily(
                        stat_date=stat_date,
                        city_code=None,
                        city_name=None,
                        ship_type_code=None,
                        freshness_level="UNKNOWN",
                        match_status_code="UNKNOWN",
                        vessel_count=0,
                        matched_profile_count=0,
                        unmatched_mmsi_count=0,
                        invalid_position_count=0,
                        source_snapshot_id=None,
                        source_layer_code="NOT_AVAILABLE",
                        sample_count=0,
                        coverage_rate=Decimal("0.00"),
                        confidence_level="UNKNOWN",
                        not_computable_reasons_json=["SOURCE_MISSING"],
                        uncertainty_reasons_json=["AIS 快照缺失，不能计算新鲜度分布"],
                        source_versions_json={"source": "vessel_ais_snapshot"},
                        source_updated_at=None,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
                continue
            rows = positions_by_snapshot.get(snapshot.snapshot_id) or []
            if rows:
                acc: dict[tuple[str | None, str | None, str, str], dict[str, int]] = defaultdict(
                    lambda: {"vessel": 0, "matched": 0, "unmatched": 0, "invalid": 0}
                )
                for row in rows:
                    key = (row.city_code, row.city_name, row.freshness_level or "UNKNOWN", row.match_status_code or "UNKNOWN")
                    item = acc[key]
                    item["vessel"] += 1
                    item["matched"] += 1 if row.vessel_profile_id is not None or row.match_status_code == "MATCHED_PROFILE" else 0
                    item["unmatched"] += 1 if row.match_status_code == "UNMATCHED_MMSI" else 0
                    item["invalid"] += 1 if not row.valid_position_flag or row.match_status_code == "INVALID_POSITION" else 0
                for (city_code, city_name, freshness, match_status), item in acc.items():
                    coverage = snapshot.coverage_rate
                    reasons = ["COVERAGE_TOO_LOW"] if coverage is not None and Decimal(str(coverage)) < Decimal("50") else []
                    self.db.add(
                        FactVesselAisFreshnessDaily(
                            stat_date=stat_date,
                            city_code=city_code,
                            city_name=city_name,
                            ship_type_code=None,
                            freshness_level=freshness,
                            match_status_code=match_status,
                            vessel_count=item["vessel"],
                            matched_profile_count=item["matched"],
                            unmatched_mmsi_count=item["unmatched"],
                            invalid_position_count=item["invalid"],
                            source_snapshot_id=snapshot.snapshot_id,
                            source_layer_code="AIS_SNAPSHOT",
                            sample_count=snapshot.scanned_profile_count,
                            coverage_rate=coverage,
                            confidence_level=_coverage_confidence(coverage),
                            not_computable_reasons_json=reasons,
                            uncertainty_reasons_json=snapshot.uncertainty_notes_json or [],
                            source_versions_json={"snapshot_id": snapshot.snapshot_id, "source_indices": snapshot.source_indices_json or []},
                            source_updated_at=snapshot.generated_at,
                            generated_at=now,
                            job_run_id=job_run_id,
                        )
                    )
                    output += 1
            else:
                for item in city_by_snapshot.get(snapshot.snapshot_id) or []:
                    distribution = item.freshness_distribution_json or {"UNKNOWN": item.positioned_count}
                    for freshness, count in distribution.items():
                        self.db.add(
                            FactVesselAisFreshnessDaily(
                                stat_date=stat_date,
                                city_code=item.city_code,
                                city_name=item.city_name,
                                ship_type_code=None,
                                freshness_level=str(freshness),
                                match_status_code="CITY_BUCKET",
                                vessel_count=int(count or 0),
                                matched_profile_count=item.matched_position_count,
                                unmatched_mmsi_count=item.unmatched_mmsi_count,
                                invalid_position_count=item.invalid_position_count,
                                source_snapshot_id=snapshot.snapshot_id,
                                source_layer_code="AIS_SNAPSHOT",
                                sample_count=snapshot.scanned_profile_count,
                                coverage_rate=snapshot.coverage_rate,
                                confidence_level=_coverage_confidence(snapshot.coverage_rate),
                                not_computable_reasons_json=[],
                                uncertainty_reasons_json=snapshot.uncertainty_notes_json or [],
                                source_versions_json={"snapshot_id": snapshot.snapshot_id, "city_item": item.id},
                                source_updated_at=item.latest_position_time or snapshot.generated_at,
                                generated_at=now,
                                job_run_id=job_run_id,
                            )
                        )
                        output += 1
        await self.db.flush()
        return AggregationResult(
            "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY",
            len(positions) + len(city_items),
            output,
            output,
            ["fact_vessel_ais_freshness_daily"],
        )

    async def run_vessel_trajectory_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselTrajectoryDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_VESSEL_TRAJECTORY_DAILY", FactVesselTrajectoryDaily.__tablename__)
        samples = (
            await self.db.execute(
                select(VesselRouteSegmentMatchSample)
                .where(VesselRouteSegmentMatchSample.created_at >= datetime.combine(start, datetime.min.time()))
                .where(VesselRouteSegmentMatchSample.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
            )
        ).scalars().all()
        output = 0
        now = _utcnow()
        if not samples:
            for stat_date in _dates(start, end):
                self.db.add(
                    FactVesselTrajectoryDaily(
                        stat_date=stat_date,
                        vessel_profile_id=None,
                        mmsi=None,
                        ship_type_code=None,
                        track_coverage_rate=None,
                        gap_count=0,
                        anomaly_point_count=0,
                        stay_count=0,
                        route_match_count=0,
                        latest_position_time=None,
                        source_layer_code="NOT_AVAILABLE",
                        sample_count=0,
                        coverage_rate=Decimal("0.00"),
                        confidence_level="UNKNOWN",
                        not_computable_reasons_json=["HISTORICAL_AIS_UNCONFIGURED"],
                        uncertainty_reasons_json=["历史 AIS 或航段匹配样本缺失"],
                        source_versions_json={"source": "vessel_route_segment_match_sample"},
                        source_updated_at=None,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
            await self.db.flush()
            return AggregationResult(
                "ANALYSIS_VESSEL_TRAJECTORY_DAILY",
                0,
                output,
                output,
                ["fact_vessel_trajectory_daily"],
                {"not_computable_reasons": ["HISTORICAL_AIS_UNCONFIGURED"]},
            )

        acc: dict[tuple[date, int | None, str | None, str | None], dict[str, Any]] = defaultdict(
            lambda: {"coverage": [], "gap": 0, "route": 0, "latest": None, "confidence": []}
        )
        for sample in samples:
            stat_date = _date_of(sample.latest_position_time, sample.created_at)
            if stat_date is None or not (start <= stat_date <= end):
                continue
            key = (stat_date, sample.vessel_profile_id, sample.mmsi, sample.ship_type_code)
            item = acc[key]
            item["coverage"].append(sample.covered_ratio)
            item["gap"] += int(sample.gap_count or 0)
            item["route"] += 1
            item["latest"] = max([value for value in (item["latest"], sample.latest_position_time) if value is not None], default=None)
            item["confidence"].append(sample.confidence_level)
        for key, item in acc.items():
            coverage = _avg(item["coverage"])
            reasons = ["COVERAGE_TOO_LOW"] if coverage is not None and coverage < Decimal("50") else []
            self.db.add(
                FactVesselTrajectoryDaily(
                    stat_date=key[0],
                    vessel_profile_id=key[1],
                    mmsi=key[2],
                    ship_type_code=key[3],
                    track_coverage_rate=coverage,
                    gap_count=int(item["gap"]),
                    anomaly_point_count=0,
                    stay_count=0,
                    route_match_count=int(item["route"]),
                    latest_position_time=item["latest"],
                    source_layer_code="SPATIAL_OBSERVATION",
                    sample_count=int(item["route"]),
                    coverage_rate=coverage,
                    confidence_level=_coverage_confidence(coverage),
                    not_computable_reasons_json=reasons,
                    uncertainty_reasons_json=[],
                    source_versions_json={"source": "vessel_route_segment_match_sample", "version": ROUND9_VERSION},
                    source_updated_at=item["latest"],
                    generated_at=now,
                    job_run_id=job_run_id,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_VESSEL_TRAJECTORY_DAILY", len(samples), output, output, ["fact_vessel_trajectory_daily"])

    async def run_vessel_node_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselNodeDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_VESSEL_NODE_DAILY", FactVesselNodeDaily.__tablename__)
        snapshots = (
            await self.db.execute(
                select(VesselSpatialObservationSnapshot)
                .where(VesselSpatialObservationSnapshot.observation_type_code == "NODE")
                .where(VesselSpatialObservationSnapshot.generated_at >= datetime.combine(start, datetime.min.time()))
                .where(VesselSpatialObservationSnapshot.generated_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
            )
        ).scalars().all()
        snapshot_ids = [row.snapshot_id for row in snapshots]
        items = (
            await self.db.execute(select(VesselNodeObservationItem).where(VesselNodeObservationItem.snapshot_id.in_(snapshot_ids)))
        ).scalars().all() if snapshot_ids else []
        vessels = (
            await self.db.execute(select(VesselNodeObservationVessel).where(VesselNodeObservationVessel.snapshot_id.in_(snapshot_ids)))
        ).scalars().all() if snapshot_ids else []
        by_node: dict[tuple[str, int], list[VesselNodeObservationVessel]] = defaultdict(list)
        for row in vessels:
            by_node[(row.snapshot_id, row.node_id)].append(row)
        snapshot_map = {row.snapshot_id: row for row in snapshots}
        output = 0
        now = _utcnow()
        if not items:
            for stat_date in _dates(start, end):
                self.db.add(
                    FactVesselNodeDaily(
                        stat_date=stat_date,
                        node_id=None,
                        node_name=None,
                        city_code=None,
                        radius_km=None,
                        ship_type_code=None,
                        deadweight_bucket_code=None,
                        active_count=0,
                        stay_count=0,
                        passby_count=0,
                        low_confidence_count=0,
                        source_spatial_snapshot_id=None,
                        source_layer_code="NOT_AVAILABLE",
                        sample_count=0,
                        coverage_rate=Decimal("0.00"),
                        confidence_level="UNKNOWN",
                        not_computable_reasons_json=["SOURCE_MISSING"],
                        uncertainty_reasons_json=["节点空间观测快照缺失"],
                        source_versions_json={"source": "vessel_node_observation_item"},
                        source_updated_at=None,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
            await self.db.flush()
            return AggregationResult("ANALYSIS_VESSEL_NODE_DAILY", 0, output, output, ["fact_vessel_node_daily"])

        for item in items:
            snapshot = snapshot_map.get(item.snapshot_id)
            stat_date = _date_of(snapshot.stat_time if snapshot else None, snapshot.generated_at if snapshot else item.created_at) or start
            rows = by_node.get((item.snapshot_id, item.node_id)) or []
            grouped: dict[tuple[str | None, str | None], dict[str, int]] = defaultdict(
                lambda: {"active": 0, "stay": 0, "passby": 0, "low": 0}
            )
            if rows:
                for row in rows:
                    key = (row.ship_type_code, _dwt_bucket_code(_money(row.deadweight_ton)))
                    bucket = grouped[key]
                    bucket["active"] += 1
                    bucket["stay"] += 1 if row.match_status_code == "STAY" or (row.stay_duration_minutes or 0) > 0 else 0
                    bucket["passby"] += 1 if row.match_status_code == "PASSBY" else 0
                    low_sample = (
                        item.confidence_level in {"LOW", "UNKNOWN"}
                        or row.freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}
                        or row.risk_level in {"HIGH", "UNKNOWN"}
                        or row.quality_level in {"LOW", "UNKNOWN"}
                    )
                    bucket["low"] += 1 if low_sample else 0
            else:
                grouped[(None, None)] = {
                    "active": item.active_vessel_count,
                    "stay": item.stay_vessel_count,
                    "passby": item.passby_vessel_count,
                    "low": 0 if item.confidence_level not in {"LOW", "UNKNOWN"} else item.active_vessel_count,
                }
            for (ship_type, dwt_bucket), bucket in grouped.items():
                reasons = _merge_reason_list(item.not_computable_reasons_json)
                self.db.add(
                    FactVesselNodeDaily(
                        stat_date=stat_date,
                        node_id=item.node_id,
                        node_name=item.node_name,
                        city_code=item.city_code,
                        radius_km=item.radius_km,
                        ship_type_code=ship_type,
                        deadweight_bucket_code=dwt_bucket,
                        active_count=bucket["active"],
                        stay_count=bucket["stay"],
                        passby_count=bucket["passby"],
                        low_confidence_count=bucket["low"],
                        source_spatial_snapshot_id=item.snapshot_id,
                        source_layer_code="SPATIAL_OBSERVATION",
                        sample_count=item.active_vessel_count,
                        coverage_rate=item.coverage_rate,
                        confidence_level=item.confidence_level,
                        not_computable_reasons_json=reasons,
                        uncertainty_reasons_json=snapshot.uncertainty_notes_json if snapshot else [],
                        source_versions_json={"snapshot_id": item.snapshot_id, "source_ais_snapshot_id": snapshot.source_snapshot_id if snapshot else None},
                        source_updated_at=item.latest_position_time or (snapshot.generated_at if snapshot else item.created_at),
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_VESSEL_NODE_DAILY", len(items) + len(vessels), output, output, ["fact_vessel_node_daily"])

    async def run_vessel_route_segment_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselRouteSegmentDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result(
                "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY", FactVesselRouteSegmentDaily.__tablename__
            )
        snapshots = (
            await self.db.execute(
                select(VesselSpatialObservationSnapshot)
                .where(VesselSpatialObservationSnapshot.observation_type_code == "ROUTE")
                .where(VesselSpatialObservationSnapshot.generated_at >= datetime.combine(start, datetime.min.time()))
                .where(VesselSpatialObservationSnapshot.generated_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
            )
        ).scalars().all()
        snapshot_ids = [row.snapshot_id for row in snapshots]
        items = (
            await self.db.execute(
                select(VesselRouteSegmentObservationItem).where(VesselRouteSegmentObservationItem.snapshot_id.in_(snapshot_ids))
            )
        ).scalars().all() if snapshot_ids else []
        samples = (
            await self.db.execute(select(VesselRouteSegmentMatchSample).where(VesselRouteSegmentMatchSample.snapshot_id.in_(snapshot_ids)))
        ).scalars().all() if snapshot_ids else []
        sample_by_segment: dict[tuple[str, int], list[VesselRouteSegmentMatchSample]] = defaultdict(list)
        for row in samples:
            sample_by_segment[(row.snapshot_id, row.segment_id)].append(row)
        snapshot_map = {row.snapshot_id: row for row in snapshots}
        output = 0
        now = _utcnow()
        if not items:
            for stat_date in _dates(start, end):
                self.db.add(
                    FactVesselRouteSegmentDaily(
                        stat_date=stat_date,
                        route_id=None,
                        line_id=None,
                        route_segment_id=None,
                        segment_name=None,
                        direction_code="UNKNOWN",
                        ship_type_code=None,
                        matched_count=0,
                        reliable_match_count=0,
                        covered_ratio=None,
                        avg_direction_consistency=None,
                        gap_count=0,
                        low_confidence_count=0,
                        source_spatial_snapshot_id=None,
                        source_layer_code="NOT_AVAILABLE",
                        sample_count=0,
                        coverage_rate=Decimal("0.00"),
                        confidence_level="UNKNOWN",
                        not_computable_reasons_json=["SOURCE_MISSING"],
                        uncertainty_reasons_json=["航段空间观测快照缺失"],
                        source_versions_json={"source": "vessel_route_segment_observation_item"},
                        source_updated_at=None,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
            await self.db.flush()
            return AggregationResult("ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY", 0, output, output, ["fact_vessel_route_segment_daily"])

        for item in items:
            snapshot = snapshot_map.get(item.snapshot_id)
            stat_date = _date_of(snapshot.stat_time if snapshot else None, item.created_at) or start
            rows = sample_by_segment.get((item.snapshot_id, item.segment_id)) or []
            grouped: dict[str | None, dict[str, Any]] = defaultdict(
                lambda: {"matched": 0, "reliable": 0, "coverage": [], "direction": [], "gap": 0, "low": 0}
            )
            if rows:
                for row in rows:
                    bucket = grouped[row.ship_type_code]
                    bucket["matched"] += 1
                    bucket["reliable"] += 1 if row.confidence_level in {"HIGH", "MEDIUM"} and row.match_status_code == "MATCHED" else 0
                    bucket["coverage"].append(row.covered_ratio)
                    bucket["direction"].append(row.direction_consistency)
                    bucket["gap"] += int(row.gap_count or 0)
                    bucket["low"] += 1 if row.confidence_level in {"LOW", "UNKNOWN"} else 0
            else:
                grouped[None] = {
                    "matched": item.matched_vessel_count,
                    "reliable": item.active_vessel_count,
                    "coverage": [item.covered_ratio],
                    "direction": [item.average_match_score],
                    "gap": item.gap_count,
                    "low": 0 if item.confidence_level not in {"LOW", "UNKNOWN"} else item.matched_vessel_count,
                }
            for ship_type, bucket in grouped.items():
                coverage = _avg(bucket["coverage"])
                direction = _avg(bucket["direction"])
                reasons = _merge_reason_list(item.not_computable_reasons_json)
                self.db.add(
                    FactVesselRouteSegmentDaily(
                        stat_date=stat_date,
                        route_id=item.route_id,
                        line_id=item.line_id,
                        route_segment_id=item.segment_id,
                        segment_name=item.segment_name,
                        direction_code="FORWARD" if item.segment_id else "UNKNOWN",
                        ship_type_code=ship_type,
                        matched_count=int(bucket["matched"]),
                        reliable_match_count=int(bucket["reliable"]),
                        covered_ratio=coverage,
                        avg_direction_consistency=direction,
                        gap_count=int(bucket["gap"]),
                        low_confidence_count=int(bucket["low"]),
                        source_spatial_snapshot_id=item.snapshot_id,
                        source_layer_code="SPATIAL_OBSERVATION",
                        sample_count=item.matched_vessel_count,
                        coverage_rate=item.coverage_rate,
                        confidence_level=item.confidence_level,
                        not_computable_reasons_json=reasons,
                        uncertainty_reasons_json=snapshot.uncertainty_notes_json if snapshot else [],
                        source_versions_json={"snapshot_id": item.snapshot_id, "source_ais_snapshot_id": snapshot.source_snapshot_id if snapshot else None},
                        source_updated_at=snapshot.generated_at if snapshot else item.created_at,
                        generated_at=now,
                        job_run_id=job_run_id,
                    )
                )
                output += 1
        await self.db.flush()
        return AggregationResult(
            "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY",
            len(items) + len(samples),
            output,
            output,
            ["fact_vessel_route_segment_daily"],
        )

    async def run_vessel_quality_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselQualityDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_VESSEL_QUALITY_DAILY", FactVesselQualityDaily.__tablename__)
        rows = (await self.db.execute(select(VesselDataQualityIssue))).scalars().all()
        acc: dict[tuple[date, str, str, str], dict[str, Any]] = defaultdict(lambda: {"opened": 0, "closed": 0, "resolved": 0, "voided": 0, "duplicate": 0, "hours": []})
        for row in rows:
            opened_date = _date_of(row.created_at)
            if opened_date and start <= opened_date <= end:
                acc[(opened_date, row.issue_type_code, row.severity_code, row.status_code)]["opened"] += 1
            closed_date = _date_of(row.resolved_at)
            if closed_date and start <= closed_date <= end:
                item = acc[(closed_date, row.issue_type_code, row.severity_code, row.status_code)]
                item["closed"] += 1
                item["resolved"] += 1 if row.status_code == "RESOLVED" else 0
                item["voided"] += 1 if row.status_code == "VOIDED" else 0
                if row.resolved_at and row.created_at:
                    item["hours"].append((row.resolved_at - row.created_at).total_seconds() / 3600)
        output = 0
        now = _utcnow()
        if not acc:
            for stat_date in _dates(start, end):
                acc[(stat_date, "NO_ISSUE", "LOW", "RESOLVED")] = {"opened": 0, "closed": 0, "resolved": 0, "voided": 0, "duplicate": 0, "hours": []}
        source_updated_at = max((row.updated_at for row in rows), default=None)
        for key, item in acc.items():
            sample = int(item["opened"]) + int(item["closed"])
            self.db.add(
                FactVesselQualityDaily(
                    stat_date=key[0],
                    issue_type_code=key[1],
                    severity_code=key[2],
                    status_code=key[3],
                    opened_count=int(item["opened"]),
                    closed_count=int(item["closed"]),
                    resolved_count=int(item["resolved"]),
                    voided_count=int(item["voided"]),
                    duplicate_count=int(item["duplicate"]),
                    avg_close_hours=_avg(item["hours"]),
                    source_layer_code="QUALITY_ISSUE",
                    sample_count=sample,
                    coverage_rate=Decimal("100.00"),
                    confidence_level="HIGH" if rows else "UNKNOWN",
                    not_computable_reasons_json=[],
                    uncertainty_reasons_json=[] if rows else ["质量问题表无样本，生成空事实"],
                    source_versions_json={"source": "vessel_data_quality_issue", "version": ROUND9_VERSION},
                    source_updated_at=source_updated_at,
                    generated_at=now,
                    job_run_id=job_run_id,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_VESSEL_QUALITY_DAILY", len(rows), output, output, ["fact_vessel_quality_daily"])

    async def run_vessel_risk_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactVesselRiskDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_VESSEL_RISK_DAILY", FactVesselRiskDaily.__tablename__)
        rows = (await self.db.execute(select(VesselRiskSignal))).scalars().all()
        acc: dict[tuple[date, str, str, str], dict[str, Any]] = defaultdict(lambda: {"risk": 0, "unknown": 0, "closed": 0, "high": 0, "hours": []})
        for row in rows:
            stat_date = _date_of(row.last_detected_at, row.first_detected_at, row.created_at)
            if stat_date and start <= stat_date <= end:
                item = acc[(stat_date, row.risk_type_code, row.risk_level or "UNKNOWN", row.status_code)]
                item["risk"] += 1
                item["unknown"] += 1 if row.risk_level == "UNKNOWN" else 0
                item["closed"] += 1 if row.status_code in {"CLOSED", "MITIGATED", "FALSE_POSITIVE"} else 0
                item["high"] += 1 if row.risk_level == "HIGH" else 0
                if row.resolved_at and row.first_detected_at:
                    item["hours"].append((row.resolved_at - row.first_detected_at).total_seconds() / 3600)
        output = 0
        now = _utcnow()
        if not acc:
            for stat_date in _dates(start, end):
                acc[(stat_date, "NO_RISK", "UNKNOWN", "NOT_RUN")] = {"risk": 0, "unknown": 0, "closed": 0, "high": 0, "hours": []}
        source_updated_at = max((row.updated_at for row in rows), default=None)
        for key, item in acc.items():
            reasons = ["RISK_RULE_NOT_RUN"] if key[3] == "NOT_RUN" else []
            self.db.add(
                FactVesselRiskDaily(
                    stat_date=key[0],
                    risk_type_code=key[1],
                    risk_level=key[2],
                    status_code=key[3],
                    risk_count=int(item["risk"]),
                    unknown_count=int(item["unknown"]),
                    closed_count=int(item["closed"]),
                    high_count=int(item["high"]),
                    avg_close_hours=_avg(item["hours"]),
                    source_layer_code="RISK_SIGNAL" if rows else "NOT_AVAILABLE",
                    sample_count=int(item["risk"]),
                    coverage_rate=Decimal("100.00") if rows else Decimal("0.00"),
                    confidence_level="HIGH" if rows else "UNKNOWN",
                    not_computable_reasons_json=reasons,
                    uncertainty_reasons_json=[] if rows else ["风险信号表无样本或规则未运行"],
                    source_versions_json={"source": "vessel_risk_signal", "version": ROUND9_VERSION},
                    source_updated_at=source_updated_at,
                    generated_at=now,
                    job_run_id=job_run_id,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_VESSEL_RISK_DAILY", len(rows), output, output, ["fact_vessel_risk_daily"])

    async def run_candidate_fit_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactCandidateFitDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result("ANALYSIS_CANDIDATE_FIT_DAILY", FactCandidateFitDaily.__tablename__)
        analyses = (
            await self.db.execute(
                select(VesselCandidateAnalysis)
                .where(VesselCandidateAnalysis.generated_at >= datetime.combine(start, datetime.min.time()))
                .where(VesselCandidateAnalysis.generated_at < datetime.combine(end + timedelta(days=1), datetime.min.time()))
            )
        ).scalars().all()
        analysis_ids = [row.id for row in analyses]
        items = (
            await self.db.execute(select(VesselCandidateAnalysisItem).where(VesselCandidateAnalysisItem.analysis_id.in_(analysis_ids)))
        ).scalars().all() if analysis_ids else []
        annotations = (
            await self.db.execute(select(VesselCandidateAnalysisAnnotation).where(VesselCandidateAnalysisAnnotation.analysis_id.in_(analysis_ids)))
        ).scalars().all() if analysis_ids else []
        analysis_map = {row.id: row for row in analyses}
        ann_by_analysis: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for ann in annotations:
            ann_by_analysis[ann.analysis_id][ann.annotation_type_code] += 1
        acc: dict[tuple[date, str, str], dict[str, Any]] = defaultdict(
            lambda: {"analysis": set(), "item": 0, "not": 0, "low": 0, "ann": 0, "ann_dist": defaultdict(int), "risk_dist": defaultdict(int), "scores": [], "coverages": []}
        )
        for item in items:
            analysis = analysis_map.get(item.analysis_id)
            if analysis is None:
                continue
            stat_date = _date_of(analysis.generated_at) or start
            if not (start <= stat_date <= end):
                continue
            value_level = item.candidate_value_level
            if item.confidence_level in {"LOW", "UNKNOWN"} or item.risk_level in {"HIGH", "UNKNOWN"} or item.not_computable_reasons_json:
                value_level = "LOW" if value_level == "HIGH" else value_level
            bucket = acc[(stat_date, analysis.context_type_code, value_level)]
            bucket["analysis"].add(analysis.id)
            bucket["item"] += 1
            bucket["not"] += 1 if item.not_computable_reasons_json else 0
            bucket["low"] += 1 if item.confidence_level in {"LOW", "UNKNOWN"} else 0
            bucket["scores"].append(item.fit_score)
            bucket["coverages"].append(analysis.coverage_rate)
            for reason in item.risk_reasons_json or []:
                bucket["risk_dist"][str(reason)] += 1
        for ann in annotations:
            analysis = analysis_map.get(ann.analysis_id)
            if analysis is None:
                continue
            stat_date = _date_of(analysis.generated_at) or start
            for key in [key for key in acc if key[0] == stat_date and key[1] == analysis.context_type_code]:
                acc[key]["ann"] += 1
                acc[key]["ann_dist"][ann.annotation_type_code] += 1
                break
        output = 0
        now = _utcnow()
        if not acc:
            for stat_date in _dates(start, end):
                acc[(stat_date, "NO_CONTEXT", "LOW")] = {"analysis": set(), "item": 0, "not": 0, "low": 0, "ann": 0, "ann_dist": defaultdict(int), "risk_dist": defaultdict(int), "scores": [], "coverages": []}
        source_updated_at = max((row.updated_at for row in analyses), default=None)
        for key, bucket in acc.items():
            coverage = _avg(bucket["coverages"])
            not_reasons = ["NO_ANALYSIS_SAMPLE"] if int(bucket["item"]) == 0 else []
            if coverage is not None and coverage < Decimal("50"):
                not_reasons.append("COVERAGE_TOO_LOW")
            self.db.add(
                FactCandidateFitDaily(
                    stat_date=key[0],
                    context_type_code=key[1],
                    candidate_value_level=key[2],
                    analysis_count=len(bucket["analysis"]),
                    candidate_item_count=int(bucket["item"]),
                    not_computable_count=int(bucket["not"]),
                    low_confidence_count=int(bucket["low"]),
                    annotation_count=int(bucket["ann"]),
                    annotation_distribution_json=dict(bucket["ann_dist"]),
                    risk_reason_distribution_json=dict(bucket["risk_dist"]),
                    avg_fit_score=_avg(bucket["scores"]),
                    avg_coverage_rate=coverage,
                    source_layer_code="CANDIDATE_ANALYSIS" if analyses else "NOT_AVAILABLE",
                    sample_count=int(bucket["item"]),
                    coverage_rate=coverage or Decimal("0.00"),
                    confidence_level=_coverage_confidence(coverage, default_unknown=int(bucket["item"]) == 0),
                    not_computable_reasons_json=not_reasons,
                    uncertainty_reasons_json=[] if analyses else ["候选适配分析样本缺失"],
                    source_versions_json={"analysis_ids": sorted(bucket["analysis"]), "version": ROUND9_VERSION},
                    source_updated_at=source_updated_at,
                    generated_at=now,
                    job_run_id=job_run_id,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult("ANALYSIS_CANDIDATE_FIT_DAILY", len(analyses) + len(items), output, output, ["fact_candidate_fit_daily"])

    async def run_region_supply_demand_daily(
        self,
        start: date,
        end: date,
        *,
        force_rebuild: bool = True,
        job_run_id: int | None = None,
    ) -> AggregationResult:
        if not await self._prepare_round9_fact_window(FactRegionSupplyDemandDaily, start, end, force_rebuild=force_rebuild):
            return self._skipped_round9_result(
                "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY", FactRegionSupplyDemandDaily.__tablename__
            )
        freight_rows = (
            await self.db.execute(
                select(FactFreightCityDaily).where(FactFreightCityDaily.stat_date >= start, FactFreightCityDaily.stat_date <= end)
            )
        ).scalars().all()
        ais_rows = (
            await self.db.execute(
                select(FactVesselAisFreshnessDaily).where(
                    FactVesselAisFreshnessDaily.stat_date >= start,
                    FactVesselAisFreshnessDaily.stat_date <= end,
                )
            )
        ).scalars().all()
        asset_rows = (
            await self.db.execute(
                select(FactVesselAssetDaily).where(FactVesselAssetDaily.stat_date >= start, FactVesselAssetDaily.stat_date <= end)
            )
        ).scalars().all()
        acc: dict[tuple[date, int | None, str | None, str | None], dict[str, Any]] = defaultdict(
            lambda: {
                "demand": 0,
                "tonnage": Decimal("0"),
                "ais": 0,
                "unmatched": 0,
                "trusted": 0,
                "low_risk": 0,
                "coverage": [],
                "source_updated": None,
            }
        )
        region_by_city_date: dict[tuple[date, str | None], int | None] = {}
        for row in freight_rows:
            key = (row.stat_date, row.primary_region_id, row.city_code, None)
            region_by_city_date[(row.stat_date, row.city_code)] = row.primary_region_id
            item = acc[key]
            item["demand"] += int(row.freight_count or 0)
            item["tonnage"] += _money(row.total_tonnage)
            freight_coverage = getattr(row, "coverage_rate", None)
            if freight_coverage is not None:
                item["coverage"].append(freight_coverage)
            if row.generated_at and (item["source_updated"] is None or row.generated_at > item["source_updated"]):
                item["source_updated"] = row.generated_at
        for row in ais_rows:
            key = (row.stat_date, region_by_city_date.get((row.stat_date, row.city_code)), row.city_code, row.ship_type_code)
            item = acc[key]
            item["ais"] += int(row.vessel_count or 0)
            item["unmatched"] += int(row.unmatched_mmsi_count or 0)
            item["trusted"] += int(row.matched_profile_count or 0)
            if row.coverage_rate is not None:
                item["coverage"].append(row.coverage_rate)
            if row.generated_at and (item["source_updated"] is None or row.generated_at > item["source_updated"]):
                item["source_updated"] = row.generated_at
        ais_supply_dates = {
            row.stat_date
            for row in ais_rows
            if int(row.vessel_count or 0) > 0 or int(row.matched_profile_count or 0) > 0
        }
        for row in asset_rows:
            if row.stat_date in ais_supply_dates:
                continue
            key = (row.stat_date, None, None, row.ship_type_code)
            item = acc[key]
            item["trusted"] += int(row.trusted_profile_count or 0)
            item["low_risk"] += int(row.profile_count or 0) if row.risk_level == "LOW" else 0
            if row.coverage_rate is not None:
                item["coverage"].append(row.coverage_rate)
            if row.generated_at and (item["source_updated"] is None or row.generated_at > item["source_updated"]):
                item["source_updated"] = row.generated_at
        output = 0
        now = _utcnow()
        if not acc:
            for stat_date in _dates(start, end):
                acc[(stat_date, None, None, None)] = {
                    "demand": 0,
                    "tonnage": Decimal("0"),
                    "ais": 0,
                    "unmatched": 0,
                    "trusted": 0,
                    "low_risk": 0,
                    "coverage": [],
                    "source_updated": None,
                }
        for key, item in acc.items():
            coverage = _avg(item["coverage"]) or Decimal("0.00")
            demand = int(item["demand"])
            trusted_supply = int(item["trusted"]) or max(int(item["ais"]) - int(item["unmatched"]), 0)
            reasons: list[str] = []
            if demand == 0:
                reasons.append("DEMAND_LAYER_MISSING")
            if int(item["ais"]) == 0 and trusted_supply == 0:
                reasons.append("SUPPLY_LAYER_MISSING")
            if int(item["unmatched"]) > 0:
                reasons.append("PROFILE_COVERAGE_GAP")
            tension = None if reasons else (Decimal(demand) / Decimal(max(trusted_supply, 1))).quantize(Decimal("0.0001"))
            self.db.add(
                FactRegionSupplyDemandDaily(
                    stat_date=key[0],
                    region_id=key[1],
                    city_code=key[2],
                    cargo_category_code=None,
                    ship_type_code=key[3],
                    demand_layer_code="STANDARD_FREIGHT_SAMPLE" if demand else "NOT_AVAILABLE",
                    supply_layer_code="AIS_SUPPLY_SAMPLE" if int(item["ais"]) else "TRUSTED_PROFILE_SAMPLE" if trusted_supply else "NOT_AVAILABLE",
                    demand_sample_count=demand,
                    demand_tonnage=item["tonnage"],
                    ais_supply_count=int(item["ais"]),
                    trusted_profile_count=int(item["trusted"]),
                    low_risk_supply_count=int(item["low_risk"]),
                    unmatched_mmsi_count=int(item["unmatched"]),
                    trusted_supply=trusted_supply,
                    tension_index=tension,
                    source_layer_code="REGION_SUPPLY_DEMAND",
                    sample_count=demand + int(item["ais"]) + int(item["trusted"]),
                    coverage_rate=coverage,
                    confidence_level=_coverage_confidence(coverage, default_unknown=bool(reasons)),
                    not_computable_reasons_json=reasons,
                    uncertainty_reasons_json=["档案覆盖缺口不等同于供需紧张"] if "PROFILE_COVERAGE_GAP" in reasons else [],
                    source_versions_json={"freight_fact": DATA_VERSION, "vessel_fact": ROUND9_VERSION},
                    source_updated_at=item["source_updated"],
                    generated_at=now,
                    job_run_id=job_run_id,
                )
            )
            output += 1
        await self.db.flush()
        return AggregationResult(
            "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY",
            len(freight_rows) + len(ais_rows) + len(asset_rows),
            output,
            output,
            ["fact_region_supply_demand_daily"],
        )


async def seed_analysis_job_definitions(db: AsyncSession) -> int:
    now = datetime.utcnow()
    count = 0
    for spec in ANALYSIS_JOB_SPEC_BY_CODE.values():
        row = await db.scalar(select_from_job_definition(spec.job_code))
        if row is None:
            from app.models.analysis import AnalysisJobDefinition

            row = AnalysisJobDefinition(job_code=spec.job_code, created_at=now, updated_at=now)
            db.add(row)
        row.job_name = spec.job_name
        row.module_code = spec.module_code
        row.module_name = spec.module_name
        row.description = spec.description
        row.source_tables_json = spec.source_tables
        row.target_tables_json = spec.target_tables
        row.default_parameters_json = spec.default_parameters
        row.schedule_cron = spec.schedule_cron
        row.schedule_enabled = spec.schedule_enabled
        row.enabled = True
        row.sort_order = spec.sort_order
        row.updated_at = now
        count += 1
    await db.flush()
    return count


def select_from_job_definition(job_code: str):
    from app.models.analysis import AnalysisJobDefinition

    return select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code)
