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
    DashScopeQwenFreightParserClient,
    FreightClueSplitPayloadSchema,
    FreightParsePayloadSchema,
    FreightSemanticMapPayloadSchema,
    _apply_context_blocks_to_segments,
    _clue_schema_hint,
    _json_schema_hint,
    _prepare_segments,
    _segment_needs_strong_review,
)
from app.models.address import AdminRegion, Region, RegionCityRelation, TransportNode
from app.models.base import Base
from app.models.commodity import CommodityCategory, CommodityStandard, CommodityType
from app.models.common import CodeSequence
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightClue, FreightNormalizationSuggestion, FreightNormalizationTask
from app.modules.freight import batch_service as freight_batch_service_module
from app.modules.freight import support as freight_support_module
from app.modules.freight import tms_service as freight_tms_service_module
from app.modules.dictionary.service import CodeSequenceService
from app.modules.freight.ai_evidence_gate import (
    COMMODITY_SCOPE_UNSAFE,
    CONTEXT_BLOCK_UNSAFE,
    BATCH_ROUTE_COLLAPSE,
    CROSS_CLUE_REVIEW_MERGE,
    DUPLICATE_ROUTE_POINT,
    FIELD_EVIDENCE_CROSS_CLUE,
    FIELD_EVIDENCE_MISSING,
    FORMAL_TONNAGE_MISSING,
    LOW_ROUTE_RECALL,
    NON_FORMAL_ROUTE_NOT_READY,
    PROMPT_SCHEMA_DRIFT,
    ROUTE_FIELD_UNSAFE,
    apply_segment_evidence_gate,
    patch_semantic_map_with_gate_result,
    should_call_ai_repair,
)
from app.modules.freight.ai_semantic_validator import FreightSemanticValidator
from app.modules.freight.ai_structural_skeleton import (
    EvidenceSupportMatcher,
    FreightStructuralSkeletonBuilder,
    apply_skeleton_to_semantic_map,
    ensure_segments_for_route_clues,
)
from app.modules.freight.ai_text_index import FreightTextIndexer
from app.modules.freight.master_data_matcher import FreightMasterDataBatchMatcher
from app.modules.freight.router import router as freight_router
from app.modules.freight.schemas import (
    FreightBatchCreateRequest,
    FreightNormalizationBulkActionRequest,
    FreightCandidateConfirmRequest,
    FreightTmsInboundCreateRequest,
)
from app.modules.freight.batch_service import FreightBatchTaskService
from app.modules.freight.candidate_service import FreightCandidateService
from app.modules.freight.normalization_service import FreightNormalizationSuggestionService
from app.modules.freight.tms_service import FreightTmsInboundService


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
    monkeypatch.setattr(freight_batch_service_module, "DashScopeQwenFreightParserClient", FakeFreightParser)
    monkeypatch.setattr(freight_tms_service_module, "DashScopeQwenFreightParserClient", FakeFreightParser)


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


def test_freight_text_indexer_preserves_lines_and_empty_context() -> None:
    raw_text = "第一行\n\n第三行\n"
    indexed = FreightTextIndexer().index(raw_text)

    assert indexed.raw_text == raw_text
    assert indexed.line_map == {"L1": "第一行", "L2": "", "L3": "第三行", "L4": ""}
    assert indexed.indexed_text == "L1 第一行\nL2 \nL3 第三行\nL4 "


def test_evidence_support_matcher_accepts_spaced_city_and_dash_variants() -> None:
    assert EvidenceSupportMatcher.supports("南通", "南   通——盐   城  大麦")
    assert EvidenceSupportMatcher.supports("盐城", "南   通——盐   城  大麦")
    assert EvidenceSupportMatcher.supports("池州-涟水", "池州一一涟水")


def test_structural_skeleton_expands_multi_origin_and_trailing_contact() -> None:
    raw_text = "池州/铜陵/芜湖/马鞍山一一淮安涟水，沙子/石子，2000吨左右船\n15956651099胡"
    indexed = FreightTextIndexer().index(raw_text)
    skeleton = FreightStructuralSkeletonBuilder().build(indexed)

    assert skeleton.coverage_audit["route_unit_count"] == 4
    assert {
        (item["origin_text"], item["destination_text"])
        for item in skeleton.skeleton_units
    } == {
        ("池州", "淮安涟水"),
        ("铜陵", "淮安涟水"),
        ("芜湖", "淮安涟水"),
        ("马鞍山", "淮安涟水"),
    }
    assert skeleton.context_blocks[0]["shared_contact_phone"] == "15956651099"
    assert skeleton.context_blocks[0]["shared_contact_name"] == "胡"


def test_structural_skeleton_does_not_expand_context_as_destination() -> None:
    raw_text = "\n".join(
        [
            "牛头山—临泉  石子石粉",
            "东流菊江码头——淮安建华管桩码头，需要单机数条",
            "黄冈三江口——南京关门山        8000吨内",
            "镇江一一一一合肥，沙子",
            "南通五号桥——盐城1800吨以内",
            "15052612052   微信同号",
        ]
    )
    skeleton = FreightStructuralSkeletonBuilder().build(FreightTextIndexer().index(raw_text))

    routes = {(item["origin_text"], item["destination_text"]) for item in skeleton.skeleton_units}
    assert ("牛头山", "临泉") in routes
    assert ("东流菊江码头", "淮安建华管桩码头") in routes
    assert ("黄冈三江口", "南京关门山") in routes
    assert ("镇江", "合肥") in routes
    assert ("南通五号桥", "盐城") in routes
    assert all(destination not in {"石子", "需要单机数条", "8000吨内"} for _, destination in routes)
    assert len(skeleton.skeleton_units) == 5
    assert skeleton.context_blocks[0]["shared_contact_phone"] == "15052612052"
    assert skeleton.context_blocks[0]["shared_contact_wechat"] == "15052612052"
    assert skeleton.context_blocks[0].get("shared_contact_name") is None


def test_skeleton_reconciliation_creates_missing_fallback_segments() -> None:
    raw_text = "南京到芜湖动力煤1000吨\n太仓到无锡黄沙2000吨"
    indexed = FreightTextIndexer().index(raw_text)
    skeleton = FreightStructuralSkeletonBuilder().build(indexed)
    semantic_map = apply_skeleton_to_semantic_map({"route_clues": [], "context_blocks": [], "context_notes": []}, skeleton)
    segments, warnings = ensure_segments_for_route_clues(semantic_map, [])

    assert len(segments) == 2
    assert {item["raw_text"] for item in segments} == set(raw_text.splitlines())
    assert all(item["fallback_generated"] is True for item in segments)
    assert any("AI_SEGMENT_MISSING" in item for item in warnings)


