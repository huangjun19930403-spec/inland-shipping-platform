from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.seeds.curation.address_freight_seed import curate
from scripts.seeds.curation.commodity_seed import EXCLUDED_TMS_COMMODITY_NAMES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDRESS_CSV = Path("/Users/hj/Downloads/地址数据.csv")
WAYBILL_CSV = Path("/Users/hj/Downloads/运单数据-修正.csv")

VALID_NODE_TYPES = {
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
VALID_BUSINESS_CATEGORIES = {
    "LOADING",
    "UNLOADING",
    "TRANSFER",
    "TRANSSHIPMENT",
    "STORAGE",
    "PASSAGE",
    "COMPREHENSIVE",
}
VALID_PACKAGING_FORMS = {
    "BULK",
    "TON_BAG",
    "BAGGED",
    "BOXED",
    "CONTAINER",
    "GENERAL_CARGO",
}
VALID_HANDLING_MODES = {
    "GRAB",
    "PIPELINE",
    "CONVEYOR",
    "CRANE",
    "MANUAL",
    "SELF_UNLOADING",
    "OTHER",
}


def _read_json(relative_path: str) -> list[dict]:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


def _normalized(value: str) -> str:
    return "".join(str(value or "").split()).lower()


def test_round4_transport_node_seed_is_curated_and_consistent() -> None:
    nodes = _read_json("scripts/seed_data/address/transport_nodes.json")
    regions = _read_json("scripts/seed_data/address/business_regions.json")
    admin_regions = _read_json("scripts/seed_data/admin_region/admin_region_raw.json")

    node_codes = [row["code"] for row in nodes]
    region_codes = {row["code"] for row in regions}
    admin_codes = {row["adcode"] for row in admin_regions}
    alias_owners: dict[str, set[str]] = defaultdict(set)

    assert len(nodes) == 1181
    assert len(regions) == 6
    assert len(node_codes) == len(set(node_codes))
    assert all(row["business_region_code"] in region_codes for row in nodes)
    assert all(row["city_region_code"] in admin_codes for row in nodes)
    assert all(row["node_type_code"] in VALID_NODE_TYPES for row in nodes)

    for row in nodes:
        assert row["source"]["source_type_code"] == "TMS"
        assert row["source"]["source_address_codes"]
        assert row["profile"]["ext_json"]["source_type"] == "TMS_ADDRESS"
        assert row["longitude"] is not None
        assert row["latitude"] is not None
        for code in row.get("business_categories") or []:
            assert code in VALID_BUSINESS_CATEGORIES
        for code in row.get("packaging_forms") or []:
            assert code in VALID_PACKAGING_FORMS
        for code in row.get("handling_modes") or []:
            assert code in VALID_HANDLING_MODES
        for alias in row.get("aliases") or []:
            alias_owners[_normalized(alias["alias_name"])].add(row["code"])

    assert {term: owners for term, owners in alias_owners.items() if len(owners) > 1} == {}


def test_round4_tms_freight_seed_has_closed_historical_rows_with_full_refs() -> None:
    freights = _read_json("scripts/seed_data/freight/tms_freights.json")
    nodes = _read_json("scripts/seed_data/address/transport_nodes.json")
    regions = _read_json("scripts/seed_data/address/business_regions.json")
    standards = _read_json("scripts/seed_data/commodity/commodity_standards.json")

    node_codes = {row["code"] for row in nodes}
    region_codes = {row["code"] for row in regions}
    standard_codes = {row["code"] for row in standards}
    freight_nos = [row["freight_no"] for row in freights]
    source_refs = [row["source_ref_no"] for row in freights]

    assert len(freights) == 4081
    assert len(freight_nos) == len(set(freight_nos))
    assert len(source_refs) == len(set(source_refs))
    assert all(row["freight_no"].startswith("FR-TMS-") for row in freights)
    assert all(row["source_ref_no"].startswith("YD") for row in freights)

    for row in freights:
        assert row["source_type_code"] == "TMS"
        assert row["source_channel_code"] == "TMS_API"
        assert row["status_code"] == "CLOSED"
        assert row["hall_status_code"] == "NOT_LISTED"
        assert row["origin_node_code"] in node_codes
        assert row["destination_node_code"] in node_codes
        assert row["origin_region_code"] in region_codes
        assert row["destination_region_code"] in region_codes
        assert row["commodity_standard_code"] in standard_codes
        assert row["commodity_match_level_code"] == "STANDARD"
        assert row["origin_match_level_code"] == "NODE"
        assert row["destination_match_level_code"] == "NODE"
        assert row["raw_commodity_name"] not in EXCLUDED_TMS_COMMODITY_NAMES
        assert row["raw_commodity_name"] != "NULL"
        assert Decimal(str(row["estimated_tonnage"])) > 0
        assert row["source_ship_name"]
        assert row["normalized_ship_name"]

    commodity_counts = Counter(row["raw_commodity_name"] for row in freights)
    assert commodity_counts["碎石"] > 0
    assert commodity_counts["水泥"] > 0
    assert commodity_counts["玉米"] > 0


def test_round4_manifest_lists_address_and_freight_result_files() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "scripts" / "seed_data" / "production_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    resources = {item["resource"]: item["path"] for item in manifest["resources"]}

    assert resources["business_regions"] == "scripts/seed_data/address/business_regions.json"
    assert resources["transport_nodes"] == "scripts/seed_data/address/transport_nodes.json"
    assert resources["tms_freights"] == "scripts/seed_data/freight/tms_freights.json"


def test_round4_curation_report_matches_current_attachments_when_available() -> None:
    if not ADDRESS_CSV.exists() or not WAYBILL_CSV.exists():
        pytest.skip("Round 4 TMS address/waybill attachments are not available")

    _, _, _, report = curate(ADDRESS_CSV, WAYBILL_CSV, write_curated=False)

    assert report.address_rows == 1189
    assert report.node_count == 1181
    assert report.waybill_rows == 9926
    assert report.waybill_groups == 8168
    assert report.freight_count == 4081
    assert report.endpoint_exact_count == 189
    assert report.endpoint_alias_count == 67
    assert report.endpoint_unmatched_count == 66
    assert report.commodity_unmatched_names == []
    assert report.skipped_reason_counts == {
        "CORE_FIELD_CONFLICT": 2,
        "EXCLUDED_COMMODITY": 149,
        "NULL_KEY_FIELD": 2,
        "UNMATCHED_DESTINATION_NODE": 2414,
        "UNMATCHED_ORIGIN_NODE": 1520,
    }
