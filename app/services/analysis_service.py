"""统计分析服务"""
from typing import Optional, List
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.analysis import HeatmapStatDaily
from app.models.address import TransportNode
from app.models.cargo import CargoOpportunity
from app.models.vessel import Vessel, VesselDynamic
from app.models.route import ShippingRoute
from app.models.system import SysUser


async def get_dashboard_stats(db: AsyncSession) -> dict:
    """获取仪表盘统计数据"""
    from app.models.cargo import CommodityStandard

    # Nodes
    node_total = (await db.execute(select(func.count(TransportNode.id)))).scalar_one()
    node_approved = (await db.execute(
        select(func.count(TransportNode.id)).where(TransportNode.audit_status == 1)
    )).scalar_one()
    node_pending = (await db.execute(
        select(func.count(TransportNode.id)).where(TransportNode.audit_status == 0)
    )).scalar_one()

    # Commodities
    commodity_total = (await db.execute(select(func.count(CommodityStandard.id)))).scalar_one()

    # Vessels
    vessel_total = (await db.execute(
        select(func.count(Vessel.id)).where(Vessel.is_deleted == 0)
    )).scalar_one()
    vessel_approved = (await db.execute(
        select(func.count(Vessel.id)).where(and_(Vessel.audit_status == 1, Vessel.is_deleted == 0))
    )).scalar_one()
    vessel_pending = (await db.execute(
        select(func.count(Vessel.id)).where(and_(Vessel.audit_status == 0, Vessel.is_deleted == 0))
    )).scalar_one()

    # Routes
    route_total = (await db.execute(select(func.count(ShippingRoute.id)))).scalar_one()

    # Cargo
    today = date.today()
    today_cargo = (await db.execute(
        select(func.count(CargoOpportunity.id)).where(
            and_(
                func.date(CargoOpportunity.created_at) == today,
                CargoOpportunity.status == "CONFIRMED",
            )
        )
    )).scalar_one()
    total_cargo = (await db.execute(
        select(func.count(CargoOpportunity.id)).where(CargoOpportunity.status == "CONFIRMED")
    )).scalar_one()

    return {
        "total_nodes": node_total,
        "approved_nodes": node_approved,
        "pending_nodes": node_pending,
        "total_commodities": commodity_total,
        "total_vessels": vessel_total,
        "approved_vessels": vessel_approved,
        "pending_vessels": vessel_pending,
        "total_routes": route_total,
        "today_cargo": today_cargo,
        "total_cargo": total_cargo,
    }


async def get_cargo_heatmap(
    db: AsyncSession,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    stat_type: str = "CARGO_ORIGIN",
    region_id: Optional[int] = None,
) -> List[dict]:
    """获取货源热力数据"""
    query = select(
        HeatmapStatDaily,
        TransportNode.name.label("node_name"),
        TransportNode.longitude,
        TransportNode.latitude,
    ).join(TransportNode, HeatmapStatDaily.node_id == TransportNode.id)

    conditions = [HeatmapStatDaily.stat_type == stat_type]
    if start_date:
        conditions.append(HeatmapStatDaily.stat_date >= start_date)
    if end_date:
        conditions.append(HeatmapStatDaily.stat_date <= end_date)
    if region_id:
        conditions.append(TransportNode.region_id == region_id)

    query = query.where(and_(*conditions))
    result = await db.execute(query)
    rows = result.fetchall()

    return [
        {
            "stat_date": row.HeatmapStatDaily.stat_date,
            "node_id": row.HeatmapStatDaily.node_id,
            "node_name": row.node_name,
            "longitude": row.longitude,
            "latitude": row.latitude,
            "stat_type": row.HeatmapStatDaily.stat_type,
            "cargo_count": row.HeatmapStatDaily.cargo_count,
            "total_tonnage": row.HeatmapStatDaily.total_tonnage,
            "vessel_count": row.HeatmapStatDaily.vessel_count,
            "total_deadweight": row.HeatmapStatDaily.total_deadweight,
        }
        for row in rows
    ]


