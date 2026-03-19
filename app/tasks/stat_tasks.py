"""
航运数据统计任务

货源统计：写入事件驱动（refresh_cargo_stats），货源创建/状态变更后立即调用
船舶统计：每日 02:00 定时任务（daily_ship_stat_job），AIS数据按日更新

规则：
  - 本模块是唯一被允许读取业务表并写入统计表的代码路径
  - 所有分析接口只读统计表
"""
import asyncio
import logging
from datetime import date
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("inland.stat_tasks")


# ─────────────────────────────────────────────────
# 货源统计（事件驱动）
# ─────────────────────────────────────────────────

async def _stat_cargo_city_heatmap(db: AsyncSession, stat_date: date) -> int:
    """cargo_freight → cargo_city_heatmap
    按装货/卸货城市统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    repo = AnalysisRepository(db)
    count = 0

    for stat_type, code_col, name_col in (
        ("ORIGIN", CargoFreight.origin_admin_code, CargoFreight.origin_admin_name),
        ("DEST",   CargoFreight.dest_admin_code,   CargoFreight.dest_admin_name),
    ):
        result = await db.execute(
            select(
                code_col.label("city_code"),
                name_col.label("city_name"),
                func.count(CargoFreight.id).label("cargo_count"),
                func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
            )
            .where(
                and_(
                    code_col.isnot(None),
                    CargoFreight.deleted_at.is_(None),
                    func.date(CargoFreight.created_at) == stat_date,
                )
            )
            .group_by(code_col, name_col)
        )
        rows = result.all()
        for row in rows:
            await repo.upsert_cargo_city_heatmap(
                stat_date=stat_date,
                city_code=row.city_code,
                city_name=row.city_name or "",
                stat_type=stat_type,
                cargo_count=row.cargo_count,
                total_tonnage=float(row.total_tonnage or 0),
            )
            count += 1

    return count


async def _stat_cargo_daily(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_stat_daily
    统计当日货源总量、各状态数量及总吨位
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CargoFreight.status,
            func.count(CargoFreight.id).label("cnt"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("tonnage"),
        )
        .where(
            and_(
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CargoFreight.status)
    )
    rows = result.all()

    total_count = sum(r.cnt for r in rows)
    confirmed_count = next((r.cnt for r in rows if r.status == "CONFIRMED"), 0)
    pending_count = next((r.cnt for r in rows if r.status == "PENDING"), 0)
    total_tonnage = sum(float(r.tonnage or 0) for r in rows)
    avg_tonnage = round(total_tonnage / total_count, 2) if total_count else 0.0

    repo = AnalysisRepository(db)
    await repo.upsert_cargo_stat(
        stat_date=stat_date,
        total_count=total_count,
        confirmed_count=confirmed_count,
        pending_count=pending_count,
        total_tonnage=total_tonnage,
        avg_tonnage=avg_tonnage,
    )


async def _stat_cargo_commodity(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_commodity_stat_daily
    按货品大类统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoFreight, CommodityStandard, CommodityType, CommodityCategory
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CommodityCategory.id.label("category_id"),
            CommodityCategory.name.label("category_name"),
            func.count(CargoFreight.id).label("cargo_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .join(CommodityStandard, CommodityStandard.id == CargoFreight.commodity_id)
        .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
        .join(CommodityCategory, CommodityCategory.id == CommodityType.category_id)
        .where(
            and_(
                CargoFreight.commodity_id.isnot(None),
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CommodityCategory.id, CommodityCategory.name)
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_cargo_commodity_stat(
            stat_date=stat_date,
            commodity_category_id=row.category_id,
            category_name=row.category_name,
            cargo_count=row.cargo_count,
            total_tonnage=float(row.total_tonnage or 0),
        )


async def _stat_cargo_od(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_od_daily
    按起终点城市对统计当日OD流量
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CargoFreight.origin_admin_code.label("origin_city_code"),
            CargoFreight.origin_admin_name.label("origin_city_name"),
            CargoFreight.dest_admin_code.label("dest_city_code"),
            CargoFreight.dest_admin_name.label("dest_city_name"),
            func.count(CargoFreight.id).label("cargo_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .where(
            and_(
                CargoFreight.origin_admin_code.isnot(None),
                CargoFreight.dest_admin_code.isnot(None),
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(
            CargoFreight.origin_admin_code,
            CargoFreight.origin_admin_name,
            CargoFreight.dest_admin_code,
            CargoFreight.dest_admin_name,
        )
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_cargo_od_stat(
            stat_date=stat_date,
            origin_city_code=row.origin_city_code,
            origin_city_name=row.origin_city_name or "",
            dest_city_code=row.dest_city_code,
            dest_city_name=row.dest_city_name or "",
            cargo_count=row.cargo_count,
            total_tonnage=float(row.total_tonnage or 0),
        )


async def _stat_cargo_channel(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight + cargo_raw_message → cargo_channel_daily
    按录入渠道统计数量、解析成功数、确认数及总吨位
    """
    from app.models.cargo import CargoFreight, CargoRawMessage
    from app.repositories.analysis_repository import AnalysisRepository

    # 各渠道已确认货源数及总吨位
    freight_result = await db.execute(
        select(
            CargoFreight.source_type,
            func.count(CargoFreight.id).label("confirmed_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .where(
            and_(
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CargoFreight.source_type)
    )
    freight_rows = {r.source_type: r for r in freight_result.all()}

    # WECHAT_AI 渠道原始消息总数和解析成功数
    raw_total_result = await db.execute(
        select(func.count(CargoRawMessage.id))
        .where(func.date(CargoRawMessage.created_at) == stat_date)
    )
    raw_total = raw_total_result.scalar_one() or 0

    parsed_result = await db.execute(
        select(func.count(CargoRawMessage.id))
        .where(
            and_(
                CargoRawMessage.status == "PARSED",
                func.date(CargoRawMessage.created_at) == stat_date,
            )
        )
    )
    parsed_count = parsed_result.scalar_one() or 0

    # 汇总写入各渠道统计
    repo = AnalysisRepository(db)
    all_source_types = set(freight_rows.keys()) | {"WECHAT_AI", "TMS", "MANUAL"}
    for source_type in all_source_types:
        fr = freight_rows.get(source_type)
        raw_msg_count = raw_total if source_type == "WECHAT_AI" else 0
        parse_success = parsed_count if source_type == "WECHAT_AI" else 0
        await repo.upsert_cargo_channel_stat(
            stat_date=stat_date,
            source_type=source_type,
            raw_msg_count=raw_msg_count,
            parse_success_count=parse_success,
            confirmed_count=fr.confirmed_count if fr else 0,
            total_tonnage=float(fr.total_tonnage or 0) if fr else 0.0,
        )


# ─────────────────────────────────────────────────
# 事件驱动入口（货源写入时触发）
# ─────────────────────────────────────────────────

async def refresh_cargo_stats(stat_date: Optional[date] = None) -> None:
    """事件驱动统计刷新 — 货源创建/状态变更后触发，刷新当日所有货源统计表

    使用方式：
        from app.tasks.stat_tasks import refresh_cargo_stats
        background_tasks.add_task(refresh_cargo_stats, date.today())
    """
    from app.core.database import AsyncSessionLocal

    target = stat_date or date.today()
    logger.info(f"[stat_tasks] refresh_cargo_stats date={target}")

    async with AsyncSessionLocal() as db:
        try:
            await _stat_cargo_city_heatmap(db, target)
            await _stat_cargo_daily(db, target)
            await _stat_cargo_commodity(db, target)
            await _stat_cargo_od(db, target)
            await _stat_cargo_channel(db, target)
            await db.commit()
            logger.info(f"[stat_tasks] refresh_cargo_stats done date={target}")
        except Exception as exc:
            await db.rollback()
            logger.error(
                f"[stat_tasks] refresh_cargo_stats failed date={target}: {exc}",
                exc_info=True,
            )


# ─────────────────────────────────────────────────
# 船舶统计（快照模式，事件驱动全量替换）
# ─────────────────────────────────────────────────

def _point_in_polygon(lon: float, lat: float, polygon: list) -> bool:
    """射线法判断点是否在多边形内
    polygon: [[lng1,lat1], [lng2,lat2], ...]
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _find_nearest_city(
    lon: float, lat: float, city_list: list
) -> Optional[tuple]:
    """欧氏距离找最近城市质心（内河场景同省域内误差可接受）
    city_list: [(code, name, province_name, lon, lat), ...]
    """
    if not city_list:
        return None
    return min(city_list, key=lambda c: (c[3] - lon) ** 2 + (c[4] - lat) ** 2)


async def _stat_ship_region(db: AsyncSession) -> int:
    """vessel_dynamic → ship_stat_region（航运商业区域热力快照）

    归属逻辑：
      1. current_node_id → transport_node.region_id（精确）
      2. 只有 GPS → Region.boundary_coordinates 射线法（Python）
    """
    from datetime import datetime
    from sqlalchemy import delete as sa_delete
    from app.models.vessel import Vessel, VesselDynamic
    from app.models.address import Region, TransportNode
    from app.models.analysis import ShipStatRegion

    # Step1: 加载全部有效区域及多边形
    regions_result = await db.execute(
        select(Region).where(
            and_(Region.status == 1, Region.deleted_at.is_(None))
        )
    )
    regions = regions_result.scalars().all()
    if not regions:
        logger.warning("[stat_tasks] ship_region: 无可用航运区域，跳过")
        return 0

    region_meta = {
        r.id: {
            "name": r.name,
            "center_lon": float(r.center_longitude) if r.center_longitude else None,
            "center_lat": float(r.center_latitude) if r.center_latitude else None,
            "boundary": r.boundary_coordinates or [],
            "boundary_coordinates": r.boundary_coordinates,
        }
        for r in regions
    }

    # Step2: 查所有有效船舶位置
    rows_result = await db.execute(
        select(
            VesselDynamic.current_longitude,
            VesselDynamic.current_latitude,
            Vessel.deadweight,
            TransportNode.region_id,
        )
        .join(Vessel, Vessel.id == VesselDynamic.vessel_id)
        .outerjoin(TransportNode, TransportNode.id == VesselDynamic.current_node_id)
        .where(and_(Vessel.data_status == 1, Vessel.is_deleted == 0))
    )

    # Step3: 归区域
    buckets: dict[int, dict] = {}
    for row in rows_result.all():
        rid = None
        # 优先：通过节点直接取 region_id
        if row.region_id:
            rid = row.region_id
        # 兜底：GPS 射线法
        elif row.current_longitude and row.current_latitude:
            lon = float(row.current_longitude)
            lat = float(row.current_latitude)
            for region_id, meta in region_meta.items():
                if meta["boundary"] and _point_in_polygon(lon, lat, meta["boundary"]):
                    rid = region_id
                    break

        if rid and rid in region_meta:
            b = buckets.setdefault(rid, {"vessel_count": 0, "total_deadweight": 0.0})
            b["vessel_count"] += 1
            b["total_deadweight"] += float(row.deadweight or 0)

    # Step4: 全量替换
    total = sum(b["vessel_count"] for b in buckets.values()) or 1
    now = datetime.now()
    new_rows = []
    for r in regions:
        b = buckets.get(r.id, {"vessel_count": 0, "total_deadweight": 0.0})
        meta = region_meta[r.id]
        new_rows.append(ShipStatRegion(
            region_id=r.id,
            region_name=meta["name"],
            center_longitude=meta["center_lon"],
            center_latitude=meta["center_lat"],
            boundary_coordinates=meta["boundary_coordinates"],
            vessel_count=b["vessel_count"],
            total_deadweight=b["total_deadweight"],
            ratio=round(b["vessel_count"] / total * 100, 3),
            refreshed_at=now,
        ))

    await db.execute(sa_delete(ShipStatRegion))
    db.add_all(new_rows)
    await db.flush()
    logger.info(f"[stat_tasks] ship_region 刷新完成，区域数={len(new_rows)}")
    return len(new_rows)


async def _stat_ship_city(db: AsyncSession) -> int:
    """vessel_dynamic → ship_stat_city（城市级热力快照）

    归属逻辑：
      1. 有 current_node_id → transport_node.city 文本匹配 admin_region（精确）
      2. 只有 GPS → 欧氏距离最近的 admin_region 市级质心（近似）
    """
    from datetime import datetime
    from sqlalchemy import delete as sa_delete
    from app.models.vessel import Vessel, VesselDynamic
    from app.models.address import AdminRegion, TransportNode
    from app.models.analysis import ShipStatCity

    # Step1: 加载全部市级行政区（level=2）
    cities_result = await db.execute(
        select(AdminRegion).where(
            and_(AdminRegion.level == 2, AdminRegion.status == 1)
        )
    )
    cities = cities_result.scalars().all()
    if not cities:
        logger.warning("[stat_tasks] ship_city: 无市级行政区数据，跳过")
        return 0

    city_by_name: dict[str, AdminRegion] = {c.name: c for c in cities}
    city_list = [
        (c.code, c.name, "", float(c.longitude), float(c.latitude))
        for c in cities if c.longitude and c.latitude
    ]

    # 查询省份名称（通过 parent_code 自关联）
    province_codes = {c.parent_code for c in cities if c.parent_code}
    prov_result = await db.execute(
        select(AdminRegion.code, AdminRegion.name).where(
            and_(AdminRegion.code.in_(province_codes), AdminRegion.level == 1)
        )
    )
    province_by_code: dict[str, str] = {r.code: r.name for r in prov_result.all()}

    # 补充 city_list 的省份名
    city_list = [
        (c.code, c.name, province_by_code.get(c.parent_code, ""),
         float(c.longitude), float(c.latitude))
        for c in cities if c.longitude and c.latitude
    ]

    # Step2: 有 current_node_id 的船 → 按 transport_node.city 聚合
    node_agg_result = await db.execute(
        select(
            TransportNode.city.label("city_name"),
            TransportNode.province.label("province_name"),
            func.count(Vessel.id).label("vessel_count"),
            func.coalesce(func.sum(Vessel.deadweight), 0).label("total_deadweight"),
        )
        .join(VesselDynamic, VesselDynamic.vessel_id == Vessel.id)
        .join(TransportNode, TransportNode.id == VesselDynamic.current_node_id)
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
                VesselDynamic.current_node_id.isnot(None),
                TransportNode.city.isnot(None),
                TransportNode.deleted_at.is_(None),
            )
        )
        .group_by(TransportNode.city, TransportNode.province)
    )

    # Step3: 只有 GPS（无节点）的船
    gps_result = await db.execute(
        select(
            VesselDynamic.current_longitude,
            VesselDynamic.current_latitude,
            Vessel.deadweight,
        )
        .join(Vessel, Vessel.id == VesselDynamic.vessel_id)
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
                VesselDynamic.current_node_id.is_(None),
                VesselDynamic.current_longitude.isnot(None),
                VesselDynamic.current_latitude.isnot(None),
            )
        )
    )

    # Step4: 合并统计
    city_buckets: dict[str, dict] = {}

    for row in node_agg_result.all():
        admin = city_by_name.get(row.city_name)
        key = row.city_name
        if key not in city_buckets:
            city_buckets[key] = {
                "city_code": admin.code if admin else "",
                "city_name": row.city_name,
                "province_name": row.province_name or "",
                "longitude": float(admin.longitude) if admin and admin.longitude else None,
                "latitude": float(admin.latitude) if admin and admin.latitude else None,
                "vessel_count": 0,
                "total_deadweight": 0.0,
            }
        city_buckets[key]["vessel_count"] += row.vessel_count
        city_buckets[key]["total_deadweight"] += float(row.total_deadweight or 0)

    for row in gps_result.all():
        matched = _find_nearest_city(
            float(row.current_longitude), float(row.current_latitude), city_list
        )
        if not matched:
            continue
        code, name, province_name, lon, lat = matched
        if name not in city_buckets:
            city_buckets[name] = {
                "city_code": code,
                "city_name": name,
                "province_name": province_name,
                "longitude": lon,
                "latitude": lat,
                "vessel_count": 0,
                "total_deadweight": 0.0,
            }
        city_buckets[name]["vessel_count"] += 1
        city_buckets[name]["total_deadweight"] += float(row.deadweight or 0)

    # Step5: 全量替换
    total = sum(b["vessel_count"] for b in city_buckets.values()) or 1
    now = datetime.now()
    new_rows = [
        ShipStatCity(
            **{k: v for k, v in b.items()},
            ratio=round(b["vessel_count"] / total * 100, 3),
            refreshed_at=now,
        )
        for b in city_buckets.values()
        if b["vessel_count"] > 0
    ]

    await db.execute(sa_delete(ShipStatCity))
    db.add_all(new_rows)
    await db.flush()
    logger.info(f"[stat_tasks] ship_city 刷新完成，城市数={len(new_rows)}")
    return len(new_rows)


async def _stat_ship_dwt(db: AsyncSession) -> int:
    """vessel.deadweight → ship_stat_dwt（载重吨分布快照）

    一次 SQL 查出所有分桶计数，Python 端拼装后全量替换。
    """
    from datetime import datetime
    from sqlalchemy import case, delete as sa_delete
    from app.models.vessel import Vessel
    from app.models.analysis import ShipStatDwt

    row = (await db.execute(
        select(
            func.count(Vessel.id).label("total"),
            func.sum(case(
                (and_(Vessel.deadweight.isnot(None), Vessel.deadweight < 500), 1),
                else_=0,
            )).label("lt_500"),
            func.sum(case(
                (and_(Vessel.deadweight >= 500, Vessel.deadweight < 1000), 1),
                else_=0,
            )).label("seg_500_1000"),
            func.sum(case(
                (and_(Vessel.deadweight >= 1000, Vessel.deadweight < 2000), 1),
                else_=0,
            )).label("seg_1000_2000"),
            func.sum(case(
                (and_(Vessel.deadweight >= 2000, Vessel.deadweight < 5000), 1),
                else_=0,
            )).label("seg_2000_5000"),
            func.sum(case(
                (Vessel.deadweight >= 5000, 1),
                else_=0,
            )).label("gte_5000"),
            func.sum(case(
                (Vessel.deadweight.is_(None), 1),
                else_=0,
            )).label("unknown"),
        )
        .where(and_(Vessel.data_status == 1, Vessel.is_deleted == 0))
    )).one()

    total = row.total or 1
    now = datetime.now()
    segments = [
        ("500吨以下",   None, 500,  int(row.lt_500 or 0)),
        ("500-1000吨",  500,  1000, int(row.seg_500_1000 or 0)),
        ("1000-2000吨", 1000, 2000, int(row.seg_1000_2000 or 0)),
        ("2000-5000吨", 2000, 5000, int(row.seg_2000_5000 or 0)),
        ("5000吨以上",  5000, None, int(row.gte_5000 or 0)),
        ("未录入",      None, None, int(row.unknown or 0)),
    ]

    await db.execute(sa_delete(ShipStatDwt))
    db.add_all([
        ShipStatDwt(
            segment_label=label,
            min_dwt=mn,
            max_dwt=mx,
            vessel_count=cnt,
            ratio=round(cnt / total * 100, 3),
            refreshed_at=now,
        )
        for label, mn, mx, cnt in segments
    ])
    await db.flush()
    logger.info(f"[stat_tasks] ship_dwt 刷新完成，总船数={row.total}")
    return len(segments)


async def _stat_ship_age(db: AsyncSession) -> int:
    """vessel.build_year → ship_stat_age（船龄分布快照）

    船龄 = 当前年份 - build_year，一次 SQL 查出所有分桶。
    """
    from datetime import datetime, date as date_cls
    from sqlalchemy import case, delete as sa_delete, literal
    from app.models.vessel import Vessel
    from app.models.analysis import ShipStatAge

    current_year = date_cls.today().year
    age_expr = literal(current_year) - Vessel.build_year

    row = (await db.execute(
        select(
            func.count(Vessel.id).label("total"),
            func.sum(case(
                (and_(Vessel.build_year.isnot(None), age_expr <= 5), 1),
                else_=0,
            )).label("age_0_5"),
            func.sum(case(
                (and_(Vessel.build_year.isnot(None), age_expr >= 6, age_expr <= 10), 1),
                else_=0,
            )).label("age_6_10"),
            func.sum(case(
                (and_(Vessel.build_year.isnot(None), age_expr >= 11, age_expr <= 15), 1),
                else_=0,
            )).label("age_11_15"),
            func.sum(case(
                (and_(Vessel.build_year.isnot(None), age_expr >= 16, age_expr <= 20), 1),
                else_=0,
            )).label("age_16_20"),
            func.sum(case(
                (and_(Vessel.build_year.isnot(None), age_expr > 20), 1),
                else_=0,
            )).label("age_over_20"),
            func.sum(case(
                (Vessel.build_year.is_(None), 1),
                else_=0,
            )).label("unknown"),
        )
        .where(and_(Vessel.data_status == 1, Vessel.is_deleted == 0))
    )).one()

    total = row.total or 1
    now = datetime.now()
    segments = [
        ("5年以内",  0,    5,    int(row.age_0_5 or 0)),
        ("6-10年",   6,    10,   int(row.age_6_10 or 0)),
        ("11-15年",  11,   15,   int(row.age_11_15 or 0)),
        ("16-20年",  16,   20,   int(row.age_16_20 or 0)),
        ("20年以上", 21,   None, int(row.age_over_20 or 0)),
        ("未知",     None, None, int(row.unknown or 0)),
    ]

    await db.execute(sa_delete(ShipStatAge))
    db.add_all([
        ShipStatAge(
            age_range_label=label,
            min_age=mn,
            max_age=mx,
            vessel_count=cnt,
            ratio=round(cnt / total * 100, 3),
            refreshed_at=now,
        )
        for label, mn, mx, cnt in segments
    ])
    await db.flush()
    logger.info(f"[stat_tasks] ship_age 刷新完成，总船数={row.total}")
    return len(segments)


# ─────────────────────────────────────────────────
# 船舶统计刷新入口（事件驱动）
# ─────────────────────────────────────────────────

async def refresh_vessel_static_stats() -> dict:
    """刷新船舶静态统计（vessel 数据变更时触发）

    覆盖：ship_stat_dwt、ship_stat_age
    调用方：vessel_service.py 的 CRUD/import 操作末尾
    """
    from app.core.database import AsyncSessionLocal

    logger.info("[stat_tasks] 开始刷新船舶静态统计")
    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            results["ship_stat_dwt"] = await _stat_ship_dwt(db)
            results["ship_stat_age"] = await _stat_ship_age(db)
            await db.commit()
            logger.info(f"[stat_tasks] 船舶静态统计刷新完成: {results}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 船舶静态统计刷新失败: {exc}", exc_info=True)
            raise
    return results


async def refresh_vessel_dynamic_stats() -> dict:
    """刷新船舶动态统计（Kafka AIS 更新后节流触发）

    覆盖：ship_stat_region、ship_stat_city
    调用方：vessel_dynamic_consumer.py（30s 节流）
    """
    from app.core.database import AsyncSessionLocal

    logger.info("[stat_tasks] 开始刷新船舶动态统计")
    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            results["ship_stat_region"] = await _stat_ship_region(db)
            results["ship_stat_city"] = await _stat_ship_city(db)
            await db.commit()
            logger.info(f"[stat_tasks] 船舶动态统计刷新完成: {results}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 船舶动态统计刷新失败: {exc}", exc_info=True)
            raise
    return results


async def refresh_all_vessel_stats() -> dict:
    """全量刷新船舶所有统计（管理员手动触发，忽略节流）

    覆盖：ship_stat_region、ship_stat_city、ship_stat_dwt、ship_stat_age
    """
    from app.core.database import AsyncSessionLocal

    logger.info("[stat_tasks] 开始全量刷新船舶统计")
    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            results["ship_stat_region"] = await _stat_ship_region(db)
            results["ship_stat_city"] = await _stat_ship_city(db)
            results["ship_stat_dwt"] = await _stat_ship_dwt(db)
            results["ship_stat_age"] = await _stat_ship_age(db)
            await db.commit()
            logger.info(f"[stat_tasks] 船舶全量统计刷新完成: {results}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 船舶全量统计刷新失败: {exc}", exc_info=True)
            raise
    return results


# ─────────────────────────────────────────────────
# 管理员手动全量重跑接口（同时刷新货源+船舶）
# ─────────────────────────────────────────────────

async def daily_stat_job(target_date: Optional[date] = None) -> dict:
    """手动触发全量统计（管理员使用，同时刷新货源+船舶）"""
    from app.core.database import AsyncSessionLocal

    stat_date = target_date or date.today()
    logger.info(f"[stat_tasks] 全量统计 date={stat_date}")

    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            results["city_heatmap_rows"] = await _stat_cargo_city_heatmap(db, stat_date)
            await _stat_cargo_daily(db, stat_date)
            results["cargo_stat_daily"] = True
            await _stat_cargo_commodity(db, stat_date)
            results["cargo_commodity_stat"] = True
            await _stat_cargo_od(db, stat_date)
            results["cargo_od_stat"] = True
            await _stat_cargo_channel(db, stat_date)
            results["cargo_channel_stat"] = True
            # 船舶统计（快照模式，不需要 stat_date）
            results["ship_stat_region"] = await _stat_ship_region(db)
            results["ship_stat_city"] = await _stat_ship_city(db)
            results["ship_stat_dwt"] = await _stat_ship_dwt(db)
            results["ship_stat_age"] = await _stat_ship_age(db)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 全量统计失败 date={stat_date}: {exc}", exc_info=True)
            raise

    results["stat_date"] = str(stat_date)
    return results
