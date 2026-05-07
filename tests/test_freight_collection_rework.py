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
from app.integrations.ai.dashscope_qwen_client import (
    FreightClueSplitPayloadSchema,
    FreightParsePayloadSchema,
    _apply_context_blocks_to_segments,
    _clue_schema_hint,
    _json_schema_hint,
    _prepare_segments,
)
from app.models.address import AdminRegion, Region, RegionCityRelation, TransportNode
from app.models.base import Base
from app.models.commodity import CommodityCategory, CommodityStandard, CommodityType
from app.models.common import CodeSequence
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightClue, FreightNormalizationSuggestion, FreightNormalizationTask
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
        ("FREIGHT_NORMALIZATION_TASK_NO", "FNT", "freight_normalization_task", "task_no"),
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
        "raw_tonnage_text": "1000吨",
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
            "context_blocks": [
                {
                    "context_block_id": "B1",
                    "route_clue_ids": [1],
                    "shared_contact_name": "王经理",
                    "shared_contact_phone": "13900000000",
                    "evidence": ["公共联系人"],
                    "scope_reason": "联系人位于同一连续公告块",
                }
            ],
        }
    )

    assert len(payload.freight_clues) == 1
    assert len(payload.context_blocks) == 1
    assert len(payload.context_notes) == 1
    assert payload.context_notes[0].context_type_code == "CONTACT"


def test_context_blocks_inherit_trailing_contact_to_all_segments() -> None:
    segments, warnings = _apply_context_blocks_to_segments(
        [
            {"segment_index": 1, "context_block_id": "B1", "raw_text": "泰州姜堰一一盐城阜宁1200吨左右", "origin_text": "泰州姜堰", "destination_text": "盐城阜宁", "commodity_name": "货源"},
            {"segment_index": 2, "context_block_id": "B1", "raw_text": "马鞍山——灌南，石子，1500吨左右", "origin_text": "马鞍山", "destination_text": "灌南", "commodity_name": "石子"},
        ],
        [
            {
                "context_block_id": "B1",
                "route_clue_ids": [1, 2],
                "shared_contact_name": "小王",
                "shared_contact_phone": "18205543462",
                "evidence": ["电话☎️ 18205543462小王"],
                "scope_reason": "末尾联系人覆盖同一连续公告块",
            }
        ],
    )

    assert warnings
    assert {item["contact_phone"] for item in segments} == {"18205543462"}
    assert {item["contact_name"] for item in segments} == {"小王"}
    assert all(item["inherited_context"]["contact"] == "小王 18205543462" for item in segments)


def test_context_blocks_do_not_auto_inherit_shared_tonnage() -> None:
    segments, warnings = _apply_context_blocks_to_segments(
        [
            {
                "segment_index": 1,
                "context_block_id": "B1",
                "raw_text": "济宁到绍兴吨包50米船",
                "origin_text": "济宁",
                "destination_text": "绍兴",
                "commodity_name": "吨包",
            }
        ],
        [
            {
                "context_block_id": "B1",
                "route_clue_ids": [1],
                "shared_tonnage_text": "2000-2500吨、800-950",
                "shared_contact_phone": "13562723159",
                "evidence": ["13562723159"],
                "scope_reason": "同一公告块联系人覆盖路线；吨位仅作为候选上下文",
            }
        ],
    )

    assert segments[0].get("contact_phone") == "13562723159"
    assert segments[0].get("raw_tonnage_text") is None
    assert any("公共吨位" in item for item in warnings)


def test_wechat_split_schema_accepts_route_clues_missing_commodity() -> None:
    payload = FreightClueSplitPayloadSchema.model_validate(
        {
            "route_clues": [
                {
                    "segment_index": 1,
                    "raw_text": "怀远安澜一泗洪双沟，要船",
                    "origin_text": "怀远安澜",
                    "destination_text": "泗洪双沟",
                    "commodity_name": None,
                    "missing_field_codes": ["COMMODITY"],
                    "origin_match_level_code": "RAW",
                    "destination_match_level_code": "RAW",
                    "is_freight_candidate": True,
                    "evidence": ["怀远安澜一泗洪双沟"],
                }
            ],
            "context_notes": [],
            "ignored_notes": [{"raw_text": "寻船", "drop_reason": "公告标题"}],
        }
    )

    assert len(payload.freight_clues) == 1
    assert payload.freight_clues[0].commodity_name is None
    assert payload.freight_clues[0].missing_field_codes == ["COMMODITY"]


