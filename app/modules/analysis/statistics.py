"""分析统计聚合执行器。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import AdminRegion, RegionCityRelation, TransportNode
from app.models.analysis import (
    AnalysisBucketDefinition,
    FactFreightCityDaily,
    FactFreightCommodityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightNodeDaily,
    FactFreightPriceDaily,
    FactRegionDaily,
    FactShipCityDaily,
    FactShipDaily,
    FactShipFlowDaily,
)
from app.models.commodity import CommodityStandard, CommodityType
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightTmsInbound
from app.models.ship import ShipCapacity, ShipOperation, ShipProfile
from app.modules.analysis.job_catalog import ANALYSIS_JOB_SPEC_BY_CODE


DATA_VERSION = "FORMAL_ANALYSIS_V1"
LOCAL_SAMPLE_VERSION = "LOCAL_SAMPLE"
VALID_FREIGHT_STATUSES = {"PUBLISHED", "MATCHING", "EXPIRED", "CLOSED"}
SUCCESS_STATUS = {"status_code": "SUCCESS", "status_name": "成功"}


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


def _date_of(*values: Any) -> date | None:
    for value in values:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
    return None


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

    async def run(self, job_code: str, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if start > end:
            raise ValueError("date_from must be earlier than date_to")
        if job_code == "ANALYSIS_ALL_DAILY":
            return await self._run_all(start, end, force_rebuild=force_rebuild)
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
        handler = handlers.get(job_code)
        if handler is None:
            raise ValueError(f"unsupported analysis job: {job_code}")
        return await handler(start, end, force_rebuild=force_rebuild)

    async def _run_all(self, start: date, end: date, *, force_rebuild: bool) -> AggregationResult:
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
            "ANALYSIS_REGION_DAILY",
        ]
        results: list[AggregationResult] = []
        for code in ordered_codes:
            results.append(await self.run(code, start, end, force_rebuild=force_rebuild))
        return AggregationResult(
            job_code="ANALYSIS_ALL_DAILY",
            input_rows=sum(item.input_rows for item in results),
            output_rows=sum(item.output_rows for item in results),
            affected_rows=sum(item.affected_rows for item in results),
            target_tables=sorted({table for item in results for table in (item.target_tables or [])}),
            extra={"children": [item.as_summary() for item in results]},
        )

    async def _clear(self, model, start: date, end: date) -> None:
        await self.db.execute(delete(model).where(model.stat_date >= start, model.stat_date <= end))

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

    async def _ship_context(self) -> tuple[list[ShipProfile], dict[int, ShipCapacity], dict[int, ShipOperation], dict[str, AdminRegion], dict[str, int | None]]:
        ships = (
            await self.db.execute(select(ShipProfile).where(ShipProfile.deleted_at.is_(None)).order_by(ShipProfile.id.asc()))
        ).scalars().all()
        capacities = (await self.db.execute(select(ShipCapacity))).scalars().all()
        operations = (await self.db.execute(select(ShipOperation))).scalars().all()
        city_by_code, primary_region = await self._city_context()
        return list(ships), {row.ship_id: row for row in capacities}, {row.ship_id: row for row in operations}, city_by_code, primary_region

    async def run_ship_daily(self, start: date, end: date, *, force_rebuild: bool = True) -> AggregationResult:
        if force_rebuild:
            await self._clear(FactShipDaily, start, end)
        ships, capacities, operations, _, _ = await self._ship_context()
        output = 0
        now = datetime.utcnow()
        for stat_date in _dates(start, end):
            acc: dict[tuple, dict[str, Decimal | int | str]] = defaultdict(lambda: {"count": 0, "active": 0, "dwt": Decimal("0"), "age_name": "", "dwt_name": ""})
            for ship in ships:
                capacity = capacities.get(ship.id)
                operation = operations.get(ship.id)
                deadweight = _money(capacity.deadweight_ton) if capacity and capacity.deadweight_ton is not None else Decimal("0")
                age_code, age_name = _age_bucket(ship.building_year, stat_date)
                dwt_code, dwt_name = _dwt_bucket(deadweight)
                status_code = ship.operation_status_code or getattr(operation, "dynamic_status_code", None) or "UNKNOWN"
                key = (ship.ship_type_code, ship.registry_city_code, ship.business_region_id, status_code, age_code, dwt_code)
                item = acc[key]
                item["count"] = int(item["count"]) + 1
                item["active"] = int(item["active"]) + (0 if ship.profile_status_code == "INACTIVE" or status_code == "SUSPENDED" else 1)
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
        ships, capacities, _, city_by_code, primary_region = await self._ship_context()
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
                active = 0 if ship.profile_status_code == "INACTIVE" or (day_idx + ship.id) % 17 == 0 else 1
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
        ships, capacities, _, _, primary_region = await self._ship_context()
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
