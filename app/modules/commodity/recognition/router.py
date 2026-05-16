"""Routes for standard commodity recognition."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.commodity.recognition.schemas import (
    CommodityRecognitionAdoptionResponse,
    CommodityRecognitionAliasAdoptRequest,
    CommodityRecognitionCreateRequest,
    CommodityRecognitionResponse,
    CommodityRecognitionStandardAdoptRequest,
)
from app.modules.commodity.recognition.service import CommodityRecognitionService

router = APIRouter(prefix="/recognitions", tags=["commodity-recognition"])


@router.post("", response_model=CommodityRecognitionResponse)
async def create_recognition(
    body: CommodityRecognitionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityRecognitionService(db)
    return await service.create_recognition(body)


@router.get("/{recognition_id}", response_model=CommodityRecognitionResponse)
async def get_recognition(
    recognition_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityRecognitionService(db)
    return await service.get_recognition(recognition_id)


@router.post("/{recognition_id}/adopt-alias", response_model=CommodityRecognitionAdoptionResponse)
async def adopt_alias(
    recognition_id: int,
    body: CommodityRecognitionAliasAdoptRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityRecognitionService(db)
    return await service.adopt_alias(recognition_id, body, operator_id=current_user.id)


@router.post("/{recognition_id}/adopt-standard", response_model=CommodityRecognitionAdoptionResponse)
async def adopt_standard(
    recognition_id: int,
    body: CommodityRecognitionStandardAdoptRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityRecognitionService(db)
    return await service.adopt_standard(recognition_id, body, operator_id=current_user.id)