def test_prepare_segments_keeps_route_semantics_even_when_route_field_unstable() -> None:
    accepted, ignored, warnings = _prepare_segments(
        "镇江95号——巢湖 合肥沙子",
        [
            {
                "segment_index": 1,
                "semantic_role_code": "ROUTE",
                "raw_text": "镇江95号——巢湖 合肥沙子",
                "origin_text": "镇江95号",
                "destination_text": None,
                "commodity_name": "沙子",
                "availability_status_code": "READY",
                "confidence_score": 0.78,
            }
        ],
    )

    assert len(accepted) == 1
    assert ignored == []
    assert accepted[0]["availability_status_code"] == "UNKNOWN"
    assert accepted[0]["needs_strong_review"] is True
    assert any("路线字段不完整" in item for item in warnings)


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
async def test_wechat_parse_keeps_route_clue_missing_commodity_for_manual_completion(session: AsyncSession) -> None:
    FakeFreightParser.segments = [
        {
            "segment_index": 1,
            "raw_text": "怀远安澜一泗洪双沟，要船",
            "cargo_title": "怀远安澜 至 泗洪双沟 待补货品",
            "commodity_name": None,
            "origin_text": "怀远安澜",
            "destination_text": "泗洪双沟",
            "availability_status_code": "READY",
            "confidence_score": 0.72,
            "evidence": ["怀远安澜一泗洪双沟"],
        }
    ]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="寻船\n怀远安澜一泗洪双沟，要船"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 1
    candidate = detail.candidates[0]
    assert candidate.raw_origin_text == "怀远安澜"
    assert candidate.raw_destination_text == "泗洪双沟"
    assert candidate.raw_commodity_name is None
    assert candidate.availability_status_code == "UNKNOWN"
    assert "缺少货品" in (candidate.manual_review_reason or "")


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
async def test_wechat_tonnage_sample_persists_range_and_raw_tonnage(session: AsyncSession) -> None:
    sample_rows = [
        ("马鞍山当涂", "淮安黑山路", "石子", "1500-2000内", None, 1500, 2000),
        ("池州牛头山", "淮安杨庄闸", "石子", "2000左右", 2000, None, None),
        ("池州长久", "宿迁", "瓜子片", "2000吨", 2000, None, None),
        ("铜陵", "凤阳", "石英沙", "2000吨左右船", 2000, None, None),
        ("池州251", "南通七号桥", "石子", "1500-2000左右", None, 1500, 2000),
        ("武穴亚东", "洪泽九牛", "石粉", "2-3500吨", None, 2000, 3500),
        ("巢湖", "宿迁", "石英沙", "2000吨左右", 2000, None, None),
        ("黄岗", "盱眙", "水渣", "2000--2500吨", None, 2000, 2500),
        ("阳新华新", "靖江金桥", "石子", "7500左右", 7500, None, None),
    ]
    FakeFreightParser.segments = [
        {
            "segment_index": index,
            "raw_text": f"{origin}—{destination} {commodity} {raw_tonnage}",
            "context_summary": "继承公共联系人 18155088770",
            "cargo_title": f"{origin} 至 {destination} {commodity}",
            "commodity_name": commodity,
            "origin_text": origin,
            "destination_text": destination,
            "raw_tonnage_text": raw_tonnage,
            "estimated_tonnage": estimated,
            "min_tonnage": min_tonnage,
            "max_tonnage": max_tonnage,
            "contact_phone": "18155088770",
            "availability_status_code": "READY",
            "confidence_score": 0.87,
            "evidence": [f"{origin}—{destination} {commodity} {raw_tonnage}", "18155088770"],
        }
        for index, (origin, destination, commodity, raw_tonnage, estimated, min_tonnage, max_tonnage) in enumerate(sample_rows, start=1)
    ]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="微信群吨位样例\n18155088770"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 9
    by_route = {(item.raw_origin_text, item.raw_destination_text): item for item in detail.candidates}
    assert by_route[("马鞍山当涂", "淮安黑山路")].raw_tonnage_text == "1500-2000内"
    assert by_route[("马鞍山当涂", "淮安黑山路")].min_tonnage == Decimal("1500.00")
    assert by_route[("马鞍山当涂", "淮安黑山路")].max_tonnage == Decimal("2000.00")
    assert by_route[("池州牛头山", "淮安杨庄闸")].estimated_tonnage == Decimal("2000.00")
    assert by_route[("武穴亚东", "洪泽九牛")].raw_tonnage_text == "2-3500吨"
    assert by_route[("武穴亚东", "洪泽九牛")].min_tonnage == Decimal("2000.00")
    assert by_route[("武穴亚东", "洪泽九牛")].max_tonnage == Decimal("3500.00")
    assert by_route[("黄岗", "盱眙")].min_tonnage == Decimal("2000.00")
    assert by_route[("黄岗", "盱眙")].max_tonnage == Decimal("2500.00")
    assert by_route[("阳新华新", "靖江金桥")].estimated_tonnage == Decimal("7500.00")
    assert {item.contact_phone for item in detail.candidates} == {"18155088770"}