@pytest.mark.asyncio
async def test_review_timeout_keeps_complete_local_evidence_ready() -> None:
    indexed = FreightTextIndexer().index("南京海宏码头——涟水红日港，石子，1800吨以内船")
    semantic_map = {
        "route_clues": [
            {
                "clue_temp_id": "C1",
                "line_refs": ["L1"],
                "raw_text": "南京海宏码头——涟水红日港，石子，1800吨以内船",
                "origin": {"text": "南京海宏码头"},
                "destination": {"text": "涟水红日港"},
            }
        ],
        "context_blocks": [],
        "context_notes": [],
    }
    segments = [
        _segment(
            clue_temp_id="C1",
            raw_text="南京海宏码头——涟水红日港，石子，1800吨以内船",
            origin_text="南京海宏码头",
            destination_text="涟水红日港",
            commodity_name="石子",
            raw_tonnage_text="1800吨以内",
            availability_status_code="UNKNOWN",
            confidence_score=0.62,
            evidence=["南京海宏码头——涟水红日港，石子，1800吨以内船"],
        )
    ]
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())

    async def timeout_call(**kwargs):  # noqa: ANN003
        raise TimeoutError("review timeout")

    client._call_json = timeout_call  # type: ignore[method-assign]
    review_results, review_raw, failed_count, metrics = await client.review_risky_segments(
        indexed,
        semantic_map,
        segments,
        runtime={
            "review_threshold": 0.65,
            "review_batch_size": 8,
            "review_concurrency": 1,
            "review_model": "qwen-plus",
            "api_key": "test",
            "timeout": 1,
            "budget": None,
        },
    )

    assert review_results == []
    assert failed_count == 0
    assert metrics[0]["review_chunk_size"] == 1
    assert review_raw["chunks"][0]["local_pass_count"] == 1
    assert segments[0]["availability_status_code"] == "READY"
    assert segments[0]["ai_review_status_code"] == "PASS"
    assert segments[0]["needs_strong_review"] is False


def test_semantic_validator_marks_untraceable_ai_output_for_review() -> None:
    indexed = FreightTextIndexer().index("南京港装动力煤\n到芜湖港")
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": "C1", "line_refs": ["L9"], "raw_text": "南京港装动力煤"},
            {"clue_temp_id": "C2", "line_refs": ["L1"], "raw_text": "不存在的路线"},
        ]
    }
    validator = FreightSemanticValidator(indexed)

    warnings = validator.validate_semantic_map(semantic_map)
    segments = [{"clue_temp_id": "C3", "line_refs": ["L1"], "raw_text": "南京港装动力煤"}]
    segment_warnings = validator.validate_segments(semantic_map, segments)

    assert any("line_refs 不存在" in item for item in warnings)
    assert any("raw_text 无法" in item for item in warnings)
    assert all(item["needs_strong_review"] is True for item in semantic_map["route_clues"])
    assert any("clue_temp_id 不存在" in item for item in segment_warnings)
    assert segments[0]["needs_strong_review"] is True


def test_semantic_validator_marks_cross_contact_context_block_for_review() -> None:
    raw_text = "芜湖到江阴板坯\n17356202909王\n@所有人\n上海闵行到桐乡现金\n18226924092"
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": "C1", "line_refs": ["L1"], "context_block_id": "B1", "raw_text": "芜湖到江阴板坯"},
            {"clue_temp_id": "C2", "line_refs": ["L4"], "context_block_id": "B1", "raw_text": "上海闵行到桐乡现金"},
        ],
        "context_blocks": [
            {
                "context_block_id": "B1",
                "route_clue_ids": [1, "C2"],
                "line_refs": ["L1", "L2", "L3", "L4", "L5"],
                "raw_text": raw_text,
                "shared_contact_phone": "17356202909",
            }
        ],
    }
    validator = FreightSemanticValidator(indexed)

    warnings = validator.validate_semantic_map(semantic_map)
    segments = [
        {
            "clue_temp_id": "C2",
            "line_refs": ["L4"],
            "raw_text": "上海闵行到桐乡现金",
            "origin_text": "上海闵行",
            "destination_text": "桐乡",
            "commodity_name": "货源",
            "contact_phone": "17356202909",
            "context_block_id": "B1",
            "availability_status_code": "READY",
            "confidence_score": 0.95,
        }
    ]
    segment_warnings = validator.validate_segments(semantic_map, segments)

    assert any("MULTI_CONTACT_BLOCK" in item for item in warnings)
    assert any("CONTEXT_BLOCK_CONFLICT" in item for item in warnings)
    assert semantic_map["context_blocks"][0]["route_clue_ids"] == ["C1", "C2"]
    assert segments[0]["contact_phone"] is None
    assert segments[0]["needs_strong_review"] is True
    assert any("CONTACT_SCOPE_CONFLICT" in item for item in segment_warnings)
    assert _segment_needs_strong_review(segments[0], confidence_threshold=0.80) is True


def test_semantic_validator_marks_low_route_recall_when_many_lines_become_one_clue() -> None:
    raw_text = "\n".join([f"路线{i}" for i in range(1, 8)])
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [
            {
                "clue_temp_id": "C1",
                "line_refs": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
                "raw_text": raw_text,
            }
        ]
    }
    warnings = FreightSemanticValidator(indexed).validate_semantic_map(semantic_map)

    assert any("LOW_ROUTE_RECALL" in item for item in warnings)
    assert semantic_map["route_clues"][0]["needs_strong_review"] is True


