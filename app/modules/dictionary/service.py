"""dictionary 模块 service。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.dictionary.repository import CodeSequenceRepository, DictItemRepository, DictRepository
from app.modules.dictionary.schemas import (
    CodeSequenceCreateRequest,
    CodeSequenceResponse,
    CodeSequenceUpdateRequest,
    DictCreateRequest,
    DictItemCreateRequest,
    DictItemResponse,
    DictItemUpdateRequest,
    DictOptionItemResponse,
    DictOptionsResponse,
    DictResponse,
    DictUpdateRequest,
    PageResponse,
)


def _to_dict_response(entity) -> DictResponse:
    return DictResponse(
        id=entity.id,
        dict_code=entity.dict_code,
        dict_name=entity.dict_name,
        dict_name_en=entity.dict_name_en,
        description=entity.description,
        is_system=entity.is_system,
        status=entity.status,
        is_enabled=entity.status == 1,
        sort_order=entity.sort_order,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_item_response(entity) -> DictItemResponse:
    return DictItemResponse(
        id=entity.id,
        dict_id=entity.dict_id,
        item_code=entity.item_code,
        item_name=entity.item_name,
        item_name_en=entity.item_name_en,
        parent_item_id=entity.parent_item_id,
        item_value=entity.item_value,
        color=entity.color,
        description=entity.description,
        ext_json=entity.ext_json,
        is_default=entity.is_default,
        is_system=entity.is_system,
        status=entity.status,
        is_enabled=entity.status == 1,
        sort_order=entity.sort_order,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class DictionaryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = DictRepository(db)
        self.item_repo = DictItemRepository(db)

    async def list_dicts(
        self,
        keyword: str | None,
        is_enabled: bool | None,
        page: int,
        page_size: int,
    ) -> PageResponse[DictResponse]:
        items, total = await self.repo.list_dicts(keyword, is_enabled, page, page_size)
        return PageResponse[DictResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_dict_response(item) for item in items],
        )

    async def create_dict(self, payload: DictCreateRequest) -> DictResponse:
        if await self.repo.exists_dict_code(payload.dict_code):
            raise ConflictError(f"dict_code already exists: {payload.dict_code}")
        entity = await self.repo.create_dict(
            {
                "dict_code": payload.dict_code.strip(),
                "dict_name": payload.dict_name.strip(),
                "dict_name_en": payload.dict_name_en,
                "description": payload.description,
                "is_system": payload.is_system,
                "status": 1 if payload.is_enabled else 0,
                "sort_order": payload.sort_order,
            }
        )
        await self.db.commit()
        return _to_dict_response(entity)

    async def update_dict(self, dict_id: int, payload: DictUpdateRequest) -> DictResponse:
        updates = payload.model_dump(exclude_none=True)
        if "is_enabled" in updates:
            updates["status"] = 1 if updates.pop("is_enabled") else 0
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_dict(dict_id, updates)
        if entity is None:
            raise NotFoundError("StdDict", dict_id)
        await self.db.commit()
        return _to_dict_response(entity)

    async def disable_dict(self, dict_id: int) -> None:
        ok = await self.repo.delete_dict(dict_id)
        if not ok:
            raise NotFoundError("StdDict", dict_id)
        await self.db.commit()

    async def get_dict_detail(self, code: str) -> dict:
        entity = await self.repo.get_dict_by_code(code)
        if entity is None:
            raise NotFoundError("StdDict", code)
        items, total = await self.item_repo.list_items(code, None, None, 1, 1000)
        return {
            "dict": _to_dict_response(entity),
            "items_total": total,
            "items": [_to_item_response(item) for item in items],
        }

    async def get_options(self, dict_codes: list[str]) -> list[DictOptionsResponse]:
        normalized_codes = []
        seen_codes: set[str] = set()
        for raw_code in dict_codes:
            code = (raw_code or "").strip()
            if not code or code in seen_codes:
                continue
            normalized_codes.append(code)
            seen_codes.add(code)

        results: list[DictOptionsResponse] = []
        for code in normalized_codes:
            entity = await self.repo.get_dict_by_code(code)
            if entity is None or entity.status != 1:
                results.append(DictOptionsResponse(dict_code=code, dict_name=code, items=[]))
                continue
            items, _ = await self.item_repo.list_items(code, None, True, 1, 1000)
            results.append(
                DictOptionsResponse(
                    dict_code=entity.dict_code,
                    dict_name=entity.dict_name,
                    items=[
                        DictOptionItemResponse(
                            dict_code=entity.dict_code,
                            item_code=item.item_code,
                            item_name=item.item_name,
                            item_name_en=item.item_name_en,
                            item_value=item.item_value,
                            color=item.color,
                            description=item.description,
                            is_default=item.is_default,
                            sort_order=item.sort_order,
                        )
                        for item in items
                    ],
                )
            )
        return results


class DictionaryItemService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = DictItemRepository(db)

    async def list_items(
        self,
        dict_code: str,
        keyword: str | None,
        is_enabled: bool | None,
        page: int,
        page_size: int,
    ) -> PageResponse[DictItemResponse]:
        items, total = await self.repo.list_items(dict_code, keyword, is_enabled, page, page_size)
        return PageResponse[DictItemResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_item_response(item) for item in items],
        )

    async def create_item(self, dict_code: str, payload: DictItemCreateRequest) -> DictItemResponse:
        dictionary = await self.repo.get_dict_by_code(dict_code)
        if dictionary is None:
            raise NotFoundError("StdDict", dict_code)
        if await self.repo.exists_item_code(dict_code, payload.item_code):
            raise ConflictError(f"item_code already exists in dict {dict_code}: {payload.item_code}")
        entity = await self.repo.create_item(
            {
                "dict_id": dictionary.id,
                "item_code": payload.item_code.strip(),
                "item_name": payload.item_name.strip(),
                "item_name_en": payload.item_name_en,
                "parent_item_id": payload.parent_item_id,
                "item_value": payload.item_value,
                "color": payload.color,
                "description": payload.description,
                "ext_json": payload.ext_json,
                "is_default": payload.is_default,
                "is_system": payload.is_system,
                "status": 1 if payload.is_enabled else 0,
                "sort_order": payload.sort_order,
            }
        )
        await self.db.commit()
        return _to_item_response(entity)

    async def update_item(self, item_id: int, payload: DictItemUpdateRequest) -> DictItemResponse:
        updates = payload.model_dump(exclude_none=True)
        if "is_enabled" in updates:
            updates["status"] = 1 if updates.pop("is_enabled") else 0
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_item(item_id, updates)
        if entity is None:
            raise NotFoundError("StdDictItem", item_id)
        await self.db.commit()
        return _to_item_response(entity)

    async def disable_item(self, item_id: int) -> None:
        ok = await self.repo.delete_item(item_id)
        if not ok:
            raise NotFoundError("StdDictItem", item_id)
        await self.db.commit()

    async def reorder_items(self, dict_code: str, ordered_ids: list[int]) -> int:
        count = await self.repo.batch_sort_items(dict_code, ordered_ids)
        await self.db.commit()
        return count


class CodeSequenceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CodeSequenceRepository(db)

    @staticmethod
    def _to_response(item) -> CodeSequenceResponse:
        return CodeSequenceResponse(
            id=item.id,
            business_code=item.biz_code,
            business_name=item.biz_name,
            target_table=item.target_table,
            target_column=item.target_column,
            prefix=item.prefix,
            date_format=item.date_format,
            separator=item.separator,
            current_value=item.current_value,
            value_length=item.value_length,
            step=item.step,
            reset_rule=item.reset_rule,
            is_enabled=item.is_enabled,
            remark=item.remark,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _normalize_date_format(date_format: str | None) -> str | None:
        if not date_format:
            return None
        token_map = {
            "yyyy": "%Y",
            "yy": "%y",
            "MM": "%m",
            "dd": "%d",
            "HH": "%H",
            "mm": "%M",
            "ss": "%S",
        }
        fmt = date_format
        for token, value in token_map.items():
            fmt = fmt.replace(token, value)
        return fmt

    @classmethod
    def _format_code(cls, item, now: datetime) -> str:
        date_text = None
        normalized_format = cls._normalize_date_format(item.date_format)
        if normalized_format:
            date_text = now.strftime(normalized_format)

        serial_text = str(item.current_value).zfill(item.value_length)
        parts = [item.prefix or ""]
        if date_text:
            parts.append(date_text)
        parts.append(serial_text)
        separator = item.separator or ""
        if separator:
            return separator.join([part for part in parts if part != ""])
        return "".join(parts)

    @staticmethod
    def _should_reset(item, now: datetime) -> bool:
        rule = (item.reset_rule or "NONE").upper()
        if rule == "NONE":
            return False
        if item.updated_at is None:
            return False
        previous = item.updated_at
        if rule == "DAY":
            return previous.date() != now.date()
        if rule == "MONTH":
            return previous.year != now.year or previous.month != now.month
        if rule == "YEAR":
            return previous.year != now.year
        return False

    async def list_sequences(
        self,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[CodeSequenceResponse]:
        items, total = await self.repo.list_sequences(keyword, page, page_size)
        return PageResponse[CodeSequenceResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[self._to_response(item) for item in items],
        )

    async def get_sequence_detail(self, business_code: str) -> CodeSequenceResponse:
        item = await self.repo.get_sequence_by_biz_code(business_code)
        if item is None:
            raise NotFoundError("CodeSequence", business_code)
        return self._to_response(item)

    async def create_sequence(self, payload: CodeSequenceCreateRequest) -> CodeSequenceResponse:
        existing = await self.repo.get_sequence_by_biz_code(payload.business_code)
        if existing is not None:
            raise ConflictError(f"sequence already exists: {payload.business_code}")
        entity = await self.repo.create_sequence(
            {
                "biz_code": payload.business_code.strip(),
                "biz_name": payload.business_name.strip(),
                "target_table": payload.target_table.strip(),
                "target_column": payload.target_column.strip(),
                "prefix": payload.prefix or "",
                "date_format": payload.date_format,
                "separator": payload.separator,
                "current_value": payload.current_value,
                "value_length": payload.value_length,
                "step": payload.step,
                "reset_rule": payload.reset_rule.upper(),
                "is_enabled": payload.is_enabled,
                "remark": payload.remark,
            }
        )
        await self.db.commit()
        return self._to_response(entity)

    async def update_sequence(
        self,
        business_code: str,
        payload: CodeSequenceUpdateRequest,
    ) -> CodeSequenceResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if "business_name" in updates:
            updates["biz_name"] = updates.pop("business_name").strip()
        if "target_table" in updates:
            updates["target_table"] = updates["target_table"].strip()
        if "target_column" in updates:
            updates["target_column"] = updates["target_column"].strip()
        if "reset_rule" in updates:
            updates["reset_rule"] = str(updates["reset_rule"]).upper()
        entity = await self.repo.update_sequence(business_code, updates)
        if entity is None:
            raise NotFoundError("CodeSequence", business_code)
        await self.db.commit()
        return self._to_response(entity)

    async def next_code(self, business_code: str) -> str:
        current = await self.repo.get_sequence_by_biz_code(business_code)
        if current is None:
            raise NotFoundError("CodeSequence", business_code)
        if not current.is_enabled:
            raise ValidationError(f"sequence is disabled: {business_code}")

        now = datetime.utcnow()
        reset_needed = self._should_reset(current, now)
        updated = await self.repo.next_code(business_code, reset=reset_needed)
        if updated is None:
            raise NotFoundError("CodeSequence", business_code)
        return self._format_code(updated, now)