@pytest.mark.asyncio
async def test_wechat_group_notice_humanized_parse_keeps_tonnage_on_own_line(session: AsyncSession) -> None:
    rows = [
        ("济宁", "泰州", "货源", "700—1400", None, 700, 1400, None),
        ("江阴", "高邮", "货源", "1200吨", 1200, None, None, None),
        ("微山", "扬州仪征", "吨包", "2000-2500吨", None, 2000, 2500, None),
        ("济宁", "绍兴", "吨包", None, None, None, None, "50米船"),
        ("万丰", "丹阳", "焦炭", None, None, None, None, "拖队一条"),
        ("嘉祥", "如东", "货源", "800–950", None, 800, 950, None),
        ("微山鱼台", "张家港永兴", "货源", "800–1300", None, 800, 1300, None),
        ("微山，鱼台", "南浔至桐乡", "货源", "800–1300", None, 800, 1300, None),
        ("微山，鱼台", "如东", "货源", "650–900", None, 650, 900, None),
        ("济宁", "高邮", "货源", "800–1400", None, 800, 1400, None),
        ("鱼台", "盱眙", "货", "1000–1500", None, 1000, 1500, None),
        ("鱼台", "宝应", "货源", "2000–3000", None, 2000, 3000, None),
        ("滕州", "阜宁", "货源", "600–1200", None, 600, 1200, None),
        ("鱼台", "如皋", "货源", "800–1100", None, 800, 1100, None),
        ("六干河", "阜宁", "货源", "800-1500", None, 800, 1500, None),
        ("上海", "盐城", "货源", "800–1800", None, 800, 1800, None),
        ("微山.宋闸.滕州.枣庄", "巨野，万丰", "货源", "800–2000", None, 800, 2000, None),
        ("济宁", "泰兴", "货源", "700–1000", None, 700, 1000, None),
    ]
    FakeFreightParser.segments = [
        {
            "segment_index": index,
            "semantic_role_code": "ROUTE",
            "line_refs": [index + 1],
            "raw_text": f"{origin}至{destination}{commodity}{raw_tonnage or vessel or ''}",
            "cargo_title": f"{origin} 至 {destination} {commodity}",
            "cargo_description": vessel,
            "commodity_name": commodity,
            "origin_text": origin,
            "destination_text": destination,
            "raw_tonnage_text": raw_tonnage,
            "estimated_tonnage": estimated,
            "min_tonnage": min_tonnage,
            "max_tonnage": max_tonnage,
            "quantity_description": vessel,
            "vessel_description": vessel,
            "contact_phone": "13562723159",
            "availability_status_code": "READY",
            "confidence_score": 0.9,
            "evidence": [f"{origin}至{destination}{commodity}{raw_tonnage or vessel or ''}", "13562723159"],
            "tonnage_decision": {
                "status_code": "PASS",
                "selected_text": raw_tonnage,
                "reason": "吨位来自本行" if raw_tonnage else "本行只有船型/拖队描述，不应误入吨位",
            },
        }
        for index, (origin, destination, commodity, raw_tonnage, estimated, min_tonnage, max_tonnage, vessel) in enumerate(rows, start=1)
    ]
    raw_text = """群公告
济宁至泰州700—1400
江阴到高邮1200吨
微山到扬州仪征吨包2000-2500吨
济宁到绍兴吨包50米船
万丰到丹阳焦炭拖队一条
嘉祥至如东800–950
微山鱼台至张家港永兴800–1300
微山，鱼台至南浔至桐乡800–1300
微山，鱼台至如东650–900
济宁至高邮800–1400
鱼台至盱眙货1000–1500
鱼台至宝应2000–3000
滕州至阜宁600–1200
鱼台至如皋800–1100
六干河至阜宁800-1500
上海至盐城800–1800
微山.宋闸.滕州.枣庄至巨野，万丰800–2000
济宁至泰兴700–1000
13562723159"""

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text=raw_text), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)
    by_route = {(item.raw_origin_text, item.raw_destination_text): item for item in detail.candidates}

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 18
    assert ("济宁", "泰州") in by_route
    assert by_route[("济宁", "泰州")].min_tonnage == Decimal("700.00")
    assert by_route[("微山", "扬州仪征")].raw_tonnage_text == "2000-2500吨"
    assert by_route[("微山", "扬州仪征")].max_tonnage == Decimal("2500.00")
    assert by_route[("济宁", "绍兴")].raw_tonnage_text is None
    assert by_route[("济宁", "绍兴")].ai_review_status_code == "PASS"
    assert by_route[("济宁", "绍兴")].availability_status_code == "READY"
    assert "50米船" in (by_route[("济宁", "绍兴")].cargo_description or "")
    assert by_route[("万丰", "丹阳")].raw_tonnage_text is None
    assert by_route[("万丰", "丹阳")].ai_review_status_code == "PASS"
    assert by_route[("万丰", "丹阳")].availability_status_code == "READY"
    assert "拖队一条" in (by_route[("万丰", "丹阳")].cargo_description or "")
    assert {item.contact_phone for item in detail.candidates} == {"13562723159"}
    assert all("2000-2500吨、800" not in str(item.raw_tonnage_text or "") for item in detail.candidates)

    bulk = await FreightCandidateService(session).bulk_confirm_batch(batch.id, operator_id=7)
    assert bulk.confirmed_count == 18
    assert bulk.skipped_count == 0


