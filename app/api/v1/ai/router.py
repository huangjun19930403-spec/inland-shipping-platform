"""AI 解析路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_roles
from app.models.cargo import CargoRawMessage, CargoAiParseResult
from app.schemas.cargo import CargoRawMessageResponse, CargoAiParseResultResponse
from app.schemas.common import success

router = APIRouter()


@router.get("/parse-status/{raw_message_id}", summary="获取原始消息的AI解析状态")
async def get_parse_status(
    raw_message_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    result = await db.execute(
        select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
    )
    raw_msg = result.scalar_one_or_none()
    if not raw_msg:
        raise HTTPException(status_code=404, detail="原始消息不存在")

    parse_results_res = await db.execute(
        select(CargoAiParseResult).where(CargoAiParseResult.raw_message_id == raw_message_id)
    )
    parse_results = list(parse_results_res.scalars().all())

    return success(data={
        "raw_message": CargoRawMessageResponse.model_validate(raw_msg),
        "parse_results": [CargoAiParseResultResponse.model_validate(r) for r in parse_results],
        "parse_count": len(parse_results),
    })


@router.post("/reparse/{raw_message_id}", summary="重新触发AI解析")
async def reparse_raw_message(
    raw_message_id: int,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    result = await db.execute(
        select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
    )
    raw_msg = result.scalar_one_or_none()
    if not raw_msg:
        raise HTTPException(status_code=404, detail="原始消息不存在")
    if raw_msg.status == "PARSING":
        raise HTTPException(status_code=400, detail="正在解析中，请稍候")

    raw_msg.status = "PARSING"
    await db.commit()

    # Actual AI parsing would be triggered as a background task here.
    # The AI service integration is handled outside this router.

    return success(message="已重新提交AI解析")
