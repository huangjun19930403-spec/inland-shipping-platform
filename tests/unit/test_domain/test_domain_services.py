"""核心 domain/service tests（Phase 6）。"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.domain.address.service import AddressService
from app.domain.audit.service import AuditService
from app.domain.cargo.service import CargoService
from app.models.address import AdminRegion, Waterway
from app.models.audit import AuditTask
from app.repositories.address_repository import AddressRepository
from app.repositories.ai_repository import AiRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.cargo_repository import CargoRepository


@pytest.mark.asyncio
async def test_address_service_region_relation_tables_are_used(db_session):
    address_repo = AddressRepository(db_session)
    audit_svc = AuditService(audit_repo=AuditRepository(db_session))
    service = AddressService(address_repo=address_repo, audit_svc=audit_svc)

    waterway = await address_repo.create_waterway(
        Waterway(code="WW-TEST-001", name="测试水系", level=1, status=1)
    )
    city = await address_repo.create_admin_region(
        AdminRegion(
            code="320100",
            name="南京市",
            level=2,
            longitude=118.78,
            latitude=32.04,
            status=1,
        )
    )
    await address_repo.save()

    region = await service.create_region(
        name="测试商业区域",
        operator_id=1,
        waterway_ids=[waterway.id],
        boundary_coordinates=[
            [118.0, 31.5],
            [119.2, 31.5],
            [119.2, 32.6],
            [118.0, 32.6],
        ],
    )

    waterway_map, city_map = await address_repo.list_region_relation_maps([region.id])
    assert waterway.id in waterway_map[region.id]
    assert city.id in city_map[region.id]


@pytest.mark.asyncio
async def test_cargo_service_create_manual_freight_writes_audit_snapshot(db_session):
    cargo_repo = CargoRepository(db_session)
    address_repo = AddressRepository(db_session)
    audit_svc = AuditService(audit_repo=AuditRepository(db_session))
    ai_repo = AiRepository(db_session)
    service = CargoService(
        cargo_repo=cargo_repo,
        address_repo=address_repo,
        audit_svc=audit_svc,
        ai_repo=ai_repo,
    )

    freight = await service.create_manual_freight(
        operator_id=1,
        origin_admin_code="320100",
        origin_admin_name="南京市",
        origin_raw_text="南京",
        dest_admin_code="420100",
        dest_admin_name="武汉市",
        dest_raw_text="武汉",
        commodity_text="煤炭",
        tonnage=1200.5,
        loading_date="2026-03-19",
        freight_price=80.0,
        source_type="MANUAL",
        record_source="MANUAL",
        record_status="ACTIVE",
        analysis_status="READY",
        data_quality_score=95.0,
        location_match_score=90.0,
        commodity_match_score=88.0,
        is_test_data=0,
        source_message_time=datetime(2026, 3, 19, 10, 0, 0),
    )

    assert freight.id is not None
    assert freight.record_status == "ACTIVE"
    assert float(freight.data_quality_score) == 95.0

    audit_tasks = (
        await db_session.execute(
            select(AuditTask).where(
                AuditTask.target_type == "CARGO_FREIGHT",
                AuditTask.target_id == freight.id,
            )
        )
    ).scalars().all()
    assert len(audit_tasks) == 1
