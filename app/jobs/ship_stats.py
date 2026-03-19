"""船舶统计任务主实现（一期快照口径）.

统计口径：
1. 仅统计有效船舶：`vessel.data_status = 1 AND vessel.is_deleted = 0`
2. 区域/城市热力基于 `vessel_dynamic` 最新位置快照（非日报）
3. 载重吨/船龄分布基于 `vessel` 标准档案快照
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as date_cls, datetime
from typing import Optional

from sqlalchemy import and_, case, delete, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, Region, RegionAddressRelation, TransportNode
from app.models.analysis import ShipStatAge, ShipStatCity, ShipStatDwt, ShipStatRegion
from app.models.vessel import Vessel, VesselDynamic

try:
    from celery import shared_task
except Exception:  # pragma: no cover - celery 未安装时降级
    def shared_task(*_args, **_kwargs):  # type: ignore
        def _decorator(func):
            return func
        return _decorator

logger = logging.getLogger("inland.jobs.ship_stats")


def _vessel_base_filters() -> list:
    return [Vessel.data_status == 1, Vessel.is_deleted == 0]


def _normalize_city_name(name: Optional[str]) -> str:
    if not name:
        return ""
    text = str(name).strip()
    if text.endswith("市"):
        return text[:-1]
    return text


def _point_in_polygon(lon: float, lat: float, polygon: list) -> bool:
    """射线法点位归属（区域多边形）。"""
    if not polygon or len(polygon) < 3:
        return False

    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _find_nearest_city(lon: float, lat: float, city_points: list) -> Optional[tuple]:
    """坐标兜底匹配最近城市质心。"""
    if not city_points:
        return None
    return min(city_points, key=lambda c: (c[4] - lon) ** 2 + (c[5] - lat) ** 2)


async def _compute_ship_region_snapshot(db: AsyncSession) -> int:
    """区域热力快照：动态区域 > 节点主归属区域 > 经纬度点落区。"""
    regions = (
        await db.execute(
            select(Region).where(and_(Region.status == 1, Region.deleted_at.is_(None)))
        )
    ).scalars().all()

    await db.execute(delete(ShipStatRegion))
    if not regions:
        await db.flush()
        logger.warning("[jobs.ship_stats] no active region, snapshot cleared")
        return 0

    region_meta = {
        r.id: {
            "name": r.name,
            "center_longitude": float(r.center_longitude) if r.center_longitude else None,
            "center_latitude": float(r.center_latitude) if r.center_latitude else None,
            "boundary": r.boundary_coordinates or [],
            "boundary_coordinates": r.boundary_coordinates,
        }
        for r in regions
    }

    rows = (
        await db.execute(
            select(
                Vessel.deadweight,
                VesselDynamic.current_longitude,
                VesselDynamic.current_latitude,
                VesselDynamic.current_region_id,
                RegionAddressRelation.region_id.label("node_region_id"),
            )
            .join(VesselDynamic, VesselDynamic.vessel_id == Vessel.id)
            .outerjoin(
                RegionAddressRelation,
                and_(
                    RegionAddressRelation.transport_node_id == VesselDynamic.current_node_id,
                    RegionAddressRelation.is_primary == 1,
                ),
            )
            .where(and_(*_vessel_base_filters()))
        )
    ).all()

    bucket: dict[int, dict] = {}
    for row in rows:
        matched_region_id: Optional[int] = None

        if row.current_region_id and row.current_region_id in region_meta:
            matched_region_id = int(row.current_region_id)
        elif row.node_region_id and row.node_region_id in region_meta:
            matched_region_id = int(row.node_region_id)
        elif row.current_longitude is not None and row.current_latitude is not None:
            lon = float(row.current_longitude)
            lat = float(row.current_latitude)
            for region_id, meta in region_meta.items():
                if _point_in_polygon(lon, lat, meta["boundary"]):
                    matched_region_id = int(region_id)
                    break

        if matched_region_id is None:
            continue

        item = bucket.setdefault(
            matched_region_id,
            {"vessel_count": 0, "total_deadweight": 0.0},
        )
        item["vessel_count"] += 1
        item["total_deadweight"] += float(row.deadweight or 0)

    total_vessels = sum(item["vessel_count"] for item in bucket.values()) or 1
    now = datetime.now()

    db.add_all(
        [
            ShipStatRegion(
                region_id=r.id,
                region_name=region_meta[r.id]["name"],
                center_longitude=region_meta[r.id]["center_longitude"],
                center_latitude=region_meta[r.id]["center_latitude"],
                boundary_coordinates=region_meta[r.id]["boundary_coordinates"],
                vessel_count=bucket.get(r.id, {}).get("vessel_count", 0),
                total_deadweight=bucket.get(r.id, {}).get("total_deadweight", 0.0),
                ratio=round(
                    bucket.get(r.id, {}).get("vessel_count", 0) / total_vessels * 100, 3
                ),
                refreshed_at=now,
            )
            for r in regions
        ]
    )
    await db.flush()
    return len(regions)


async def _compute_ship_city_snapshot(db: AsyncSession) -> int:
    """城市热力快照：节点城市 > 动态城市代码 > 经纬度最近城市。"""
    cities = (
        await db.execute(
            select(AdminRegion).where(and_(AdminRegion.level == 2, AdminRegion.status == 1))
        )
    ).scalars().all()

    await db.execute(delete(ShipStatCity))
    if not cities:
        await db.flush()
        logger.warning("[jobs.ship_stats] no active city region, snapshot cleared")
        return 0

    city_by_code = {city.code: city for city in cities if city.code}
    city_by_name = {
        _normalize_city_name(city.name): city
        for city in cities
        if city.name
    }

    province_codes = {city.parent_code for city in cities if city.parent_code}
    provinces = (
        await db.execute(
            select(AdminRegion.code, AdminRegion.name).where(
                and_(
                    AdminRegion.code.in_(province_codes),
                    AdminRegion.level == 1,
                )
            )
        )
    ).all()
    province_by_code = {row.code: row.name for row in provinces}

    city_points = [
        (
            city.code,
            city.name,
            province_by_code.get(city.parent_code, ""),
            _normalize_city_name(city.name),
            float(city.longitude),
            float(city.latitude),
        )
        for city in cities
        if city.longitude is not None and city.latitude is not None
    ]

    rows = (
        await db.execute(
            select(
                Vessel.deadweight,
                VesselDynamic.current_city_code,
                VesselDynamic.current_longitude,
                VesselDynamic.current_latitude,
                TransportNode.city_code.label("node_city_code"),
                TransportNode.city.label("node_city_name"),
                TransportNode.province.label("node_province_name"),
            )
            .join(VesselDynamic, VesselDynamic.vessel_id == Vessel.id)
            .outerjoin(TransportNode, TransportNode.id == VesselDynamic.current_node_id)
            .where(and_(*_vessel_base_filters()))
        )
    ).all()

    bucket: dict[str, dict] = {}

    for row in rows:
        matched_code: Optional[str] = None
        matched_name: Optional[str] = None
        matched_province: Optional[str] = None
        matched_lng: Optional[float] = None
        matched_lat: Optional[float] = None

        if row.node_city_code and row.node_city_code in city_by_code:
            city = city_by_code[row.node_city_code]
            matched_code = city.code
            matched_name = city.name
            matched_province = province_by_code.get(city.parent_code, row.node_province_name or "")
            matched_lng = float(city.longitude) if city.longitude is not None else None
            matched_lat = float(city.latitude) if city.latitude is not None else None
        elif row.current_city_code and row.current_city_code in city_by_code:
            city = city_by_code[row.current_city_code]
            matched_code = city.code
            matched_name = city.name
            matched_province = province_by_code.get(city.parent_code, "")
            matched_lng = float(city.longitude) if city.longitude is not None else None
            matched_lat = float(city.latitude) if city.latitude is not None else None
        else:
            normalized = _normalize_city_name(row.node_city_name)
            if normalized and normalized in city_by_name:
                city = city_by_name[normalized]
                matched_code = city.code
                matched_name = city.name
                matched_province = province_by_code.get(city.parent_code, row.node_province_name or "")
                matched_lng = float(city.longitude) if city.longitude is not None else None
                matched_lat = float(city.latitude) if city.latitude is not None else None

        if matched_code is None and row.current_longitude is not None and row.current_latitude is not None:
            nearest = _find_nearest_city(
                float(row.current_longitude),
                float(row.current_latitude),
                city_points,
            )
            if nearest:
                matched_code, matched_name, matched_province, _, matched_lng, matched_lat = nearest

        if matched_code is None:
            continue

        item = bucket.setdefault(
            matched_code,
            {
                "city_code": matched_code,
                "city_name": matched_name or "",
                "province_name": matched_province or "",
                "longitude": matched_lng,
                "latitude": matched_lat,
                "vessel_count": 0,
                "total_deadweight": 0.0,
            },
        )
        item["vessel_count"] += 1
        item["total_deadweight"] += float(row.deadweight or 0)

    total_vessels = sum(item["vessel_count"] for item in bucket.values()) or 1
    now = datetime.now()

    db.add_all(
        [
            ShipStatCity(
                city_code=item["city_code"],
                city_name=item["city_name"],
                province_name=item["province_name"],
                longitude=item["longitude"],
                latitude=item["latitude"],
                vessel_count=item["vessel_count"],
                total_deadweight=item["total_deadweight"],
                ratio=round(item["vessel_count"] / total_vessels * 100, 3),
                refreshed_at=now,
            )
            for item in bucket.values()
            if item["vessel_count"] > 0
        ]
    )
    await db.flush()
    return len(bucket)


async def _compute_ship_dwt_snapshot(db: AsyncSession) -> int:
    """载重吨分布快照。"""
    row = (
        await db.execute(
            select(
                func.count(Vessel.id).label("total"),
                func.sum(
                    case(
                        (and_(Vessel.deadweight.isnot(None), Vessel.deadweight < 500), 1),
                        else_=0,
                    )
                ).label("lt_500"),
                func.sum(
                    case(
                        (
                            and_(Vessel.deadweight >= 500, Vessel.deadweight < 1000),
                            1,
                        ),
                        else_=0,
                    )
                ).label("seg_500_1000"),
                func.sum(
                    case(
                        (
                            and_(Vessel.deadweight >= 1000, Vessel.deadweight < 2000),
                            1,
                        ),
                        else_=0,
                    )
                ).label("seg_1000_2000"),
                func.sum(
                    case(
                        (
                            and_(Vessel.deadweight >= 2000, Vessel.deadweight < 5000),
                            1,
                        ),
                        else_=0,
                    )
                ).label("seg_2000_5000"),
                func.sum(case((Vessel.deadweight >= 5000, 1), else_=0)).label("gte_5000"),
                func.sum(case((Vessel.deadweight.is_(None), 1), else_=0)).label("unknown"),
            )
            .where(and_(*_vessel_base_filters()))
        )
    ).one()

    total = int(row.total or 0) or 1
    now = datetime.now()
    segments = [
        ("500吨以下", None, 500, int(row.lt_500 or 0)),
        ("500-1000吨", 500, 1000, int(row.seg_500_1000 or 0)),
        ("1000-2000吨", 1000, 2000, int(row.seg_1000_2000 or 0)),
        ("2000-5000吨", 2000, 5000, int(row.seg_2000_5000 or 0)),
        ("5000吨以上", 5000, None, int(row.gte_5000 or 0)),
        ("未录入", None, None, int(row.unknown or 0)),
    ]

    await db.execute(delete(ShipStatDwt))
    db.add_all(
        [
            ShipStatDwt(
                segment_label=label,
                min_dwt=min_dwt,
                max_dwt=max_dwt,
                vessel_count=count,
                ratio=round(count / total * 100, 3),
                refreshed_at=now,
            )
            for label, min_dwt, max_dwt, count in segments
        ]
    )
    await db.flush()
    return len(segments)


async def _compute_ship_age_snapshot(db: AsyncSession) -> int:
    """船龄分布快照（当前年份 - build_year）。"""
    current_year = date_cls.today().year
    age_expr = literal(current_year) - Vessel.build_year

    row = (
        await db.execute(
            select(
                func.count(Vessel.id).label("total"),
                func.sum(
                    case(
                        (and_(Vessel.build_year.isnot(None), age_expr <= 5), 1),
                        else_=0,
                    )
                ).label("age_0_5"),
                func.sum(
                    case(
                        (
                            and_(
                                Vessel.build_year.isnot(None),
                                age_expr >= 6,
                                age_expr <= 10,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("age_6_10"),
                func.sum(
                    case(
                        (
                            and_(
                                Vessel.build_year.isnot(None),
                                age_expr >= 11,
                                age_expr <= 15,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("age_11_15"),
                func.sum(
                    case(
                        (
                            and_(
                                Vessel.build_year.isnot(None),
                                age_expr >= 16,
                                age_expr <= 20,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("age_16_20"),
                func.sum(
                    case(
                        (and_(Vessel.build_year.isnot(None), age_expr > 20), 1),
                        else_=0,
                    )
                ).label("age_over_20"),
                func.sum(case((Vessel.build_year.is_(None), 1), else_=0)).label("unknown"),
            )
            .where(and_(*_vessel_base_filters()))
        )
    ).one()

    total = int(row.total or 0) or 1
    now = datetime.now()
    segments = [
        ("5年以内", 0, 5, int(row.age_0_5 or 0)),
        ("6-10年", 6, 10, int(row.age_6_10 or 0)),
        ("11-15年", 11, 15, int(row.age_11_15 or 0)),
        ("16-20年", 16, 20, int(row.age_16_20 or 0)),
        ("20年以上", 21, None, int(row.age_over_20 or 0)),
        ("未知", None, None, int(row.unknown or 0)),
    ]

    await db.execute(delete(ShipStatAge))
    db.add_all(
        [
            ShipStatAge(
                age_range_label=label,
                min_age=min_age,
                max_age=max_age,
                vessel_count=count,
                ratio=round(count / total * 100, 3),
                refreshed_at=now,
            )
            for label, min_age, max_age, count in segments
        ]
    )
    await db.flush()
    return len(segments)


async def run_ship_dynamic_stats() -> dict:
    """刷新区域+城市热力快照。"""
    logger.info("[jobs.ship_stats] run dynamic snapshot")
    result: dict[str, int] = {}

    async with AsyncSessionLocal() as db:
        try:
            result["ship_stat_region"] = await _compute_ship_region_snapshot(db)
            result["ship_stat_city"] = await _compute_ship_city_snapshot(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("[jobs.ship_stats] dynamic snapshot failed")
            raise

    return result


async def run_ship_static_stats() -> dict:
    """刷新载重吨+船龄快照。"""
    logger.info("[jobs.ship_stats] run static snapshot")
    result: dict[str, int] = {}

    async with AsyncSessionLocal() as db:
        try:
            result["ship_stat_dwt"] = await _compute_ship_dwt_snapshot(db)
            result["ship_stat_age"] = await _compute_ship_age_snapshot(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("[jobs.ship_stats] static snapshot failed")
            raise

    return result


async def run_ship_stats() -> dict:
    """刷新四张船舶快照（区域、城市、载重、船龄）。"""
    logger.info("[jobs.ship_stats] run full snapshot")
    result: dict[str, int] = {}

    async with AsyncSessionLocal() as db:
        try:
            result["ship_stat_region"] = await _compute_ship_region_snapshot(db)
            result["ship_stat_city"] = await _compute_ship_city_snapshot(db)
            result["ship_stat_dwt"] = await _compute_ship_dwt_snapshot(db)
            result["ship_stat_age"] = await _compute_ship_age_snapshot(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("[jobs.ship_stats] full snapshot failed")
            raise

    return result


@shared_task(name="app.jobs.ship_stats.run_ship_dynamic_stats_task")
def run_ship_dynamic_stats_task() -> dict:
    """Celery 同步入口：刷新区域/城市热力快照。"""
    return asyncio.run(run_ship_dynamic_stats())


@shared_task(name="app.jobs.ship_stats.run_ship_static_stats_task")
def run_ship_static_stats_task() -> dict:
    """Celery 同步入口：刷新载重吨/船龄快照。"""
    return asyncio.run(run_ship_static_stats())


@shared_task(name="app.jobs.ship_stats.run_ship_stats_task")
def run_ship_stats_task() -> dict:
    """Celery 同步入口：刷新全部船舶统计快照。"""
    return asyncio.run(run_ship_stats())


__all__ = [
    "run_ship_dynamic_stats",
    "run_ship_static_stats",
    "run_ship_stats",
    "run_ship_dynamic_stats_task",
    "run_ship_static_stats_task",
    "run_ship_stats_task",
]
