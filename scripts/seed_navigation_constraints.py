"""通航约束点 E2E/基础数据初始化脚本。"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import NavigationConstraintPoint, NavigationConstraintProfile


CONSTRAINT_SEEDS: list[dict[str, Any]] = [
    {
        "point": {
            "code": "E2E_CONSTRAINT_LOCK",
            "name": "E2E测试船闸约束点",
            "constraint_type_code": "LOCK",
            "province_code": "320000",
            "city_code": "320500",
            "longitude": Decimal("120.52000000"),
            "latitude": Decimal("31.36000000"),
            "severity_level": 2,
            "description": "E2E 船闸通行限制样例",
            "status": 1,
        },
        "profile": {
            "max_tonnage": Decimal("1000.00"),
            "max_allowed_draft_m": Decimal("2.80"),
            "max_beam_m": Decimal("16.00"),
            "max_length_m": Decimal("90.00"),
            "allowed_time_window": "08:00-18:00",
            "rule_description": "E2E船闸通行限制",
        },
    },
    {
        "point": {
            "code": "E2E_CONSTRAINT_BRIDGE",
            "name": "E2E测试桥梁净空约束点",
            "constraint_type_code": "BRIDGE",
            "province_code": "320000",
            "city_code": "320500",
            "longitude": Decimal("120.44000000"),
            "latitude": Decimal("31.42000000"),
            "severity_level": 2,
            "description": "E2E 桥梁净空限制样例",
            "status": 1,
        },
        "profile": {
            "max_air_draft_m": Decimal("7.50"),
            "max_beam_m": Decimal("18.00"),
            "rule_description": "E2E桥梁净空限制",
        },
    },
    {
        "point": {
            "code": "E2E_CONSTRAINT_SHALLOW",
            "name": "E2E测试浅滩水深约束点",
            "constraint_type_code": "SHALLOW",
            "province_code": "320000",
            "city_code": "320200",
            "longitude": Decimal("120.34000000"),
            "latitude": Decimal("31.50000000"),
            "severity_level": 3,
            "description": "E2E 浅滩水深限制样例",
            "status": 1,
        },
        "profile": {
            "min_water_depth_m": Decimal("3.20"),
            "max_allowed_draft_m": Decimal("2.50"),
            "under_keel_clearance_m": Decimal("0.50"),
            "warning_message": "低水位期间需复核吃水",
        },
    },
]


async def seed_navigation_constraints() -> None:
    point_count = 0
    profile_count = 0

    async with AsyncSessionLocal() as session:
        for item in CONSTRAINT_SEEDS:
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
