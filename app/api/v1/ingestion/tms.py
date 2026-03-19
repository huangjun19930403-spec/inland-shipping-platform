"""一期数据接入域 - TMS 接入入口"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
from app.models.cargo import TmsCargoRaw
from app.repositories.cargo_repository import CargoRepository
from app.schemas.common import success

router = APIRouter()


@router.post("/cargo/tms/raw", summary="TMS货源原始数据接入")
async def ingest_tms_raw(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    tms_message_id = str(body.get("tms_message_id") or "").strip()
    payload = body.get("raw_payload")
    if not tms_message_id or payload is None:
        raise HTTPException(status_code=400, detail="tms_message_id 和 raw_payload 必填")

    repo = CargoRepository(db)
    existing = await repo.get_tms_raw_by_msg_id(tms_message_id)
    if existing:
        return success(data={"id": existing.id, "message": "重复消息已忽略"})

    saved = await repo.create_tms_raw(
        TmsCargoRaw(
            tms_message_id=tms_message_id,
            raw_payload=payload,
            tms_origin_name=body.get("tms_origin_name"),
            tms_origin_lng=body.get("tms_origin_lng"),
            tms_origin_lat=body.get("tms_origin_lat"),
            tms_origin_region=body.get("tms_origin_region"),
            tms_dest_name=body.get("tms_dest_name"),
            tms_dest_lng=body.get("tms_dest_lng"),
            tms_dest_lat=body.get("tms_dest_lat"),
            tms_dest_region=body.get("tms_dest_region"),
            process_status="PENDING",
        )
    )
    await repo.save()
    return success(data={"id": saved.id, "tms_message_id": tms_message_id})
