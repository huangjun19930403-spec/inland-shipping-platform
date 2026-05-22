"""货品分类与类型正式初始化脚本。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.commodity import CommodityCategory, CommodityType


COMMODITY_CATEGORY_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "commodity"
    / "commodity_categories.json"
)
COMMODITY_TYPE_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "commodity"
    / "commodity_types.json"
)


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


async def seed_commodity_taxonomy() -> None:
    categories = _load_json(COMMODITY_CATEGORY_FILE)
    types = _load_json(COMMODITY_TYPE_FILE)

    async with AsyncSessionLocal() as session:
        category_id_by_code: dict[str, int] = {}

        for row in categories:
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if not code or not name:
                continue

            entity = await session.scalar(select(CommodityCategory).where(CommodityCategory.code == code))
            if entity is None:
                entity = CommodityCategory(
                    code=code,
                    name=name,
                    description=row.get("description"),
                    sort_order=int(row.get("sort_order") or 0),
                )
                session.add(entity)
                await session.flush()
            else:
                entity.name = name
                entity.description = row.get("description")
                entity.sort_order = int(row.get("sort_order") or 0)
                entity.deleted_at = None
            category_id_by_code[code] = int(entity.id)

        for row in types:
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            category_code = str(row.get("category_code") or "").strip()
            category_id = category_id_by_code.get(category_code)
            if not code or not name or category_id is None:
                continue

            entity = await session.scalar(select(CommodityType).where(CommodityType.code == code))
            if entity is None:
                entity = CommodityType(
                    category_id=category_id,
                    code=code,
                    name=name,
                    description=row.get("description"),
                    sort_order=int(row.get("sort_order") or 0),
                )
                session.add(entity)
                await session.flush()
            else:
                entity.category_id = category_id
                entity.name = name
                entity.description = row.get("description")
                entity.sort_order = int(row.get("sort_order") or 0)
                entity.deleted_at = None

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_commodity_taxonomy())
