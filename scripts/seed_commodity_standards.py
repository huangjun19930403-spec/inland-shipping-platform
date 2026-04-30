"""首版高频标准货品与别名初始化脚本。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.commodity import CommodityAlias, CommodityStandard, CommodityType


COMMODITY_STANDARD_FILE = (
    Path(__file__).resolve().parent
    / "seed_data"
    / "commodity"
    / "commodity_standards.json"
)


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


async def seed_commodity_standards() -> None:
    standards = _load_json(COMMODITY_STANDARD_FILE)
    if not standards:
        return

    async with AsyncSessionLocal() as session:
        for row in standards:
            code = str(row.get("code") or "").strip()
            type_code = str(row.get("type_code") or "").strip()
            name = str(row.get("name") or "").strip()
            if not code or not type_code or not name:
                continue

            commodity_type = await session.scalar(
                select(CommodityType).where(
                    CommodityType.code == type_code,
                    CommodityType.deleted_at.is_(None),
                )
            )
            if commodity_type is None:
                continue

            entity = await session.scalar(
                select(CommodityStandard).where(CommodityStandard.code == code)
            )
            if entity is None:
                entity = CommodityStandard(
                    type_id=commodity_type.id,
                    code=code,
                    name=name,
                    short_name=row.get("short_name"),
                    english_name=row.get("english_name"),
                    main_unit=row.get("main_unit") or "吨",
                    density_range_desc=row.get("density_range_desc"),
                    dangerous_grade_code=row.get("dangerous_grade_code"),
                    is_active=bool(row.get("is_active", True)),
                )
                session.add(entity)
                await session.flush()
            else:
                entity.type_id = commodity_type.id
                entity.name = name
                entity.short_name = row.get("short_name")
                entity.english_name = row.get("english_name")
                entity.main_unit = row.get("main_unit") or entity.main_unit
                entity.density_range_desc = row.get("density_range_desc")
                entity.dangerous_grade_code = row.get("dangerous_grade_code")
                entity.is_active = bool(row.get("is_active", True))
                entity.deleted_at = None
                await session.flush()
            entity.audit_status = "APPROVED"

            await session.execute(
                delete(CommodityAlias).where(
                    CommodityAlias.commodity_standard_id == entity.id
                )
            )
            aliases = row.get("aliases") or []
            deduped_aliases = []
            for alias in [name, row.get("short_name"), *aliases]:
                alias_name = str(alias or "").strip()
                if alias_name and alias_name not in deduped_aliases:
                    deduped_aliases.append(alias_name)
            for index, alias_name in enumerate(deduped_aliases):
                session.add(
                    CommodityAlias(
                        commodity_standard_id=entity.id,
                        alias_name=alias_name,
                        source_type_code="SYSTEM",
                        is_primary=index == 0,
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_commodity_standards())
