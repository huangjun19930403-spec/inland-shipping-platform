"""dictionary 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common import CodeSequence
from app.models.dictionary import StdDict, StdDictItem


class DictRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_dict_by_code(self, code: str) -> StdDict | None:
        return await self.db.scalar(select(StdDict).where(StdDict.dict_code == code))

    async def get_dict_by_id(self, dict_id: int) -> StdDict | None:
        return await self.db.scalar(select(StdDict).where(StdDict.id == dict_id))

    async def list_dicts(
        self,
        keyword: str | None,
        is_enabled: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StdDict], int]:
        stmt = select(StdDict)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    StdDict.dict_code.ilike(like_value),
                    StdDict.dict_name.ilike(like_value),
                    StdDict.dict_name_en.ilike(like_value),
                )
            )
        if is_enabled is not None:
            stmt = stmt.where(StdDict.status == (1 if is_enabled else 0))

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.db.execute(total_stmt)).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(StdDict.sort_order.asc(), StdDict.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def create_dict(self, data: dict[str, Any]) -> StdDict:
        entity = StdDict(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_dict(self, dict_id: int, data: dict[str, Any]) -> StdDict | None:
        entity = await self.get_dict_by_id(dict_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def delete_dict(self, dict_id: int) -> bool:
        entity = await self.get_dict_by_id(dict_id)
        if entity is None:
            return False
        entity.status = 0
        await self.db.flush()
        return True

    async def exists_dict_code(self, code: str) -> bool:
        entity = await self.get_dict_by_code(code)
        return entity is not None


class DictItemRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_dict_id_by_code(self, dict_code: str) -> int | None:
        entity = await self.db.scalar(select(StdDict).where(StdDict.dict_code == dict_code))
        return None if entity is None else int(entity.id)

    async def get_item_by_id(self, item_id: int) -> StdDictItem | None:
        return await self.db.scalar(select(StdDictItem).where(StdDictItem.id == item_id))

    async def list_items(
        self,
        dict_code: str,
        keyword: str | None,
        is_enabled: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StdDictItem], int]:
        dict_id = await self._get_dict_id_by_code(dict_code)
        if dict_id is None:
            return [], 0

        stmt = select(StdDictItem).where(StdDictItem.dict_id == dict_id)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    StdDictItem.item_code.ilike(like_value),
                    StdDictItem.item_name.ilike(like_value),
                    StdDictItem.item_name_en.ilike(like_value),
                )
            )
        if is_enabled is not None:
            stmt = stmt.where(StdDictItem.status == (1 if is_enabled else 0))

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.db.execute(total_stmt)).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(StdDictItem.sort_order.asc(), StdDictItem.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def create_item(self, data: dict[str, Any]) -> StdDictItem:
        entity = StdDictItem(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_item(self, item_id: int, data: dict[str, Any]) -> StdDictItem | None:
        entity = await self.get_item_by_id(item_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def delete_item(self, item_id: int) -> bool:
        entity = await self.get_item_by_id(item_id)
        if entity is None:
            return False
        entity.status = 0
        await self.db.flush()
        return True

    async def exists_item_code(self, dict_code: str, item_code: str) -> bool:
        dict_id = await self._get_dict_id_by_code(dict_code)
        if dict_id is None:
            return False
        entity = await self.db.scalar(
            select(StdDictItem).where(
                StdDictItem.dict_id == dict_id,
                StdDictItem.item_code == item_code,
            )
        )
        return entity is not None

    async def batch_sort_items(self, dict_code: str, ordered_ids: list[int]) -> int:
        dict_id = await self._get_dict_id_by_code(dict_code)
        if dict_id is None:
            return 0

        sorted_count = 0
        for index, item_id in enumerate(ordered_ids):
            entity = await self.db.scalar(
                select(StdDictItem).where(
                    StdDictItem.id == item_id,
                    StdDictItem.dict_id == dict_id,
                )
            )
            if entity is None:
                continue
            entity.sort_order = index + 1
            sorted_count += 1
        await self.db.flush()
        return sorted_count

    async def get_dict_by_code(self, dict_code: str) -> StdDict | None:
        return await self.db.scalar(select(StdDict).where(StdDict.dict_code == dict_code))

    async def replace_items(self, dict_id: int, rows: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(StdDictItem).where(StdDictItem.dict_id == dict_id))
        for row in rows:
            self.db.add(StdDictItem(**row))
        await self.db.flush()


class CodeSequenceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_sequences(
        self,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CodeSequence], int]:
        stmt = select(CodeSequence)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    CodeSequence.biz_code.ilike(like_value),
                    CodeSequence.biz_name.ilike(like_value),
                    CodeSequence.target_table.ilike(like_value),
                    CodeSequence.target_column.ilike(like_value),
                    CodeSequence.prefix.ilike(like_value),
                    CodeSequence.remark.ilike(like_value),
                )
            )
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.db.execute(total_stmt)).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(CodeSequence.biz_code.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_sequence_by_biz_code(self, biz_code: str, *, for_update: bool = False) -> CodeSequence | None:
        stmt = select(CodeSequence).where(CodeSequence.biz_code == biz_code)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.db.scalar(stmt)

    async def get_sequence_by_code(self, business_code: str) -> CodeSequence | None:
        return await self.get_sequence_by_biz_code(business_code)

    async def create_sequence(self, data: dict[str, Any]) -> CodeSequence:
        entity = CodeSequence(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_sequence(self, biz_code: str, data: dict[str, Any]) -> CodeSequence | None:
        entity = await self.get_sequence_by_biz_code(biz_code)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def next_code(self, biz_code: str, reset: bool = False) -> CodeSequence | None:
        entity = await self.get_sequence_by_biz_code(biz_code, for_update=True)
        if entity is None:
            return None
        if reset:
            entity.current_value = 0
        entity.current_value = int(entity.current_value or 0) + int(entity.step or 1)
        entity.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def reserve_codes(self, biz_code: str, count: int, reset: bool = False) -> CodeSequence | None:
        entity = await self.get_sequence_by_biz_code(biz_code, for_update=True)
        if entity is None:
            return None
        if count <= 0:
            return entity
        if reset:
            entity.current_value = 0
        step = int(entity.step or 1)
        entity.current_value = int(entity.current_value or 0) + step * int(count)
        entity.updated_at = datetime.utcnow()
        await self.db.flush()
        return entity