@pytest.mark.asyncio
async def test_wechat_ship_notice_humanized_parse_splits_destinations_and_infers_review_only_fields(session: AsyncSession) -> None:
    raw_text = """寻船
淮南平圩一泰兴江边，矸石，要船，现货，装卸快💥

澎泽一一准南，装卸快，石子，石粉，大小船不限💥💥

准宾中心港一一淮南凤台，蚌埠五源，沙子
13855459656
…………
………………
怀远安澜一泗洪双沟，要船

镇江95号——巢湖 合肥沙子
13855459656
—————
铜陵一一一蚌埠闸下，石粉，要船

牛头山一一蒙城双，石粉/石子💥💥💥

芜湖一一临泉，石粉石子
铜陵一一临泉 ，石粉石粉
牛头山—临泉  石子石粉

武穴一一一蚌埠闸下，石子
码头镇一一蚌埠闸下石子

武穴——一合肥，沙石
牛头山长久一一合肥，石子
牛头山长久一蚌埠闸下，要船，

霍邱东湖码头—涡阳港城东码头，沙子
13855459656"""
    route_rows = [
        (1, "淮南平圩", "泰兴江边", "矸石", "淮南平圩一泰兴江边，矸石，要船，现货，装卸快", "装卸快；要船；现货", "PASS", None, []),
        (2, "澎泽", "准南", "石子/石粉", "澎泽一一准南，装卸快，石子，石粉，大小船不限", "装卸快；大小船不限", "PASS", None, []),
        (3, "准宾中心港", "淮南凤台", "沙子", "准宾中心港一一淮南凤台，蚌埠五源，沙子", None, "PASS", None, []),
        (3, "准宾中心港", "蚌埠五源", "沙子", "准宾中心港一一淮南凤台，蚌埠五源，沙子", None, "PASS", None, ["MULTI_DESTINATION_SPLIT"]),
        (4, "怀远安澜", "泗洪双沟", "沙子", "怀远安澜一泗洪双沟，要船", "要船；货品由同一公告块前后沙子上下文推断", "REVIEW_REQUIRED", "本条缺少货品，AI 根据同一公告块上下文推断为沙子", ["INFERRED_COMMODITY"]),
        (5, "镇江95号", "巢湖", "沙子", "镇江95号——巢湖 合肥沙子", None, "PASS", None, []),
        (5, "镇江95号", "合肥", "沙子", "镇江95号——巢湖 合肥沙子", None, "PASS", None, ["MULTI_DESTINATION_SPLIT"]),
        (6, "铜陵", "蚌埠闸下", "石粉", "铜陵一一一蚌埠闸下，石粉，要船", "要船", "PASS", None, []),
        (7, "牛头山", "蒙城双", "石粉/石子", "牛头山一一蒙城双，石粉/石子", None, "PASS", None, []),
        (8, "芜湖", "临泉", "石粉石子", "芜湖一一临泉，石粉石子", None, "PASS", None, []),
        (9, "铜陵", "临泉", "石粉石粉", "铜陵一一临泉 ，石粉石粉", None, "PASS", None, []),
        (10, "牛头山", "临泉", "石子石粉", "牛头山—临泉  石子石粉", None, "PASS", None, []),
        (11, "武穴", "蚌埠闸下", "石子", "武穴一一一蚌埠闸下，石子", None, "PASS", None, []),
        (12, "码头镇", "蚌埠闸下", "石子", "码头镇一一蚌埠闸下石子", None, "PASS", None, []),
        (13, "武穴", "合肥", "沙石", "武穴——一合肥，沙石", None, "PASS", None, []),
        (14, "牛头山长久", "合肥", "石子", "牛头山长久一一合肥，石子", None, "PASS", None, []),
        (15, "牛头山长久", "蚌埠闸下", "石子", "牛头山长久一蚌埠闸下，要船，", "要船；货品由相邻牛头山长久至合肥石子推断", "REVIEW_REQUIRED", "本条缺少货品，AI 根据相邻同起点线路推断为石子", ["INFERRED_COMMODITY"]),
        (16, "霍邱东湖码头", "涡阳港城东码头", "沙子", "霍邱东湖码头—涡阳港城东码头，沙子", None, "PASS", None, []),
    ]
    FakeFreightParser.segments = [
        {
            "segment_index": index,
            "semantic_role_code": "ROUTE",
            "line_refs": [index],
            "raw_text": raw,
            "cargo_title": f"{origin} 至 {destination} {commodity}",
            "cargo_description": description,
            "commodity_name": commodity,
            "origin_text": origin,
            "destination_text": destination,
            "quantity_description": description,
            "vessel_description": "要船" if description and "要船" in description else None,
            "contact_phone": "13855459656",
            "availability_status_code": "READY",
            "manual_review_reason": review_reason,
            "ai_review_status_code": review_status,
            "ai_review_reason": review_reason,
            "ai_review_json": {
                "summary": review_reason or "AI 判断路线、货品、联系人可信；无吨位不阻断",
                "inferred_field_codes": missing_codes,
            },
            "missing_field_codes": missing_codes,
            "inference_basis": {"commodity": review_reason} if review_reason else None,
            "confidence_score": 0.88 if review_status == "PASS" else 0.72,
            "evidence": [raw, "13855459656"],
        }
        for index, origin, destination, commodity, raw, description, review_status, review_reason, missing_codes in route_rows
    ]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text=raw_text), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)
    by_route = {(item.raw_origin_text, item.raw_destination_text): item for item in detail.candidates}

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 18
    assert len(detail.candidates) == 18
    assert ("准宾中心港", "淮南凤台") in by_route
    assert ("准宾中心港", "蚌埠五源") in by_route
    assert by_route[("准宾中心港", "淮南凤台")].contact_phone == "13855459656"
    assert by_route[("准宾中心港", "蚌埠五源")].contact_phone == "13855459656"
    assert ("镇江95号", "巢湖") in by_route
    assert ("镇江95号", "合肥") in by_route
    assert by_route[("镇江95号", "巢湖")].contact_phone == "13855459656"
    assert by_route[("镇江95号", "合肥")].contact_phone == "13855459656"
    assert by_route[("怀远安澜", "泗洪双沟")].raw_commodity_name == "沙子"
    assert by_route[("怀远安澜", "泗洪双沟")].ai_review_status_code == "REVIEW_REQUIRED"
    assert by_route[("怀远安澜", "泗洪双沟")].availability_status_code == "UNKNOWN"
    assert by_route[("牛头山长久", "蚌埠闸下")].raw_commodity_name == "石子"
    assert by_route[("牛头山长久", "蚌埠闸下")].ai_review_status_code == "REVIEW_REQUIRED"
    assert by_route[("淮南平圩", "泰兴江边")].raw_tonnage_text is None
    assert by_route[("淮南平圩", "泰兴江边")].ai_review_status_code == "PASS"
    assert by_route[("淮南平圩", "泰兴江边")].availability_status_code == "READY"

    bulk = await FreightCandidateService(session).bulk_confirm_batch(batch.id, operator_id=7)
    assert bulk.confirmed_count == 16
    assert bulk.skipped_count == 2
    assert {item["candidate_no"] for item in bulk.skipped} == {
        by_route[("怀远安澜", "泗洪双沟")].candidate_no,
        by_route[("牛头山长久", "蚌埠闸下")].candidate_no,
    }


