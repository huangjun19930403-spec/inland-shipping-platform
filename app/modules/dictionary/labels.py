"""字典与行政区划中文展示辅助。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import AdminRegion
from app.models.dictionary import StdDict, StdDictItem


DictLabelMap = dict[str, dict[str, str]]
RegionLabelMap = dict[str, str]


async def load_dict_label_map(db: AsyncSession, dict_codes: list[str]) -> DictLabelMap:
    codes = [code for code in dict_codes if code]
    if not codes:
        return {}
    result = await db.execute(
        select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
        .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
        .where(
            StdDict.dict_code.in_(codes),
            StdDict.status == 1,
            StdDictItem.status == 1,
        )
    )
    labels: DictLabelMap = {}
    for dict_code, item_code, item_name in result.all():
        labels.setdefault(dict_code, {})[item_code] = item_name
    return labels


async def load_admin_region_label_map(db: AsyncSession, admin_codes: list[str | None]) -> RegionLabelMap:
    codes = sorted({code for code in admin_codes if code})
    if not codes:
        return {}
    rows = (
        await db.execute(
            select(AdminRegion.code, AdminRegion.name).where(
                AdminRegion.code.in_(codes),
                AdminRegion.status == 1,
            )
        )
    ).all()
    return {code: name for code, name in rows}


def dict_label(labels: DictLabelMap, dict_code: str, item_code: str | None) -> str | None:
    if not item_code:
        return None
    return labels.get(dict_code, {}).get(item_code)


def region_label(labels: RegionLabelMap, admin_code: str | None) -> str | None:
    if not admin_code:
        return None
    return labels.get(admin_code)


def status_name(status: int | None) -> str | None:
    if status is None:
        return None
    return "启用" if status == 1 else "停用"
