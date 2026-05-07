from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.core.exceptions import ValidationError
from app.models.address import AdminRegion, Region, RegionCityRelation, TransportNode
from app.models.base import Base
from app.models.commodity import CommodityCategory, CommodityStandard, CommodityType
from app.models.common import CodeSequence
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightClue
from app.modules.freight import service as freight_service_module
from app.modules.freight.schemas import (
    FreightBatchCreateRequest,
    FreightCandidateConfirmRequest,
    FreightTmsInboundCreateRequest,
)
from app.modules.freight.service import FreightBatchTaskService, FreightCandidateService, FreightTmsInboundService


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


class FakeFreightParser:
    segments: list[dict] = []
    prompt_version = "test_prompt_v2"
    last_source_type: str | None = None

    def __init__(self, runtime_config) -> None:
        self.runtime_config = runtime_config

    async def parse(self, raw_content: str, *, source_type_code: str = "WECHAT"):
        self.__class__.last_source_type = source_type_code
        return SimpleNamespace(
            segments=list(self.__class__.segments),
            prompt_version=self.__class__.prompt_version,
            parsed_payload={"segments": list(self.__class__.segments), "source": raw_content},
            raw_response={"ok": True},
        )


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        await _seed_foundation(db)
        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def fake_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeFreightParser.segments = []
    FakeFreightParser.prompt_version = "test_prompt_v2"
    FakeFreightParser.last_source_type = None
    monkeypatch.setattr(freight_service_module, "DashScopeQwenFreightParserClient", FakeFreightParser)