@pytest.mark.asyncio
async def test_candidate_ai_review_required_blocks_quick_confirm_and_manual_accepts(session: AsyncSession) -> None:
    candidate = FreightCandidate(
        candidate_no="FCA-AI-REVIEW",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_origin_text="济宁",
        raw_destination_text="绍兴",
        raw_commodity_name="吨包",
        cargo_title="济宁至绍兴吨包",
        cargo_description="50米船",
        commodity_match_level_code="RAW",
        origin_match_level_code="RAW",
        destination_match_level_code="RAW",
        availability_status_code="UNKNOWN",
        ai_review_status_code="REVIEW_REQUIRED",
        ai_review_json={"reason": "缺少可归属本条货源的吨位"},
        manual_review_reason="缺少可归属本条货源的吨位",
        status_code="PENDING",
    )
    session.add(candidate)
    await session.commit()

    with pytest.raises(ValidationError, match="需要编辑确认"):
        await FreightCandidateService(session).confirm(candidate.id, FreightCandidateConfirmRequest(remark="确认"), operator_id=1)

    freight = await FreightCandidateService(session).confirm(
        candidate.id,
        FreightCandidateConfirmRequest(
            remark="人工补吨位确认",
            overrides={"raw_tonnage_text": "2000吨", "estimated_tonnage": Decimal("2000"), "availability_status_code": "READY"},
        ),
        operator_id=1,
    )
    refreshed = await session.scalar(select(FreightCandidate).where(FreightCandidate.id == candidate.id))

    assert freight.raw_tonnage_text == "2000吨"
    assert refreshed is not None
    assert refreshed.ai_review_status_code == "MANUAL_ACCEPTED"


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
        raw_tonnage_text="1000吨",
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
    assert stored.raw_tonnage_text == "1000吨"
    assert stored.origin_match_level_code == "NODE"
    assert stored.commodity_match_level_code == "STANDARD"
    assert refreshed_candidate is not None
    assert refreshed_candidate.status_code == "CONFIRMED"
    assert refreshed_candidate.confirmed_freight_id == stored.id


