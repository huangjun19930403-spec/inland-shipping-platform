"""Apply explicit map-inferred water-body matches for planned navigation gaps.

The normal self-heal pass is intentionally conservative and only matches by
local names/aliases or existing guide geometry. Several planned-gap channels
have neither. This script captures the deterministic map/data decisions for
those gaps so the follow-up seed rebuild can use real local water geometry,
while still marking partial evidence as not route-verified.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelWaterBodyMatch, NavigationWaterBody
from app.models.address import NavigationChannel


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/planned_gap_water_body_match_repair_20260604.json"
MATCH_BATCH = "AUTO-PLANNED-GAP-MAP-WATER-NAME-20260604"
NAME_SOURCE = "MAP_LABEL_AND_LOCAL_REVIER_GEOMETRY"
PRODUCTION_BODY_ROLES = {"PRIMARY_HIERARCHY", "RX_FILL_GAP"}
PLANNING_LEVEL_GRADE = {
    "NATIONAL_CORE": "III",
    "NATIONAL_NETWORK": "III",
    "NATIONAL_IMPORTANT": "IV",
    "PROVINCIAL_HIGH_GRADE": "IV",
    "REGIONAL_IMPORTANT": "V",
    "PLANNED_GAP": "VI",
    "REVIEW": "VI",
}


@dataclass(frozen=True, slots=True)
class BodyRule:
    water_body_id: int
    matched_term: str
    score: int
    match_type_code: str = "MAP_LABEL_EXPLICIT_WATER_BODY"
    inferred_name: str | None = None
    issue_codes: tuple[str, ...] = ("MAP_LABEL_OR_PLANNED_GAP_INFERRED",)


@dataclass(frozen=True, slots=True)
class PlannedGapRule:
    channel_code: str
    body_rules: tuple[BodyRule, ...]
    publish_boundary_candidate: bool
    route_verification_status_code: str
    evidence: tuple[dict[str, str], ...]
    note: str


RULES: tuple[PlannedGapRule, ...] = (
    PlannedGapRule(
        channel_code="NC-SUBEI-CANAL",
        body_rules=(
            BodyRule(
                water_body_id=286848,
                matched_term="京杭运河",
                score=94,
                match_type_code="LOCAL_REVIER_EXACT_WATER_BODY",
                issue_codes=("PLANNED_GAP_ALIAS_TO_LOCAL_REVIER_NAME",),
            ),
        ),
        publish_boundary_candidate=True,
        route_verification_status_code="HIFLEET_CACHE_CANDIDATE",
        evidence=(
            {
                "source_code": "LOCAL_REVIER_WATER_BODY",
                "description": "本地 Revier 一级水系水体 286848 原始 NAME=京杭运河，可覆盖苏北运河候选路径的主干水域。",
            },
            {
                "source_code": "LOCAL_HIFLEET_CACHE",
                "description": "本地 HiFleet cache 1/21/44 与京杭运河水体存在覆盖，可继续反向生成 seed 中心线。",
            },
        ),
        note="苏北运河作为规划缺口，先绑定本地京杭运河实体；完整性仍以后续轨迹验证结果为准。",
    ),
    PlannedGapRule(
        channel_code="NC-XUSULIAN-CORRIDOR",
        body_rules=(
            BodyRule(
                water_body_id=287907,
                matched_term="徐洪河",
                score=86,
                match_type_code="LOCAL_REVIER_PARTIAL_CORRIDOR_WATER_BODY",
                issue_codes=("PLANNED_GAP_PARTIAL_WATER_BODY_MATCH",),
            ),
        ),
        publish_boundary_candidate=False,
        route_verification_status_code="PARTIAL_WATER_BODY_ONLY",
        evidence=(
            {
                "source_code": "LOCAL_REVIER_WATER_BODY",
                "description": "本地 Revier 四级水系水体 287907 原始 NAME=徐洪河，是徐宿连通道的可用局部水系证据。",
            },
        ),
        note="徐宿连通道仅有徐洪河局部水体，不能直接标记为完整边界或完整 Graph。",
    ),
    PlannedGapRule(
        channel_code="NC-SUSHEN-INNER-PORT-LINE",
        body_rules=(
            BodyRule(
                water_body_id=287899,
                matched_term="吴淞江",
                inferred_name="吴淞江",
                score=82,
                match_type_code="MAP_LABEL_INFERRED_UNNAMED_REVIER_WATER_BODY",
                issue_codes=("UNNAMED_REVIER_WATER_BODY_MAP_LABEL_INFERRED", "ROUTE_VERIFICATION_REQUIRED"),
            ),
        ),
        publish_boundary_candidate=False,
        route_verification_status_code="UNNAMED_WATER_BODY_NAMED_ONLY",
        evidence=(
            {
                "source_code": "LOCAL_REVIER_WATER_BODY",
                "description": "本地 Revier 四级水系水体 287899 原始 NAME 为空，bbox 位于苏申内港线吴淞江候选区间。",
            },
            {
                "source_code": "MAP_LABEL_INFERENCE",
                "description": "按地图位置将该未命名四级双线河作为吴淞江候选水体补生产显示名。",
            },
        ),
        note="该规则只解决无名称水体和候选匹配，不直接发布完整苏申内港线边界。",
    ),
    PlannedGapRule(
        channel_code="NC-DALU-LINE",
        body_rules=(
            BodyRule(
                water_body_id=289177,
                matched_term="大治河",
                score=90,
                match_type_code="LOCAL_REVIER_EXACT_WATER_BODY",
                issue_codes=("PLANNED_GAP_ALIAS_TO_LOCAL_REVIER_NAME",),
            ),
        ),
        publish_boundary_candidate=True,
        route_verification_status_code="LOCAL_WATER_BODY_BOUNDARY_CANDIDATE",
        evidence=(
            {
                "source_code": "LOCAL_REVIER_WATER_BODY",
                "description": "本地 Revier 五级水系水体 289177 原始 NAME=大治河，可作为大芦线候选水道的一段真实水体。",
            },
        ),
        note="大芦线先绑定本地大治河实体；是否完整通航仍由边界和轨迹验证决定。",
    ),
    PlannedGapRule(
        channel_code="NC-DAPU-LINE",
        body_rules=(
            BodyRule(
                water_body_id=289177,
                matched_term="大治河",
                score=78,
                match_type_code="LOCAL_REVIER_PARTIAL_CORRIDOR_WATER_BODY",
                issue_codes=("PLANNED_GAP_PARTIAL_WATER_BODY_MATCH", "ROUTE_VERIFICATION_REQUIRED"),
            ),
            BodyRule(
                water_body_id=289178,
                matched_term="闸港",
                score=76,
                match_type_code="LOCAL_REVIER_PARTIAL_CORRIDOR_WATER_BODY",
                issue_codes=("PLANNED_GAP_PARTIAL_WATER_BODY_MATCH", "ROUTE_VERIFICATION_REQUIRED"),
            ),
        ),
        publish_boundary_candidate=False,
        route_verification_status_code="PARTIAL_WATER_BODY_ONLY",
        evidence=(
            {
                "source_code": "LOCAL_REVIER_WATER_BODY",
                "description": "本地 Revier 五级水系水体 289177=大治河、289178=闸港，仅能作为大浦线相关水域候选证据。",
            },
        ),
        note="大浦线仍缺北横河/浦东运河等完整本地实体，不能直接标记完整。",
    ),
)


@dataclass(slots=True)
class RepairReport:
    generated_at: str
    dry_run: bool
    requested_channel_codes: list[str]
    channel_count: int = 0
    water_body_name_update_count: int = 0
    match_created_count: int = 0
    match_existing_count: int = 0
    technical_grade_derived_count: int = 0
    blocked_rule_count: int = 0
    publish_boundary_candidate_channel_codes: list[str] = field(default_factory=list)
    partial_only_channel_codes: list[str] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair planned-gap channel water-body matches with explicit map-inferred rules.")
    parser.add_argument("--channel-code", action="append", dest="channel_codes", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _norm_name(value: str) -> str:
    return re.sub(r"[\s\t\n\-_/（）()·—]+", "", value.strip())


def _display_name(body: NavigationWaterBody) -> str | None:
    return body.production_name or body.display_name or body.water_body_name or body.normalized_water_name


def _is_placeholder_name(value: str | None) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith("未命名水域")


def _derived_grade(channel: NavigationChannel) -> str:
    return PLANNING_LEVEL_GRADE.get(str(channel.planning_level_code or ""), "VI")


async def _channel(session: AsyncSession, channel_code: str) -> NavigationChannel | None:
    return await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == channel_code))


async def _existing_current_match(
    session: AsyncSession,
    *,
    channel_id: int,
    water_body_id: int,
) -> NavigationChannelWaterBodyMatch | None:
    return await session.scalar(
        select(NavigationChannelWaterBodyMatch).where(
            NavigationChannelWaterBodyMatch.channel_id == channel_id,
            NavigationChannelWaterBodyMatch.water_body_id == water_body_id,
            NavigationChannelWaterBodyMatch.is_current.is_(True),
        )
    )


async def _apply_rule(
    *,
    session: AsyncSession,
    rule: PlannedGapRule,
    dry_run: bool,
) -> dict[str, Any]:
    channel = await _channel(session, rule.channel_code)
    result: dict[str, Any] = {
        "channel_code": rule.channel_code,
        "status": "PENDING",
        "note": rule.note,
        "publish_boundary_candidate": rule.publish_boundary_candidate,
        "route_verification_status_code": rule.route_verification_status_code,
        "evidence": list(rule.evidence),
        "body_results": [],
    }
    if channel is None:
        result["status"] = "BLOCKED"
        result["issue_codes"] = ["CHANNEL_NOT_FOUND"]
        return result

    result["channel_id"] = int(channel.id)
    result["channel_name"] = channel.channel_name
    if not (channel.technical_grade_current_code or channel.technical_grade_planned_code):
        result["technical_grade_derived_code"] = _derived_grade(channel)
        if not dry_run:
            channel.technical_grade_planned_code = _derived_grade(channel)
            audit = dict(channel.source_audit_summary or {})
            audit["technical_grade_auto_derivation"] = {
                "source": "repair_planned_gap_water_body_matches",
                "planning_level_code": channel.planning_level_code,
                "derived_planned_grade_code": channel.technical_grade_planned_code,
                "derived_at": datetime.now(UTC).isoformat(),
            }
            channel.source_audit_summary = audit

    blocker_codes: list[str] = []
    for body_rule in rule.body_rules:
        body = await session.get(NavigationWaterBody, body_rule.water_body_id)
        body_result: dict[str, Any] = {
            "water_body_id": body_rule.water_body_id,
            "matched_term": body_rule.matched_term,
            "score": body_rule.score,
            "match_type_code": body_rule.match_type_code,
        }
        if body is None:
            body_result["status"] = "BLOCKED"
            body_result["issue_codes"] = ["WATER_BODY_NOT_FOUND"]
            blocker_codes.append("WATER_BODY_NOT_FOUND")
            result["body_results"].append(body_result)
            continue
        body_result.update(
            {
                "current_name": _display_name(body),
                "body_role_code": body.body_role_code,
                "water_level_min": body.water_level_min,
                "water_level_max": body.water_level_max,
                "water_type_code": body.water_type_code,
                "has_geometry": bool(body.geometry_wgs84_json),
            }
        )
        if not body.is_enabled:
            blocker_codes.append("WATER_BODY_DISABLED")
            body_result.setdefault("issue_codes", []).append("WATER_BODY_DISABLED")
        if body.body_role_code not in PRODUCTION_BODY_ROLES:
            blocker_codes.append("WATER_BODY_ROLE_NOT_PRODUCTION")
            body_result.setdefault("issue_codes", []).append("WATER_BODY_ROLE_NOT_PRODUCTION")
        if not body.geometry_wgs84_json:
            blocker_codes.append("WATER_BODY_GEOMETRY_MISSING")
            body_result.setdefault("issue_codes", []).append("WATER_BODY_GEOMETRY_MISSING")

        name_updated = False
        if body_rule.inferred_name and (
            _is_placeholder_name(body.production_name)
            or _is_placeholder_name(body.display_name)
            or _is_placeholder_name(body.normalized_water_name)
        ):
            if not dry_run:
                body.production_name = body_rule.inferred_name
                body.display_name = body_rule.inferred_name
                body.normalized_water_name = _norm_name(body_rule.inferred_name)
                body.name_status_code = "PRODUCTION_NAMED"
                body.name_source_code = NAME_SOURCE
                body.name_note = (
                    f"Auto named by repair_planned_gap_water_body_matches for {rule.channel_code}; "
                    "raw Revier NAME remains available through linked water_area rows."
                )
            name_updated = True
        body_result["name_update_status"] = "UPDATED" if name_updated else "UNCHANGED"

        existing = await _existing_current_match(
            session,
            channel_id=int(channel.id),
            water_body_id=body_rule.water_body_id,
        )
        if existing is not None:
            body_result["match_status"] = "EXISTS"
            body_result["match_id"] = int(existing.id)
            result["body_results"].append(body_result)
            continue
        if not dry_run:
            match = NavigationChannelWaterBodyMatch(
                channel_id=int(channel.id),
                water_body_id=body_rule.water_body_id,
                match_batch_code=MATCH_BATCH,
                match_type_code=body_rule.match_type_code,
                matched_term=body_rule.matched_term,
                score=body_rule.score,
                confidence_code="AUTO_HIGH_CONFIDENCE" if body_rule.score >= 90 else "AUTO_SPATIAL_CONFIDENCE",
                issue_codes=list(body_rule.issue_codes),
                is_current=True,
                source_water_area_ids_json=body.source_water_area_ids_json or [],
                source_trace_json={
                    "source": "repair_planned_gap_water_body_matches",
                    "rule_batch_code": MATCH_BATCH,
                    "name_source_code": NAME_SOURCE,
                    "channel_code": rule.channel_code,
                    "route_verification_status_code": rule.route_verification_status_code,
                    "publish_boundary_candidate": rule.publish_boundary_candidate,
                    "evidence": list(rule.evidence),
                    "applied_at": datetime.now(UTC).isoformat(),
                },
            )
            session.add(match)
            await session.flush()
            body_result["match_id"] = int(match.id)
        body_result["match_status"] = "CREATED" if not dry_run else "DRY_RUN_CREATE"
        result["body_results"].append(body_result)

    if blocker_codes:
        result["status"] = "BLOCKED"
        result["issue_codes"] = sorted(set(blocker_codes))
    else:
        result["status"] = "READY_FOR_BOUNDARY_REBUILD" if rule.publish_boundary_candidate else "MATCHED_PARTIAL_ONLY"
    return result


async def main() -> None:
    args = parse_args()
    requested = set(args.channel_codes or [])
    rules = [rule for rule in RULES if not requested or rule.channel_code in requested]
    report = RepairReport(
        generated_at=datetime.now(UTC).isoformat(),
        dry_run=bool(args.dry_run),
        requested_channel_codes=sorted(requested),
        channel_count=len(rules),
    )
    async with AsyncSessionLocal() as session:
        for rule in rules:
            result = await _apply_rule(session=session, rule=rule, dry_run=bool(args.dry_run))
            report.rules.append(result)
            if result.get("status") == "BLOCKED":
                report.blocked_rule_count += 1
            if result.get("publish_boundary_candidate"):
                report.publish_boundary_candidate_channel_codes.append(rule.channel_code)
            else:
                report.partial_only_channel_codes.append(rule.channel_code)
            if result.get("technical_grade_derived_code"):
                report.technical_grade_derived_count += 1
            for body_result in result.get("body_results") or []:
                if body_result.get("name_update_status") == "UPDATED":
                    report.water_body_name_update_count += 1
                if body_result.get("match_status") in {"CREATED", "DRY_RUN_CREATE"}:
                    report.match_created_count += 1
                if body_result.get("match_status") == "EXISTS":
                    report.match_existing_count += 1
        if not args.dry_run:
            await session.commit()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "channel_count": report.channel_count,
                "water_body_name_update_count": report.water_body_name_update_count,
                "match_created_count": report.match_created_count,
                "match_existing_count": report.match_existing_count,
                "technical_grade_derived_count": report.technical_grade_derived_count,
                "blocked_rule_count": report.blocked_rule_count,
                "publish_boundary_candidate_channel_codes": report.publish_boundary_candidate_channel_codes,
                "partial_only_channel_codes": report.partial_only_channel_codes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
