from __future__ import annotations

import json
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
from app.integrations.ai.dashscope_qwen_client import FreightClueSplitPayloadSchema, FreightParsePayloadSchema, _clue_schema_hint, _json_schema_hint
from app.models.address import AdminRegion, Region, RegionCityRelation, TransportNode
from app.models.base import Base
from app.models.commodity import CommodityCategory, CommodityStandard, CommodityType
from app.models.common import CodeSequence
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightClue, FreightNormalizationSuggestion
from app.modules.freight import service as freight_service_module
from app.modules.freight.schemas import (
    FreightBatchCreateRequest,
    FreightCandidateConfirmRequest,
    FreightTmsInboundCreateRequest,
)
from app.modules.freight.service import (
    FreightBatchTaskService,
    FreightCandidateService,
    FreightNormalizationSuggestionService,
    FreightTmsInboundService,
)


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

    async def parse(self, raw_content: str, *, source_type_code: str = "WECHAT", progress_callback=None):
        self.__class__.last_source_type = source_type_code
        if progress_callback is not None:
            await progress_callback("AI_EXTRACT", "AI 抽取字段", "测试解析进度", 50)
        return SimpleNamespace(
            segments=list(self.__class__.segments),
            prompt_version=self.__class__.prompt_version,
            parsed_payload={"segments": list(self.__class__.segments), "source": raw_content},
            raw_response={"ok": True},
            review_failed_count=0,
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
        "availability_status_code": "READY",
        "confidence_score": 0.91,
        "context_summary": "完整货源线索",
    }
    payload.update(overrides)
    return payload


def test_ai_parse_schema_normalizes_null_availability_status() -> None:
    payload = FreightParsePayloadSchema.model_validate(
        {
            "segments": [
                {
                    "raw_text": "建德—平湖：塘渣",
                    "cargo_title": "建德至平湖塘渣",
                    "commodity_name": "塘渣",
                    "origin_text": "建德",
                    "destination_text": "平湖",
                    "availability_status_code": None,
                    "confidence_score": None,
                    "evidence": None,
                    "needs_strong_review": None,
                }
            ]
        }
    )

    segment = payload.segments[0]
    assert segment.availability_status_code == "UNKNOWN"
    assert segment.confidence_score == 0.5
    assert segment.evidence == []
    assert segment.needs_strong_review is False


def test_ai_schema_hints_do_not_contain_real_example_values() -> None:
    hint_text = json.dumps({"extract": _json_schema_hint(), "split": _clue_schema_hint()}, ensure_ascii=False)

    assert "蒋姐" not in hint_text
    assert "15381664761" not in hint_text
    assert "建德" not in hint_text
    assert "平湖" not in hint_text


def test_wechat_split_schema_separates_freight_clues_and_context_notes() -> None:
    payload = FreightClueSplitPayloadSchema.model_validate(
        {
            "freight_clues": [
                {
                    "segment_index": 1,
                    "raw_text": "A地—B地：货品",
                    "context_summary": "继承公共运价和联系人",
                    "inherited_context": {"price": "公共运价", "contact": "公共联系人"},
                    "is_freight_candidate": True,
                    "evidence": ["路线", "货品", "公共联系人"],
                }
            ],
            "context_notes": [
                {
                    "note_index": 1,
                    "raw_text": "公共联系人",
                    "context_type_code": "CONTACT",
                    "applies_to": [1],
                    "evidence": ["跟随上一组路线"],
                }
            ],
        }
    )

    assert len(payload.freight_clues) == 1
    assert len(payload.context_notes) == 1
    assert payload.context_notes[0].context_type_code == "CONTACT"