async def get_vessel_heatmap(
    db: AsyncSession, region_id: Optional[int] = None
) -> List[dict]:
    """获取船舶分布热力数据（基于最新动态）"""
    query = select(
        TransportNode.id.label("node_id"),
        TransportNode.name.label("node_name"),
        TransportNode.longitude,
        TransportNode.latitude,
        func.count(VesselDynamic.id).label("vessel_count"),
        func.sum(Vessel.deadweight).label("total_deadweight"),
    ).join(
        VesselDynamic, VesselDynamic.current_node_id == TransportNode.id
    ).join(
        Vessel, Vessel.id == VesselDynamic.vessel_id
    )

    if region_id:
        query = query.where(TransportNode.region_id == region_id)

    query = query.group_by(TransportNode.id, TransportNode.name, TransportNode.longitude, TransportNode.latitude)
    result = await db.execute(query)
    rows = result.fetchall()

    return [
        {
            "node_id": row.node_id,
            "node_name": row.node_name,
            "longitude": row.longitude,
            "latitude": row.latitude,
            "vessel_count": row.vessel_count,
            "total_deadweight": row.total_deadweight or 0,
        }
        for row in rows
    ]


async def get_cargo_trends(db: AsyncSession, days: int = 7) -> dict:
    """获取货源趋势数据（最近N天每日数量）"""
    items = []
    for i in range(days - 1, -1, -1):
        target_date = date.today() - timedelta(days=i)
        res = await db.execute(
            select(
                func.count(CargoOpportunity.id).label("count"),
                func.sum(CargoOpportunity.tonnage).label("total_tonnage"),
            ).where(
                and_(
                    func.date(CargoOpportunity.created_at) == target_date,
                    CargoOpportunity.status == "CONFIRMED",
                )
            )
        )
        row = res.fetchone()
        items.append({
            "date": target_date.strftime("%Y-%m-%d"),
            "count": row.count or 0,
            "total_tonnage": row.total_tonnage or Decimal("0"),
        })

    return {"items": items, "days": days}


async def get_top_nodes(
    db: AsyncSession, stat_type: str = "CARGO_ORIGIN", limit: int = 10
) -> dict:
    """获取货源最多的 Top N 节点"""
    # Aggregate from heatmap_stat_daily if available
    res = await db.execute(
        select(
            HeatmapStatDaily.node_id,
            TransportNode.name.label("node_name"),
            func.sum(HeatmapStatDaily.cargo_count).label("cargo_count"),
            func.sum(HeatmapStatDaily.total_tonnage).label("total_tonnage"),
        )
        .join(TransportNode, HeatmapStatDaily.node_id == TransportNode.id)
        .where(HeatmapStatDaily.stat_type == stat_type)
        .group_by(HeatmapStatDaily.node_id, TransportNode.name)
        .order_by(func.sum(HeatmapStatDaily.cargo_count).desc())
        .limit(limit)
    )
    rows = res.fetchall()

    items = [
        {
            "node_id": row.node_id,
            "node_name": row.node_name,
            "cargo_count": row.cargo_count or 0,
            "total_tonnage": row.total_tonnage or Decimal("0"),
        }
        for row in rows
    ]
    return {"stat_type": stat_type, "items": items}