@pytest.mark.asyncio
async def test_confirmed_batch_cannot_be_reparsed(session: AsyncSession) -> None:
    batch = FreightBatchTask(batch_no="FBT-REPARSE", source_type_code="WECHAT", source_channel_code="WECHAT_TEXT", raw_text="已确认批次", status_code="PARSED")
    session.add(batch)
    await session.flush()
    session.add(
        FreightCandidate(
            candidate_no="FCA-CONFIRMED",
            source_type_code="WECHAT",
            source_channel_code="WECHAT_TEXT",
            source_batch_id=batch.id,
            cargo_title="已确认货源",
            raw_origin_text="南京港",
            raw_destination_text="芜湖港",
            raw_commodity_name="动力煤",
            availability_status_code="READY",
            status_code="CONFIRMED",
            confirmed_freight_id=123,
        )
    )
    await session.commit()

    with pytest.raises(ValidationError, match="不能重新解析"):
        await FreightBatchTaskService(session).parse(batch.id, requested_by=7)
    with pytest.raises(ValidationError, match="不能重新解析"):
        await FreightBatchTaskService(session).run_parse_now(batch.id, requested_by=7)


@pytest.mark.asyncio
async def test_candidate_list_filters_by_source_batch_id(session: AsyncSession) -> None:
    batch_a = FreightBatchTask(batch_no="FBT-A", source_type_code="WECHAT", source_channel_code="WECHAT_TEXT", raw_text="A", status_code="PARSED")
    batch_b = FreightBatchTask(batch_no="FBT-B", source_type_code="WECHAT", source_channel_code="WECHAT_TEXT", raw_text="B", status_code="PARSED")
    session.add_all([batch_a, batch_b])
    await session.flush()
    session.add_all(
        [
            FreightCandidate(
                candidate_no="FCA-A",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=batch_a.id,
                raw_origin_text="南京港",
                raw_destination_text="芜湖港",
                raw_commodity_name="动力煤",
                cargo_title="A 批次货源",
                availability_status_code="READY",
                status_code="PENDING",
            ),
            FreightCandidate(
                candidate_no="FCA-B",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=batch_b.id,
                raw_origin_text="南京港",
                raw_destination_text="芜湖港",
                raw_commodity_name="动力煤",
                cargo_title="B 批次货源",
                availability_status_code="READY",
                status_code="PENDING",
            ),
        ]
    )
    await session.commit()

    result = await FreightCandidateService(session).list_items(
        keyword=None,
        status_code=None,
        source_type_code=None,
        source_batch_id=batch_a.id,
        page=1,
        page_size=20,
    )

    assert result.total == 1
    assert result.items[0].source_batch_id == batch_a.id
    assert result.items[0].candidate_no == "FCA-A"