def test_evidence_gate_marks_weak_commodity_as_suggestion_not_top_level() -> None:
    raw_text = "A到B黄沙\nC到D要船"
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [{"clue_temp_id": "C1", "line_refs": ["L2"], "raw_text": "C到D要船"}],
        "context_notes": [
            {
                "note_id": "N1",
                "context_type_code": "COMMODITY",
                "line_refs": ["L1"],
                "raw_text": "A到B黄沙",
                "applies_to": ["C1"],
                "scope_type_code": "WEAK_INFERRED",
            }
        ],
    }
    segments = [
        {
            "clue_temp_id": "C1",
            "segment_index": 1,
            "route_intent_code": "SEEK_VESSEL",
            "line_refs": ["L2"],
            "raw_text": "C到D要船",
            "origin_text": "C",
            "destination_text": "D",
            "commodity_name": "黄沙",
            "availability_status_code": "READY",
            "field_evidence": {
                "origin_text": {"value": "C", "source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "C到D"},
                "destination_text": {"value": "D", "source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "C到D"},
                "commodity_name": {
                    "value": "黄沙",
                    "source_type_code": "WEAK_INFERRED",
                    "line_refs": ["L1"],
                    "evidence_text": "A到B黄沙",
                },
            },
        }
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert COMMODITY_SCOPE_UNSAFE in result.issue_codes
    assert segments[0]["commodity_name"] is None
    assert segments[0]["availability_status_code"] == "UNKNOWN"
    assert segments[0]["ai_review_json"]["suggested_fields"]["commodity_name"]["value"] == "黄沙"


def test_evidence_gate_requires_formal_tonnage_but_not_ready_for_seek_vessel() -> None:
    indexed = FreightTextIndexer().index("南京到芜湖动力煤\n怀远安澜到泗洪双沟要船")
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": "C1", "line_refs": ["L1"], "raw_text": "南京到芜湖动力煤"},
            {"clue_temp_id": "C2", "line_refs": ["L2"], "raw_text": "怀远安澜到泗洪双沟要船"},
        ]
    }
    base_evidence = {
        "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "南京到芜湖"},
        "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "南京到芜湖"},
        "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "动力煤"},
    }
    segments = [
        {
            "clue_temp_id": "C1",
            "line_refs": ["L1"],
            "raw_text": "南京到芜湖动力煤",
            "route_intent_code": "FORMAL_FREIGHT",
            "origin_text": "南京",
            "destination_text": "芜湖",
            "commodity_name": "动力煤",
            "availability_status_code": "READY",
            "field_evidence": base_evidence,
        },
        {
            "clue_temp_id": "C2",
            "line_refs": ["L2"],
            "raw_text": "怀远安澜到泗洪双沟要船",
            "route_intent_code": "SEEK_VESSEL",
            "origin_text": "怀远安澜",
            "destination_text": "泗洪双沟",
            "commodity_name": "沙子",
            "availability_status_code": "READY",
            "field_evidence": {
                "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "怀远安澜"},
                "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "泗洪双沟"},
                "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "沙子"},
            },
        },
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert FORMAL_TONNAGE_MISSING in result.issue_codes
    assert NON_FORMAL_ROUTE_NOT_READY in result.issue_codes
    assert all(segment["availability_status_code"] == "UNKNOWN" for segment in segments)


def test_evidence_gate_flags_route_point_errors_and_context_scope() -> None:
    indexed = FreightTextIndexer().index("太仓到无锡黄沙2000吨")
    semantic_map = {
        "_schema_compat_flags": ["freight_clues"],
        "route_clues": [{"clue_temp_id": "C1", "line_refs": ["L1"], "raw_text": "太仓到无锡黄沙2000吨"}],
        "context_blocks": [
            {
                "context_block_id": "B1",
                "route_clue_ids": ["C1"],
                "line_refs": ["L1"],
                "raw_text": "太仓到无锡黄沙2000吨",
                "shared_tonnage_text": "2000吨",
                "scope_type_code": "UNKNOWN",
            }
        ],
    }
    segments = [
        {
            "clue_temp_id": "C1",
            "line_refs": ["L1"],
            "raw_text": "太仓到无锡黄沙2000吨",
            "origin_text": "太仓到无锡",
            "destination_text": "太仓到无锡",
            "commodity_name": "黄沙",
            "raw_tonnage_text": "2000吨",
            "availability_status_code": "READY",
            "field_evidence": {
                "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "黄沙"},
                "raw_tonnage_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "2000吨"},
            },
            "tonnage_decision": {
                "status_code": "PASS",
                "selected_text": "2000吨",
                "source_type_code": "LOCAL_LINE",
                "line_refs": ["L1"],
                "belongs_to_current_segment": True,
            },
        }
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)
    patch_semantic_map_with_gate_result(semantic_map, result)

    assert PROMPT_SCHEMA_DRIFT in result.issue_codes
    assert CONTEXT_BLOCK_UNSAFE in result.issue_codes
    assert DUPLICATE_ROUTE_POINT in result.issue_codes
    assert ROUTE_FIELD_UNSAFE in result.issue_codes
    assert segments[0]["availability_status_code"] == "UNKNOWN"
    assert semantic_map["quality_gate"]["should_review"] is True


def test_evidence_gate_low_route_recall_requires_ai_repair() -> None:
    raw_text = "\n".join([f"路线{i}" for i in range(1, 8)])
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [
            {
                "clue_temp_id": "C1",
                "line_refs": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
                "raw_text": raw_text,
            }
        ]
    }
    segments = [{"clue_temp_id": "C1", "line_refs": ["L1"], "raw_text": "路线1", "origin_text": "A", "destination_text": "B"}]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert LOW_ROUTE_RECALL in result.issue_codes
    assert should_call_ai_repair(result) is True
    assert segments[0]["needs_strong_review"] is True


def test_evidence_gate_marks_missing_field_evidence() -> None:
    indexed = FreightTextIndexer().index("南京到芜湖动力煤1000吨")
    semantic_map = {"route_clues": [{"clue_temp_id": "C1", "line_refs": ["L1"], "raw_text": "南京到芜湖动力煤1000吨"}]}
    segments = [
        {
            "clue_temp_id": "C1",
            "line_refs": ["L1"],
            "raw_text": "南京到芜湖动力煤1000吨",
            "origin_text": "南京",
            "destination_text": "芜湖",
            "commodity_name": "动力煤",
            "raw_tonnage_text": "1000吨",
            "tonnage_decision": {"status_code": "PASS", "selected_text": "1000吨", "belongs_to_current_segment": True},
            "availability_status_code": "READY",
        }
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert FIELD_EVIDENCE_MISSING in result.issue_codes
    assert segments[0]["availability_status_code"] == "UNKNOWN"


def test_evidence_gate_flags_cross_clue_field_evidence() -> None:
    indexed = FreightTextIndexer().index("南京到芜湖动力煤1000吨\n太仓到无锡黄沙2000吨")
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": "C1", "line_refs": ["L1"], "raw_text": "南京到芜湖动力煤1000吨"},
            {"clue_temp_id": "C2", "line_refs": ["L2"], "raw_text": "太仓到无锡黄沙2000吨"},
        ]
    }
    segments = [
        {
            "clue_temp_id": "C1",
            "line_refs": ["L1"],
            "raw_text": "南京到芜湖动力煤1000吨",
            "origin_text": "太仓",
            "destination_text": "无锡",
            "commodity_name": "黄沙",
            "raw_tonnage_text": "2000吨",
            "availability_status_code": "READY",
            "field_evidence": {
                "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "太仓"},
                "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "无锡"},
                "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "黄沙"},
                "raw_tonnage_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "2000吨"},
            },
            "tonnage_decision": {
                "status_code": "PASS",
                "selected_text": "2000吨",
                "source_type_code": "LOCAL_LINE",
                "line_refs": ["L2"],
                "belongs_to_current_segment": True,
            },
        }
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert FIELD_EVIDENCE_CROSS_CLUE in result.issue_codes
    assert segments[0]["availability_status_code"] == "UNKNOWN"


def test_evidence_gate_flags_batch_route_collapse() -> None:
    lines = [
        "南通芦泾港码头一长兴小浦尾渣1200吨",
        "马鞍山——灌云 铁粉 1180吨",
        "南通华能——德清 石膏",
        "兴化——张家港 钢渣450吨",
        "常州—上海 600左右线材",
    ]
    indexed = FreightTextIndexer().index("\n".join(lines))
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": f"C{index}", "line_refs": [f"L{index}"], "raw_text": line}
            for index, line in enumerate(lines, start=1)
        ]
    }
    segments = [
        {
            "clue_temp_id": f"C{index}",
            "segment_uid": f"C{index}:S1",
            "line_refs": ["L2"],
            "raw_text": lines[1],
            "origin_text": "马鞍山",
            "destination_text": "灌云",
            "commodity_name": "铁粉",
            "raw_tonnage_text": "1180吨",
            "availability_status_code": "READY",
            "field_evidence": {
                "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "马鞍山"},
                "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "灌云"},
                "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "铁粉"},
                "raw_tonnage_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L2"], "evidence_text": "1180吨"},
            },
            "tonnage_decision": {
                "status_code": "PASS",
                "selected_text": "1180吨",
                "source_type_code": "LOCAL_LINE",
                "line_refs": ["L2"],
                "belongs_to_current_segment": True,
            },
        }
        for index in range(1, 6)
    ]

    result = apply_segment_evidence_gate(indexed, semantic_map, segments)

    assert BATCH_ROUTE_COLLAPSE in result.issue_codes
    assert all(segment["availability_status_code"] == "UNKNOWN" for segment in segments)


