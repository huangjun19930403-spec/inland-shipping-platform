"""dictionary 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.dictionary.schemas import (
    CodeSequenceCreateRequest,
    CodeSequenceResponse,
    CodeSequenceUpdateRequest,
    DictCreateRequest,
    DictItemCreateRequest,
    DictItemListQuery,
    DictItemOrderRequest,
    DictItemResponse,
    DictItemUpdateRequest,
    DictListQuery,
    DictOptionsResponse,
    DictResponse,
    DictUpdateRequest,
    PageResponse,
)
from app.modules.dictionary.service import CodeSequenceService, DictionaryItemService, DictionaryService

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/dicts", response_model=PageResponse[DictResponse])
async def list_dicts(
    query: DictListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    return await service.list_dicts(query.keyword, query.is_enabled, query.page, query.page_size)


@router.get("/dicts/{dict_code}")
async def get_dict_detail(
    dict_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    return await service.get_dict_detail(dict_code)


@router.get("/options", response_model=list[DictOptionsResponse])
async def get_dict_options(
    dict_codes: list[str] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    return await service.get_options(dict_codes)


@router.post("/dicts", response_model=DictResponse)
async def create_dict(
    body: DictCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    return await service.create_dict(body)


@router.put("/dicts/{dict_id}", response_model=DictResponse)
async def update_dict(
    dict_id: int,
    body: DictUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    return await service.update_dict(dict_id, body)


@router.delete("/dicts/{dict_id}")
async def delete_dict(
    dict_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryService(db)
    await service.disable_dict(dict_id)
    return {"ok": True}


@router.get("/dicts/{dict_code}/items", response_model=PageResponse[DictItemResponse])
async def list_items(
    dict_code: str,
    query: DictItemListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryItemService(db)
    return await service.list_items(dict_code, query.keyword, query.is_enabled, query.page, query.page_size)


@router.post("/dicts/{dict_code}/items", response_model=DictItemResponse)
async def create_item(
    dict_code: str,
    body: DictItemCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryItemService(db)
    return await service.create_item(dict_code, body)


@router.put("/items/{item_id}", response_model=DictItemResponse)
async def update_item(
    item_id: int,
    body: DictItemUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryItemService(db)
    return await service.update_item(item_id, body)


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryItemService(db)
    await service.disable_item(item_id)
    return {"ok": True}


@router.put("/dicts/{dict_code}/items/order")
async def reorder_items(
    dict_code: str,
    body: DictItemOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    service = DictionaryItemService(db)
    count = await service.reorder_items(dict_code, body.ordered_ids)
    return {"ok": True, "updated_count": count}


@router.get("/code-sequences", response_model=PageResponse[CodeSequenceResponse])
async def list_code_sequences(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    service = CodeSequenceService(db)
    return await service.list_sequences(keyword, page, page_size)


@router.post("/code-sequences", response_model=CodeSequenceResponse)
async def create_code_sequence(
    body: CodeSequenceCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CodeSequenceService(db)
    return await service.create_sequence(body)


@router.get("/code-sequences/{business_code}", response_model=CodeSequenceResponse)
async def get_code_sequence_detail(
    business_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = CodeSequenceService(db)
    return await service.get_sequence_detail(business_code)


@router.put("/code-sequences/{business_code}", response_model=CodeSequenceResponse)
async def update_code_sequence(
    business_code: str,
    body: CodeSequenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CodeSequenceService(db)
    return await service.update_sequence(business_code, body)