@pytest.mark.asyncio
async def test_batch_detail_reports_parse_progress_for_reentry(session: AsyncSession) -> None:
    batch = FreightBatchTask(
        batch_no="FBT-PARSING",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_text="解析中的原文",
        status_code="PARSING",
        parse_stage_code="AI_EXTRACT",
        parse_stage_name="AI 抽取字段",
        parse_stage_message="AI 正在抽取字段",
        parse_progress_percent=55,
        parse_heartbeat_at=datetime.utcnow(),
        ai_elapsed_seconds=12,
    )
    session.add(batch)
    await session.commit()

    detail = await FreightBatchTaskService(session).get_detail(batch.id)

    assert detail.batch.status_code == "PARSING"
    assert detail.batch.parse_is_stale is False
    assert detail.batch.next_action_code == "VIEW_PARSE_PROGRESS"
    assert detail.batch.parse_stage_name == "AI 抽取字段"


@pytest.mark.asyncio
async def test_batch_handoff_review_blocks_reparse_and_keeps_pending_candidates(session: AsyncSession) -> None:
    FakeFreightParser.segments = [_segment()]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="南京港装动力煤到芜湖港"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)
    assert detail.batch.pending_count == 1

    handoff = await service.handoff_review(batch.id, operator_id=7)
    detail = await service.get_detail(batch.id)

    assert handoff.handoff_count == 1
    assert detail.batch.review_flow_status_code == "QUEUED_FOR_REVIEW"
    assert detail.batch.next_action_code == "OPEN_PENDING_QUEUE"
    assert detail.candidates[0].status_code == "PENDING"
    with pytest.raises(ValidationError, match="已移交待确认"):
        await service.parse(batch.id, requested_by=7)


