"""analysis 模块 service。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import NotFoundError, ValidationError
from app.models.address import AdminRegion, AdminRegionBoundary, Region, TransportNode
from app.models.analysis import (
    AnalysisJobDefinition,
    AnalysisJobRun,
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
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.dictionary import StdDict, StdDictItem
from app.modules.address.boundary_utils import (
    boundary_paths_for_precision,
    extract_geojson_polygons,
    serialize_boundary_paths,
)
from app.modules.analysis.schemas import (
    AnalysisJobRunDetailResponse,
    AnalysisJobRunResponse,
    AnalysisOverviewResponse,
    AnalysisTaskDetailResponse,
    AnalysisTaskResponse,
    AnalysisTaskTriggerRequest,
    BoundaryHeatMapItem,
    ChartPoint,
    FlowAnalysisOverviewResponse,
    FlowMapItem,
    FreightAnalysisOverviewResponse,
    HeatMapItem,
    MetricCard,
    PageResponse,
    PriceAnalysisOverviewResponse,
    RegionAnalysisOverviewResponse,
    ShipAnalysisOverviewResponse,
)


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


def _metric(code: str, title: str, value: Any, unit: str | None = None, description: str | None = None) -> MetricCard:
    numeric = _num(value)
    if numeric.is_integer():
        display_value: int | float = int(numeric)
    else:
        display_value = round(numeric, 2)
    return MetricCard(code=code, title=title, value=display_value, unit=unit, description=description)


def _job_to_response(entity: AnalysisJobRun) -> AnalysisJobRunResponse:
    return AnalysisJobRunResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=entity.module_name,
        stat_date_from=entity.stat_date_from,
        stat_date_to=entity.stat_date_to,
        status_code=entity.status_code,
        status_name=entity.status_name,
        celery_task_id=entity.celery_task_id,
        queued_at=entity.queued_at,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        duration_ms=entity.duration_ms,
        input_rows=entity.input_rows,
        output_rows=entity.output_rows,
        affected_rows=entity.affected_rows,
        error_message=entity.error_message,
        triggered_by=entity.triggered_by,
        created_at=entity.created_at,
    )


def _task_to_response(entity: AnalysisJobDefinition) -> AnalysisTaskResponse:
    return AnalysisTaskResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=entity.module_name,
        description=entity.description,
        source_tables_json=entity.source_tables_json,
        target_tables_json=entity.target_tables_json,
        default_parameters_json=entity.default_parameters_json,
        schedule_cron=entity.schedule_cron,
        schedule_enabled=entity.schedule_enabled,
        enabled=entity.enabled,
        last_run_id=entity.last_run_id,
        last_status_code=entity.last_status_code,
        last_finished_at=entity.last_finished_at,
        last_result_summary_json=entity.last_result_summary_json,
        sort_order=entity.sort_order,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _status_name(status_code: str) -> str:
    return {
        "QUEUED": "排队中",
        "RUNNING": "运行中",
        "SUCCESS": "成功",
        "PARTIAL_SUCCESS": "部分成功",
        "FAILED": "失败",
    }.get(status_code, status_code)


class AnalysisDashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
        return FreightAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _metric("freight_count", "货源量", totals["freight_count"], "条"),
                _metric("confirmed_count", "确认货源", totals["confirmed_count"], "条"),
                _metric("total_tonnage", "总吨位", totals["total_tonnage"], "吨"),
                _metric("avg_unit_price", "平均运价", totals["avg_unit_price"], "元/吨"),
                _metric("raw_level_count", "待清洗货源", raw_quality["raw_level_count"], "条", "原文级装卸地或货品仍需清洗提升"),
            ],
            trend=await self.freight_trend(start, end),
            node_ranking=await self.freight_node_ranking(start, end, 12),
            commodity_structure=await self.freight_commodity_structure(start, end),
            price_distribution=await self.freight_price_distribution(start, end),
            hot_routes=await self.freight_hot_routes(start, end, 8),
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

    async def freight_hot_routes(self, start: date, end: date, limit: int = 10) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
        origin_city = aliased(AdminRegion)
        destination_city = aliased(AdminRegion)
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
                .where(FactFreightFlowDaily.stat_date >= start, FactFreightFlowDaily.stat_date <= end)
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
        return [
            FlowMapItem(
                origin_id=row[0],
                origin_name=row[1] or row[8] or row[10] or "未知起点",
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5] or row[9] or row[11] or "未知终点",
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                commodity_name=row[12],
                value=int(_num(row[13])),
                freight_count=int(_num(row[13])),
                tonnage=round(_num(row[14]), 2),
                avg_unit_price=round(_num(row[15]), 2),
            )
            for row in rows
        ]

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

    async def ship_flow_map(self, start: date, end: date, limit: int = 30) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
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
                    func.sum(FactShipFlowDaily.ship_count),
                    func.sum(FactShipFlowDaily.voyage_count),
                    func.sum(FactShipFlowDaily.total_deadweight_ton),
                )
                .join(origin, origin.id == FactShipFlowDaily.origin_node_id)
                .join(destination, destination.id == FactShipFlowDaily.destination_node_id)
                .where(FactShipFlowDaily.stat_date >= start, FactShipFlowDaily.stat_date <= end)
                .group_by(origin.id, origin.name, origin.longitude, origin.latitude, destination.id, destination.name, destination.longitude, destination.latitude)
                .order_by(func.sum(FactShipFlowDaily.voyage_count).desc())
                .limit(limit)
            )
        ).all()
        return [
            FlowMapItem(
                origin_id=row[0],
                origin_name=row[1],
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5],
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                value=int(_num(row[9])),
                ship_count=int(_num(row[8])),
                voyage_count=int(_num(row[9])),
                tonnage=round(_num(row[10]), 2),
            )
            for row in rows
        ]

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

    async def flow_overview(self, date_from: date | None, date_to: date | None) -> FlowAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        freight_flows = await self.freight_hot_routes(start, end, 20)
        ship_flows = await self.ship_flow_map(start, end, 20)
        return FlowAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _metric("freight_flow_count", "货源流向", len(freight_flows), "条"),
                _metric("ship_flow_count", "船舶流向", len(ship_flows), "条"),
                _metric("top_freight_route", "最热货源流向", freight_flows[0].freight_count if freight_flows else 0, "条"),
                _metric("top_ship_route", "最热船舶流向", ship_flows[0].voyage_count if ship_flows else 0, "航次"),
            ],
            freight_flows=freight_flows,
            ship_flows=ship_flows,
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

    async def list_jobs(
        self,
        module_code: str | None,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun)
        if module_code:
            stmt = stmt.where(AnalysisJobRun.module_code == module_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisJobRunResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_job_to_response(row) for row in rows],
        )

    async def get_job_detail(self, job_run_id: int) -> AnalysisJobRunDetailResponse:
        row = await self.db.scalar(select(AnalysisJobRun).where(AnalysisJobRun.id == job_run_id))
        if row is None:
            raise NotFoundError("AnalysisJobRun", job_run_id)
        base = _job_to_response(row).model_dump()
        return AnalysisJobRunDetailResponse(
            **base,
            parameters_json=row.parameters_json,
            result_summary_json=row.result_summary_json,
        )

    async def list_tasks(
        self,
        module_code: str | None,
        enabled: bool | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisTaskResponse]:
        stmt = select(AnalysisJobDefinition)
        if module_code:
            stmt = stmt.where(AnalysisJobDefinition.module_code == module_code)
        if enabled is not None:
            stmt = stmt.where(AnalysisJobDefinition.enabled == enabled)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobDefinition.sort_order.asc(), AnalysisJobDefinition.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisTaskResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_task_to_response(row) for row in rows],
        )

    async def get_task_detail(self, job_code: str) -> AnalysisTaskDetailResponse:
        row = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if row is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        runs = (
            await self.db.execute(
                select(AnalysisJobRun)
                .where(AnalysisJobRun.job_code == job_code)
                .order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .limit(20)
            )
        ).scalars().all()
        base = _task_to_response(row).model_dump()
        return AnalysisTaskDetailResponse(**base, recent_runs=[_job_to_response(item) for item in runs])

    async def list_task_runs(
        self,
        job_code: str,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun).where(AnalysisJobRun.job_code == job_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisJobRunResponse](total=total, page=page, page_size=page_size, items=[_job_to_response(row) for row in rows])

    async def trigger_task(self, job_code: str, payload: AnalysisTaskTriggerRequest, triggered_by: str | None) -> AnalysisJobRunResponse:
        definition = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if definition is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        if not definition.enabled:
            raise ValidationError("分析任务已停用，不能手动触发", {"job_code": job_code})
        now = datetime.utcnow()
        parameters = {
            **(definition.default_parameters_json or {}),
            **(payload.parameters_json or {}),
            "force_rebuild": payload.force_rebuild,
        }
        run = AnalysisJobRun(
            job_code=definition.job_code,
            job_name=definition.job_name,
            module_code=definition.module_code,
            module_name=definition.module_name,
            stat_date_from=payload.date_from,
            stat_date_to=payload.date_to,
            status_code="QUEUED",
            status_name=_status_name("QUEUED"),
            queued_at=now,
            parameters_json=parameters,
            triggered_by=triggered_by,
            created_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(run)

        try:
            from app.tasks.analysis_tasks import run_analysis_job

            async_result = run_analysis_job.apply_async(
                args=[
                    definition.job_code,
                    payload.date_from.isoformat(),
                    payload.date_to.isoformat(),
                    payload.force_rebuild,
                    {"job_run_id": run.id, "triggered_by": triggered_by, **(payload.parameters_json or {})},
                ],
                queue="analysis",
            )
            run.celery_task_id = async_result.id
        except Exception as exc:
            run.status_code = "FAILED"
            run.status_name = _status_name("FAILED")
            run.finished_at = datetime.utcnow()
            run.error_message = f"Celery 任务投递失败：{exc}"
            await self.db.commit()
            raise ValidationError("Celery 任务投递失败，请确认 Redis 和 analysis-worker 已启动", {"error": str(exc)}) from exc
        await self.db.commit()
        await self.db.refresh(run)
        return _job_to_response(run)