async def _seed_foundation(session: AsyncSession) -> None:
    for biz_code, prefix, target_table, target_column in (
        ("FREIGHT_BATCH_NO", "FBT", "freight_batch_task", "batch_no"),
        ("FREIGHT_TMS_INBOUND_NO", "FTI", "freight_tms_inbound", "inbound_no"),
        ("FREIGHT_CLUE_NO", "FCU", "freight_clue", "clue_no"),
        ("FREIGHT_CANDIDATE_NO", "FCA", "freight_candidate", "candidate_no"),
        ("FREIGHT_NO", "FR", "freight", "freight_no"),
    ):
        session.add(
            CodeSequence(
                biz_code=biz_code,
                biz_name=biz_code,
                target_table=target_table,
                target_column=target_column,
                prefix=prefix,
                date_format=None,
                separator=None,
                current_value=0,
                value_length=4,
                step=1,
                reset_rule="NONE",
                is_enabled=True,
            )
        )

    city_a = AdminRegion(code="320100", name="南京市", short_name="南京", level=2, province_code="320000", city_code="320100", status=1)
    city_b = AdminRegion(code="340200", name="芜湖市", short_name="芜湖", level=2, province_code="340000", city_code="340200", status=1)
    session.add_all([city_a, city_b])
    await session.flush()

    region = Region(code="RG-TEST", name="长江下游", region_type_code="SHIPPING_ANALYSIS_REGION", status=1, audit_status="APPROVED")
    session.add(region)
    await session.flush()
    session.add_all(
        [
            RegionCityRelation(region_id=region.id, city_region_id=city_a.id, relation_type_code="PRIMARY", is_primary=True),
            RegionCityRelation(region_id=region.id, city_region_id=city_b.id, relation_type_code="PRIMARY", is_primary=True),
        ]
    )

    node_a = TransportNode(
        code="ND-NJ",
        name="南京港",
        short_name="南京港",
        node_type_code="PORT",
        province_code="320000",
        city_code="320100",
        city_region_id=city_a.id,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    node_b = TransportNode(
        code="ND-WH",
        name="芜湖港",
        short_name="芜湖港",
        node_type_code="PORT",
        province_code="340000",
        city_code="340200",
        city_region_id=city_b.id,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    session.add_all([node_a, node_b])

    category = CommodityCategory(code="CC-BULK", name="散货", audit_status="APPROVED")
    session.add(category)
    await session.flush()
    commodity_type = CommodityType(category_id=category.id, code="CT-COAL", name="煤炭", audit_status="APPROVED")
    session.add(commodity_type)
    await session.flush()
    commodity = CommodityStandard(
        type_id=commodity_type.id,
        code="CS-COAL",
        name="动力煤",
        short_name="煤炭",
        main_unit_code="TON",
        is_active=True,
        audit_status="APPROVED",
    )
    session.add(commodity)
    await session.commit()


def _segment(**overrides) -> dict:
    payload = {
        "raw_text": "南京港装动力煤1000吨到芜湖港，运价42元/吨，联系王经理13800000000",
        "cargo_title": "南京港至芜湖港动力煤",
        "commodity_name": "动力煤",
        "origin_text": "南京港",
        "destination_text": "芜湖港",
        "estimated_tonnage": 1000,
        "unit_price": "42",
        "price_unit": "元/吨",
        "contact_name": "王经理",
        "contact_phone": "13800000000",
        "confidence_score": 0.91,
        "context_summary": "完整货源线索",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_wechat_parse_creates_matched_candidate(session: AsyncSession) -> None:
    FakeFreightParser.segments = [_segment()]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="群消息：南京港装动力煤到芜湖港"), creator_id=7)
    detail = await service.parse(batch.id, requested_by=7)

    assert FakeFreightParser.last_source_type == "WECHAT"
    assert detail.batch.status_code == "PARSED"
    assert detail.batch.prompt_version == "test_prompt_v2"
    assert len(detail.clues) == 1
    assert len(detail.candidates) == 1
    candidate = detail.candidates[0]
    assert candidate.source_batch_id == batch.id
    assert candidate.raw_origin_text == "南京港"
    assert candidate.origin_node_name == "南京港"
    assert candidate.destination_node_name == "芜湖港"
    assert candidate.commodity_standard_name == "动力煤"


@pytest.mark.asyncio
async def test_tms_inbound_is_idempotent_and_parses_multiple_waybills(session: AsyncSession) -> None:
    FakeFreightParser.segments = [
        _segment(source_ref_no="TMS-001"),
        _segment(source_ref_no="TMS-002", estimated_tonnage=1500, unit_price="45"),
    ]

    payload = FreightTmsInboundCreateRequest(
        idempotency_key="tms:test:001",
        external_ref_no="TMS-001",
        payload_json={"waybills": [{"waybillNo": "TMS-001"}, {"waybillNo": "TMS-002"}]},
        raw_content="两条标准运单",
    )
    service = FreightTmsInboundService(session)
    first = await service.create(payload)
    second = await service.create(payload)
    detail = await service.parse(first.id)

    assert first.id == second.id
    assert FakeFreightParser.last_source_type == "TMS"
    assert detail.inbound.status_code == "PARSED"
    assert detail.inbound.candidate_count == 2
    assert [item.source_ref_no for item in detail.candidates] == ["TMS-001", "TMS-002"]


@pytest.mark.asyncio
async def test_candidate_confirm_blocks_missing_required_fields(session: AsyncSession) -> None:
    candidate = FreightCandidate(
        candidate_no="FCA-BLOCK",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        cargo_title="缺少标准货品",
        status_code="PENDING",
        origin_province_code="320000",
        origin_city_code="320100",
        destination_province_code="340000",
        destination_city_code="340200",
    )
    session.add(candidate)
    await session.commit()

    with pytest.raises(ValidationError):
        await FreightCandidateService(session).confirm(candidate.id, FreightCandidateConfirmRequest(remark="确认"), operator_id=1)


@pytest.mark.asyncio
async def test_candidate_confirm_writes_formal_freight_with_source_trace(session: AsyncSession) -> None:
    commodity = await session.scalar(select(CommodityStandard).where(CommodityStandard.code == "CS-COAL"))
    origin = await session.scalar(select(TransportNode).where(TransportNode.code == "ND-NJ"))
    destination = await session.scalar(select(TransportNode).where(TransportNode.code == "ND-WH"))
    batch = FreightBatchTask(batch_no="FBT-SOURCE", source_type_code="WECHAT", source_channel_code="WECHAT_TEXT", raw_text="南京港到芜湖港", status_code="PARSED")
    session.add(batch)
    await session.flush()
    clue = FreightClue(
        clue_no="FCU-SOURCE",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        source_batch_id=batch.id,
        segment_index=1,
        raw_text="南京港装动力煤1000吨到芜湖港",
        status_code="CANDIDATE_CREATED",
    )
    session.add(clue)
    await session.flush()
    candidate = FreightCandidate(
        candidate_no="FCA-READY",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        source_batch_id=batch.id,
        clue_id=clue.id,
        source_ref_no="WX-001",
        raw_text=clue.raw_text,
        cargo_title="南京港至芜湖港动力煤",
        commodity_standard_id=commodity.id,
        estimated_tonnage=Decimal("1000"),
        unit_price=Decimal("42"),
        price_unit="元/吨",
        origin_node_id=origin.id,
        destination_node_id=destination.id,
        origin_province_code=origin.province_code,
        origin_city_code=origin.city_code,
        destination_province_code=destination.province_code,
        destination_city_code=destination.city_code,
        origin_region_id_cache=1,
        destination_region_id_cache=1,
        contact_name="王经理",
        contact_phone="13800000000",
        confidence_score=Decimal("0.91"),
        completeness_score=Decimal("1.00"),
        status_code="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(candidate)
    await session.commit()

    freight = await FreightCandidateService(session).confirm(
        candidate.id,
        FreightCandidateConfirmRequest(remark="确认入库"),
        operator_id=99,
    )
    stored = await session.scalar(select(Freight).where(Freight.id == freight.id))
    refreshed_candidate = await session.scalar(select(FreightCandidate).where(FreightCandidate.id == candidate.id))

    assert stored is not None
    assert stored.source_batch_id == batch.id
    assert stored.source_clue_id == clue.id
    assert stored.source_candidate_id == candidate.id
    assert stored.hall_status_code == "NOT_LISTED"
    assert refreshed_candidate is not None
    assert refreshed_candidate.status_code == "CONFIRMED"
    assert refreshed_candidate.confirmed_freight_id == stored.id