def test_review_merge_requires_segment_uid_and_preserves_original_identity() -> None:
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())
    segments = [
        {
            "clue_temp_id": "C1",
            "segment_uid": "C1:S1",
            "segment_index": 1,
            "line_refs": ["L1"],
            "raw_text": "南通到长兴尾渣1200吨",
            "origin_text": "南通",
            "destination_text": "长兴",
            "commodity_name": "尾渣",
            "availability_status_code": "UNKNOWN",
            "needs_strong_review": True,
        },
        {
            "clue_temp_id": "C18",
            "segment_uid": "C18:S1",
            "segment_index": 1,
            "line_refs": ["L42"],
            "raw_text": "12号武汉-连云港钢结构，需45米仓口",
            "origin_text": "武汉",
            "destination_text": "连云港",
            "commodity_name": "钢结构",
            "availability_status_code": "UNKNOWN",
            "needs_strong_review": True,
        },
    ]
    review_results = [
        {
            "clue_temp_id": "C18",
            "segment_index": 1,
            "line_refs": ["L42"],
            "raw_text": "12号武汉-连云港钢结构，需45米仓口",
            "origin_text": "武汉",
            "destination_text": "连云港",
            "commodity_name": "钢结构",
            "ai_review_status_code": "PASS",
        }
    ]

    merged = client.merge_review_results(segments, review_results)

    assert merged[0]["clue_temp_id"] == "C1"
    assert merged[0]["line_refs"] == ["L1"]
    assert merged[0]["origin_text"] == "南通"
    assert CROSS_CLUE_REVIEW_MERGE in {
        issue["code"]
        for issue in merged[0]["ai_review_json"]["field_quality_gate"]["issues"]
    }


def test_review_merge_discards_cross_clue_patch_for_existing_uid() -> None:
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())
    segments = [
        {
            "clue_temp_id": "C1",
            "segment_uid": "C1:S1",
            "segment_index": 1,
            "line_refs": ["L1"],
            "raw_text": "南通到长兴尾渣1200吨",
            "origin_text": "南通",
            "destination_text": "长兴",
            "commodity_name": "尾渣",
            "availability_status_code": "UNKNOWN",
            "needs_strong_review": True,
        }
    ]
    review_results = [
        {
            "segment_uid": "C1:S1",
            "clue_temp_id": "C18",
            "segment_index": 1,
            "line_refs": ["L42"],
            "raw_text": "12号武汉-连云港钢结构，需45米仓口",
            "origin_text": "武汉",
            "destination_text": "连云港",
            "commodity_name": "钢结构",
            "ai_review_status_code": "PASS",
        }
    ]

    merged = client.merge_review_results(segments, review_results)

    assert merged[0]["clue_temp_id"] == "C1"
    assert merged[0]["origin_text"] == "南通"
    assert merged[0]["destination_text"] == "长兴"
    assert CROSS_CLUE_REVIEW_MERGE in {
        issue["code"]
        for issue in merged[0]["ai_review_json"]["field_quality_gate"]["issues"]
    }


