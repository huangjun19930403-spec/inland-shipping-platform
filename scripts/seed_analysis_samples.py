"""数据分析模块本地验证事实数据 seed。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import RegionCityRelation, TransportNode
from app.models.analysis import (
    AnalysisBucketDefinition,
    AnalysisIndicatorDefinition,
    AnalysisJobRun,
    AnalysisSnapshot,
    FactFreightCommodityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightPriceDaily,
    FactRegionDaily,
    FactShipDaily,
    FactShipFlowDaily,
)
from app.models.commodity import CommodityStandard, CommodityType
from app.models.freight import Freight
from app.models.ship import ShipCapacity, ShipProfile


DATA_VERSION = "ROUND4_LOCAL_SAMPLE"

PRICE_BUCKETS = [
    ("PRICE_LT_20", "20元/吨以下", None, Decimal("20")),
    ("PRICE_20_35", "20-35元/吨", Decimal("20"), Decimal("35")),
    ("PRICE_35_50", "35-50元/吨", Decimal("35"), Decimal("50")),
    ("PRICE_50_70", "50-70元/吨", Decimal("50"), Decimal("70")),
    ("PRICE_GT_70", "70元/吨以上", Decimal("70"), None),
]

AGE_BUCKETS = [
    ("AGE_0_5", "0-5年", 0, 5),
    ("AGE_6_10", "6-10年", 6, 10),
    ("AGE_11_20", "11-20年", 11, 20),
    ("AGE_21_30", "21-30年", 21, 30),
    ("AGE_GT_30", "30年以上", 31, None),
]

DEADWEIGHT_BUCKETS = [
    ("DWT_LT_1000", "1000吨以下", Decimal("0"), Decimal("1000")),
    ("DWT_1000_3000", "1000-3000吨", Decimal("1000"), Decimal("3000")),
    ("DWT_3000_6000", "3000-6000吨", Decimal("3000"), Decimal("6000")),
    ("DWT_6000_10000", "6000-10000吨", Decimal("6000"), Decimal("10000")),
    ("DWT_GT_10000", "10000吨以上", Decimal("10000"), None),
]

INDICATORS = [
    ("FREIGHT", "FREIGHT_COUNT", "货源量", "条", "LINE", "货源采集与正式货源总量"),
    ("FREIGHT", "FREIGHT_TONNAGE", "货源吨位", "吨", "LINE", "货源估算吨位"),
    ("FREIGHT", "AVG_UNIT_PRICE", "平均运价", "元/吨", "LINE", "货源发布均价"),
    ("SHIP", "ACTIVE_SHIP_COUNT", "活跃船舶", "艘", "LINE", "样例船舶活跃趋势"),
    ("SHIP", "SHIP_TYPE_DISTRIBUTION", "船型分布", "艘", "PIE", "船舶主档船型结构"),
    ("REGION", "REGION_HEAT", "区域热力", "热度", "MAP", "节点与区域热力"),
    ("FLOW", "FREIGHT_FLOW", "货源流向", "条", "MAP", "起终点流向"),
    ("PRICE", "PRICE_BUCKET", "运价区间", "条", "BAR", "运价分布"),
]

MODULES = {
    "FREIGHT": "货源分析",
    "SHIP": "船舶分析",
    "REGION": "区域分析",
    "FLOW": "流向分析",
    "PRICE": "运价分析",
}


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _ship_age_bucket(building_year: int | None) -> tuple[str, str]:
    if not building_year:
        return "AGE_UNKNOWN", "未知船龄"
    age = max(date.today().year - building_year, 0)
    for code, name, low, high in AGE_BUCKETS:
        if age >= low and (high is None or age <= high):
            return code, name
    return "AGE_UNKNOWN", "未知船龄"


def _deadweight_bucket(deadweight: Decimal | None) -> tuple[str, str]:
    if deadweight is None:
        return "DWT_UNKNOWN", "未知载重"
    for code, name, low, high in DEADWEIGHT_BUCKETS:
        if deadweight >= low and (high is None or deadweight < high):
            return code, name
    return "DWT_UNKNOWN", "未知载重"


def _price_bucket(price: Decimal) -> tuple[str, str, Decimal | None, Decimal | None]:
    for code, name, low, high in PRICE_BUCKETS:
        if (low is None or price >= low) and (high is None or price < high):
            return code, name, low, high
    return PRICE_BUCKETS[-1]


async def _node_region_map(session, nodes: list[TransportNode]) -> dict[int, int | None]:
    city_ids = [node.city_region_id for node in nodes]
    rows = (
        await session.execute(
            select(RegionCityRelation)
            .where(RegionCityRelation.city_region_id.in_(city_ids))
            .order_by(RegionCityRelation.is_primary.desc(), RegionCityRelation.sort_order.asc())
        )
    ).scalars().all()
    by_city: dict[int, int] = {}
    for row in rows:
        by_city.setdefault(row.city_region_id, row.region_id)
    return {node.id: by_city.get(node.city_region_id) for node in nodes}


async def _clear(session) -> None:
    for model in (
        AnalysisSnapshot,
        AnalysisJobRun,
        FactRegionDaily,
        FactShipFlowDaily,
        FactShipDaily,
        FactFreightPriceDaily,
        FactFreightCommodityDaily,
        FactFreightFlowDaily,
        FactFreightDaily,
        AnalysisBucketDefinition,
        AnalysisIndicatorDefinition,
    ):
        await session.execute(delete(model))


async def _seed_definitions(session, now: datetime) -> None:
    for idx, (module, code, name, unit, chart, description) in enumerate(INDICATORS, start=1):
        session.add(
            AnalysisIndicatorDefinition(
                module_code=module,
                indicator_code=code,
                indicator_name=name,
                unit=unit,
                chart_type_code=chart,
                description=description,
                sort_order=idx,
                status=1,
                created_at=now,
                updated_at=now,
            )
        )
    sort = 1
    for code, name, low, high in PRICE_BUCKETS:
        session.add(
            AnalysisBucketDefinition(
                bucket_group_code="FREIGHT_PRICE",
                bucket_code=code,
                bucket_name=name,
                min_value=low,
                max_value=high,
                unit="元/吨",
                sort_order=sort,
                status=1,
                created_at=now,
                updated_at=now,
            )
        )
        sort += 1
    for code, name, low, high in AGE_BUCKETS:
        session.add(
            AnalysisBucketDefinition(
                bucket_group_code="SHIP_AGE",
                bucket_code=code,
                bucket_name=name,
                min_value=low,
                max_value=high,
                unit="年",
                sort_order=sort,
                status=1,
                created_at=now,
                updated_at=now,
            )
        )
        sort += 1
    for code, name, low, high in DEADWEIGHT_BUCKETS:
        session.add(
            AnalysisBucketDefinition(
                bucket_group_code="SHIP_DEADWEIGHT",
                bucket_code=code,
                bucket_name=name,
                min_value=low,
                max_value=high,
                unit="吨",
                sort_order=sort,
                status=1,
                created_at=now,
                updated_at=now,
            )
        )
        sort += 1


async def seed_analysis_samples() -> None:
    async with AsyncSessionLocal() as session:
        nodes = list(
            (
                await session.execute(
                    select(TransportNode)
                    .where(TransportNode.deleted_at.is_(None), TransportNode.status == 1)
                    .where(~TransportNode.code.like("E2E%"), ~TransportNode.name.like("%E2E%"))
                    .order_by(TransportNode.is_hot_node.desc(), TransportNode.sort_order.asc(), TransportNode.id.asc())
                )
            ).scalars().all()
        )
        commodities = list(
            (
                await session.execute(
                    select(CommodityStandard)
                    .where(CommodityStandard.deleted_at.is_(None), CommodityStandard.is_active.is_(True))
                    .order_by(CommodityStandard.id.asc())
                )
            ).scalars().all()
        )
        freights = list(
            (
                await session.execute(
                    select(Freight)
                    .where(Freight.deleted_at.is_(None), Freight.freight_no.like("FR-LOCAL-%"))
                    .order_by(Freight.id.asc())
                )
            ).scalars().all()
        )
        ships = list(
            (
                await session.execute(
                    select(ShipProfile)
                    .where(ShipProfile.deleted_at.is_(None), ShipProfile.ais_id.like("AISCNINLAND%"))
                    .order_by(ShipProfile.id.asc())
                )
            ).scalars().all()
        )
        if len(nodes) < 8 or len(commodities) < 8 or len(freights) < 100 or len(ships) < 80:
            raise RuntimeError("seed_analysis_samples requires foundation, ship and freight local sample data")

        await _clear(session)
        now = datetime.utcnow()
        await _seed_definitions(session, now)

        type_rows = (await session.execute(select(CommodityType))).scalars().all()
        type_category = {row.id: row.category_id for row in type_rows}
        commodity_type = {row.id: row.type_id for row in commodities}
        commodity_category = {row.id: type_category.get(row.type_id) for row in commodities}
        node_region = await _node_region_map(session, nodes)
        capacity_rows = (
            await session.execute(select(ShipCapacity).where(ShipCapacity.ship_id.in_([ship.id for ship in ships])))
        ).scalars().all()
        capacity_map = {row.ship_id: row for row in capacity_rows}

        start = date.today() - timedelta(days=89)
        dates = [start + timedelta(days=offset) for offset in range(90)]

        for day_idx, stat_date in enumerate(dates):
            flow_count_total = 0
            tonnage_total = Decimal("0")
            amount_total = Decimal("0")
            commodity_acc: dict[int, dict[str, Decimal | int]] = {}
            price_acc: dict[str, dict[str, Decimal | int | str | None]] = {}
            region_acc: dict[tuple[int | None, int], dict[str, Decimal | int]] = {}

            for flow_idx in range(8):
                seed = day_idx * 11 + flow_idx * 7
                origin = nodes[seed % len(nodes)]
                destination = nodes[(seed * 3 + 5) % len(nodes)]
                if origin.id == destination.id:
                    destination = nodes[(seed * 3 + 6) % len(nodes)]
                commodity = commodities[(seed * 5 + 2) % len(commodities)]
                freight_count = 3 + ((seed + flow_idx) % 9)
                tonnage = _money(420 + ((seed * 137) % 7800))
                price = _money(18 + ((seed * 11) % 62))
                amount = tonnage * price
                flow_count_total += freight_count
                tonnage_total += tonnage
                amount_total += amount
                session.add(
                    FactFreightFlowDaily(
                        stat_date=stat_date,
                        origin_node_id=origin.id,
                        destination_node_id=destination.id,
                        origin_region_id=node_region.get(origin.id),
                        destination_region_id=node_region.get(destination.id),
                        origin_city_code=origin.city_code,
                        destination_city_code=destination.city_code,
                        commodity_standard_id=commodity.id,
                        freight_count=freight_count,
                        total_tonnage=tonnage,
                        avg_unit_price=price,
                        min_unit_price=max(price - Decimal("6.00"), Decimal("8.00")),
                        max_unit_price=price + Decimal("8.00"),
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )
                acc = commodity_acc.setdefault(commodity.id, {"count": 0, "tonnage": Decimal("0"), "amount": Decimal("0")})
                acc["count"] = int(acc["count"]) + freight_count
                acc["tonnage"] = acc["tonnage"] + tonnage
                acc["amount"] = acc["amount"] + amount

                bucket_code, bucket_name, bucket_min, bucket_max = _price_bucket(price)
                pacc = price_acc.setdefault(
                    bucket_code,
                    {"name": bucket_name, "min": bucket_min, "max": bucket_max, "count": 0, "tonnage": Decimal("0"), "amount": Decimal("0")},
                )
                pacc["count"] = int(pacc["count"]) + freight_count
                pacc["tonnage"] = pacc["tonnage"] + tonnage
                pacc["amount"] = pacc["amount"] + amount

                for node, inbound, outbound in ((origin, 0, freight_count), (destination, freight_count, 0)):
                    key = (node_region.get(node.id), node.id)
                    racc = region_acc.setdefault(key, {"count": 0, "in": 0, "out": 0, "tonnage": Decimal("0"), "amount": Decimal("0"), "ship": 0})
                    racc["count"] = int(racc["count"]) + freight_count
                    racc["in"] = int(racc["in"]) + inbound
                    racc["out"] = int(racc["out"]) + outbound
                    racc["tonnage"] = racc["tonnage"] + tonnage
                    racc["amount"] = racc["amount"] + amount
                    racc["ship"] = int(racc["ship"]) + 1 + seed % 5

            avg_price = (amount_total / tonnage_total).quantize(Decimal("0.01")) if tonnage_total else None
            session.add(
                FactFreightDaily(
                    stat_date=stat_date,
                    freight_count=flow_count_total,
                    confirmed_count=max(flow_count_total - (day_idx % 6), 0),
                    candidate_count=8 + day_idx % 9,
                    source_inbound_count=5 + day_idx % 7,
                    total_tonnage=tonnage_total,
                    total_estimated_amount=amount_total.quantize(Decimal("0.01")),
                    avg_unit_price=avg_price,
                    data_version=DATA_VERSION,
                    generated_at=now,
                )
            )

            for commodity_id, acc in commodity_acc.items():
                tonnage = acc["tonnage"]
                amount = acc["amount"]
                session.add(
                    FactFreightCommodityDaily(
                        stat_date=stat_date,
                        commodity_standard_id=commodity_id,
                        commodity_category_id=commodity_category.get(commodity_id),
                        commodity_type_id=commodity_type.get(commodity_id),
                        freight_count=int(acc["count"]),
                        total_tonnage=tonnage,
                        avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )

            for bucket_code, acc in price_acc.items():
                tonnage = acc["tonnage"]
                amount = acc["amount"]
                session.add(
                    FactFreightPriceDaily(
                        stat_date=stat_date,
                        price_bucket_code=bucket_code,
                        price_bucket_name=str(acc["name"]),
                        min_unit_price=acc["min"],
                        max_unit_price=acc["max"],
                        freight_count=int(acc["count"]),
                        total_tonnage=tonnage,
                        avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )

            for (region_id, node_id), acc in region_acc.items():
                tonnage = acc["tonnage"]
                amount = acc["amount"]
                session.add(
                    FactRegionDaily(
                        stat_date=stat_date,
                        region_id=region_id,
                        node_id=node_id,
                        freight_count=int(acc["count"]),
                        inbound_count=int(acc["in"]),
                        outbound_count=int(acc["out"]),
                        total_tonnage=tonnage,
                        ship_count=int(acc["ship"]),
                        avg_unit_price=(amount / tonnage).quantize(Decimal("0.01")) if tonnage else None,
                        heat_value=Decimal(int(acc["count"])) * Decimal("1.35") + (tonnage / Decimal("1000")),
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )

            ship_groups: dict[tuple[str, str, str, int | None, str], dict[str, Decimal | int]] = {}
            for ship in ships:
                capacity = capacity_map.get(ship.id)
                deadweight = capacity.deadweight_ton if capacity else None
                age_code, age_name = _ship_age_bucket(ship.building_year)
                dwt_code, dwt_name = _deadweight_bucket(deadweight)
                key = (ship.ship_type_code, age_code, dwt_code, ship.business_region_id, ship.operation_status_code or "UNKNOWN")
                group = ship_groups.setdefault(key, {"count": 0, "active": 0, "dwt": Decimal("0"), "age_name": age_name, "dwt_name": dwt_name})
                group["count"] = int(group["count"]) + 1
                group["active"] = int(group["active"]) + (0 if ship.profile_status_code == "INACTIVE" or (day_idx + ship.id) % 19 == 0 else 1)
                group["dwt"] = group["dwt"] + (deadweight or Decimal("0"))

            for (ship_type, age_code, dwt_code, region_id, status_code), group in ship_groups.items():
                session.add(
                    FactShipDaily(
                        stat_date=stat_date,
                        ship_type_code=ship_type,
                        registry_city_code=None,
                        business_region_id=region_id,
                        operation_status_code=status_code,
                        age_bucket_code=age_code,
                        age_bucket_name=str(group["age_name"]),
                        deadweight_bucket_code=dwt_code,
                        deadweight_bucket_name=str(group["dwt_name"]),
                        ship_count=int(group["count"]),
                        active_ship_count=int(group["active"]),
                        total_deadweight_ton=group["dwt"],
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )

            for flow_idx in range(4):
                seed = day_idx * 13 + flow_idx * 9
                origin = nodes[(seed + 3) % len(nodes)]
                destination = nodes[(seed * 2 + 11) % len(nodes)]
                if origin.id == destination.id:
                    destination = nodes[(seed * 2 + 12) % len(nodes)]
                ship_count = 2 + seed % 12
                voyage_count = ship_count + 1 + seed % 8
                session.add(
                    FactShipFlowDaily(
                        stat_date=stat_date,
                        origin_node_id=origin.id,
                        destination_node_id=destination.id,
                        origin_region_id=node_region.get(origin.id),
                        destination_region_id=node_region.get(destination.id),
                        origin_city_code=origin.city_code,
                        destination_city_code=destination.city_code,
                        ship_count=ship_count,
                        voyage_count=voyage_count,
                        total_deadweight_ton=Decimal(voyage_count * (1600 + seed % 5600)),
                        data_version=DATA_VERSION,
                        generated_at=now,
                    )
                )

        job_specs = [
            ("ANALYSIS_FREIGHT_DAILY", "货源日事实生成", "FREIGHT", "SUCCESS", "成功"),
            ("ANALYSIS_FREIGHT_FLOW", "货源流向事实生成", "FLOW", "SUCCESS", "成功"),
            ("ANALYSIS_SHIP_DAILY", "船舶日事实生成", "SHIP", "SUCCESS", "成功"),
            ("ANALYSIS_REGION_HEAT", "区域热力生成", "REGION", "PARTIAL_SUCCESS", "部分成功"),
            ("ANALYSIS_PRICE_BUCKET", "运价区间生成", "PRICE", "SUCCESS", "成功"),
        ]
        for idx in range(24):
            code, name, module, status, status_name = job_specs[idx % len(job_specs)]
            finished = now - timedelta(hours=idx * 5)
            started = finished - timedelta(minutes=4 + idx % 9)
            run = AnalysisJobRun(
                job_code=code,
                job_name=name,
                module_code=module,
                module_name=MODULES[module],
                stat_date_from=start,
                stat_date_to=dates[-1],
                status_code="FAILED" if idx in (7, 19) else status,
                status_name="失败" if idx in (7, 19) else status_name,
                started_at=started,
                finished_at=finished,
                affected_rows=900 + idx * 37 if idx not in (7, 19) else 0,
                parameters_json={"range_days": 90, "data_version": DATA_VERSION},
                result_summary_json={"generated_tables": ["fact_freight_daily", "fact_ship_daily", "fact_region_daily"], "sample": True},
                error_message="样例任务模拟上游轨迹缺口，已跳过部分船舶流向。" if idx in (7, 19) else None,
                triggered_by="system_seed",
                created_at=finished,
            )
            session.add(run)
            await session.flush()
            if idx < 5:
                session.add(
                    AnalysisSnapshot(
                        snapshot_code=f"ROUND4-SNAPSHOT-{idx + 1:02d}",
                        module_code=module,
                        snapshot_name=f"{MODULES[module]}样例快照",
                        stat_date_from=start,
                        stat_date_to=dates[-1],
                        payload_json={"status": "seeded", "module": module, "range_days": 90},
                        generated_by_job_id=run.id,
                        generated_at=finished,
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_analysis_samples())