@pytest.mark.asyncio
async def test_location_matching_prefers_node_before_city(session: AsyncSession) -> None:
    city = await session.scalar(select(AdminRegion).where(AdminRegion.code == "320100"))
    assert city is not None
    node = TransportNode(
        code="ND-CITY-NAME",
        name="南京市",
        short_name="南京市",
        node_type_code="PORT",
        province_code="320000",
        city_code="320100",
        city_region_id=city.id,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    session.add(node)
    await session.commit()

    normalized, options, basis = await FreightCandidateService(session)._match_location("南京市")

    assert normalized["match_level_code"] == "NODE"
    assert normalized["node_id"] == node.id
    assert normalized["city_code"] == "320100"
    assert options[0]["level"] == "NODE"
    assert basis["status"] == "MATCHED_NODE"


@pytest.mark.asyncio
async def test_location_matching_city_short_name_beats_weak_node_contains(session: AsyncSession) -> None:
    city = AdminRegion(code="340500", name="马鞍山市", short_name="马鞍山", level=2, province_code="340000", city_code="340500", status=1)
    session.add(city)
    await session.flush()
    node = TransportNode(
        code="ND-MAS-CIHU",
        name="马鞍山慈湖港",
        short_name="慈湖港",
        node_type_code="PORT",
        province_code="340000",
        city_code="340500",
        city_region_id=city.id,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    session.add(node)
    await session.commit()

    normalized, options, basis = await FreightCandidateService(session)._match_location("马鞍山", "CITY")

    assert normalized["match_level_code"] == "CITY"
    assert normalized["city_code"] == "340500"
    assert normalized.get("node_id") is None
    assert options[0]["level"] == "CITY"
    assert basis["status"] == "MATCHED_CITY"


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

    service = FreightNormalizationSuggestionService(session)
    task = await service.task_repo.create(
        {
            "task_no": "FNT-TEST-0001",
            "status_code": "QUEUED",
            "stage_code": "QUEUED",
            "stage_name": "排队中",
            "stage_message": "测试任务",
            "progress_percent": 0,
            "requested_by": 2,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
    )
    await session.commit()
    result = await service.run_clean_now(task.id, operator_id=2)
    stored = await session.scalar(select(Freight).where(Freight.id == freight.id))
    suggestions = (await session.execute(select(FreightNormalizationSuggestion))).scalars().all()
    stored_task = await session.scalar(select(FreightNormalizationTask).where(FreightNormalizationTask.id == task.id))

    assert result.task_id == task.id
    assert result.status_code == "SUCCESS"
    assert result.auto_applied_count >= 3
    assert stored_task is not None
    assert stored_task.status_code == "SUCCESS"
    assert stored is not None
    assert stored.commodity_standard_id is not None
    assert stored.origin_city_code == "320100"
    assert stored.destination_city_code == "340200"
    assert {item.status_code for item in suggestions} == {"AUTO_APPLIED"}
