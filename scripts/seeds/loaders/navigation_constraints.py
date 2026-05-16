"""通航约束点基础数据初始化脚本。"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import NavigationConstraintPoint, NavigationConstraintProfile


CONSTRAINT_SEED_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "navigation_constraints"
    / "constraint_points.json"
)

DECIMAL_FIELDS = {
    "longitude",
    "latitude",
    "max_tonnage",
    "max_allowed_draft_m",
    "min_water_depth_m",
    "under_keel_clearance_m",
    "max_air_draft_m",
    "max_beam_m",
    "max_length_m",
}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in DECIMAL_FIELDS:
        if key in normalized:
            normalized[key] = _decimal_or_none(normalized[key])
    return normalized


def load_navigation_constraint_seed(path: Path = CONSTRAINT_SEED_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "point": _normalize_payload(row.get("point") or {}),
                "profile": _normalize_payload(row.get("profile") or {}),
            }
        )
    return result


async def seed_navigation_constraints() -> None:
    constraint_seeds = load_navigation_constraint_seed()
    point_count = 0
    profile_count = 0

    async with AsyncSessionLocal() as session:
        for item in constraint_seeds:
            point_payload = item["point"]
            profile_payload = item["profile"]

            point = await session.scalar(
                select(NavigationConstraintPoint).where(
                    NavigationConstraintPoint.code == point_payload["code"]
                )
            )
            if point is None:
                point = NavigationConstraintPoint(**point_payload)
                session.add(point)
                await session.flush()
            else:
                for key, value in point_payload.items():
                    setattr(point, key, value)
                await session.flush()
            point_count += 1

            profile = await session.scalar(
                select(NavigationConstraintProfile).where(
                    NavigationConstraintProfile.constraint_point_id == point.id
                )
            )
            if profile is None:
                profile = NavigationConstraintProfile(
                    constraint_point_id=point.id,
                    **profile_payload,
                )
                session.add(profile)
            else:
                for key, value in profile_payload.items():
                    setattr(profile, key, value)
            profile_count += 1

        await session.commit()

    print(
        "seed_navigation_constraints completed: "
        f"constraint_count={point_count}, profile_count={profile_count}"
    )


if __name__ == "__main__":
    asyncio.run(seed_navigation_constraints())