def test_user_multi_contact_sample_preserves_seventeen_clues_and_contact_scopes() -> None:
    top_routes = [
        "芜湖……江阴    板坯3300吨，8号船到就装，装卸速度快",
        "芜湖---镇江   2-5000 板坯   20000吨货 11号档期",
        "码头镇—江阴 石子8-10000  石子  9号",
        "扬州恒润-上海蘊藻浜绿安库冷卷   1270吨，现金结账",
        "池州-----淮安     2000左右 石子 长期货",
        "湖口------东台  水渣   2000左右",
        "马鞍山-----东台  水渣   2000左右",
        "常州港-------东台    水渣  2000左右",
        "黄石----连云港  石子  2000左右",
    ]
    bottom_routes = [
        "上海闵行——桐乡600-900吨 装卸快 现金",
        "9号 上海闵行——海盐 1000吨左右 装卸快 现金",
        "扬州恒润——上海蘊藻浜绿安库  冷卷   1270吨",
        "黄石——连云港   石子 2000左右",
        "10号上海苏建——常州1150吨热卷",
        "11-12号上海苏建——常州765吨热卷",
        "⭐️江海河——马鞍山 1100吨左右 重废",
        "南通中天——杭州 钢材 随船装（滚动发",
    ]
    raw_text = "\n".join([*top_routes, "17356202909王", "@所有人", *bottom_routes, "18226924092"])
    indexed = FreightTextIndexer().index(raw_text)
    route_clues = [
        {"clue_temp_id": f"C{index}", "line_refs": [f"L{index}"], "context_block_id": "B1", "raw_text": raw}
        for index, raw in enumerate(top_routes, start=1)
    ] + [
        {"clue_temp_id": f"C{index}", "line_refs": [f"L{index + 2}"], "context_block_id": "B2", "raw_text": raw}
        for index, raw in enumerate(bottom_routes, start=10)
    ]
    semantic_map = {
        "route_clues": route_clues,
        "context_blocks": [
            {
                "context_block_id": "B1",
                "route_clue_ids": [f"C{index}" for index in range(1, 10)],
                "line_refs": [*[f"L{index}" for index in range(1, 10)], "L10"],
                "shared_contact_name": "王",
                "shared_contact_phone": "17356202909",
                "evidence": ["17356202909王"],
                "scope_reason": "联系人位于上半段连续路线之后，且未跨 @所有人",
            },
            {
                "context_block_id": "B2",
                "route_clue_ids": [f"C{index}" for index in range(10, 18)],
                "line_refs": [*[f"L{index}" for index in range(12, 20)], "L20"],
                "shared_contact_phone": "18226924092",
                "evidence": ["18226924092"],
                "scope_reason": "尾部手机号覆盖 @所有人 之后最近连续路线块",
            },
        ],
    }
    warnings = FreightSemanticValidator(indexed).validate_semantic_map(semantic_map)
    segments = [
        {
            "clue_temp_id": f"C{index}",
            "line_refs": clue["line_refs"],
            "raw_text": clue["raw_text"],
            "origin_text": "测试起点",
            "destination_text": "测试终点",
            "commodity_name": "测试货品",
            "contact_phone": "17356202909" if index <= 9 else "18226924092",
            "context_block_id": "B1" if index <= 9 else "B2",
            "availability_status_code": "READY",
            "confidence_score": 0.92,
        }
        for index, clue in enumerate(route_clues, start=1)
    ]
    segment_warnings = FreightSemanticValidator(indexed).validate_segments(semantic_map, segments)
    top_payload, _ = DashScopeQwenFreightParserClient._build_evidence_payload(indexed, semantic_map, route_clues[:9])
    bottom_payload, _ = DashScopeQwenFreightParserClient._build_evidence_payload(indexed, semantic_map, route_clues[9:])

    assert len(semantic_map["route_clues"]) == 17
    assert not any("LOW_ROUTE_RECALL" in item for item in warnings)
    assert not segment_warnings
    assert {item["contact_phone"] for item in segments[:9]} == {"17356202909"}
    assert {item["contact_phone"] for item in segments[9:]} == {"18226924092"}
    assert "18226924092" not in json.dumps(top_payload, ensure_ascii=False)
    assert "17356202909" not in json.dumps(bottom_payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_code_sequence_service_reserves_multiple_codes_in_one_call(session: AsyncSession) -> None:
    codes = await CodeSequenceService(session).next_codes("FREIGHT_CLUE_NO", 3)
    next_code = await CodeSequenceService(session).next_code("FREIGHT_CLUE_NO")

    assert codes == ["FCU0001", "FCU0002", "FCU0003"]
    assert next_code == "FCU0004"


@pytest.mark.asyncio
async def test_master_data_batch_matcher_matches_segments_with_single_loaded_cache(session: AsyncSession) -> None:
    matcher = FreightMasterDataBatchMatcher(session)

    results = await matcher.match_segments([_segment(), _segment(destination_text="芜湖", destination_match_level_code="CITY")])

    assert results[0]["origin"]["selected"]["node_id"] is not None
    assert results[0]["destination"]["selected"]["node_id"] is not None
    assert results[0]["commodity"]["level"] == "STANDARD"
    assert results[1]["destination"]["selected"]["match_level_code"] == "CITY"


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


def test_semantic_map_schema_ignores_formal_candidate_fields_and_uses_string_clue_refs() -> None:
    payload = FreightSemanticMapPayloadSchema.model_validate(
        {
            "route_clues": [
                {
                    "clue_temp_id": 1,
                    "line_refs": ["L1"],
                    "context_block_id": "B1",
                    "raw_text": "芜湖到江阴板坯",
                    "route_summary": "疑似路线线索",
                    "origin_text": "芜湖",
                    "destination_text": "江阴",
                    "commodity_name": "板坯",
                    "inherited_context": {"contact": "王"},
                    "needs_strong_review": True,
                }
            ],
            "context_blocks": [{"context_block_id": "B1", "route_clue_ids": [1], "line_refs": ["L2"], "shared_contact_phone": "17356202909"}],
        }
    )

    clue = payload.route_clues[0].model_dump(exclude_none=True)
    assert "origin_text" not in clue
    assert "destination_text" not in clue
    assert "commodity_name" not in clue
    assert "inherited_context" not in clue
    assert "needs_strong_review" not in clue
    assert payload.context_blocks[0].route_clue_ids == ["C1"]


def test_detail_evidence_pack_does_not_include_full_indexed_source_text() -> None:
    raw_text = "L0 不应出现\n芜湖到江阴板坯\n17356202909王\n@所有人\n上海闵行到桐乡现金"
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": "C1", "line_refs": ["L2"], "context_block_id": "B1", "raw_text": "芜湖到江阴板坯"},
            {"clue_temp_id": "C2", "line_refs": ["L5"], "context_block_id": "B2", "raw_text": "上海闵行到桐乡现金"},
        ],
        "context_blocks": [
            {"context_block_id": "B1", "route_clue_ids": ["C1"], "line_refs": ["L3"], "shared_contact_phone": "17356202909"},
            {"context_block_id": "B2", "route_clue_ids": ["C2"], "line_refs": ["L5"], "shared_contact_phone": "18226924092"},
        ],
    }

    evidence_payload, metrics = DashScopeQwenFreightParserClient._build_evidence_payload(
        indexed,
        semantic_map,
        [semantic_map["route_clues"][0]],
    )
    messages = DashScopeQwenFreightParserClient._detail_messages(evidence_payload)
    review_messages = DashScopeQwenFreightParserClient._review_messages({**evidence_payload, "segments": [_segment(line_refs=["L2"], raw_text="芜湖到江阴板坯")]})
    prompt_text = json.dumps(messages, ensure_ascii=False)
    review_prompt_text = json.dumps(review_messages, ensure_ascii=False)

    assert "indexed_source_text" not in prompt_text
    assert "indexed_source_text" not in review_prompt_text
    assert indexed.indexed_text not in prompt_text
    assert indexed.indexed_text not in review_prompt_text
    assert "上海闵行到桐乡现金" not in prompt_text
    assert "上海闵行到桐乡现金" not in review_prompt_text
    assert {line["line_ref"] for line in evidence_payload["evidence_lines"]} == {"L2", "L3"}
    assert metrics["evidence_line_count"] == 2


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
    clue = payload.freight_clues[0].model_dump(exclude_none=True)
    assert "commodity_name" not in clue
    assert clue["missing_field_codes"] == ["COMMODITY"]


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
async def test_wechat_parse_around_twenty_routes_records_timings_and_heartbeat(session: AsyncSession) -> None:
    FakeFreightParser.segments = [
        _segment(
            segment_index=index,
            raw_text=f"南京港装动力煤第{index}船到芜湖港",
            cargo_title=f"南京港至芜湖港动力煤 {index}",
        )
        for index in range(1, 21)
    ]

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="20 条微信群路线样例"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)
    stored = await session.scalar(select(FreightBatchTask).where(FreightBatchTask.id == batch.id))

    assert detail.batch.status_code == "PARSED"
    assert detail.batch.candidate_count == 20
    assert detail.batch.parse_heartbeat_at is not None
    assert stored is not None
    assert stored.ai_semantic_map_json["pipeline_version"] == "freight_ai_semantic_pipeline_v3"
    assert "MATCHING" in stored.raw_response_json["timings"]
    assert "SAVING" in stored.raw_response_json["timings"]