async def run_daily_stats(db: AsyncSession, target_date: Optional[date] = None) -> dict:
    """聚合每日统计数据，写入 heatmap_stat_daily（UPSERT）"""
    if target_date is None:
        target_date = date.today()

    inserted = 0
    updated = 0

    # Aggregate CARGO_ORIGIN (by origin_node_id)
    origin_res = await db.execute(
        select(
            CargoOpportunity.origin_node_id.label("node_id"),
            func.count(CargoOpportunity.id).label("cargo_count"),
            func.sum(CargoOpportunity.tonnage).label("total_tonnage"),
        )
        .where(
            and_(
                func.date(CargoOpportunity.created_at) == target_date,
                CargoOpportunity.status == "CONFIRMED",
                CargoOpportunity.origin_node_id.isnot(None),
            )
        )
        .group_by(CargoOpportunity.origin_node_id)
    )
    origin_rows = origin_res.fetchall()

    for row in origin_rows:
        # Try update first, then insert
        existing_res = await db.execute(
            select(HeatmapStatDaily).where(
                and_(
                    HeatmapStatDaily.stat_date == target_date,
                    HeatmapStatDaily.node_id == row.node_id,
                    HeatmapStatDaily.stat_type == "CARGO_ORIGIN",
                )
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.cargo_count = row.cargo_count
            existing.total_tonnage = row.total_tonnage or Decimal("0")
            updated += 1
        else:
            stat = HeatmapStatDaily(
                stat_date=target_date,
                node_id=row.node_id,
                stat_type="CARGO_ORIGIN",
                cargo_count=row.cargo_count,
                total_tonnage=row.total_tonnage or Decimal("0"),
                vessel_count=0,
                total_deadweight=Decimal("0"),
            )
            db.add(stat)
            inserted += 1

    # Aggregate CARGO_DEST (by dest_node_id)
    dest_res = await db.execute(
        select(
            CargoOpportunity.dest_node_id.label("node_id"),
            func.count(CargoOpportunity.id).label("cargo_count"),
            func.sum(CargoOpportunity.tonnage).label("total_tonnage"),
        )
        .where(
            and_(
                func.date(CargoOpportunity.created_at) == target_date,
                CargoOpportunity.status == "CONFIRMED",
                CargoOpportunity.dest_node_id.isnot(None),
            )
        )
        .group_by(CargoOpportunity.dest_node_id)
    )
    dest_rows = dest_res.fetchall()

    for row in dest_rows:
        existing_res = await db.execute(
            select(HeatmapStatDaily).where(
                and_(
                    HeatmapStatDaily.stat_date == target_date,
                    HeatmapStatDaily.node_id == row.node_id,
                    HeatmapStatDaily.stat_type == "CARGO_DEST",
                )
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.cargo_count = row.cargo_count
            existing.total_tonnage = row.total_tonnage or Decimal("0")
            updated += 1
        else:
            stat = HeatmapStatDaily(
                stat_date=target_date,
                node_id=row.node_id,
                stat_type="CARGO_DEST",
                cargo_count=row.cargo_count,
                total_tonnage=row.total_tonnage or Decimal("0"),
                vessel_count=0,
                total_deadweight=Decimal("0"),
            )
            db.add(stat)
            inserted += 1

    # Aggregate VESSEL stats (by current_node_id from VesselDynamic)
    vessel_res = await db.execute(
        select(
            VesselDynamic.current_node_id.label("node_id"),
            func.count(VesselDynamic.id).label("vessel_count"),
            func.sum(Vessel.deadweight).label("total_deadweight"),
        )
        .join(Vessel, Vessel.id == VesselDynamic.vessel_id)
        .where(VesselDynamic.current_node_id.isnot(None))
        .group_by(VesselDynamic.current_node_id)
    )
    vessel_rows = vessel_res.fetchall()

    for row in vessel_rows:
        existing_res = await db.execute(
            select(HeatmapStatDaily).where(
                and_(
                    HeatmapStatDaily.stat_date == target_date,
                    HeatmapStatDaily.node_id == row.node_id,
                    HeatmapStatDaily.stat_type == "VESSEL",
                )
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.vessel_count = row.vessel_count
            existing.total_deadweight = row.total_deadweight or Decimal("0")
            updated += 1
        else:
            stat = HeatmapStatDaily(
                stat_date=target_date,
                node_id=row.node_id,
                stat_type="VESSEL",
                cargo_count=0,
                total_tonnage=Decimal("0"),
                vessel_count=row.vessel_count,
                total_deadweight=row.total_deadweight or Decimal("0"),
            )
            db.add(stat)
            inserted += 1

    await db.flush()
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
    }
