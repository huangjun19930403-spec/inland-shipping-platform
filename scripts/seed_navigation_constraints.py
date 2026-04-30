"""通航约束点基础数据初始化脚本。"""

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
            "code": "NC_CHANGZHOU_BENNIU_LOCK",
            "name": "常州奔牛船闸通航限制点",
            "constraint_type_code": "LOCK",
            "province_code": "320000",
            "city_code": "320500",
            "longitude": Decimal("120.52000000"),
            "latitude": Decimal("31.36000000"),
            "severity_level": 2,
            "description": "江南运河常州段船闸通行限制样例。",
            "status": 1,
        },
        "profile": {
            "max_tonnage": Decimal("1000.00"),
            "max_allowed_draft_m": Decimal("2.80"),
            "max_beam_m": Decimal("16.00"),
            "max_length_m": Decimal("90.00"),
            "allowed_time_window": "08:00-18:00",
            "rule_description": "1000 吨级以下船舶白天排队通行，重载船需提前复核闸室尺度。",
        },
    },
    {
        "point": {
            "code": "NC_JIANGYIN_BRIDGE_CLEARANCE",
            "name": "江阴长江大桥净空约束点",
            "constraint_type_code": "BRIDGE",
            "province_code": "320000",
            "city_code": "320500",
            "longitude": Decimal("120.44000000"),
            "latitude": Decimal("31.42000000"),
            "severity_level": 2,
            "description": "长江下游桥区净空约束样例。",
            "status": 1,
        },
        "profile": {
            "max_air_draft_m": Decimal("7.50"),
            "max_beam_m": Decimal("18.00"),
            "rule_description": "高水位期间需复核空载高度和船宽，超限船舶不得通过桥区。",
        },
    },
    {
        "point": {
            "code": "NC_TAICANG_WATER_DEPTH",
            "name": "太仓港上游浅水约束点",
            "constraint_type_code": "SHALLOW",
            "province_code": "320000",
            "city_code": "320200",
            "longitude": Decimal("120.34000000"),
            "latitude": Decimal("31.50000000"),
            "severity_level": 3,
            "description": "长江下游局部浅水航段水深约束样例。",
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
