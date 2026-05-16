from __future__ import annotations

import json
from pathlib import Path

from app.modules.commodity.recognition.matcher import (
    CommodityDeterministicMatcher,
    is_packaging_only_text,
)
from app.modules.commodity.recognition.repository import CommodityAliasMatchRow, CommodityStandardMatchRow


ROOT = Path(__file__).resolve().parents[1]


def _seed_match_rows() -> list[CommodityStandardMatchRow]:
    standards = json.loads((ROOT / "scripts/seed_data/commodity/commodity_standards.json").read_text())
    rows: list[CommodityStandardMatchRow] = []
    for index, item in enumerate(standards, start=1):
        rows.append(
            CommodityStandardMatchRow(
                id=index,
                code=item["code"],
                name=item["name"],
                short_name=item.get("short_name"),
                english_name=item.get("english_name"),
                category_id=None,
                category_name=None,
                type_id=index,
                type_name=item.get("type_code"),
                main_unit_code=item.get("main_unit_code") or "TON",
                cargo_form_code=item.get("cargo_form_code"),
                is_bulk_cargo=True,
                is_container_suitable=bool(item.get("is_container_suitable")),
                is_hazardous=bool(item.get("is_hazardous")),
                pollution_risk_level_code=item.get("pollution_risk_level_code"),
                recognition_priority=int(item.get("recognition_priority") or 50),
                aliases=tuple(
                    CommodityAliasMatchRow(
                        id=index * 1000 + alias_index,
                        alias_name=alias["alias_name"],
                        alias_type_code=alias.get("alias_type_code") or "COMMON_NAME",
                        match_weight=int(alias.get("match_weight") or 80),
                        is_enabled=bool(alias.get("is_enabled", True)),
                    )
                    for alias_index, alias in enumerate(item.get("aliases") or [], start=1)
                ),
            )
        )
    return rows


def test_production_seed_core_aliases_match_expected_standards() -> None:
    matcher = CommodityDeterministicMatcher(_seed_match_rows(), packaging_terms={"吨袋", "吨包", "散装"})

    for raw_name in ("黄沙", "黄砂", "河沙"):
        assert matcher.match(raw_name)[0].standard_code == "STD_RIVER_SAND"

    assert matcher.match("矿粉")[0].standard_code == "STD_MINERAL_POWDER_GENERAL"
    assert matcher.match("Pta吨包")[0].standard_code == "STD_PTA"


def test_packaging_only_text_is_not_a_standard_commodity_candidate() -> None:
    assert is_packaging_only_text("吨袋", {"吨袋", "吨包"})
    matcher = CommodityDeterministicMatcher(_seed_match_rows(), packaging_terms={"吨袋", "吨包", "散装"})
    assert matcher.match("吨袋") == []


def test_commodity_recognition_module_stays_separate_from_other_ai_domains() -> None:
    module_dir = ROOT / "app/modules/commodity/recognition"
    forbidden = ("app.modules.freight", "app.modules.vessel", "app.modules.analysis")
    for path in module_dir.glob("*.py"):
        source = path.read_text()
        assert not any(token in source for token in forbidden), path
