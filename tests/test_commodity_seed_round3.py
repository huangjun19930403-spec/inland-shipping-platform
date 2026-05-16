from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.freight.service import _is_packaging_only_commodity_text
from scripts.seeds.curation.commodity_seed import (
    EXCLUDED_TMS_COMMODITY_NAMES,
    build_commodity_term_index,
    build_coverage_report,
    load_seed_standards,
    normalize_commodity_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TMS_COMMODITY_CSV = Path("/Users/hj/Downloads/货品数据.csv")

VALID_CARGO_FORM_CODES = {
    "BULK_GRANULAR",
    "POWDER",
    "BLOCK",
    "LIQUID",
    "BAGGED",
    "CONTAINERIZED",
    "ROLL",
    "EQUIPMENT",
    "OTHER",
}
VALID_PACKAGING_FORM_CODES = {
    "BULK",
    "TON_BAG",
    "BAGGED",
    "BOXED",
    "CONTAINER",
    "GENERAL_CARGO",
}
VALID_TRANSPORT_MODE_CODES = {"WATER", "ROAD", "RAIL", "MANUAL", "UNKNOWN"}
VALID_SHIP_TYPE_CODES = {
    "DRY_BULK",
    "GENERAL_CARGO",
    "SELF_UNLOADING_SAND",
    "BULK_CEMENT",
    "CONTAINER",
    "BULK_CONTAINER",
    "MULTI_PURPOSE",
    "OIL_TANKER",
    "CHEMICAL_TANKER",
    "ENGINEERING",
    "TUG",
    "OTHER",
}
VALID_NODE_TYPE_CODES = {
    "PORT",
    "TERMINAL",
    "ANCHORAGE",
    "LOCK",
    "LOGISTICS_PARK",
    "RAIL_STATION",
    "HIGHWAY_PORT",
    "INTERMODAL_HUB",
    "OTHER",
}
VALID_HANDLING_MODE_CODES = {
    "GRAB",
    "PIPELINE",
    "CONVEYOR",
    "CRANE",
    "MANUAL",
    "SELF_UNLOADING",
    "OTHER",
}
VALID_RULE_TYPE_CODES = {"RECOMMENDED", "ALLOWED", "FORBIDDEN"}


def _standards() -> list[dict]:
    return load_seed_standards(
        PROJECT_ROOT / "scripts" / "seed_data" / "commodity" / "commodity_standards.json"
    )


def _types() -> list[dict]:
    return json.loads(
        (
            PROJECT_ROOT
            / "scripts"
            / "seed_data"
            / "commodity"
            / "commodity_types.json"
        ).read_text(encoding="utf-8")
    )


def _categories() -> list[dict]:
    return json.loads(
        (
            PROJECT_ROOT
            / "scripts"
            / "seed_data"
            / "commodity"
            / "commodity_categories.json"
        ).read_text(encoding="utf-8")
    )


def _term_index() -> dict[str, str]:
    index, duplicates = build_commodity_term_index(_standards())
    assert duplicates == {}
    return index


def test_round3_commodity_seed_has_national_core_coverage_and_unique_terms() -> None:
    categories = _categories()
    types = _types()
    standards = _standards()
    category_codes = {row["code"] for row in categories}
    type_codes = {row["code"] for row in types}
    codes = [row["code"] for row in standards]
    standard_type_codes = {row["type_code"] for row in standards}
    category_names = {row["name"] for row in categories}

    assert len(categories) >= 19
    assert len(types) >= 116
    assert len(standards) >= 160
    assert len(codes) == len(set(codes))
    assert {row["category_code"] for row in types}.issubset(category_codes)
    assert standard_type_codes.issubset(type_codes)
    assert type_codes.issubset(standard_type_codes)
    assert build_commodity_term_index(standards)[1] == {}
    assert {
        "煤炭及制品",
        "石油、天然气及制品",
        "金属矿石",
        "钢铁及有色金属",
        "矿物性建筑材料",
        "水泥",
        "木材",
        "非金属矿石",
        "化肥及农药",
        "盐",
        "粮食",
        "机械设备",
        "化工原料及制品",
        "农、林、牧、渔业产品",
    }.issubset(category_names)


def test_round3_commodity_seed_uses_known_dictionary_codes() -> None:
    for row in _standards():
        assert row["cargo_form_code"] in VALID_CARGO_FORM_CODES
        for item in row.get("packaging_forms") or []:
            assert item["code"] in VALID_PACKAGING_FORM_CODES
        for item in row.get("transport_modes") or []:
            assert item["code"] in VALID_TRANSPORT_MODE_CODES
        for item in row.get("ship_type_rules") or []:
            assert item["code"] in VALID_SHIP_TYPE_CODES
            assert item["rule_type_code"] in VALID_RULE_TYPE_CODES
        for item in row.get("node_type_rules") or []:
            assert item["code"] in VALID_NODE_TYPE_CODES
            assert item["rule_type_code"] in VALID_RULE_TYPE_CODES
        for item in row.get("handling_mode_rules") or []:
            assert item["code"] in VALID_HANDLING_MODE_CODES
            assert item["rule_type_code"] in VALID_RULE_TYPE_CODES


def test_round3_core_match_examples_resolve_to_intended_standards() -> None:
    index = _term_index()

    assert index[normalize_commodity_name("矿粉")] == "STD_MINERAL_POWDER_GENERAL"
    assert index[normalize_commodity_name("铁矿粉")] == "STD_IRON_ORE_FINE"
    assert index[normalize_commodity_name("铁精粉")] == "STD_IRON_ORE_FINE"
    assert index[normalize_commodity_name("Pta吨包")] == "STD_PTA"
    assert index[normalize_commodity_name("碎石")] == "STD_CRUSHED_STONE_10_20"
    assert index[normalize_commodity_name("水泥")] == "STD_BULK_CEMENT_PO425"
    assert index[normalize_commodity_name("玉米")] == "STD_CORN_BULK"
    assert normalize_commodity_name("吨包") not in index
    assert normalize_commodity_name("吨袋") not in index
    for excluded_name in EXCLUDED_TMS_COMMODITY_NAMES:
        if excluded_name.startswith("测试货品"):
            assert normalize_commodity_name(excluded_name) not in index


def test_round3_packaging_only_terms_are_runtime_guarded() -> None:
    assert _is_packaging_only_commodity_text("吨包")
    assert _is_packaging_only_commodity_text(" 吨袋 ")
    assert not _is_packaging_only_commodity_text("Pta吨包")


def test_round3_ton_bag_composite_goods_have_ton_bag_packaging() -> None:
    standards = {row["code"]: row for row in _standards()}

    for code in ["STD_PTA", "STD_POTASH_FERTILIZER", "STD_BULK_CEMENT_PO425"]:
        packaging_codes = {
            item["code"] for item in standards[code].get("packaging_forms") or []
        }
        assert "TON_BAG" in packaging_codes


def test_round3_tms_attachment_is_covered_when_available() -> None:
    if not TMS_COMMODITY_CSV.exists():
        pytest.skip("TMS commodity CSV attachment is not available in this environment")

    report = build_coverage_report(TMS_COMMODITY_CSV)

    assert report.row_count == 126
    assert report.unique_count == 118
    assert report.covered_count == 114
    assert report.excluded_count == 4
    assert report.unmatched_names == []
    assert report.duplicate_terms == {}