@pytest.mark.asyncio
async def test_wechat_parse_creates_matched_candidate(session: AsyncSession) -> None:
    FakeFreightParser.segments = [_segment()]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="群消息：南京港装动力煤到芜湖港"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)

    assert FakeFreightParser.last_source_type == "WECHAT"
    assert detail.batch.status_code == "PARSED"
    assert detail.batch.prompt_version == "test_prompt_v2"
    assert detail.batch.parse_stage_code == "DONE"
    assert detail.batch.parse_progress_percent == 100
    assert detail.batch.ai_elapsed_seconds >= 0
    assert len(detail.clues) == 1
    assert len(detail.candidates) == 1
    candidate = detail.candidates[0]
    assert candidate.source_batch_id == batch.id
    assert candidate.raw_origin_text == "南京港"
    assert candidate.origin_node_name == "南京港"
    assert candidate.destination_node_name == "芜湖港"
    assert candidate.commodity_standard_name == "动力煤"
    assert candidate.availability_status_code == "READY"


@pytest.mark.asyncio
async def test_wechat_parse_ignores_context_only_segments(session: AsyncSession) -> None:
    FakeFreightParser.segments = [
        _segment(),
        {
            "segment_index": 2,
            "raw_text": "运费18元装卸快",
            "context_summary": "公共运价和装卸备注",
            "is_freight_candidate": False,
            "drop_reason": "上下文片段不能单独生成货源候选",
            "confidence_score": 0.9,
            "availability_status_code": "UNKNOWN",
        },
    ]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="路线和公共上下文"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.clue_count == 2
    assert detail.batch.candidate_count == 1
    assert len(detail.candidates) == 1
    assert [item.status_code for item in detail.clues].count("IGNORED") == 1


@pytest.mark.asyncio
async def test_wechat_shared_context_sample_creates_four_candidates(session: AsyncSession) -> None:
    FakeFreightParser.segments = [
        {
            "segment_index": index,
            "raw_text": raw_text,
            "context_summary": "继承下雨天正常装卸、运费18元装卸快、联系19521552671陈",
            "cargo_title": f"{origin} 至 {destination} {commodity}",
            "commodity_name": commodity,
            "origin_text": origin,
            "destination_text": destination,
            "unit_price": 18,
            "price_unit": "元/吨",
            "contact_name": "陈",
            "contact_phone": "19521552671",
            "availability_status_code": "READY",
            "confidence_score": 0.9,
            "evidence": [raw_text, "下雨天正常装卸", "运费18元装卸快", "联系19521552671陈"],
        }
        for index, (origin, destination, commodity, raw_text) in enumerate(
            [
                ("建德", "平湖", "塘渣", "建德—平湖：塘渣"),
                ("建德", "嘉兴", "塘渣", "建德—嘉兴：塘渣"),
                ("建德", "德清", "塘渣", "建德—德清：塘渣"),
                ("建德", "绍兴", "机沙", "建德—绍兴：机沙"),
            ],
            start=1,
        )
    ]
    raw_text = "群公告\n建德—平湖：塘渣\n建德—嘉兴：塘渣\n建德—德清：塘渣\n下雨天正常装卸\n建德—绍兴：机沙\n运费18元装卸快\n联系19521552671陈"

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text=raw_text), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 4
    assert {(item.raw_origin_text, item.raw_destination_text, item.raw_commodity_name) for item in detail.candidates} == {
        ("建德", "平湖", "塘渣"),
        ("建德", "嘉兴", "塘渣"),
        ("建德", "德清", "塘渣"),
        ("建德", "绍兴", "机沙"),
    }
    assert {item.contact_name for item in detail.candidates} == {"陈"}
    assert {item.contact_phone for item in detail.candidates} == {"19521552671"}
    assert "蒋姐" not in json.dumps([item.model_dump(mode="json") for item in detail.candidates], ensure_ascii=False)
    assert "15381664761" not in json.dumps([item.model_dump(mode="json") for item in detail.candidates], ensure_ascii=False)


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
    detail = await service.run_parse_now(first.id)

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
        cargo_title="缺少装卸地原文",
        status_code="PENDING",
        availability_status_code="READY",
    )
    session.add(candidate)
    await session.commit()

    with pytest.raises(ValidationError):
        await FreightCandidateService(session).confirm(candidate.id, FreightCandidateConfirmRequest(remark="确认"), operator_id=1)