@pytest.mark.asyncio
async def test_staged_wechat_parse_records_evidence_metrics_in_timings(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    class StagedParser:
        wechat_prompt_version = "staged_test"

        def __init__(self, runtime_config) -> None:
            self.runtime_config = runtime_config

        async def _runtime(self) -> dict:
            return {
                "provider": "TEST",
                "semantic_model": "qwen-plus",
                "detail_model": "qwen-turbo",
                "review_model": "qwen-plus",
                "detail_batch_size": 8,
                "detail_concurrency": 2,
                "review_threshold": 0.80,
            }

        async def parse_semantic_map(self, indexed_text, *, runtime=None, progress_callback=None):  # noqa: ANN001
            return (
                {
                    "route_clues": [{"clue_temp_id": "C1", "line_refs": ["L1"], "context_block_id": "B1", "raw_text": "南京港装动力煤到芜湖港"}],
                    "context_blocks": [{"context_block_id": "B1", "route_clue_ids": ["C1"], "line_refs": ["L1"], "shared_contact_phone": "13800000000"}],
                    "warnings": [],
                },
                {"ok": True},
            )

        async def complete_candidate_fields(self, indexed_text, semantic_map, *, runtime=None, progress_callback=None):  # noqa: ANN001
            return (
                [
                    _segment(
                        clue_temp_id="C1",
                        line_refs=["L1"],
                        context_block_id="B1",
                        raw_text="南京港装动力煤到芜湖港",
                        evidence=["南京港装动力煤到芜湖港", "13800000000"],
                    )
                ],
                [{"ok": True}],
                [],
                [{"batch_index": 1, "clue_count": 1, "evidence_line_count": 1}],
            )

        async def review_risky_segments(self, indexed_text, semantic_map, segments, *, runtime=None, progress_callback=None):  # noqa: ANN001
            return [], None, 0, []

        def merge_review_results(self, segments, review_results):  # noqa: ANN001
            return segments

    monkeypatch.setattr(freight_batch_service_module, "DashScopeQwenFreightParserClient", StagedParser)

    service = FreightBatchTaskService(session)
    batch = await service.create_wechat_batch(FreightBatchCreateRequest(raw_text="南京港装动力煤到芜湖港，联系13800000000"), creator_id=7)
    detail = await service.run_parse_now(batch.id, requested_by=7)
    stored = await session.scalar(select(FreightBatchTask).where(FreightBatchTask.id == batch.id))

    assert detail.batch.status_code == "PARSED"
    assert stored is not None
    timings = stored.raw_response_json["timings"]
    assert timings["AI_DETAIL_REQUEST_COUNT"] == 1
    assert timings["AI_DETAIL_EVIDENCE_LINE_COUNTS"] == [1]
    assert timings["AI_REVIEW_REQUEST_COUNT"] == 0


@pytest.mark.asyncio
async def test_wechat_reparse_saving_failure_keeps_existing_unconfirmed_data(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = FreightBatchTask(
        batch_no="FBT-RETRY",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_text="旧批次重新解析",
        status_code="FAILED",
        review_flow_status_code="REVIEWING",
    )
    session.add(batch)
    await session.flush()
    clue = FreightClue(
        clue_no="FCU-OLD",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        source_batch_id=batch.id,
        segment_index=1,
        raw_text="旧线索",
        status_code="CANDIDATE_CREATED",
    )
    session.add(clue)
    await session.flush()
    session.add(
        FreightCandidate(
            candidate_no="FCA-OLD",
            source_type_code="WECHAT",
            source_channel_code="WECHAT_TEXT",
            source_batch_id=batch.id,
            clue_id=clue.id,
            raw_origin_text="南京港",
            raw_destination_text="芜湖港",
            raw_commodity_name="动力煤",
            cargo_title="旧候选",
            availability_status_code="READY",
            status_code="PENDING",
        )
    )
    await session.commit()
    FakeFreightParser.segments = [_segment(raw_text="新线索")]

    async def fail_bulk_create(self, rows):  # noqa: ANN001
        raise RuntimeError("模拟保存失败")

    monkeypatch.setattr(freight_support_module.FreightCandidateRepository, "bulk_create", fail_bulk_create)

    with pytest.raises(RuntimeError, match="模拟保存失败"):
        await FreightBatchTaskService(session).run_parse_now(batch.id, requested_by=7)

    candidates = await freight_support_module.FreightCandidateRepository(session).list_by_batch(batch.id)
    clues = await freight_support_module.FreightClueRepository(session).list_by_batch(batch.id)
    refreshed = await session.scalar(select(FreightBatchTask).where(FreightBatchTask.id == batch.id))
    assert [item.candidate_no for item in candidates] == ["FCA-OLD"]
    assert [item.clue_no for item in clues] == ["FCU-OLD"]
    assert refreshed is not None
    assert refreshed.status_code == "FAILED"


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


def test_normalization_suggestion_routes_are_task_scoped_only() -> None:
    paths = {route.path for route in freight_router.routes}

    assert "/normalization-suggestions" not in paths
    assert "/normalization-suggestions/bulk-apply" not in paths
    assert "/normalization-suggestions/{suggestion_id}/apply" not in paths
    assert "/normalization-suggestions/{suggestion_id}/reject" not in paths
    assert "/normalization/tasks/{task_id}/suggestions" in paths
    assert "/normalization/tasks/{task_id}/suggestions/bulk-apply" in paths
    assert "/normalization/tasks/{task_id}/suggestions/bulk-reject" in paths
    assert "/normalization/tasks/{task_id}/suggestions/{suggestion_id}/apply" in paths
    assert "/normalization/tasks/{task_id}/suggestions/{suggestion_id}/reject" in paths


@pytest.mark.asyncio
async def test_ai_detail_dirty_price_tonnage_enters_review_without_schema_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_text = "芜湖到江阴 板坯 5200/5500左右"
    indexed = FreightTextIndexer().index(raw_text)
    semantic_map = {
        "route_clues": [
            {
                "clue_temp_id": "C1",
                "line_refs": ["L1"],
                "context_block_id": "B1",
                "raw_text": raw_text,
                "route_summary": "芜湖到江阴板坯",
                "confidence_score": 0.9,
            }
        ],
        "context_blocks": [{"context_block_id": "B1", "route_clue_ids": ["C1"], "line_refs": ["L1"]}],
        "context_notes": [],
    }
    payload = {
        "segments": [
            {
                "clue_temp_id": "C1",
                "segment_index": 1,
                "context_block_id": "B1",
                "line_refs": ["L1"],
                "raw_text": raw_text,
                "origin_text": "芜湖",
                "destination_text": "江阴",
                "commodity_name": "板坯",
                "unit_price": "5200/5500左右",
                "availability_status_code": "READY",
                "confidence_score": 0.9,
            }
        ]
    }
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())

    async def fake_call_json(**kwargs):
        _ = kwargs
        return payload, {"ok": True}

    monkeypatch.setattr(client, "_call_json", fake_call_json)

    segments, _, warnings, _ = await client.complete_candidate_fields(
        indexed,
        semantic_map,
        runtime={
            "detail_model": "qwen-turbo",
            "api_key": "test",
            "timeout": 30,
            "detail_batch_size": 8,
            "detail_concurrency": 1,
        },
    )

    assert len(segments) == 1
    assert segments[0].get("unit_price") is None
    assert segments[0]["raw_tonnage_text"] == "5200/5500左右"
    assert segments[0]["needs_strong_review"] is True
    assert segments[0]["ai_review_status_code"] == "REVIEW_REQUIRED"
    assert "AI 将疑似吨位误填为价格" in segments[0]["manual_review_reason"]
    assert any("疑似吨位误填为价格" in item for item in warnings)


@pytest.mark.asyncio
async def test_wechat_detail_model_upgrades_for_complex_semantic_map(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_lines = [
        "南京到芜湖动力煤1000吨",
        "太仓到无锡黄沙2000吨",
        "镇江到常州石子1500吨",
    ]
    indexed = FreightTextIndexer().index("\n".join(raw_lines))
    semantic_map = {
        "route_clues": [
            {"clue_temp_id": f"C{index}", "line_refs": [f"L{index}"], "raw_text": line}
            for index, line in enumerate(raw_lines, start=1)
        ],
        "context_blocks": [{"context_block_id": "B1", "route_clue_ids": ["C1", "C2"], "line_refs": ["L1", "L2"]}],
    }
    segments_payload = {
        "segments": [
            {
                "clue_temp_id": "C1",
                "segment_index": 1,
                "line_refs": ["L1"],
                "raw_text": raw_lines[0],
                "origin_text": "南京",
                "destination_text": "芜湖",
                "commodity_name": "动力煤",
                "raw_tonnage_text": "1000吨",
                "estimated_tonnage": 1000,
                "availability_status_code": "READY",
                "confidence_score": 0.9,
                "field_evidence": {
                    "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "南京"},
                    "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "芜湖"},
                    "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "动力煤"},
                    "raw_tonnage_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "1000吨"},
                },
                "tonnage_decision": {
                    "status_code": "PASS",
                    "selected_text": "1000吨",
                    "source_type_code": "LOCAL_LINE",
                    "line_refs": ["L1"],
                    "belongs_to_current_segment": True,
                },
            }
        ]
    }
    called_models: list[str] = []
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())

    async def fake_call_json(**kwargs):
        called_models.append(kwargs["model"])
        return segments_payload, {"ok": True, "model": kwargs["model"]}

    monkeypatch.setattr(client, "_call_json", fake_call_json)

    _, _, _, metrics = await client.complete_candidate_fields(
        indexed,
        semantic_map,
        runtime={
            "semantic_model": "qwen-plus",
            "detail_model": "qwen-turbo",
            "api_key": "test",
            "timeout": 30,
            "detail_batch_size": 8,
            "detail_concurrency": 1,
        },
    )

    assert called_models == ["qwen-plus"]
    assert metrics[0]["detail_model"] == "qwen-plus"


@pytest.mark.asyncio
async def test_wechat_parse_low_route_recall_calls_ai_repair_once(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_lines = [
        "南京到芜湖动力煤1000吨",
        "太仓到无锡黄沙2000吨",
        "镇江到常州石子1500吨",
        "苏州到杭州矿粉1800吨",
        "泰州到盐城砂石1200吨",
        "常州到南通钢材2200吨",
        "扬州到淮安水渣1300吨",
    ]
    raw_text = "\n".join(raw_lines)
    low_recall_map = {
        "route_clues": [{"clue_temp_id": "C1", "line_refs": [f"L{i}" for i in range(1, 8)], "raw_text": raw_text}],
        "context_blocks": [],
        "context_notes": [],
    }
    repaired_map = {
        "semantic_map": {
            "route_clues": [
                {"clue_temp_id": f"C{index}", "line_refs": [f"L{index}"], "raw_text": line}
                for index, line in enumerate(raw_lines, start=1)
            ],
            "context_blocks": [],
            "context_notes": [],
        },
        "segments": [],
        "repair_summary": "拆分为七条线索",
    }
    detail_payload = {
        "segments": [
            {
                "clue_temp_id": "C1",
                "segment_index": 1,
                "line_refs": ["L1"],
                "raw_text": raw_lines[0],
                "origin_text": "南京",
                "destination_text": "芜湖",
                "commodity_name": "动力煤",
                "raw_tonnage_text": "1000吨",
                "estimated_tonnage": 1000,
                "availability_status_code": "READY",
                "confidence_score": 0.91,
                "evidence": [raw_lines[0]],
                "field_evidence": {
                    "origin_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "南京"},
                    "destination_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "芜湖"},
                    "commodity_name": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "动力煤"},
                    "raw_tonnage_text": {"source_type_code": "LOCAL_LINE", "line_refs": ["L1"], "evidence_text": "1000吨"},
                },
                "tonnage_decision": {
                    "status_code": "PASS",
                    "selected_text": "1000吨",
                    "source_type_code": "LOCAL_LINE",
                    "line_refs": ["L1"],
                    "belongs_to_current_segment": True,
                },
            }
        ]
    }
    stage_calls: list[str] = []
    client = DashScopeQwenFreightParserClient(runtime_config=SimpleNamespace())

    async def fake_runtime():
        return {
            "provider": "TEST",
            "semantic_model": "qwen-plus",
            "detail_model": "qwen-turbo",
            "review_model": "qwen-plus",
            "api_key": "test",
            "timeout": 30,
            "detail_batch_size": 8,
            "detail_concurrency": 1,
            "review_threshold": 0.80,
            "warn_raw_chars": 0,
        }

    async def fake_call_json(**kwargs):
        stage_calls.append(kwargs["stage_code"])
        if kwargs["stage_code"] == "AI_SEMANTIC_MAP":
            return low_recall_map, {"stage": "semantic"}
        if kwargs["stage_code"] == "AI_SEMANTIC_REPAIR":
            return repaired_map, {"stage": "repair"}
        if kwargs["stage_code"] == "AI_DETAIL":
            return detail_payload, {"stage": "detail", "model": kwargs["model"]}
        raise AssertionError(f"unexpected stage {kwargs['stage_code']}")

    monkeypatch.setattr(client, "_runtime", fake_runtime)
    monkeypatch.setattr(client, "_call_json", fake_call_json)

    parsed = await client.parse(raw_text, source_type_code="WECHAT")

    assert stage_calls.count("AI_SEMANTIC_REPAIR") == 0
    assert parsed.semantic_map["coverage_audit"]["route_unit_count"] == 7
    assert len(parsed.segments) == 7


@pytest.mark.asyncio
async def test_normalization_task_suggestions_are_isolated_and_review_status_closes(session: AsyncSession) -> None:
    node = await session.scalar(select(TransportNode).where(TransportNode.code == "ND-NJ"))
    assert node is not None
    now = datetime.utcnow()
    freight_one = Freight(
        freight_no="FR-NORM-0001",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_origin_text="南京港",
        raw_destination_text="芜湖港",
        raw_commodity_name="动力煤",
        cargo_title="南京港至芜湖港动力煤",
        commodity_match_level_code="STANDARD",
        origin_match_level_code="RAW",
        destination_match_level_code="NODE",
        estimated_tonnage=Decimal("1000"),
        status_code="PUBLISHED",
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
    )
    freight_two = Freight(
        freight_no="FR-NORM-0002",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        raw_origin_text="南京港",
        raw_destination_text="芜湖港",
        raw_commodity_name="动力煤",
        cargo_title="南京港至芜湖港动力煤",
        commodity_match_level_code="STANDARD",
        origin_match_level_code="RAW",
        destination_match_level_code="NODE",
        estimated_tonnage=Decimal("1200"),
        status_code="PUBLISHED",
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
    )
    task_one = FreightNormalizationTask(
        task_no="FNT-SCOPE-0001",
        status_code="SUCCESS",
        review_status_code="PENDING_REVIEW",
        stage_code="DONE",
        stage_name="清洗完成",
        progress_percent=100,
        scanned_count=1,
        suggestion_count=1,
        pending_count=1,
        finished_at=now,
        heartbeat_at=now,
    )
    task_two = FreightNormalizationTask(
        task_no="FNT-SCOPE-0002",
        status_code="SUCCESS",
        review_status_code="PENDING_REVIEW",
        stage_code="DONE",
        stage_name="清洗完成",
        progress_percent=100,
        scanned_count=1,
        suggestion_count=2,
        pending_count=2,
        finished_at=now,
        heartbeat_at=now,
    )
    session.add_all([freight_one, freight_two, task_one, task_two])
    await session.flush()
    suggestion_one = FreightNormalizationSuggestion(
        clean_task_id=task_one.id,
        freight_id=freight_one.id,
        suggestion_type_code="ORIGIN",
        raw_text="南京港",
        current_level_code="RAW",
        suggested_level_code="NODE",
        suggested_node_id=node.id,
        suggested_province_code=node.province_code,
        suggested_city_code=node.city_code,
        confidence_score=Decimal("0.9000"),
        status_code="PENDING",
        auto_apply_flag=False,
    )
    suggestion_two = FreightNormalizationSuggestion(
        clean_task_id=task_two.id,
        freight_id=freight_two.id,
        suggestion_type_code="ORIGIN",
        raw_text="南京港",
        current_level_code="RAW",
        suggested_level_code="NODE",
        suggested_node_id=node.id,
        suggested_province_code=node.province_code,
        suggested_city_code=node.city_code,
        confidence_score=Decimal("0.9000"),
        status_code="PENDING",
        auto_apply_flag=False,
    )
    suggestion_three = FreightNormalizationSuggestion(
        clean_task_id=task_two.id,
        freight_id=freight_two.id,
        suggestion_type_code="COMMODITY",
        raw_text="动力煤",
        current_level_code="RAW",
        suggested_level_code="STANDARD",
        confidence_score=Decimal("0.7000"),
        status_code="PENDING",
        auto_apply_flag=False,
    )
    session.add_all([suggestion_one, suggestion_two, suggestion_three])
    await session.commit()

    service = FreightNormalizationSuggestionService(session)
    task_one_page = await service.list_task_suggestions(
        task_one.id,
        keyword=None,
        status_code="PENDING",
        suggestion_type_code=None,
        page=1,
        page_size=20,
    )

    assert [item.id for item in task_one_page.items] == [suggestion_one.id]

    applied = await service.apply(task_one.id, suggestion_one.id, operator_id=9)
    assert applied.status_code == "APPLIED"
    task_one_detail = await service.get_task(task_one.id)
    assert task_one_detail.review_status_code == "COMPLETED"
    assert task_one_detail.pending_count == 0
    assert task_one_detail.applied_count == 1

    bulk_result = await service.bulk_reject(
        task_two.id,
        FreightNormalizationBulkActionRequest(apply_all_filtered=True),
        operator_id=9,
    )
    task_two_detail = await service.get_task(task_two.id)

    assert bulk_result.processed_count == 2
    assert task_two_detail.review_status_code == "COMPLETED"
    assert task_two_detail.pending_count == 0
    assert task_two_detail.rejected_count == 2


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
    assert result.review_status_code == "NOT_REQUIRED"
    assert result.auto_applied_count >= 3
    assert stored_task is not None
    assert stored_task.status_code == "SUCCESS"
    assert stored_task.review_status_code == "NOT_REQUIRED"
    assert stored_task.review_completed_at is not None
    assert stored is not None
    assert stored.commodity_standard_id is not None
    assert stored.origin_city_code == "320100"
    assert stored.destination_city_code == "340200"
    assert {item.status_code for item in suggestions} == {"AUTO_APPLIED"}
