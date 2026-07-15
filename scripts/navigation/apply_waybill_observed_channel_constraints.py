"""Attach waybill-observed vessel constraints to matched navigation channels.

The CSV route labels are operational evidence, not official technical grades.
This script writes them only into source_audit_summary and optional aliases for
high-confidence name variants.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import NavigationChannel


REPORT_DIR = Path("runtime/navigation-production/reports")
DEFAULT_ANALYSIS = REPORT_DIR / "waybill_route_reference_analysis_constraints_20260608.json"

WATER_TO_CHANNEL: dict[str, dict[str, Any]] = {
    "京杭大运河": {"channel_code": "NC-GRAND-CANAL", "alias": "京杭大运河", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "长江干流": {"channel_code": "NC-YANGTZE", "alias": "长江干流", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "长江干流(江苏段)": {"channel_code": "NC-YANGTZE", "match_policy_code": "SECTION_LABEL_TO_MAIN_CHANNEL"},
    "长江干流(安徽段)": {"channel_code": "NC-YANGTZE", "match_policy_code": "SECTION_LABEL_TO_MAIN_CHANNEL"},
    "黄浦江": {"channel_code": "NC-HUANGPU-RIVER", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "钱塘江": {"channel_code": "NC-QIANTANG-RIVER", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "富春江": {"channel_code": "NC-FUCHUN-RIVER", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "淮河": {"channel_code": "NC-HUAIHE", "match_policy_code": "HIGH_CONFIDENCE_ALIAS"},
    "淮河上游": {"channel_code": "NC-HUAIHE", "match_policy_code": "SECTION_LABEL_TO_MAIN_CHANNEL"},
    "沙颖河": {"channel_code": "NC-SHAYING-RIVER", "alias": "沙颖河", "match_policy_code": "NAME_VARIANT_ALIAS"},
}

BLOCKED_WATER_SYSTEMS: dict[str, str] = {
    "苏州河": "Route-level label; graph51 missing-water analysis showed it is not segment-level evidence.",
    "通榆河": "No local NavigationChannel exists yet; create missing channel/seed candidate first.",
}


def _constraint_payload(item: dict[str, Any], *, match_policy_code: str, source_csv: str) -> dict[str, Any]:
    return {
        "water_system_name": item["water_system_name"],
        "match_policy_code": match_policy_code,
        "source_policy_code": item.get("source_policy_code") or "OBSERVED_WAYBILL_CONSTRAINT_NOT_OFFICIAL_GRADE",
        "source_csv": source_csv,
        "condition_reference_count": item.get("condition_reference_count"),
        "geometry_reference_count": item.get("geometry_reference_count"),
        "od_count": item.get("od_count"),
        "route_count": item.get("route_count"),
        "observed_max_tonnage": item.get("observed_max_tonnage"),
        "observed_max_ship_width_m": item.get("observed_max_ship_width_m"),
        "observed_max_ship_length_m": item.get("observed_max_ship_length_m"),
        "observed_tonnage_stats": item.get("observed_tonnage_stats"),
        "observed_ship_width_m_stats": item.get("observed_ship_width_m_stats"),
        "observed_ship_length_m_stats": item.get("observed_ship_length_m_stats"),
        "quality_codes": item.get("quality_codes") or {},
    }


def _merge_aliases(existing: list[Any] | None, alias: str | None) -> tuple[list[str], bool]:
    aliases = [str(item) for item in (existing or []) if str(item or "").strip()]
    if not alias:
        return aliases, False
    if alias in aliases:
        return aliases, False
    return [*aliases, alias], True


async def run(*, analysis_path: Path, apply: bool, output: Path) -> dict[str, Any]:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    source_csv = str((analysis.get("args") or {}).get("source_csv") or analysis.get("source_csv") or "")
    rows_by_water = {
        str(item.get("water_system_name")): item
        for item in analysis.get("condition_constraints_by_water_system", [])
        if item.get("water_system_name")
    }
    applied_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    report: dict[str, Any] = {
        "applied": apply,
        "applied_at": applied_at,
        "analysis_path": str(analysis_path),
        "updated_channels": [],
        "blocked_water_systems": [],
        "unmapped_water_systems": [],
        "guardrail": (
            "Observed waybill constraints are evidence only. They do not replace official channel grade or deterministic "
            "vessel constraint validation."
        ),
    }
    async with AsyncSessionLocal() as session:
        channel_rows = list(
            (
                await session.execute(
                    select(NavigationChannel).where(
                        NavigationChannel.channel_code.in_(
                            {entry["channel_code"] for entry in WATER_TO_CHANNEL.values()}
                        )
                    )
                )
            ).scalars()
        )
        channel_by_code = {row.channel_code: row for row in channel_rows}
        for water_name, item in rows_by_water.items():
            if water_name in BLOCKED_WATER_SYSTEMS:
                report["blocked_water_systems"].append(
                    {
                        "water_system_name": water_name,
                        "reason": BLOCKED_WATER_SYSTEMS[water_name],
                        "condition_reference_count": item.get("condition_reference_count"),
                        "geometry_reference_count": item.get("geometry_reference_count"),
                    }
                )
                continue
            mapping = WATER_TO_CHANNEL.get(water_name)
            if mapping is None:
                report["unmapped_water_systems"].append(
                    {
                        "water_system_name": water_name,
                        "condition_reference_count": item.get("condition_reference_count"),
                        "geometry_reference_count": item.get("geometry_reference_count"),
                    }
                )
                continue
            channel = channel_by_code.get(mapping["channel_code"])
            if channel is None:
                report["unmapped_water_systems"].append(
                    {
                        "water_system_name": water_name,
                        "channel_code": mapping["channel_code"],
                        "reason": "mapped local channel not found",
                    }
                )
                continue
            aliases, alias_added = _merge_aliases(channel.alias_names, mapping.get("alias"))
            existing_summary = dict(channel.source_audit_summary or {})
            evidence_by_water = dict(existing_summary.get("waybill_observed_constraints_by_water_system") or {})
            evidence_by_water[water_name] = _constraint_payload(
                item,
                match_policy_code=str(mapping["match_policy_code"]),
                source_csv=source_csv,
            )
            next_summary = {
                **existing_summary,
                "waybill_observed_constraints_by_water_system": evidence_by_water,
                "waybill_observed_constraints_source_policy_code": "OBSERVED_WAYBILL_CONSTRAINT_NOT_OFFICIAL_GRADE",
                "waybill_observed_constraints_updated_at": applied_at,
            }
            report["updated_channels"].append(
                {
                    "channel_id": int(channel.id),
                    "channel_code": channel.channel_code,
                    "channel_name": channel.channel_name,
                    "water_system_name": water_name,
                    "match_policy_code": mapping["match_policy_code"],
                    "alias_added": mapping.get("alias") if alias_added else None,
                    "official_grade_current": channel.technical_grade_current_code,
                    "official_grade_planned": channel.technical_grade_planned_code,
                    "observed_max_tonnage": item.get("observed_max_tonnage"),
                    "observed_max_ship_width_m": item.get("observed_max_ship_width_m"),
                    "observed_max_ship_length_m": item.get("observed_max_ship_length_m"),
                    "condition_reference_count": item.get("condition_reference_count"),
                    "geometry_reference_count": item.get("geometry_reference_count"),
                }
            )
            if apply:
                channel.alias_names = aliases
                channel.source_audit_summary = next_summary
        if apply:
            await session.commit()
    report["updated_channel_count"] = len({item["channel_code"] for item in report["updated_channels"]})
    report["updated_water_system_count"] = len(report["updated_channels"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_DIR / f"waybill_observed_channel_constraints_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.json",
    )
    args = parser.parse_args()
    report = asyncio.run(run(analysis_path=args.analysis, apply=args.apply, output=args.output))
    print(
        json.dumps(
            {
                "applied": report["applied"],
                "updated_channel_count": report["updated_channel_count"],
                "updated_water_system_count": report["updated_water_system_count"],
                "blocked_water_system_count": len(report["blocked_water_systems"]),
                "unmapped_water_system_count": len(report["unmapped_water_systems"]),
            },
            ensure_ascii=False,
        )
    )
    print(args.output)


if __name__ == "__main__":
    main()