@pytest.mark.asyncio
async def test_raw_level_candidate_can_confirm_without_standard_master_data(session: AsyncSession) -> None:
    candidate = FreightCandidate(
        candidate_no="FCA-RAW",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_origin_text="马鞍山",
        raw_destination_text="昆山",
        raw_commodity_name="矿粉",
        cargo_title="马鞍山至昆山矿粉",
        commodity_standard_id=None,
        commodity_match_level_code="RAW",
        origin_match_level_code="RAW",
        destination_match_level_code="RAW",
        availability_status_code="READY",
        status_code="PENDING",
    )
    session.add(candidate)
    await session.commit()

    freight = await FreightCandidateService(session).confirm(
        candidate.id,
        FreightCandidateConfirmRequest(remark="原文级确认"),
        operator_id=1,
    )
    stored = await session.scalar(select(Freight).where(Freight.id == freight.id))

    assert stored is not None
    assert stored.commodity_standard_id is None
    assert stored.origin_city_code is None
    assert stored.destination_city_code is None
    assert stored.raw_origin_text == "马鞍山"
    assert stored.raw_destination_text == "昆山"
    assert stored.raw_commodity_name == "矿粉"
    assert stored.origin_match_level_code == "RAW"


@pytest.mark.asyncio
async def test_candidate_confirm_blocks_non_ready_without_edit(session: AsyncSession) -> None:
    commodity = await session.scalar(select(CommodityStandard).where(CommodityStandard.code == "CS-COAL"))
    candidate = FreightCandidate(
        candidate_no="FCA-FULL",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        cargo_title="船已够线索",
        commodity_standard_id=commodity.id,
        status_code="PENDING",
        availability_status_code="FULL",
        manual_review_reason="原文显示船已经够了",
        origin_province_code="320000",
        origin_city_code="320100",
        destination_province_code="340000",
        destination_city_code="340200",
    )
    session.add(candidate)
    await session.commit()

    with pytest.raises(ValidationError, match="需要编辑确认"):
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
        raw_origin_text="南京港",
        raw_destination_text="芜湖港",
        raw_commodity_name="动力煤",
        cargo_title="南京港至芜湖港动力煤",
        commodity_standard_id=commodity.id,
        commodity_match_level_code="STANDARD",
        estimated_tonnage=Decimal("1000"),
        unit_price=Decimal("42"),
        price_unit="元/吨",
        origin_node_id=origin.id,
        destination_node_id=destination.id,
        origin_match_level_code="NODE",
        destination_match_level_code="NODE",
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
        availability_status_code="READY",
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
    assert stored.raw_origin_text == "南京港"
    assert stored.origin_match_level_code == "NODE"
    assert stored.commodity_match_level_code == "STANDARD"
    assert refreshed_candidate is not None
    assert refreshed_candidate.status_code == "CONFIRMED"
    assert refreshed_candidate.confirmed_freight_id == stored.id


@pytest.mark.asyncio
async def test_normalization_clean_auto_applies_high_confidence_raw_freight(session: AsyncSession) -> None:
    freight = Freight(
        freight_no="FR-RAW-0001",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_origin_text="南京港",
        raw_destination_text="芜湖港",
        raw_commodity_name="动力煤",
        cargo_title="南京港至芜湖港动力煤",
        commodity_standard_id=None,
        commodity_match_level_code="RAW",
        origin_match_level_code="RAW",
        destination_match_level_code="RAW",
        estimated_tonnage=Decimal("1000"),
        unit_price=Decimal("42"),
        price_unit="元/吨",
        status_code="PUBLISHED",
        published_at=datetime.utcnow(),
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
    )
    session.add(freight)
    await session.commit()

    result = await FreightNormalizationSuggestionService(session).clean(operator_id=2)
    stored = await session.scalar(select(Freight).where(Freight.id == freight.id))
    suggestions = (await session.execute(select(FreightNormalizationSuggestion))).scalars().all()

    assert result.auto_applied_count >= 3
    assert stored is not None
    assert stored.commodity_standard_id is not None
    assert stored.origin_city_code == "320100"
    assert stored.destination_city_code == "340200"
    assert {item.status_code for item in suggestions} == {"AUTO_APPLIED"}
