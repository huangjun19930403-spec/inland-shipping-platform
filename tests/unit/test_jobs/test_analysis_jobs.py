"""核心 analysis jobs tests（Phase 6）。"""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.jobs import cargo_stats, ship_stats
from app.models.address import AdminRegion, Region
from app.models.analysis import (
    CargoChannelDaily,
    CargoCityHeatmap,
    CargoCommodityStatDaily,
    CargoOdDaily,
    ShipStatAge,
    ShipStatCity,
    ShipStatDwt,
    ShipStatRegion,
)
from app.models.cargo import CargoFreight, CommodityCategory, CommodityStandard, CommodityType
from app.models.vessel import Vessel, VesselDynamic


@pytest.mark.asyncio
async def test_run_cargo_stats_generates_daily_rows(session_factory, db_session, monkeypatch):
    stat_day = date.today()

    db_session.add_all(
        [
            AdminRegion(code="320100", name="南京市", level=2, longitude=118.78, latitude=32.04, status=1),
            AdminRegion(code="420100", name="武汉市", level=2, longitude=114.31, latitude=30.52, status=1),
        ]
    )
    await db_session.flush()

    cat = CommodityCategory(code="CAT-01", name="散货", status=1, audit_status=1)
    db_session.add(cat)
    await db_session.flush()

    ctype = CommodityType(category_id=cat.id, code="T-01", name="煤炭", status=1, audit_status=1)
    db_session.add(ctype)
    await db_session.flush()

    std = CommodityStandard(type_id=ctype.id, code="STD-01", name="动力煤", status=1, audit_status=1)
    db_session.add(std)
    await db_session.flush()

    db_session.add(
        CargoFreight(
            freight_no="CS-TEST-0001",
            source_type="MANUAL",
            status="CONFIRMED",
            record_source="MANUAL",
            record_status="ACTIVE",
            analysis_status="READY",
            is_test_data=0,
            origin_admin_code="320100",
            origin_admin_name="南京市",
            dest_admin_code="420100",
            dest_admin_name="武汉市",
            origin_precision="CITY",
            dest_precision="CITY",
            commodity_id=std.id,
            tonnage=1200,
            created_at=datetime.now(),
        )
    )
    await db_session.commit()

    monkeypatch.setattr(cargo_stats, "AsyncSessionLocal", session_factory)
    result = await cargo_stats.run_cargo_stats(stat_day)
    assert result["cargo_heatmap_rows"] >= 2
    assert result["cargo_commodity_rows"] >= 1
    assert result["cargo_od_rows"] >= 1

    heatmap_rows = (
        await db_session.execute(
            select(CargoCityHeatmap).where(CargoCityHeatmap.stat_date == stat_day)
        )
    ).scalars().all()
    assert len(heatmap_rows) >= 2

    channel_rows = (
        await db_session.execute(
            select(CargoChannelDaily).where(CargoChannelDaily.stat_date == stat_day)
        )
    ).scalars().all()
    assert len(channel_rows) >= 3

    commodity_rows = (
        await db_session.execute(
            select(CargoCommodityStatDaily).where(CargoCommodityStatDaily.stat_date == stat_day)
        )
    ).scalars().all()
    assert len(commodity_rows) >= 1

    od_rows = (
        await db_session.execute(select(CargoOdDaily).where(CargoOdDaily.stat_date == stat_day))
    ).scalars().all()
    assert len(od_rows) >= 1


@pytest.mark.asyncio
async def test_run_ship_stats_generates_snapshot_rows(session_factory, db_session, monkeypatch):
    db_session.add(AdminRegion(code="320000", name="江苏省", level=1, status=1))
    db_session.add(
        AdminRegion(
            code="320100",
            name="南京市",
            level=2,
            parent_code="320000",
            longitude=118.78,
            latitude=32.04,
            status=1,
        )
    )
    await db_session.flush()

    region = Region(
        code="RG-001",
        name="苏皖区域",
        status=1,
        boundary_coordinates=[
            [118.0, 31.0],
            [119.5, 31.0],
            [119.5, 33.0],
            [118.0, 33.0],
        ],
        center_longitude=118.75,
        center_latitude=32.0,
    )
    db_session.add(region)
    await db_session.flush()

    vessel = Vessel(
        vessel_no="VS-TEST-0001",
        vessel_name="测试船舶A",
        mmsi="413000111",
        deadweight=1800,
        build_year=2018,
        data_status=1,
        is_deleted=0,
        audit_status=1,
    )
    db_session.add(vessel)
    await db_session.flush()

    db_session.add(
        VesselDynamic(
            vessel_id=vessel.id,
            mmsi=vessel.mmsi,
            current_longitude=118.90,
            current_latitude=32.05,
            current_region_id=region.id,
            current_city_code="320100",
            data_source="AIS",
            vessel_status="UNDERWAY",
        )
    )
    await db_session.commit()

    monkeypatch.setattr(ship_stats, "AsyncSessionLocal", session_factory)
    result = await ship_stats.run_ship_stats()
    assert result["ship_stat_region"] >= 1
    assert result["ship_stat_city"] >= 1
    assert result["ship_stat_dwt"] >= 1
    assert result["ship_stat_age"] >= 1

    assert len((await db_session.execute(select(ShipStatRegion))).scalars().all()) >= 1
    assert len((await db_session.execute(select(ShipStatCity))).scalars().all()) >= 1
    assert len((await db_session.execute(select(ShipStatDwt))).scalars().all()) >= 1
    assert len((await db_session.execute(select(ShipStatAge))).scalars().all()) >= 1
